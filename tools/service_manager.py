"""Local lifecycle helper. Secrets, logs and uploaded videos stay outside Git."""
import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
from urllib.request import ProxyHandler, build_opener

import psutil
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = Path(os.environ.get('FORTEBANK_PRIVATE_ROOT', str(Path.home() / 'Documents' / 'ForteBankPrivate')))
RUNTIME = PRIVATE / 'service_runtime'
ENV_FILE = RUNTIME / 'service.env'
STATE_FILE = RUNTIME / 'server.json'
URL = 'http://127.0.0.1:8000'


def initialize():
    RUNTIME.mkdir(parents=True, exist_ok=True)
    if not ENV_FILE.exists():
        model = Path(os.environ.get('MODEL_PATH', str(Path.home() / 'Documents' / 'Codex' /
                       'fortebank-local' / 'models' / 'Qwen3-VL-2B-Instruct')))
        if not model.is_dir():
            raise RuntimeError('Set MODEL_PATH to existing offline weights')
        values = {'API_KEY': secrets.token_urlsafe(40), 'ANALYSIS_MODE': 'real',
                  'MODEL_PATH': model.as_posix(), 'UPLOAD_DIR': (PRIVATE / 'service_uploads').as_posix(),
                  'WORKER_LOCK_PATH': (RUNTIME / 'gpu_worker.lock').as_posix()}
        ENV_FILE.write_text(''.join(f'{key}={value}\n' for key, value in values.items()), encoding='utf-8')
    return dotenv_values(ENV_FILE)


def health():
    try:
        with build_opener(ProxyHandler({})).open(URL + '/health', timeout=2) as response:
            return json.load(response)
    except (OSError, ValueError):
        return None


def managed_process():
    if not STATE_FILE.exists():
        return None
    state = json.loads(STATE_FILE.read_text(encoding='utf-8'))
    try:
        process = psutil.Process(state['pid'])
        if abs(process.create_time() - state['created_at']) > 0.1:
            return None
        if str(ROOT / 'start_backend.py').casefold() not in ' '.join(process.cmdline()).casefold():
            return None
        return process
    except (psutil.Error, KeyError):
        return None


def start():
    initialize()
    process = managed_process()
    if not process:
        if health() is not None:
            raise RuntimeError('Port 8000 belongs to another service; stop it first')
        env = os.environ.copy()
        env.update(FORTEBANK_ENV_FILE=str(ENV_FILE), HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
                   HF_HUB_DISABLE_TELEMETRY='1', PYTHONDONTWRITEBYTECODE='1',
                   INFERENCE_AUDIT_DIR=str(PRIVATE / 'inference_audit'))
        with (RUNTIME / 'server.log').open('ab') as log:
            child = subprocess.Popen([sys.executable, '-B', str(ROOT / 'start_backend.py'), '--mode', 'real'],
                cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        process = psutil.Process(child.pid)
        STATE_FILE.write_text(json.dumps({'pid': child.pid, 'created_at': process.create_time(),
                                        'source': str(ROOT), 'url': URL}), encoding='utf-8')
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        result = health()
        if result and result.get('ready'):
            print(json.dumps({'service': 'ready', 'url': URL, **result}))
            return
        if not process.is_running():
            raise RuntimeError('Service startup failed; inspect local service_runtime/server.log')
        time.sleep(1)
    raise RuntimeError('Service startup timeout; inspect local service log')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('start', 'stop', 'status'))
    args = parser.parse_args()
    if args.action == 'start':
        start()
    elif args.action == 'status':
        print(json.dumps({'running': managed_process() is not None, 'health': health()}))
    else:
        process = managed_process()
        if process:
            process.terminate()
            try:
                process.wait(timeout=15)
            except psutil.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        print(json.dumps({'service': 'stopped'}))


if __name__ == '__main__':
    main()
