"""Release integration guards, all data generated or in-memory."""
from pathlib import Path
import pytest
from tests.test_backend import client, video, submit, wait_job
from backend import main, config
from backend.services import analyzer_service as service


def test_upload_limit_removes_partial_upload(client, monkeypatch):
    monkeypatch.setattr(config, 'MAX_UPLOAD_BYTES', 4)
    response = client.post('/api/v1/analyze', headers={'X-API-Key': 'test-key'},
                          files={'file': ('generated.mov', b'12345', 'video/quicktime')})
    assert response.status_code == 413
    assert not list(Path(main.UPLOAD_DIR).glob('*.mov'))
    assert not main.jobs


def test_health_has_no_paths_or_secrets(client):
    response = client.get('/health')
    assert response.status_code == 200
    assert response.json() == {'ready': True, 'mode': 'fake',
                               'inference_version': '2026.10.18.10',
                               'model_name': None, 'quantization': None,
                               'positive_verification': False,
                               'rules_version': 'possible-signs-2026.10.18.1',
                               'assessment_mode': 'possible_signs'}
    assert 'test-key' not in response.text


def test_full_queue_rejects_upload_without_leaving_file(client, video, monkeypatch):
    monkeypatch.setattr(config, 'MAX_PENDING_JOBS', 1)
    main.jobs['synthetic-busy'] = {'status': 'processing'}
    try:
        before = set(Path(main.UPLOAD_DIR).glob('*.mov'))
        with video.open('rb') as stream:
            response = client.post('/api/v1/analyze', headers={'X-API-Key':'test-key'},
                                  files={'file':('generated.mov',stream,'video/quicktime')})
        assert response.status_code == 429
        assert set(Path(main.UPLOAD_DIR).glob('*.mov')) == before
    finally:
        main.jobs.pop('synthetic-busy',None)


def test_changed_cash_type_reaches_rules_unchanged(video, monkeypatch):
    from types import SimpleNamespace
    analyzer = service.VideoAnalyzer(mode='real')
    data = {'status': 'complete', 'observations': [{'type':'cash_on_desk_with_next_customer',
             'start_sec':0, 'end_sec':1, 'description':'Synthetic candidate',
             'condition_checks': {}}]}
    analyzer.engine = SimpleNamespace(analyze_video=lambda path: SimpleNamespace(to_dict=lambda:data))
    seen = []
    def rules(result, path):
        seen.append(result)
        return {'verdict':'no_violation','violations':[]}
    monkeypatch.setattr('backend.services.rules_adapter.run_rule_engine', rules)
    analyzer.run_analysis(str(video))
    assert seen == [data]


def test_expired_queue_job_never_runs_and_cleans_upload(tmp_path):
    import time
    path = tmp_path / 'expired.mov'
    path.write_bytes(b'generated')
    main.job_lifecycle['expired'] = {'deadline_monotonic': time.perf_counter() - 1}
    class Analyzer:
        def run_analysis(self, path):
            raise AssertionError('Expired job must not run')
    main.process_video('expired', str(path), Analyzer())
    assert main.jobs['expired']['status'] == 'failed'
    assert 'waiting in queue' in main.jobs['expired']['error']
    assert not path.exists()


def test_inference_gets_remaining_budget_and_original_config_restored(video, monkeypatch):
    import time
    from types import SimpleNamespace
    from app.inference import InferenceConfig
    analyzer = service.VideoAnalyzer(mode='real')
    original = InferenceConfig(Path('synthetic-unused'))
    seen = []
    def analyze(path):
        seen.append(analyzer.engine.config.time_budget_seconds)
        return SimpleNamespace(to_dict=lambda: {'status':'complete','observations':[]})
    analyzer.engine = SimpleNamespace(config=original, analyze_video=analyze)
    analyzer.job_deadline = time.perf_counter() + 25
    monkeypatch.setattr(config, 'INFERENCE_AUDIT_DIR', None)
    analyzer.run_analysis(str(video))
    assert 0 < seen[0] <= 25
    assert analyzer.engine.config is original


def test_optional_audit_is_local_and_not_part_of_public_response(video, tmp_path, monkeypatch):
    from types import SimpleNamespace
    import json
    analyzer = service.VideoAnalyzer(mode='real')
    payload = {'status':'complete','observations':[]}
    analyzer.engine = SimpleNamespace(analyze_video=lambda path: SimpleNamespace(to_dict=lambda: payload))
    monkeypatch.setattr(config, 'INFERENCE_AUDIT_DIR', tmp_path / 'audit')
    response = analyzer.run_analysis(str(video))
    assert response == {'verdict':'no_violation','violations':[]}
    files = list((tmp_path / 'audit').glob('*.json'))
    assert len(files) == 1
    assert json.loads(files[0].read_text(encoding='utf-8'))['inference'] == payload


def test_possible_screen_sign_reaches_http_and_jpeg(client, video, monkeypatch):
    from types import SimpleNamespace
    from backend.services import rules_adapter
    monkeypatch.setattr(config, 'ASSESSMENT_MODE', 'possible_signs')
    data = {'status':'complete','duration_sec':2.0,'processed_windows':1,'planned_windows':1,
            'observations':[{'type':'workstation_left_with_screen_on','start_sec':0.0,'end_sec':1.0,
             'description':'Artificial screen candidate.', 'condition_checks':{
                 'cashier_left_workplace':{'state':'observed','evidence_timestamps_sec':[0.0,0.5]},
                 'screen_on_after_departure':{'state':'observed','evidence_timestamps_sec':[0.5,1.0]},
             }}]}
    analyzer = service.VideoAnalyzer(mode='real')
    analyzer.engine = SimpleNamespace(analyze_video=lambda path: SimpleNamespace(to_dict=lambda:data))
    original = service.VideoAnalyzer.run_analysis
    monkeypatch.setattr(service.VideoAnalyzer,'run_analysis',lambda self,path:original(analyzer,path))
    result = wait_job(client,submit(client,video.read_bytes()))
    assert result['status']=='done' and result['verdict']=='violation'
    assert len(result['violations'][0]['evidence_frames']) in (1,2,3)
    assert 'норма не подтверждена' in result['violations'][0]['description']
    assert result['violations'][0]['timecode_sec']==0.5


def test_public_methodology_explains_project_and_regulatory_basis(client):
    response=client.get('/methodology')
    assert response.status_code==200
    assert 'юридическое заключение' in response.text
    assert 'чек-листе проекта' in response.text
    assert 'test-key' not in response.text
    assert '/methodology' not in client.get('/openapi.json').json()['paths']
