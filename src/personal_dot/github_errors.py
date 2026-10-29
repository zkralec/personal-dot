"""Application-authored GitHub diagnostics; never retain provider bodies."""

MESSAGES = {
    "configuration_missing": "GitHub owner, app ID, installation ID and private-key path must be configured",
    "key_missing": "GITHUB_APP_PRIVATE_KEY_PATH does not exist",
    "key_unreadable": "GITHUB_APP_PRIVATE_KEY_PATH is not readable by the worker",
    "key_permissions": "GitHub private key must be a regular owner-only file owned by the worker UID",
    "key_invalid": "GitHub private key is not a valid unencrypted RSA PEM of at least 2048 bits",
    "installation_mismatch": "GitHub installation does not match the configured personal owner and app",
    "installation_suspended": "GitHub installation is suspended",
    "contents_permission": "GitHub App installation requires Contents read permission",
    "authentication_rejected": "GitHub rejected application or installation authentication",
    "forbidden": "GitHub access forbidden; verify installation permissions",
    "rate_limited": "GitHub rate limit reached; retry later",
    "inaccessible": "GitHub repository or resource is missing or inaccessible to this installation",
    "empty": "GitHub repository has no commit to inspect",
    "request_rejected": "GitHub rejected the read request or repository token scope",
    "unavailable": "GitHub service unavailable",
    "timeout": "GitHub request timed out",
    "transport": "GitHub connection failed",
    "redirect": "GitHub redirect rejected; verify repository identity",
    "invalid_response": "GitHub returned an invalid response",
    "response_limit": "GitHub response exceeded the configured byte limit",
    "unsupported": "GitHub repository is unsupported for bounded inspection",
    "overlap": "Another repository inspection is active; submit one repository at a time",
}


class GitHubError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code if code in MESSAGES else "invalid_response"
        super().__init__(MESSAGES[self.code])


def safe_code(error: GitHubError) -> str:
    return error.code if error.code in MESSAGES else "invalid_response"


def safe_message(error: GitHubError) -> str:
    return MESSAGES[safe_code(error)]
