"""Real HTTP and forked RQ execution; GitHub is an in-process HTTP fixture."""

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

from tests.test_github import key_file  # Fixture creates an ephemeral synthetic key.

WORKER = """
import httpx
from rq import Worker
from personal_dot import jobs
from personal_dot.config import Settings
from personal_dot.github import GitHubClient
from personal_dot.queue import get_queue, get_redis
from tests.test_github import API
api = API()
api.add('README.md', b'# Synthetic repository evidence')
jobs.get_github_client = lambda: GitHubClient(Settings(), httpx.Client(transport=httpx.MockTransport(api)))
Worker([get_queue()], connection=get_redis()).work(burst=True, with_scheduler=False)
"""


def test_github_http_and_forked_worker(tmp_path, key_file):
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1', 0))
        port = reservation.getsockname()[1]
    env = {**os.environ, 'API_HOST': '127.0.0.1', 'API_PORT': str(port),
           'OPENAI_API_KEY': '', 'PUSHOVER_API_TOKEN': '', 'PUSHOVER_USER_KEY': '',
           'RUN_OPENAI_INTEGRATION': '0', 'GITHUB_OWNER': 'zkralec', 'GITHUB_APP_ID': '5519145',
           'GITHUB_INSTALLATION_ID': '176370838', 'GITHUB_APP_PRIVATE_KEY_PATH': str(key_file)}
    def request(path, payload=None):
        body = None if payload is None else json.dumps(payload).encode()
        with urllib.request.urlopen(urllib.request.Request(f'http://127.0.0.1:{port}' + path,
            data=body, headers={'Content-Type': 'application/json'}), timeout=3) as response:
            return json.load(response)
    processes = []
    with (tmp_path / 'github-process.log').open('w+') as log:
        try:
            api = subprocess.Popen([sys.executable, '-m', 'personal_dot.server'], env=env,
                                   stdout=log, stderr=subprocess.STDOUT)
            processes.append(api)
            for _ in range(80):
                try:
                    assert request('/health')['status'] == 'ok'
                    break
                except (urllib.error.URLError, OSError):
                    assert api.poll() is None
                    time.sleep(.1)
            else:
                raise AssertionError('Isolated API did not start')
            listing = request('/tasks', {'type': 'github_discover'})
            inspection = request('/tasks', {'type': 'github_inspect', 'payload': {'repository': 'repo'}})
            worker = subprocess.Popen([sys.executable, '-c', WORKER], env=env,
                                      stdout=log, stderr=subprocess.STDOUT)
            processes.append(worker)
            assert worker.wait(timeout=30) == 0
            listed = request('/tasks/' + listing['id'])
            inspected = request('/tasks/' + inspection['id'])
            assert listed['status'] == inspected['status'] == 'succeeded'
            assert listed['result']['repositories'][0]['name'] == 'repo'
            assert inspected['result']['commit'] == 'c' * 40
            assert inspected['result']['files'][0]['path'] == 'README.md'
            assert 'notification' not in inspected['execution_metadata']
            assert request('/schedules') == []
            assert request('/tasks/' + inspection['id'] + '/tool-calls') == []
            log.flush()
            assert 'ghs_fixture_token' not in (tmp_path / 'github-process.log').read_text()
        finally:
            for process in reversed(processes):
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
