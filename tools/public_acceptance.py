"""Public API acceptance using generated shapes only; no real input path accepted."""
from pathlib import Path
import json
import sys
import tempfile
import time
from urllib.parse import urlsplit

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.inference.synthetic import create_video
from service_manager import initialize, RUNTIME


def main():
    values = initialize()
    url = json.loads((RUNTIME / 'tunnel.json').read_text(encoding='utf-8'))['url']
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or not parsed.hostname.endswith('.trycloudflare.com'):
        raise ValueError('Expected the managed public HTTPS tunnel')
    report = {'url':url,'input':'generated_shapes_only'}
    with httpx.Client(base_url=url,trust_env=False,follow_redirects=False,timeout=20) as client:
        response = client.get('/health')
        response.raise_for_status()
        report['health'] = response.json()
        report['missing_key_rejected'] = client.get('/api/v1/jobs/nonexistent').status_code == 401
        report['wrong_key_rejected'] = client.get('/api/v1/jobs/nonexistent',headers={'X-API-Key':'invalid-test-key'}).status_code == 401
        client.headers['X-API-Key'] = values['API_KEY']
        report['authorized_unknown_job_http'] = client.get('/api/v1/jobs/nonexistent').status_code
        with tempfile.TemporaryDirectory(prefix='forte-public-synthetic-') as directory:
            video = Path(directory)/'generated_shapes.mov'
            create_video(video)
            started = time.perf_counter()
            with video.open('rb') as stream:
                response = client.post('/api/v1/analyze',files={'file':(video.name,stream,'video/quicktime')})
            response.raise_for_status()
            job = response.json()['job_id']
            deadline = time.monotonic()+330
            while time.monotonic()<deadline:
                response = client.get('/api/v1/jobs/'+job)
                response.raise_for_status()
                result = response.json()
                if result['status'] != 'processing': break
                time.sleep(1)
            else:
                raise TimeoutError('Public acceptance timed out')
            report.update(status=result['status'],verdict=result.get('verdict'),
                          violation_count=len(result.get('violations',[])),
                          elapsed_sec=round(time.perf_counter()-started,3))
    report['passed'] = (report['health'].get('mode')=='real' and report['missing_key_rejected']
                        and report['wrong_key_rejected'] and report['authorized_unknown_job_http']==404
                        and report.get('status')=='done' and report.get('verdict')=='no_violation'
                        and report['violation_count']==0)
    (RUNTIME/'public_acceptance.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report))
    if not report['passed']: raise SystemExit(1)


if __name__=='__main__': main()
