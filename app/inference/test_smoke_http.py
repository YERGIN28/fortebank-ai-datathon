"""HTTP probe contract checks with synthetic data and an in-memory transport."""
import io
import json
import unittest
from unittest.mock import patch

from .smoke_http import SmokeError, local_url, run_probe


class Transport:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    def open(self, request, timeout):
        self.requests.append(request)
        response = next(self.responses)
        if isinstance(response, dict):
            response = json.dumps(response).encode()
        return io.BytesIO(response)


class SmokeHttpTests(unittest.TestCase):
    def test_remote_urls_rejected(self):
        for value in ('https://example.org', 'http://example.org', 'http://127.0.0.1.evil',
                      'http://user:pass@localhost', 'http://localhost/?x=y',
                      'http://localhost:bad', 'http://localhost/path'):
            with self.subTest(value=value), self.assertRaises(SmokeError):
                local_url(value)
        self.assertEqual(local_url('http://127.0.0.1:8000/'), 'http://127.0.0.1:8000')

    def test_generated_upload_and_poll(self):
        transport = Transport([b'<html></html>', {'job_id': 'synthetic'},
                               {'status': 'processing'},
                               {'status': 'done', 'verdict': 'no_violation', 'violations': []}])
        with patch('app.inference.smoke_http.build_opener', return_value=transport), \
                patch('app.inference.smoke_http.time.sleep'):
            report = run_probe('http://127.0.0.1:8000', 'fake-key')
        self.assertTrue(report['negative_control_passed'])
        self.assertEqual(len(transport.requests), 4)
        self.assertIn(b'filename="generated_shapes.mov"', transport.requests[1].data)
        self.assertNotIn('fake-key', str(report))

    def test_placeholder_violation_fails_negative_control(self):
        transport = Transport([b'<html></html>', {'job_id': 'synthetic'},
                               {'status': 'done', 'verdict': 'violation', 'violations': [{}]}])
        with patch('app.inference.smoke_http.build_opener', return_value=transport):
            self.assertFalse(run_probe('http://localhost:8000', 'fake-key')['negative_control_passed'])

    def test_failed_job_is_not_success(self):
        transport = Transport([b'<html></html>', {'job_id': 'synthetic'}, {'status': 'failed'}])
        with patch('app.inference.smoke_http.build_opener', return_value=transport), \
                self.assertRaisesRegex(SmokeError, '^synthetic_job_failed$'):
            run_probe('http://localhost:8000', 'fake-key')

    def test_missing_key_fails_before_upload(self):
        with self.assertRaisesRegex(SmokeError, 'api_key_environment_variable_required'):
            run_probe('http://localhost:8000', None)


if __name__ == '__main__':
    unittest.main()
