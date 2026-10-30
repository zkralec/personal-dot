"""Real HTTP, forked RQ and dedicated scheduler; no external/paid providers."""
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

from tests.test_github import key_file
from tests.test_documentation_maintenance import CONFIG

WORKER = """
import os,httpx
from dataclasses import replace
from rq import Worker
from personal_dot import jobs,documentation_preview,documentation_publish,documentation_maintenance
from personal_dot.config import Settings,get_settings
from personal_dot.github import GitHubClient
from personal_dot.github_publication import PublishingGitHubClient
from personal_dot.queue import get_queue,get_redis
from tests.test_documentation_preview import Models
from tests.test_documentation_maintenance import MaintenanceGitHub
assert os.geteuid()!=0
api=MaintenanceGitHub()
settings=get_settings()
jobs.get_github_client=lambda: GitHubClient(settings,httpx.Client(transport=httpx.MockTransport(api)))
def publisher(write):
 c=PublishingGitHubClient(settings,httpx.Client(transport=httpx.MockTransport(api)))
 if not write: c.permissions={k:'read' for k in c.permissions}
 return c
documentation_publish.get_publication_client=publisher
documentation_maintenance.get_publication_client=publisher
models=Models()
def service(role,request):
 s=models.service(role,request)
 original=s.create_turn
 def call(*args,**kwargs):
  turn=original(*args,**kwargs)
  return replace(turn,metadata={**turn.metadata,'model':documentation_preview.configuration(request)[role+'_model']})
 s.create_turn=call
 return s
documentation_preview.get_documentation_service=service
Worker([get_queue()],connection=get_redis()).work(burst=True,with_scheduler=False)
"""


def test_http_worker_scheduler_maintenance_lifecycle(tmp_path, key_file):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
    env = {**os.environ, 'API_HOST': '127.0.0.1', 'API_PORT': str(port),
           'OPENAI_API_KEY': '', 'PUSHOVER_API_TOKEN': '', 'PUSHOVER_USER_KEY': '',
           'GITHUB_OWNER': 'zkralec', 'GITHUB_APP_ID': '5519145', 'GITHUB_INSTALLATION_ID': '176370838',
           'GITHUB_APP_PRIVATE_KEY_PATH': str(key_file), 'DOCS_PREVIEW_LIVE_ENABLED': 'true',
           'DOCS_PUBLISH_LIVE_ENABLED': 'true', 'DOCS_MAINTENANCE_LIVE_ENABLED': 'true',
           'RUN_OPENAI_INTEGRATION': '0', 'DOCS_PUBLISH_CHECK_POLLS': '1'}
    def request(path, payload=None, method=None):
        body = None if payload is None else json.dumps(payload).encode()
        with urllib.request.urlopen(urllib.request.Request(f'http://127.0.0.1:{port}'+path,
            data=body, method=method, headers={'Content-Type':'application/json'}), timeout=5) as response:
            return json.load(response)
    processes=[]
    with (tmp_path/'maintenance-process.log').open('w+') as log:
        try:
            api=subprocess.Popen([sys.executable,'-m','personal_dot.server'],env=env,stdout=log,stderr=subprocess.STDOUT)
            processes.append(api)
            for _ in range(80):
                try:
                    assert request('/health')['status']=='ok'; break
                except (urllib.error.URLError,OSError):
                    assert api.poll() is None; time.sleep(.1)
            else: raise AssertionError('API not ready')
            control=request('/maintenance/configuration',CONFIG,method='PUT')
            accepted=request('/tasks',{'type':'documentation_maintenance','payload':{'pilot':True},'notification_policy':'none'})
            worker=subprocess.Popen([sys.executable,'-c',WORKER],env=env,stdout=log,stderr=subprocess.STDOUT)
            processes.append(worker); assert worker.wait(timeout=30)==0
            result=request('/tasks/'+accepted['id'])
            assert result['status']=='succeeded' and result['result']['outcome']=='merged',result
            assert request('/maintenance')['pilot_succeeded']
            assert request('/maintenance',{'action':'resume'},method='PATCH')['enabled']
            scheduler=subprocess.Popen([sys.executable,'-m','personal_dot.scheduler'],env=env,stdout=log,stderr=subprocess.STDOUT)
            processes.append(scheduler)
            time.sleep(.3)
            assert scheduler.poll() is None
            assert request('/maintenance',{'action':'pause'},method='PATCH')['paused']
            assert not request('/schedules/'+control['schedule_id'])['enabled']
            assert len(request('/maintenance/budgets'))==1
            log.flush()
            assert 'ghs_synthetic_publication_secret' not in (tmp_path/'maintenance-process.log').read_text()
        finally:
            for process in reversed(processes):
                if process.poll() is None:
                    process.terminate()
                    try: process.wait(timeout=5)
                    except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)
