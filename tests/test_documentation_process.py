"""Isolated real HTTP/forked RQ pipeline; both models are authored stubs."""

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

from tests.test_documentation_preview import create_inspection

BOOTSTRAP = """
from rq import Worker
from personal_dot import documentation_preview
from personal_dot.queue import get_queue, get_redis
from tests.test_documentation_preview import Models
documentation_preview.get_documentation_service = Models().service
Worker([get_queue()], connection=get_redis()).work(burst=True, with_scheduler=False)
"""


def test_documentation_through_http_and_forked_worker(tmp_path):
    body = create_inspection()
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1', 0))
        port = reservation.getsockname()[1]
    env = {**os.environ, 'API_HOST': '127.0.0.1', 'API_PORT': str(port),
           'OPENAI_API_KEY': '', 'PUSHOVER_API_TOKEN': '', 'PUSHOVER_USER_KEY': '',
           'GITHUB_OWNER': 'zkralec', 'DOCS_PREVIEW_LIVE_ENABLED': 'false', 'RUN_OPENAI_INTEGRATION': '0'}
    def request(path, payload=None):
        data = None if payload is None else json.dumps(payload).encode()
        with urllib.request.urlopen(urllib.request.Request(f'http://127.0.0.1:{port}'+path,
            data=data, headers={'Content-Type': 'application/json'}), timeout=3) as response:
            return json.load(response)
    processes = []
    with (tmp_path/'documentation-process.log').open('w+') as log:
        try:
            api = subprocess.Popen([sys.executable, '-m', 'personal_dot.server'], env=env, stdout=log, stderr=subprocess.STDOUT)
            processes.append(api)
            for _ in range(80):
                try:
                    assert request('/health')['status'] == 'ok'; break
                except (urllib.error.URLError, OSError):
                    assert api.poll() is None; time.sleep(.1)
            else: raise AssertionError('Isolated API did not start')
            accepted = request('/tasks', body)
            worker = subprocess.Popen([sys.executable, '-c', BOOTSTRAP], env=env, stdout=log, stderr=subprocess.STDOUT)
            processes.append(worker)
            assert worker.wait(timeout=30) == 0
            task = request('/tasks/'+accepted['id'])
            assert task['status'] == 'succeeded' and task['result']['outcome'] == 'approved_candidate'
            assert task['result']['validation']['passed'] and task['result']['review']['valid']
            assert set(task['result']['calls']) == {'editor', 'reviewer'}
            assert task['execution_metadata']['usage']['total_tokens'] == 40
            assert 'notification' not in task['execution_metadata']
            assert request('/schedules') == []
            assert request('/tasks/'+task['id']+'/tool-calls') == []
        finally:
            for process in reversed(processes):
                if process.poll() is None:
                    process.terminate()
                    try: process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill(); process.wait(timeout=5)
