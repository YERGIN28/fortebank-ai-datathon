"""Real HTTP routing/media decoding with an explicitly fake local model."""
import base64
from io import BytesIO
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app.rules.context import enrich_service_context
from app.rules.decision import decide_video


class ContextTests(unittest.TestCase):
    def test_context_is_local_and_does_not_mutate_input(self):
        from evaluation.test_decision import payload, observation
        data = payload(observation("cash_left_unattended"))
        data["observations"][0].pop("condition_checks")
        reader = SimpleNamespace(duration=20, closed=False)
        reader.sample = lambda *args: [SimpleNamespace(timestamp_sec=10), SimpleNamespace(timestamp_sec=15)]
        reader.close = lambda: setattr(reader, "closed", True)
        checks = {name: {"state": "observed", "frames": [0, 1]}
                  for name in ("cashier_left_workplace", "customer_service_ongoing")}
        model = SimpleNamespace(check_service_context=lambda *args: checks)
        result = enrich_service_context(data, "synthetic.mov", model, time.perf_counter() + 10,
                                        lambda *args: reader)
        self.assertEqual(decide_video(result)["verdict"], "violation")
        self.assertEqual(data["observations"][0]["type"], "cash_left_unattended")
        self.assertTrue(reader.closed)

    def test_bad_frame_index_and_timeout(self):
        from evaluation.test_decision import payload, observation
        data = payload(observation("cash_left_unattended"))
        reader = SimpleNamespace(duration=20, sample=lambda *args: [1, 2], close=lambda: None)
        model = SimpleNamespace(check_service_context=lambda *args: {
            "cashier_left_workplace": {"state": "observed", "frames": [True]},
            "customer_service_ongoing": {"state": "observed", "frames": [0]},
        })
        with self.assertRaises(ValueError):
            enrich_service_context(data, "synthetic.mov", model, time.perf_counter() + 10,
                                   lambda *args: reader)
        with self.assertRaises(TimeoutError):
            enrich_service_context(data, "synthetic.mov", model, time.perf_counter() - 1,
                                   lambda *args: reader)


class HttpIntegrationTests(unittest.TestCase):
    def test_no_model_means_not_ready_and_no_accepted_upload(self):
        from fastapi.testclient import TestClient
        import backend.main as main
        with patch.object(main, "API_KEY", "synthetic-test-key"), \
             patch.object(main, "create_engine", side_effect=RuntimeError("synthetic missing weights")), \
             patch.object(main.log, "exception"):
            with TestClient(main.app) as client:
                response = client.post("/api/v1/analyze", headers={"X-API-Key": "synthetic-test-key"},
                                       files={"file": ("synthetic.mov", b"synthetic")})
                self.assertEqual(response.status_code, 503)
                self.assertFalse(client.get("/health").json()["ready"])

    def test_expired_job_is_failed_without_waiting_for_gpu(self):
        import backend.main as main
        job_id = "synthetic_expired"
        with patch.dict(main.jobs, {job_id: {"job_id": job_id, "status": "processing"}}), \
             patch.dict(main.job_deadlines, {job_id: time.perf_counter() - 1}):
            result = main.get_job_result(job_id)
            self.assertEqual(result, {"job_id": job_id, "status": "failed", "error": "job_timeout"})

    def test_upload_to_real_jpeg_and_verdicts(self):
        import av
        from PIL import Image
        from fastapi.testclient import TestClient
        import backend.main as main
        from backend.contracts import JobDoneResponse, JobFailedResponse
        from app.inference.schemas import InferenceResult, Observation

        class FakeModel:
            # Synthetic desired responses, not evidence of Qwen recognition quality.
            def check_cash_rules_context(self, frames, deadline):
                from app.rules.catalog import RULE_CATALOG
                from app.rules.context import RULE_TYPES
                return {name: [["o" if name == "previous_cash_outside_storage" else "r",
                                 [0, len(frames)-1]] for _ in RULE_CATALOG[name]["conditions"]]
                        for name in RULE_TYPES}

        class FakeEngine:
            model = FakeModel()
            mode = "positive"
            def load(self):
                pass
            def analyze_video(self, path):
                events = [] if self.mode == "negative" else [Observation(
                    type="cash_left_unattended", start_sec=0.5, end_sec=1,
                    description="Synthetic fake model event", evidence_timestamps_sec=[0.5],
                    timing_resolution_sec=0.5)]
                return InferenceResult(status="partial" if self.mode == "partial" else "complete",
                                       observations=events, duration_sec=2,
                                       processed_windows=1, planned_windows=1)

        test_root = Path(__file__).resolve().parents[1] / ".testtmp"
        test_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=test_root) as folder:
            assert Path(folder).resolve().is_relative_to(test_root.resolve())
            path = Path(folder) / "synthetic.mov"
            with av.open(str(path), "w") as container:
                stream = container.add_stream("mpeg4", rate=10)
                stream.width = 64
                stream.height = 64
                stream.pix_fmt = "yuv420p"
                for index in range(20):
                    frame = av.VideoFrame.from_image(Image.new("RGB", (64, 64), (index * 10, 20, 30)))
                    for packet in stream.encode(frame):
                        container.mux(packet)
                for packet in stream.encode():
                    container.mux(packet)
            video_bytes = path.read_bytes()
            engine = FakeEngine()
            with patch.object(main, "API_KEY", "synthetic-test-key"), \
                 patch.object(main, "UPLOAD_DIR", Path(folder) / "uploads"), \
                 patch.object(main, "create_engine", return_value=engine):
                with TestClient(main.app) as client:
                    for _ in range(200):
                        if client.get("/health").json()["ready"]:
                            break
                        time.sleep(0.01)
                    self.assertTrue(client.get("/health").json()["ready"])
                    self.assertEqual(client.get("/").status_code, 200)
                    self.assertEqual(client.get("/api/v1/jobs/none").status_code, 401)
                    self.assertEqual(client.get("/api/v1/jobs/none", headers={"X-API-Key": "wrong"}).status_code, 401)
                    self.assertEqual(client.post("/api/v1/analyze", files={"file": ("synthetic.mov", video_bytes)}).status_code, 401)
                    headers = {"X-API-Key": "synthetic-test-key"}
                    self.assertEqual(client.post("/api/v1/analyze", headers=headers,
                                                 files={"file": ("empty.mov", b"")}).status_code, 400)
                    self.assertEqual(client.post("/api/v1/analyze", headers=headers,
                                                 files={"file": ("wrong.txt", video_bytes)}).status_code, 400)
                    for mode in ("positive", "negative", "partial", "corrupt"):
                        engine.mode = mode
                        # Corrupt input should fail through real context decoding.
                        response = client.post("/api/v1/analyze", headers=headers,
                                               files={"file": ("../../synthetic.mov", b"bad" if mode == "corrupt" else video_bytes)})
                        self.assertEqual(response.status_code, 200)
                        job_id = response.json()["job_id"]
                        for _ in range(200):
                            result = client.get(f"/api/v1/jobs/{job_id}", headers=headers).json()
                            if result["status"] != "processing":
                                break
                            time.sleep(0.01)
                        main.job_queue.join()
                        if mode in ("partial", "corrupt"):
                            JobFailedResponse(**result)
                            self.assertNotIn("verdict", result)
                        else:
                            JobDoneResponse(**result)
                            self.assertEqual(result["verdict"], "violation" if mode == "positive" else "no_violation")
                            if mode == "positive":
                                event = result["violations"][0]
                                self.assertIn("20", event["description"])
                                image = Image.open(BytesIO(base64.b64decode(event["evidence_frames"][0]["image_base64"])))
                                image.load()
                                self.assertEqual(image.format, "JPEG")
                                self.assertEqual(image.size, (64, 64))
                        self.assertFalse(list(main.UPLOAD_DIR.glob("*.mov")))
                # Wait for the worker to terminate before another test lifespan.
                time.sleep(0.3)


if __name__ == "__main__":
    unittest.main()
