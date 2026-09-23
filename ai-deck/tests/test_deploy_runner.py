"""Separate trusted runner; commands here only touch temporary repositories."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError

import pytest


def test_child_environment_excludes_runner_and_unrelated_credentials(setup, monkeypatch):
    repo, p, factory = setup
    monkeypatch.setenv('AI_DECK_DEPLOY_TOKEN', 'private-runner-token')
    monkeypatch.setenv('AI_DECK_DEPLOY_TOKEN_FILE', '/private/runner-token')
    monkeypatch.setenv('DATABASE_URL', 'private-database-url')
    p['environment_allowlist'] = ['AI_DECK_DEPLOY_TOKEN', 'AI_DECK_DEPLOY_TOKEN_FILE']
    p['command'] = [sys.executable, '-c', 'import os; assert not any(k in os.environ for k in ("AI_DECK_DEPLOY_TOKEN", "AI_DECK_DEPLOY_TOKEN_FILE", "DATABASE_URL"))']
    with factory() as runner:
        job = finish(runner, runner.submit('alice', {'profile':'nas', 'sha':git(repo, 'rev-parse', 'HEAD')}))
        assert job['status'] == 'succeeded'

spec = importlib.util.spec_from_file_location('deploy_runner', Path(__file__).parents[1] / 'deploy_runner.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], text=True).strip()


@pytest.fixture
def setup(tmp_path):
    repo = tmp_path / 'origin'; repo.mkdir()
    git(repo, 'init', '-b', 'main')
    git(repo, 'config', 'user.email', 'test@example.com'); git(repo, 'config', 'user.name', 'Test')
    (repo / 'tracked').write_text('original')
    git(repo, 'add', '.'); git(repo, 'commit', '-m', 'initial')
    profile = {'id': 'nas', 'repository': 'https://github.com/example/repo.git', 'branch': 'main',
               'allowed_users': ['alice'], 'command': [sys.executable, '-c', 'print("deployed")'],
               'health_command': [sys.executable, '-c', 'print("healthy")'], 'timeout': 2}
    def runner(**kw):
        return m.Runner(tmp_path / 'data', [profile], token='a-long-test-token',
                        repository_resolver=lambda p: str(repo), **kw)
    return repo, profile, runner


def finish(runner, job):
    for _ in range(300):
        result = runner.job('alice', job['id'])
        if result['status'] in ('succeeded', 'failed'): return result
        time.sleep(.02)
    pytest.fail('job did not finish')


def test_exact_tip_clean_checkout_and_health(setup):
    repo, p, factory = setup
    (repo / 'tracked').write_text('dirty')
    p['command'] = [sys.executable, '-c', 'from pathlib import Path; assert Path("tracked").read_text()=="original"; print("deployed")']
    with factory() as r:
        j = finish(r, r.submit('alice', {'profile': 'nas', 'sha': git(repo, 'rev-parse', 'HEAD')}))
        assert j['status'] == 'succeeded'
        assert 'healthy' in j['log']
        with pytest.raises(m.RequestError): r.job('bob', j['id'])
        assert r.jobs('bob') == []
        assert r.profiles('alice') == [{'id': 'nas', 'repository': p['repository'], 'branch': 'main'}]
        assert r.profiles('bob') == []


def test_validation_and_stale_revision(setup):
    repo, p, factory = setup
    with factory() as r:
        for body in ({}, {'profile':'nas','sha':'main'}, {'profile':'nas','sha':'a'*40,'command':['id']}):
            with pytest.raises(m.RequestError): r.submit('alice', body)
        with pytest.raises(m.RequestError): r.submit('bob', {'profile':'nas','sha':'a'*40})
        j = finish(r, r.submit('alice', {'profile':'nas','sha':'a'*40}))
        assert j['status'] == 'failed' and 'branch tip' in j['log']


@pytest.mark.parametrize('command,health,expected', [
    ('import sys;sys.exit(3)', 'print("healthy")', 'failed'),
    ('print("deployed")', 'import sys;sys.exit(4)', 'failed'),
    ('import time;time.sleep(10)', 'print("healthy")', 'failed'),
])
def test_failure_health_and_timeout(setup, command, health, expected):
    repo,p,factory=setup
    p.update(command=[sys.executable,'-c',command], health_command=[sys.executable,'-c',health], timeout=.2)
    with factory() as r:
        assert finish(r,r.submit('alice',{'profile':'nas','sha':git(repo,'rev-parse','HEAD')}))['status']==expected


def test_logs_redacted_bounded_and_serialized(setup, monkeypatch):
    repo,p,factory=setup
    monkeypatch.setenv('TEST_API_KEY','super-sensitive-fixture')
    setup[1]['environment_allowlist'] = ['TEST_API_KEY']
    p['command']=[sys.executable,'-c','import os,time; print(os.environ["TEST_API_KEY"]); print("x"*100000); time.sleep(.2)']
    with factory() as r:
        a=r.submit('alice',{'profile':'nas','sha':git(repo,'rev-parse','HEAD')})
        b=r.submit('alice',{'profile':'nas','sha':git(repo,'rev-parse','HEAD')})
        assert r.job('alice',b['id'])['status']=='queued'
        for j in (finish(r,a),finish(r,b)):
            assert 'super-sensitive-fixture' not in j['log']
            assert len(j['log']) <= m.LOG_LIMIT
        assert 'super-sensitive-fixture' not in (r.root / 'jobs.json').read_text()


def test_restart_and_config_validation(setup):
    repo,p,factory=setup
    with factory() as r: root=r.root
    (root/'jobs.json').write_text(json.dumps({'j':{'id':'j','owner':'alice','status':'running','log':''}}))
    with factory() as r: assert r.job('alice','j')['status']=='failed'
    p['repository']='file:///tmp/evil'
    with pytest.raises(ValueError): m.Runner(root,[p],token='token')
    p['repository']='https://github.com/example/repo'; p['health_command']=[]
    with pytest.raises(ValueError): factory()


def test_http_trusted_identity_and_contract(setup):
    repo,p,factory=setup
    with factory() as r:
        server=m.make_server(r,'127.0.0.1',0)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base='http://127.0.0.1:'+str(server.server_port)
        try:
            for headers in ({'X-Desk-User':'alice'}, {'Authorization':'Bearer wrong','X-Desk-User':'alice'}, {'Authorization':'Bearer a-long-test-token'}):
                with pytest.raises(HTTPError) as e: urlopen(Request(base+'/deploy/profiles',headers=headers))
                assert e.value.code==401
            headers={'Authorization':'Bearer a-long-test-token','X-Desk-User':'alice'}
            assert json.load(urlopen(Request(base+'/deploy/profiles',headers=headers)))['items'][0]['id']=='nas'
            body=json.dumps({'profile':'nas','sha':git(repo,'rev-parse','HEAD')}).encode()
            j=json.load(urlopen(Request(base+'/deploy/jobs',data=body,headers=headers)))
            assert j['id']
            assert 'items' in json.load(urlopen(Request(base+'/deploy/jobs',headers=headers)))
        finally: server.shutdown();server.server_close();thread.join()


def test_small_stderr_secret_is_redacted_and_lock_exclusive(setup, monkeypatch):
    repo,p,factory=setup
    monkeypatch.setenv('FAKE_SECRET','runner-secret-value-123')
    setup[1]['environment_allowlist'] = ['FAKE_SECRET']
    p['command']=[sys.executable,'-c','import os,sys; sys.stderr.write(os.environ["FAKE_SECRET"]);sys.exit(1)']
    with factory() as r:
        with pytest.raises(ValueError,match='already in use'): factory()
        j=finish(r,r.submit('alice',{'profile':'nas','sha':git(repo,'rev-parse','HEAD')}))
        assert j['status']=='failed'
        assert 'runner-secret-value-123' not in j['log']
        assert '[REDACTED]' in j['log']
        assert 'runner-secret-value-123' not in (r.root/'jobs.json').read_text()


def test_nas_adapter_external_provisioning_only(tmp_path):
    root=tmp_path/'checkout'; (root/'scripts').mkdir(parents=True); (root/'ai-deck').mkdir()
    git(root, 'init', '-b', 'main'); git(root, 'config', 'user.email', 'test@example.com'); git(root, 'config', 'user.name', 'Test')
    git(root, 'commit', '--allow-empty', '-m', 'initial')
    (root/'scripts'/'render_env.py').write_text('import sys; assert "--exclude" in sys.argv and "deploy" in sys.argv; print("secret-render-output")')
    (root/'scripts'/'deploy.sh').write_text('set -eu\nsource .env.deploy\ntest "$OPERATOR_VALUE" = trusted\necho secret-deploy-output\n')
    (root/'.env.deploy').write_text('exit 99\n')
    external=tmp_path/'operator.env'; external.write_text('OPERATOR_VALUE=trusted\n'); external.chmod(0o600)
    age=tmp_path/'age.key'; age.write_text('fake-key-not-used'); age.chmod(0o600)
    env={**os.environ,'AI_DECK_NAS_DEPLOY_ENV':str(external),'SOPS_AGE_KEY_FILE':str(age),'AI_DECK_DEPLOY_PYTHON':sys.executable}
    adapter=Path(__file__).parents[1]/'run-nas-deploy.sh'
    result=subprocess.run(['bash',str(adapter),'ai-deck'],cwd=root,env=env,text=True,capture_output=True)
    assert result.returncode==0,result.stderr
    assert 'secret-' not in result.stdout
    assert (root/'.env.deploy').read_text()=='OPERATOR_VALUE=trusted\n'
    env['AI_DECK_NAS_DEPLOY_ENV']=str(root/'.env.deploy')
    result=subprocess.run(['bash',str(adapter),'ai-deck'],cwd=root,env=env,text=True,capture_output=True)
    assert result.returncode!=0
    assert 'outside the checkout' in result.stderr
