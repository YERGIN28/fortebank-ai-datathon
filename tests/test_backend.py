from pathlib import Path
import base64
import json
import logging
import threading
import time
import sys
from types import SimpleNamespace

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend import main
from backend import config
from backend.services import analyzer_service as service
from backend.services import rules_adapter
from backend.worker_lock import WorkerLock


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "API_KEY", "test-key")
    monkeypatch.setattr(main, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(main, "WORKER_LOCK_PATH", tmp_path / "worker.lock")
    monkeypatch.setattr(config, "ANALYSIS_MODE", "fake")
    original = service.analyze_video
    monkeypatch.setattr(service, "analyze_video", lambda path, **kw: original(path, delay_seconds=0))
    main.jobs.clear()
    main.job_lifecycle.clear()
    with TestClient(main.app) as instance:
        yield instance


@pytest.fixture
def video(tmp_path):
    path = tmp_path / "sample.mov"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 10, (64, 64))
    assert writer.isOpened()
    for value in range(20):
        writer.write(np.full((64, 64, 3), value * 10, dtype=np.uint8))
    writer.release()
    return path


def submit(client, content, route="/api/v1/analyze", filename="sample.mov"):
    response = client.post(route, headers={"X-API-Key": "test-key"}, files={"file": (filename, content, "video/quicktime")})
    assert response.status_code == 200, response.text
    assert set(response.json()) == {"job_id"}
    return response.json()["job_id"]


def wait_job(client, job_id, route="/api/v1/jobs/"):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        response = client.get(route + job_id, headers={"X-API-Key": "test-key"})
        assert response.status_code == 200
        result = response.json()
        if result["status"] != "processing":
            return result
        time.sleep(0.01)
    raise AssertionError("Job did not finish")


@pytest.mark.parametrize("headers", [{}, {"X-API-Key": "wrong"}, {"X-API-Key": ""}])
def test_auth_returns_same_401(client, headers):
    for response in (
        client.get("/api/v1/jobs/missing", headers=headers),
        client.post("/api/v1/analyze", headers=headers, files={"file": ("video.mov", b"video")}),
    ):
        assert response.status_code == 401
        assert response.json() == {"detail": "Invalid API key"}


def test_unconfigured_key_never_authenticates(client, monkeypatch):
    monkeypatch.setattr(main, "API_KEY", None)
    assert client.get("/api/v1/jobs/missing").status_code == 401


def test_invalid_extension_and_unknown_job(client):
    headers = {"X-API-Key": "test-key"}
    assert client.get("/api/v1/jobs/missing", headers=headers).status_code == 404
    for route in ("/api/v1/analyze", "/ui/analyze"):
        assert client.post(route, headers=headers, files={"file": ("video.mp4", b"video")}).status_code == 400


def test_public_schema_and_ui(client):
    assert set(client.get("/openapi.json").json()["paths"]) == {
        "/api/v1/analyze", "/api/v1/jobs/{job_id}",
    }
    html = client.get("/").text
    assert "X-API-Key" not in html
    assert "data:image/jpeg;base64," in html
    assert "/ui/analyze" in html
    assert "Demo mode" in html
    assert "__ANALYSIS_NOTICE__" not in html


@pytest.mark.parametrize("name", ["../../test.mov", r"C:\incoming\test.mov", "test.mov"])
def test_safe_upload_name(name):
    assert main.safe_upload_name(name) == "test.mov"


@pytest.mark.parametrize("name", [None, "", "test.mp4", "bad:name.mov", "bad\x00.mov"])
def test_invalid_upload_name(name):
    with pytest.raises(main.HTTPException) as exc:
        main.safe_upload_name(name)
    assert exc.value.status_code == 400


@pytest.mark.parametrize("route,poll", [("/api/v1/analyze", "/api/v1/jobs/"), ("/ui/analyze", "/ui/jobs/")])
def test_video_and_jpeg(client, video, route, poll):
    job_id = submit(client, video.read_bytes(), route, "../../sample.mov")
    result = wait_job(client, job_id, poll)
    assert set(result) == {"job_id", "status", "verdict", "violations"}
    assert result["status"] == "done"
    assert result["verdict"] == "violation"
    frames = result["violations"][0]["evidence_frames"]
    assert 1 <= len(frames) <= 3
    for frame in frames:
        raw = base64.b64decode(frame["image_base64"], validate=True)
        assert raw.startswith(b"\xff\xd8")
        assert cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR) is not None
    assert not list(Path(main.UPLOAD_DIR).glob("*.mov"))
    metadata = main.job_lifecycle[job_id]
    assert metadata["created_at"] <= metadata["started_at"] <= metadata["finished_at"]
    assert metadata["processing_time_sec"] >= 0


def test_empty_and_corrupt_video(client):
    response = client.post("/api/v1/analyze", headers={"X-API-Key": "test-key"}, files={"file": ("empty.mov", b"")})
    assert response.status_code == 400
    result = wait_job(client, submit(client, b"not a movie"))
    assert result["status"] == "failed"
    assert set(result) == {"job_id", "status", "error"}
    assert not list(Path(main.UPLOAD_DIR).glob("*.mov"))


def test_one_worker_and_sequential_jobs(client, video, monkeypatch):
    entered = threading.Event()
    release = threading.Event()
    calls = []
    original = service.VideoAnalyzer.run_analysis

    def controlled(self, path):
        calls.append(("start", path, threading.get_ident()))
        if len(calls) == 1:
            entered.set()
            assert release.wait(5)
        result = original(self, path)
        calls.append(("end", path, threading.get_ident()))
        return result

    monkeypatch.setattr(service.VideoAnalyzer, "run_analysis", controlled)
    try:
        first = submit(client, video.read_bytes())
        assert entered.wait(5)
        second = submit(client, video.read_bytes())
        assert main.jobs[first]["status"] == main.jobs[second]["status"] == "processing"
        assert main.job_lifecycle[second]["started_at"] is None
    finally:
        release.set()
    assert wait_job(client, first)["status"] == "done"
    assert wait_job(client, second)["status"] == "done"
    assert [row[0] for row in calls] == ["start", "end", "start", "end"]
    assert len({row[2] for row in calls}) == 1
    assert main.job_lifecycle[first]["finished_at"] <= main.job_lifecycle[second]["started_at"]


@pytest.mark.parametrize("failure", [RuntimeError("CUDA failure"), RuntimeError("Rule Engine exception")])
def test_processing_exception_is_failed(client, video, monkeypatch, failure):
    def fail(self, path):
        raise failure
    monkeypatch.setattr(service.VideoAnalyzer, "run_analysis", fail)
    result = wait_job(client, submit(client, video.read_bytes()))
    assert result["status"] == "failed"
    assert str(failure) in result["error"]
    assert "verdict" not in result


def test_cleanup_failure_does_not_kill_worker(client, video, monkeypatch):
    original = Path.unlink

    def denied(path, *args, **kwargs):
        if path.parent == main.UPLOAD_DIR:
            raise PermissionError("simulated busy file")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", denied)
    first = submit(client, video.read_bytes())
    second = submit(client, video.read_bytes())
    assert wait_job(client, first)["status"] == "done"
    assert wait_job(client, second)["status"] == "done"
    assert main.worker_thread.is_alive()
    assert "cleanup_error" in main.job_lifecycle[first]


@pytest.mark.parametrize("status", ["partial", "timeout", "unexpected"])
def test_incomplete_inference_is_failed(client, video, monkeypatch, status):
    original = service.VideoAnalyzer.run_analysis
    monkeypatch.setattr(service.VideoAnalyzer, "run_analysis", lambda self, path: original(real_analyzer(status), path))
    result = wait_job(client, submit(client, video.read_bytes()))
    assert result["status"] == "failed"
    assert status in result["error"]
    assert "verdict" not in result


def test_timeout_reports_safe_metrics_and_worker_continues(client, video, monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="uvicorn.error")
    payloads = iter([
        {
            "status": "timeout", "elapsed_sec": 307.25,
            "processed_windows": 1, "planned_windows": 3, "duration_sec": 16,
            "gpu_peak_allocated_mib": 3800, "gpu_peak_reserved_mib": 3900,
            "stage_timings_sec": {"decode": 0.25, "observe": 290, "verify_object": 7,
                                  "service_context": 10, "relevance": 0,
                                  "PRIVATE_STAGE": "PRIVATE_VALUE"},
            "observations": [{"description": "PRIVATE_OBSERVATION"}],
            "warnings": ["PRIVATE_WARNING"], "path": "PRIVATE_PATH",
        },
        {"status": "complete", "observations": [], "elapsed_sec": float("nan"),
         "stage_timings_sec": {"observe": "PRIVATE_VALUE"}},
    ])
    analyzer = service.VideoAnalyzer(mode="real")

    def analyze(path):
        data = next(payloads)
        return SimpleNamespace(to_dict=lambda: data)

    analyzer.engine = SimpleNamespace(analyze_video=analyze)
    original = service.VideoAnalyzer.run_analysis
    monkeypatch.setattr(service.VideoAnalyzer, "run_analysis", lambda self, path: original(analyzer, path))
    rules_calls = []
    original_rules = rules_adapter.run_rule_engine

    def checked_rules(data, path):
        rules_calls.append(data["status"])
        return original_rules(data, path)

    monkeypatch.setattr(rules_adapter, "run_rule_engine", checked_rules)
    first = wait_job(client, submit(client, video.read_bytes()))
    assert first["status"] == "failed"
    assert "timeout" in first["error"]
    assert "307.2s" in first["error"]
    assert "completed windows 1/3" in first["error"]
    assert "verdict" not in first
    assert rules_calls == []

    second = wait_job(client, submit(client, video.read_bytes()))
    assert second["status"] == "done"
    assert rules_calls == ["complete"]
    assert not list(Path(main.UPLOAD_DIR).glob("*.mov"))
    messages = [record.getMessage() for record in caplog.records
                if record.getMessage().startswith("Inference metrics: ")]
    assert len(messages) == 2
    metrics = json.loads(messages[0].split(": ", 1)[1])
    assert metrics["stage_timings_sec"] == {
        "decode": 0.25, "observe": 290, "verify_object": 7, "service_context": 10, "relevance": 0,
    }
    assert metrics["processed_windows"] == 1
    assert metrics["planned_windows"] == 3
    assert "PRIVATE_" not in caplog.text
    assert "NaN" not in messages[1]


def real_analyzer(status="complete", observations=None):
    analyzer = service.VideoAnalyzer(mode="real")
    data = {"status": status, "observations": observations or []}
    analyzer.engine = SimpleNamespace(analyze_video=lambda path: SimpleNamespace(to_dict=lambda: data))
    return analyzer


@pytest.mark.parametrize("observations,status", [([], "done"), ([{"type": "unknown", "description": "unclear", "start_sec": 0, "end_sec": 1}], "failed")])
def test_real_rules_final_decision(client, video, monkeypatch, observations, status):
    analyzer = real_analyzer(observations=observations)
    original = service.VideoAnalyzer.run_analysis
    monkeypatch.setattr(service.VideoAnalyzer, "run_analysis", lambda self, path: original(analyzer, path))
    result = wait_job(client, submit(client, video.read_bytes()))
    assert result["status"] == status
    if status == "done":
        assert result["verdict"] == "no_violation"
        assert result["violations"] == []
    else:
        assert "unresolved_observations" in result["error"]
        assert "verdict" not in result


def test_evidence_limit(video):
    frames = service.extract_evidence(str(video), [0, 0, 0.2, 0.5, 1])
    assert len(frames) == 3
    assert [frame["timestamp_sec"] for frame in frames] == [0, 0.2, 0.5]
    for invalid in ([], [-1], [float("nan")], [True]):
        with pytest.raises(ValueError):
            service.extract_evidence(str(video), invalid)


def test_load_once_and_shutdown(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(main, "API_KEY", "test-key")
    monkeypatch.setattr(main, "WORKER_LOCK_PATH", tmp_path / "worker.lock")
    monkeypatch.setattr(main, "UPLOAD_DIR", tmp_path / "uploads")

    class Analyzer:
        def load(self):
            calls.append(threading.get_ident())

    monkeypatch.setattr(main, "VideoAnalyzer", Analyzer)
    for _ in range(2):
        with TestClient(main.app):
            assert main.worker_thread.is_alive()
            assert calls[-1] == main.worker_thread.ident
        assert main.worker_thread is None
        assert not main.accepting_jobs
        assert main.job_queue.unfinished_tasks == 0
    assert len(calls) == 2  # One load per server lifecycle, never per job.


def test_model_startup_failure_releases_lock(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "API_KEY", "test-key")
    monkeypatch.setattr(main, "WORKER_LOCK_PATH", tmp_path / "worker.lock")
    monkeypatch.setattr(service.VideoAnalyzer, "load", lambda self: (_ for _ in ()).throw(RuntimeError("model unavailable")))
    with pytest.raises(RuntimeError, match="model unavailable"):
        with TestClient(main.app):
            pytest.fail("Startup must fail")
    assert not main.accepting_jobs
    assert main.worker_thread is None
    guard = WorkerLock(main.WORKER_LOCK_PATH)
    guard.acquire()
    guard.release()


def test_second_worker_is_rejected(client):
    with pytest.raises(RuntimeError, match="Another backend worker"):
        with TestClient(main.app):
            pytest.fail("Second worker must not start")
    assert main.worker_thread.is_alive()


def test_bad_mode_and_missing_model(monkeypatch):
    with pytest.raises(ValueError, match="ANALYSIS_MODE"):
        service.VideoAnalyzer(mode="typo").load()
    monkeypatch.setattr(config, "MODEL_PATH", None)
    with pytest.raises(RuntimeError, match="MODEL_PATH"):
        service.VideoAnalyzer(mode="real").load()


def test_real_worker_loads_engine_once(monkeypatch, tmp_path, video):
    calls = []

    class Engine:
        def __init__(self, settings):
            assert settings.model_path == tmp_path
            assert settings.refine is False
            assert settings.window_seconds == 8.0
            assert settings.time_budget_seconds == 300.0
            calls.append(("init", threading.get_ident()))

        def load(self):
            calls.append(("load", threading.get_ident()))

        def analyze_video(self, path):
            calls.append(("analyze", threading.get_ident()))
            return SimpleNamespace(to_dict=lambda: {"status": "complete", "observations": []})

    monkeypatch.setitem(sys.modules, "app.inference", SimpleNamespace(INFERENCE_VERSION="test", InferenceEngine=Engine, InferenceConfig=lambda **kw: SimpleNamespace(**kw)))
    monkeypatch.setattr(config, "ANALYSIS_MODE", "real")
    monkeypatch.setattr(config, "MODEL_PATH", str(tmp_path))
    monkeypatch.setattr(main, "API_KEY", "test-key")
    monkeypatch.setattr(main, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(main, "WORKER_LOCK_PATH", tmp_path / "worker.lock")
    with TestClient(main.app) as instance:
        ids = [submit(instance, video.read_bytes()) for _ in range(2)]
        for job_id in ids:
            result = wait_job(instance, job_id)
            assert result["status"] == "done"
            assert result["verdict"] == "no_violation"
    assert [row[0] for row in calls] == ["init", "load", "analyze", "analyze"]
    assert len({row[1] for row in calls}) == 1


def test_rule_exception_propagates(video, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("rules failed")
    monkeypatch.setattr(rules_adapter, "build_job_result", fail)
    with pytest.raises(RuntimeError, match="rules failed"):
        real_analyzer().run_analysis(str(video))


def test_partial_upload_is_removed(client, monkeypatch):
    def fail_copy(source, target):
        target.write(b"partial")
        raise OSError("upload interrupted")
    monkeypatch.setattr(main.shutil, "copyfileobj", fail_copy)
    with pytest.raises(OSError, match="upload interrupted"):
        submit(client, b"video")
    assert not list(Path(main.UPLOAD_DIR).glob("*.mov"))
    assert not main.jobs


def test_confirmed_rule_reaches_http_with_real_jpeg(client, video, monkeypatch):
    event = {"type": "cashier_leaves_during_service", "start_sec": 0, "end_sec": 1,
             "condition_checks": {
                 "cashier_left_workplace": {"state": "observed", "evidence_timestamps_sec": [0.2]},
                 "customer_service_ongoing": {"state": "observed", "evidence_timestamps_sec": [0.2, 0.5]}}}
    analyzer = real_analyzer(observations=[event])
    original = service.VideoAnalyzer.run_analysis
    monkeypatch.setattr(service.VideoAnalyzer, "run_analysis", lambda self, path: original(analyzer, path))
    result = wait_job(client, submit(client, video.read_bytes()))
    assert result["status"] == "done"
    assert result["verdict"] == "violation"
    assert 1 <= len(result["violations"][0]["evidence_frames"]) <= 3
    for frame in result["violations"][0]["evidence_frames"]:
        raw = base64.b64decode(frame["image_base64"], validate=True)
        assert cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR) is not None


def test_unattended_cash_is_not_renamed_or_rechecked_by_backend(video):
    analyzer = real_analyzer(observations=[{"type": "cash_left_unattended", "start_sec": 0, "end_sec": 1}])
    calls = []

    def check_service_context(frames, deadline):
        calls.append((len(frames), deadline))
        assert 0 < deadline - time.perf_counter() <= 300
        return {
            "cashier_left_workplace": {"state": "observed", "frames": [0, 1]},
            "customer_service_ongoing": {"state": "observed", "frames": [1]},
        }

    # Only the public method is exposed: reaching _generate would fail this test.
    analyzer.engine.model = SimpleNamespace(check_service_context=check_service_context)
    with pytest.raises(RuntimeError, match="unresolved_observations: cash_left_unattended"):
        analyzer.run_analysis(str(video))
    assert calls == []


@pytest.mark.parametrize("condition,status,verdict", [
    ("observed", "done", "violation"),
    ("refuted", "done", "no_violation"),
    ("unclear", "failed", None),
])
def test_current_ai_departure_flows_through_rules_and_http(
        client, video, monkeypatch, condition, status, verdict):
    from app.inference import InferenceConfig, InferenceEngine

    class Model:
        context_calls = 0

        def load(self): pass
        def reset_metrics(self): pass
        def metrics(self): return {}

        def observe(self, frames, deadline):
            return [{"start_frame": 1, "end_frame": 2,
                     "type": "cashier_leaves_during_service", "object_kind": "none",
                     "description": "Synthetic departure candidate."}]

        def check_service_context(self, frames, deadline):
            self.context_calls += 1
            return {
                "cashier_left_workplace": {"state": "observed", "frames": [0, len(frames) - 1]},
                "customer_service_ongoing": {
                    "state": condition, "frames": [] if condition == "unclear" else [len(frames) - 1],
                },
            }

    model = Model()
    analyzer = service.VideoAnalyzer(mode="real")
    analyzer.engine = InferenceEngine(InferenceConfig(Path("unused-mock")), model=model)
    original = service.VideoAnalyzer.run_analysis
    monkeypatch.setattr(service.VideoAnalyzer, "run_analysis", lambda self, path: original(analyzer, path))
    result = wait_job(client, submit(client, video.read_bytes(), route="/ui/analyze"), route="/ui/jobs/")
    assert result["status"] == status
    assert model.context_calls == 1  # Backend must not repeat the AI context pass.
    if verdict is not None:
        assert result["verdict"] == verdict
        if verdict == "violation":
            frames = result["violations"][0]["evidence_frames"]
            assert 1 <= len(frames) <= 3
            for frame in frames:
                raw = base64.b64decode(frame["image_base64"], validate=True)
                assert cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR) is not None
        else:
            assert result["violations"] == []
    else:
        assert "unresolved_observations" in result["error"]
        assert "verdict" not in result
    assert not list(Path(main.UPLOAD_DIR).glob("*.mov"))
