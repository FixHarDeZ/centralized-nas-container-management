"""Supervise an outbound SSH connection exposing the TLS runner through a NAS socket."""
import argparse
import json
from pathlib import PurePosixPath, Path
import re
import shlex
import signal
import subprocess
import time


def settings(path):
    config = json.loads(Path(path).read_text())
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', config['ssh_host']):
        raise ValueError('Use a configured SSH host alias')
    remote = PurePosixPath(config['socket_path'])
    if not remote.is_absolute() or '..' in remote.parts or ':' in str(remote) or len(str(remote).encode()) > 100:
        raise ValueError('Use an absolute, short Unix socket path')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+', config['runner_host']):
        raise ValueError('Invalid runner host')
    for key in ('runner_port', 'health_local_port', 'health_remote_port'):
        if type(config[key]) is not int or not 1024 <= config[key] <= 65535:
            raise ValueError('Invalid port')
    return config


def ssh_command(config):
    return ['ssh', '-NT', '-o', 'BatchMode=yes', '-o', 'ExitOnForwardFailure=yes',
            '-o', 'ServerAliveInterval=30', '-o', 'ServerAliveCountMax=3',
            '-o', 'StreamLocalBindUnlink=yes',
            '-R', f"{config['socket_path']}:{config['runner_host']}:{config['runner_port']}",
            '-L', f"127.0.0.1:{config['health_local_port']}:127.0.0.1:{config['health_remote_port']}",
            config['ssh_host']]


def run(config):
    remote = shlex.quote(config['socket_path'])
    directory = shlex.quote(str(PurePosixPath(config['socket_path']).parent))
    prefix = ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', config['ssh_host']]
    subprocess.run(prefix + [f'mkdir -p {directory} && chmod 2770 {directory}'], check=True, timeout=20)
    process = subprocess.Popen(ssh_command(config))
    def stop(signum, frame):
        process.terminate()
    old_handlers = {s: signal.signal(s, stop) for s in (signal.SIGTERM, signal.SIGINT)}
    try:
        for _ in range(20):
            if process.poll() is not None:
                raise RuntimeError('SSH tunnel stopped during startup')
            result = subprocess.run(prefix + [f'test -S {remote} && test -w {remote}'], timeout=20, capture_output=True)
            if result.returncode == 0:
                print('Deployment tunnel ready', flush=True)
                return process.wait()
            time.sleep(0.5)
        raise RuntimeError('Forwarded socket did not become ready')
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        for sig, handler in old_handlers.items():
            signal.signal(sig, handler)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    args = parser.parse_args()
    raise SystemExit(run(settings(args.config)))
