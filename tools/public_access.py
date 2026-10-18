"""Expose the local GPU service through an explicitly supplied cloudflared binary."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import time

import psutil
from service_manager import initialize, RUNTIME, URL, health

STATE = RUNTIME / 'tunnel.json'
LOG = RUNTIME / 'tunnel.log'


def process_from_state():
    if not STATE.exists():
        return None
    state = json.loads(STATE.read_text(encoding='utf-8'))
    try:
        process = psutil.Process(state['pid'])
        if abs(process.create_time() - state['created_at']) < .1 and 'cloudflared' in process.name().lower():
            return process
    except psutil.Error:
        pass
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('start', 'status', 'stop'))
    parser.add_argument('--binary', type=Path)
    args = parser.parse_args()
    values = initialize()
    process = process_from_state()
    if args.action == 'stop':
        if process:
            process.terminate()
            process.wait(timeout=10)
        print(json.dumps({'public_access': 'stopped'}))
        return
    if args.action == 'status':
        state = json.loads(STATE.read_text(encoding='utf-8')) if STATE.exists() else {}
        print(json.dumps({'running': process is not None, 'url': state.get('url')}))
        return
    if not health() or not health().get('ready'):
        raise RuntimeError('Start the local server before public access')
    if not process:
        if args.binary is None or not args.binary.is_file():
            raise RuntimeError('Provide --binary from the official Cloudflare release')
        with LOG.open('wb') as log:
            child = subprocess.Popen([str(args.binary.resolve()), 'tunnel', '--no-autoupdate',
                        '--url', URL, '--protocol', 'http2'], stdout=log, stderr=subprocess.STDOUT,
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        process = psutil.Process(child.pid)
        STATE.write_text(json.dumps({'pid':child.pid,'created_at':process.create_time()}),encoding='utf-8')
    deadline = time.monotonic() + 75
    while time.monotonic() < deadline:
        content = LOG.read_text(encoding='utf-8', errors='replace') if LOG.exists() else ''
        matches = re.findall(r'https://[a-z0-9-]+\.trycloudflare\.com', content)
        if matches:
            url = matches[-1]
            state = json.loads(STATE.read_text(encoding='utf-8'))
            state['url'] = url
            STATE.write_text(json.dumps(state),encoding='utf-8')
            (RUNTIME / 'JURY_ACCESS.txt').write_text(
                'Service: '+url+'\nAPI: '+url+'/api/v1\nHeader: X-API-Key\nKey: '+values['API_KEY']
                +'\nKeep laptop powered, awake and online. URL changes if tunnel restarts.\n',encoding='utf-8')
            print(json.dumps({'public_url':url,'credentials_saved_locally':True,
                              'temporary_url':True,'local_inference':True}))
            return
        if not process.is_running():
            raise RuntimeError('Tunnel stopped; inspect local tunnel log')
        time.sleep(1)
    raise TimeoutError('Tunnel startup timed out; inspect local tunnel log')


if __name__ == '__main__':
    main()
