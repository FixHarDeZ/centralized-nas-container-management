#!/usr/bin/env python3
"""Trusted host deployment daemon. Never run inside a coding worker.

Only operator-owned configuration supplies commands and credentials. A verified
backend bearer credential authenticates the X-Desk-User identity assertion.
"""
from __future__ import annotations

import argparse
import contextlib
import hmac
import fcntl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import queue
import re
import selectors
import signal
import ssl
import subprocess
import threading
import time
import uuid

LOG_LIMIT = 32768
GITHUB = re.compile(r'https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?\Z')
SHA = re.compile(r'[0-9a-f]{40}\Z')


class RequestError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


class Runner:
    def __init__(self, root, profiles, *, token, repository_resolver=None, environment=None):
        if not token or '\n' in token: raise ValueError('nonempty bearer token required')
        self.token = token
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.root, 0o700)
        self.config = {}
        for source in profiles:
            p = dict(source)
            if not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', p.get('id', '')): raise ValueError('invalid profile id')
            if p['id'] in self.config: raise ValueError('duplicate profile id')
            if not GITHUB.fullmatch(p.get('repository', '')): raise ValueError('repository must be GitHub HTTPS')
            p.setdefault('branch', 'main')
            if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_./-]{0,150}', p['branch']) or '..' in p['branch'] or p['branch'].endswith('/'):
                raise ValueError('invalid branch')
            if not isinstance(p.get('allowed_users'), list) or not p['allowed_users'] or not all(isinstance(u,str) and u.strip() for u in p['allowed_users']):
                raise ValueError('explicit allowed_users required')
            for key in ('command', 'health_command'):
                if not isinstance(p.get(key), list) or not p[key] or not all(isinstance(a,str) and a and '\0' not in a for a in p[key]):
                    raise ValueError('deployment and health argv required')
            p['timeout'] = float(p.get('timeout', 900))
            if not 0 < p['timeout'] <= 86400: raise ValueError('invalid timeout')
            self.config[p['id']] = p
        source_env = dict(os.environ if environment is None else environment)
        self.source_env = source_env
        basic = {'PATH', 'HOME', 'LANG', 'LC_ALL', 'TZ', 'TMPDIR', 'SYSTEMROOT'}
        self.env = {key: value for key, value in source_env.items() if key in basic}
        self.env.update(GIT_TERMINAL_PROMPT='0', GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull)
        # Git configuration injected through the environment must not rewrite URLs
        # or execute arbitrary hooks while preparing the trusted checkout.
        for key in list(self.env):
            if key.startswith(('GIT_CONFIG_KEY_', 'GIT_CONFIG_VALUE_')) or key in ('GIT_CONFIG_COUNT','GIT_DIR','GIT_WORK_TREE','GIT_INDEX_FILE'):
                self.env.pop(key)
        self.secrets = sorted({token, *(v for k,v in source_env.items() if k not in basic and len(v) >= 4)}, key=len, reverse=True)
        self.resolve_repo = repository_resolver or (lambda p: p['repository'])
        self.instance_lock = open(self.root/'runner.lock', 'a')
        try: fcntl.flock(self.instance_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.instance_lock.close()
            raise ValueError('runner data directory already in use') from None
        self.lock = threading.RLock()
        self.pending = queue.Queue()
        self.stopping = threading.Event()
        self.records = json.loads((self.root/'jobs.json').read_text()) if (self.root/'jobs.json').exists() else {}
        for j in self.records.values():
            if j['status'] in ('queued','running'):
                j.update(status='failed', log=self.clean(j.get('log','')+'\nRunner restarted; job interrupted.'))
        self.persist()
        self.thread = threading.Thread(target=self.work, daemon=True)
        self.thread.start()

    def __enter__(self): return self
    def __exit__(self, *_): self.close()
    def close(self):
        self.stopping.set(); self.pending.put(None); self.thread.join(timeout=10)
        if not self.thread.is_alive(): self.instance_lock.close()

    def clean(self, text):
        for secret in self.secrets: text = text.replace(secret, '[REDACTED]')
        text = re.sub(r'(?i)(bearer\s+)[^\s]+', r'\1[REDACTED]', text)
        text = re.sub(r'(?i)(password|token|secret|api_key)(\s*[=:]\s*)[^\s]+', r'\1\2[REDACTED]', text)
        return text[-LOG_LIMIT:]

    def persist(self):
        with self.lock:
            tmp = self.root/'jobs.tmp'
            with open(tmp,'w',encoding='utf-8') as f:
                os.chmod(tmp,0o600); json.dump(self.records,f); f.flush(); os.fsync(f.fileno())
            tmp.replace(self.root/'jobs.json')

    def profiles(self, owner):
        return [{k:p[k] for k in ('id','repository','branch')} for p in self.config.values() if owner in p['allowed_users']]

    def public(self, j): return {k:v for k,v in j.items() if k != 'owner'}
    def jobs(self, owner):
        with self.lock: return [self.public(j) for j in self.records.values() if j['owner']==owner]
    def job(self, owner, ident):
        with self.lock:
            j=self.records.get(ident)
            if not j or j['owner']!=owner: raise RequestError('job not found',404)
            return self.public(j)

    def submit(self, owner, body):
        if not isinstance(body,dict) or set(body)!= {'profile','sha'} or not isinstance(body['profile'],str) or not isinstance(body['sha'],str) or not SHA.fullmatch(body['sha']):
            raise RequestError('exactly profile and full lowercase commit sha required')
        p=self.config.get(body['profile'])
        if not p or owner not in p['allowed_users']: raise RequestError('profile unavailable',403)
        with self.lock:
            if sum(j['status'] in ('queued','running') for j in self.records.values()) >= 100: raise RequestError('queue full',429)
            j={'id':uuid.uuid4().hex,'owner':owner,'profile':p['id'],'sha':body['sha'],'status':'queued','log':'','created_at':time.time()}
            self.records[j['id']]=j; self.persist(); self.pending.put(j['id'])
            return self.public(j)

    def update(self, j, **fields):
        with self.lock: j.update(fields); self.persist()

    def command_env(self, profile):
        env = dict(self.env)
        for key in profile.get('environment_allowlist', []):
            if key.startswith(('AI_DECK_DEPLOY_TOKEN', 'GIT_CONFIG_', 'GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE', 'PYTHONPATH', 'LD_', 'DYLD_')):
                continue
            if key in self.source_env:
                env[key] = self.source_env[key]
        return env

    def execute(self, argv, cwd, timeout, *, j=None, environment=None):
        """Drain output continuously with fixed memory; terminate whole process group."""
        proc=subprocess.Popen(argv,cwd=cwd,env=environment or self.env,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,start_new_session=True)
        deadline=time.monotonic()+timeout
        output=bytearray(); timed_out=False; overflow=False
        with selectors.DefaultSelector() as selector:
            selector.register(proc.stdout,selectors.EVENT_READ)
            try:
                while selector.get_map():
                    if self.stopping.is_set() or time.monotonic()>deadline:
                        timed_out=True; break
                    for key,_ in selector.select(.05):
                        chunk=os.read(key.fileobj.fileno(),8192)
                        if not chunk: selector.unregister(key.fileobj); continue
                        if not overflow:
                            output.extend(chunk)
                            if len(output)>LOG_LIMIT:
                                # Dropping all captured output avoids exposing part
                                # of a secret split by a truncation boundary.
                                output.clear(); overflow=True
                while proc.poll() is None and time.monotonic()<deadline and not self.stopping.is_set(): time.sleep(.01)
                if proc.poll() is None: timed_out=True
            finally:
                # Also reap orphaned grandchildren after the direct child exits.
                with contextlib.suppress(ProcessLookupError): os.killpg(proc.pid,signal.SIGKILL)
                proc.wait(); proc.stdout.close()
        raw='[output exceeded log limit; omitted]' if overflow else output.decode('utf-8','replace')
        result=self.clean(raw)
        if j is not None: self.update(j,log=self.clean(j['log']+'\n'+result))
        if timed_out: raise RuntimeError('command timed out or runner stopped')
        if proc.returncode: raise RuntimeError('command failed (exit '+str(proc.returncode)+')')
        return raw.strip()

    def work(self):
        while not self.stopping.is_set():
            ident=self.pending.get()
            if ident is None: break
            j=self.records[ident]; p=self.config[j['profile']]
            self.update(j,status='running')
            checkout=self.root/'checkouts'/ident
            environment = self.command_env(p)
            try:
                checkout.mkdir(parents=True,mode=0o700)
                self.execute(['git','init','--quiet',str(checkout)],self.root,60, environment=environment)
                self.execute(['git','-C',str(checkout),'remote','add','origin',self.resolve_repo(p)],self.root,60, environment=environment)
                self.execute(['git','-C',str(checkout),'fetch','--quiet','--no-tags','--depth=1','origin','refs/heads/'+p['branch']],self.root,120, environment=environment)
                tip=self.execute(['git','-C',str(checkout),'rev-parse','FETCH_HEAD'],self.root,30, environment=environment)
                if tip!=j['sha']: raise RuntimeError('requested SHA does not equal configured remote branch tip')
                self.execute(['git','-C',str(checkout),'checkout','--quiet','--detach',tip],self.root,60, environment=environment)
                self.execute(p['command'],checkout,p['timeout'],j=j, environment=environment)
                self.execute(p['health_command'],checkout,p['timeout'],j=j, environment=environment)
                self.update(j,status='succeeded',finished_at=time.time())
            except Exception as exc:
                # Never include subprocess argv, paths, environment, or raw stderr.
                message=str(exc) if isinstance(exc,RuntimeError) else type(exc).__name__
                self.update(j,status='failed',finished_at=time.time(),log=self.clean(j['log']+'\n'+message))
            finally:
                import shutil
                shutil.rmtree(checkout,ignore_errors=True)


def make_server(runner, host='127.0.0.1', port=8792):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*_): pass
        def handle_request(self):
            try:
                auth=self.headers.get('Authorization','')
                owner=self.headers.get('X-Desk-User','')
                if not hmac.compare_digest(auth.encode(),('Bearer '+runner.token).encode()) or not owner.strip() or len(owner)>256:
                    raise RequestError('unauthorized',401)
                if self.command=='GET' and self.path=='/deploy/profiles': result={'items':runner.profiles(owner)}
                elif self.command=='GET' and self.path=='/deploy/jobs': result={'items':runner.jobs(owner)}
                elif self.command=='GET' and re.fullmatch(r'/deploy/jobs/[a-f0-9]{32}',self.path): result=runner.job(owner,self.path.rsplit('/',1)[1])
                elif self.command=='POST' and self.path=='/deploy/jobs':
                    try: length=int(self.headers.get('Content-Length','0'))
                    except ValueError: raise RequestError('invalid content length')
                    if not 0<length<=4096: raise RequestError('request body too large or empty',413)
                    self.connection.settimeout(10)
                    try: body=json.loads(self.rfile.read(length))
                    except (ValueError,UnicodeError): raise RequestError('invalid JSON')
                    result=runner.submit(owner,body)
                else: raise RequestError('not found',404)
                status=202 if self.command=='POST' else 200
            except RequestError as exc: result={'error':str(exc)}; status=exc.status
            except Exception: result={'error':'internal error'}; status=500
            data=json.dumps(result).encode()
            self.send_response(status); self.send_header('Content-Type','application/json'); self.send_header('Cache-Control','no-store'); self.send_header('Content-Length',str(len(data))); self.end_headers(); self.wfile.write(data)
        do_GET=handle_request
        do_POST=handle_request
    return ThreadingHTTPServer((host,port),Handler)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profiles',required=True); parser.add_argument('--data',required=True)
    parser.add_argument('--host',default='127.0.0.1'); parser.add_argument('--port',type=int,default=8792)
    parser.add_argument('--tls-cert'); parser.add_argument('--tls-key')
    parser.add_argument('--token-file',default=os.environ.get('AI_DECK_DEPLOY_TOKEN_FILE'))
    args=parser.parse_args()
    token=Path(args.token_file).read_text().strip() if args.token_file else os.environ.get('AI_DECK_DEPLOY_TOKEN','')
    with Runner(args.data,json.loads(Path(args.profiles).read_text()),token=token) as runner:
        server=make_server(runner,args.host,args.port)
        if bool(args.tls_cert) != bool(args.tls_key):
            parser.error('--tls-cert and --tls-key must be provided together')
        if args.tls_cert:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            context.load_cert_chain(args.tls_cert, args.tls_key)
            server.socket = context.wrap_socket(server.socket, server_side=True)
        # launchd's SIGTERM should stop active child process groups before exit.
        signal.signal(signal.SIGTERM, lambda *_: threading.Thread(target=server.shutdown, daemon=True).start())
        try: server.serve_forever()
        except KeyboardInterrupt: pass
        finally: server.server_close()

if __name__=='__main__': main()
