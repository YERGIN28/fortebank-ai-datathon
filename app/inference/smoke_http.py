"""Probe an existing local backend using a generated MOV only; no real input."""
import argparse
import json
import os
from pathlib import Path
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, HTTPRedirectHandler, ProxyHandler, build_opener
import uuid

from .synthetic import create_video


class SmokeError(ValueError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise SmokeError('redirect_rejected')


def local_url(value):
    parsed = urlsplit(value)
    if (parsed.scheme != 'http' or parsed.hostname not in ('localhost', '127.0.0.1', '::1')
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in ('', '/')):
        raise SmokeError('local_base_url_required')
    try:
        parsed.port
    except ValueError:
        raise SmokeError('invalid_port') from None
    return value.rstrip('/')


def run_probe(base_url, api_key, *, timeout=330, poll_seconds=1):
    base_url = local_url(base_url)
    if timeout <= 0 or poll_seconds <= 0:
        raise SmokeError('positive_time_limits_required')
    if not api_key:
        raise SmokeError('api_key_environment_variable_required')
    opener = build_opener(ProxyHandler({}), NoRedirect())
    started = time.perf_counter()

    def request(path, *, data=None, content_type=None, json_result=True):
        remaining = timeout - (time.perf_counter() - started)
        if remaining <= 0:
            raise SmokeError('probe_timeout')
        headers = {'x-api-key': api_key}
        if content_type:
            headers['Content-Type'] = content_type
        try:
            with opener.open(Request(base_url + path, data=data, headers=headers),
                             timeout=min(10, remaining)) as response:
                body = response.read(2 * 1024 * 1024 + 1)
        except (HTTPError, URLError, TimeoutError, OSError):
            raise SmokeError('local_http_request_failed') from None
        if len(body) > 2 * 1024 * 1024:
            raise SmokeError('response_too_large')
        if not json_result:
            return body
        try:
            result = json.loads(body)
        except (ValueError, UnicodeError):
            raise SmokeError('invalid_http_json') from None
        if not isinstance(result, dict):
            raise SmokeError('invalid_http_schema')
        return result

    html = request('/', json_result=False).lower()
    if b'<html' not in html and b'<!doctype html' not in html:
        raise SmokeError('ui_html_missing')
    with tempfile.TemporaryDirectory(prefix='forte-http-synthetic-') as directory:
        path = Path(directory) / 'generated_shapes.mov'
        create_video(path, duration_seconds=4)
        boundary = 'forte' + uuid.uuid4().hex
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
                'filename="generated_shapes.mov"\r\nContent-Type: video/quicktime\r\n\r\n').encode()
        body += path.read_bytes() + f'\r\n--{boundary}--\r\n'.encode()
        uploaded = request('/api/v1/analyze', data=body,
                           content_type='multipart/form-data; boundary=' + boundary)
    job_id = uploaded.get('job_id')
    if not isinstance(job_id, str) or not job_id or len(job_id) > 256:
        raise SmokeError('invalid_job_id')
    while time.perf_counter() - started < timeout:
        job = request('/api/v1/jobs/' + quote(job_id, safe=''))
        status = job.get('status')
        if status == 'processing':
            time.sleep(min(poll_seconds, max(0, timeout - (time.perf_counter() - started))))
            continue
        if status not in ('done', 'failed'):
            raise SmokeError('invalid_job_status')
        if status == 'failed':
            raise SmokeError('synthetic_job_failed')
        verdict = job.get('verdict')
        if verdict not in ('violation', 'no_violation', 'needs_review') or not isinstance(job.get('violations'), list):
            raise SmokeError('invalid_verdict_schema')
        return {'input': 'generated_shapes_only', 'ui_html_served': True,
                'upload_and_poll_passed': True, 'status': status, 'verdict': verdict,
                'violation_count': len(job['violations']),
                'negative_control_passed': verdict != 'violation' and not job['violations'],
                'elapsed_sec': round(time.perf_counter() - started, 3),
                'limitations': ['HTTP contract check; does not prove that Qwen and Rule Engine were called.',
                                'HTML delivery checked; interactive browser rendering not checked.']}
    raise SmokeError('probe_timeout')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:8000')
    parser.add_argument('--api-key-env', default='API_KEY')
    args = parser.parse_args()
    try:
        report = run_probe(args.base_url, os.environ.get(args.api_key_env))
    except SmokeError as error:
        raise SystemExit(str(error)) from None
    print(json.dumps(report))
    if not report['negative_control_passed']:
        raise SystemExit('negative_control_failed')


if __name__ == '__main__':
    main()
