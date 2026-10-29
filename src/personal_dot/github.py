"""Read-only GitHub App transport. Credentials live only in process memory."""

import json
import os
import re
import stat
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from pydantic import SecretStr

from personal_dot.config import Settings, get_settings
from personal_dot.github_errors import GitHubError

OWNER = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?")
REPOSITORY = re.compile(r"[A-Za-z0-9_.-]{1,100}")
SHA = re.compile(r"[0-9a-f]{40}")


def repository_name(value: str) -> str:
    if not REPOSITORY.fullmatch(value) or value in {".", ".."}:
        raise ValueError("repository must be a name, without owner, URL or path")
    return value


def private_key(path: str) -> RSAPrivateKey:
    try:
        p = Path(path)
        info = p.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_uid != os.geteuid():
            raise GitHubError("key_permissions")
        if info.st_size > 16_384:
            raise GitHubError("key_invalid")
        key = load_pem_private_key(p.read_bytes(), password=None)
        if not isinstance(key, RSAPrivateKey) or key.key_size < 2048:
            raise GitHubError("key_invalid")
        return key
    except FileNotFoundError:
        raise GitHubError("key_missing") from None
    except PermissionError:
        raise GitHubError("key_unreadable") from None
    except GitHubError:
        raise
    except Exception:
        raise GitHubError("key_invalid") from None


class GitHubClient:
    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        self.settings = settings
        if not (OWNER.fullmatch(settings.github_owner) and settings.github_app_id
                and settings.github_installation_id and settings.github_app_private_key_path):
            raise GitHubError("configuration_missing")
        self.client = client or httpx.Client(timeout=settings.github_timeout_seconds,
                                             follow_redirects=False, trust_env=False)
        self._token: SecretStr | None = None
        self._expires = 0.0
        self._repository: str | None = None
        self.installation: dict[str, Any] = {}

    def close(self) -> None:
        self._token = None
        self.client.close()

    def _jwt(self) -> str:
        now = int(time.time())
        return jwt.encode({"iat": now - 60, "exp": now + 540,
                           "iss": str(self.settings.github_app_id)},
                          private_key(self.settings.github_app_private_key_path), algorithm="RS256")

    def _request(self, method: str, path: str, token: str, *, body: dict | None = None,
                 limit: int | None = None) -> dict[str, Any]:
        # No supplied URLs, redirects, Link targets, git clients or remote code.
        token_path = f"/app/installations/{self.settings.github_installation_id}/access_tokens"
        if not path.startswith('/') or path.startswith('//') or (method != 'GET' and not (method == 'POST' and path == token_path)):
            raise GitHubError("request_rejected")
        headers = {"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json",
                   "X-GitHub-Api-Version": "2026-03-10", "User-Agent": "personal-dot-read-only"}
        cap = min(limit or self.settings.github_response_bytes, self.settings.github_response_bytes)
        try:
            with self.client.stream(method, "https://api.github.com" + path, headers=headers, json=body,
                                    follow_redirects=False) as response:
                status = response.status_code
                if status not in {200, 201}:
                    if 300 <= status < 400:
                        code = "redirect"
                    elif status == 401:
                        code = "authentication_rejected"
                    elif status == 429 or (status == 403 and response.headers.get('x-ratelimit-remaining') == '0'):
                        code = "rate_limited"
                    else:
                        code = {403: "forbidden", 404: "inaccessible", 409: "empty", 422: "request_rejected"}.get(status, "unavailable")
                    raise GitHubError(code)
                content = bytearray()
                for chunk in response.iter_bytes(chunk_size=65_536):
                    if len(content) + len(chunk) > cap:
                        raise GitHubError("response_limit")
                    content.extend(chunk)
                data = json.loads(content)
                if not isinstance(data, dict):
                    raise GitHubError("invalid_response")
                return data
        except GitHubError:
            raise
        except httpx.TimeoutException:
            raise GitHubError("timeout") from None
        except httpx.HTTPError:
            raise GitHubError("transport") from None
        except Exception:
            raise GitHubError("invalid_response") from None

    def authenticate(self, repository: str | None = None) -> None:
        if repository is not None:
            repository_name(repository)
        app_jwt = self._jwt()
        base = f"/app/installations/{self.settings.github_installation_id}"
        installation = self._request('GET', base, app_jwt)
        account = installation.get('account', {})
        if not isinstance(account, dict) or not isinstance(installation.get('permissions'), dict):
            raise GitHubError('invalid_response')
        if (installation.get('id') != self.settings.github_installation_id
                or installation.get('app_id') != self.settings.github_app_id
                or account.get('type') != 'User'
                or type(account.get('id')) is not int or account['id'] <= 0
                or str(account.get('login', '')).lower() != self.settings.github_owner.lower()):
            raise GitHubError("installation_mismatch")
        if installation.get('suspended_at') is not None:
            raise GitHubError("installation_suspended")
        if installation.get('permissions', {}).get('contents') not in {'read', 'write'}:
            raise GitHubError("contents_permission")
        if installation.get('repository_selection') not in {'all', 'selected'}:
            raise GitHubError('invalid_response')
        self.installation = {"id": installation['id'], "app_id": installation['app_id'],
                             "owner": self.settings.github_owner, "owner_id": account['id'],
                             "repository_selection": installation.get('repository_selection')}
        body: dict[str, Any] = {"permissions": {"contents": "read", "metadata": "read"}}
        if repository is not None:
            body['repositories'] = [repository]
        try:
            issued = self._request('POST', base + '/access_tokens', app_jwt, body=body)
        except GitHubError as exc:
            if repository is not None and exc.code == 'request_rejected':
                raise GitHubError('inaccessible') from None
            raise
        try:
            expires = datetime.fromisoformat(issued['expires_at'].replace('Z', '+00:00'))
            permissions = issued['permissions']
            if (expires.tzinfo is None or not 60 < expires.timestamp() - time.time() <= 3900
                    or not isinstance(issued['token'], str) or not issued['token']
                    or permissions.get('contents') != 'read'
                    or any(value != 'read' for value in permissions.values())
                    or set(permissions) - {'contents', 'metadata'}):
                raise ValueError
        except Exception:
            raise GitHubError("invalid_response") from None
        self._token = SecretStr(issued['token'])
        self._expires = expires.timestamp()
        self._repository = repository

    def get(self, path: str, *, limit: int | None = None) -> dict[str, Any]:
        if self._token is None or time.time() >= self._expires - 60:
            self.authenticate(self._repository)
        assert self._token is not None
        return self._request('GET', path, self._token.get_secret_value(), limit=limit)


def get_github_client() -> GitHubClient:
    return GitHubClient(get_settings())
