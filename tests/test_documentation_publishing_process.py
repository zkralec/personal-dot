"""Real HTTP/forked non-root RQ lifecycle, simulated GitHub and model services."""

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

from tests.test_documentation_preview import create_inspection
from tests.test_github import key_file

WORKER = """
import os
import httpx
from rq import Worker
from personal_dot import documentation_preview, documentation_publish
from personal_dot.config import Settings, get_settings
from personal_dot.github_publication import PublishingGitHubClient
from personal_dot.queue import get_queue, get_redis
from tests.test_documentation_preview import Models
from tests.test_documentation_publish import GitHubService
assert os.geteuid() != 0
documentation_preview.get_documentation_service = Models().service
api = GitHubService()
documentation_publish.get_publication_client = lambda write: PublishingGitHubClient(Settings(), httpx.Client(transport=httpx.MockTransport(api)))
get_settings().docs_publish_live_enabled = True
Worker([get_queue()], connection=get_redis()).work(burst=True, with_scheduler=False)
"""


def test_publication_http_and_forked_worker(tmp_path, key_file):
    body = create_inspection()
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1', 0))
        port = reservation.getsockname()[1]
    env = {**os.environ, 'API_HOST': '127.0.0.1', 'API_PORT': str(port),
           'OPENAI_API_KEY': '', 'PUSHOVER_API_TOKEN': '', 'PUSHOVER_USER_KEY': '',
           'RUN_OPENAI_INTEGRATION': '0', 'GITHUB_OWNER': 'zkralec', 'GITHUB_APP_ID': '5519145',
           'GITHUB_INSTALLATION_ID': '176370838', 'GITHUB_APP_PRIVATE_KEY_PATH': str(key_file),
           'DOCS_PREVIEW_LIVE_ENABLED': 'false', 'DOCS_PUBLISH_LIVE_ENABLED': 'false'}
    def request(path, payload=None):
        data = None if payload is None else json.dumps(payload).encode()
        with urllib.request.urlopen(urllib.request.Request(f'http://127.0.0.1:{port}' + path,
            data=data, headers={'Content-Type': 'application/json'}), timeout=3) as response:
            return json.load(response)
    processes = []
    with (tmp_path / 'publication-process.log').open('w+') as log:
        try:
            server = subprocess.Popen([sys.executable, '-m', 'personal_dot.server'], env=env, stdout=log, stderr=subprocess.STDOUT)
            processes.append(server)
            for _ in range(80):
                try:
                    assert request('/health')['status'] == 'ok'
                    break
                except (urllib.error.URLError, OSError):
                    assert server.poll() is None
                    time.sleep(.1)
            else:
                raise AssertionError('Isolated API did not start')
            preview = request('/tasks', body)
            def work():
                worker = subprocess.Popen([sys.executable, '-c', WORKER], env=env, stdout=log, stderr=subprocess.STDOUT)
                processes.append(worker)
                assert worker.wait(timeout=30) == 0
            work()
            approved = request('/tasks/' + preview['id'])
            assert approved['result']['outcome'] == 'approved_candidate'
            task = request('/tasks', {'type': 'documentation_publish', 'payload': {'preview_task_id': preview['id'], 'allow_publish': True}})
            work()
            result = request('/tasks/' + task['id'])
            assert result['status'] == 'succeeded', result
            assert result['result']['published'] and result['result']['merged']
            assert result['result']['branch_deleted'] and not result['result']['deployed']
            assert result['result']['attribution']['author']['email'] == '157630586+zkralec@users.noreply.github.com'
            assert request('/schedules') == []
            assert request('/tasks/' + task['id'] + '/tool-calls') == []
            log.flush()
            assert 'ghs_synthetic_publication_secret' not in (tmp_path / 'publication-process.log').read_text()
        finally:
            for process in reversed(processes):
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
