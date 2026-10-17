"""One local model per worker. No mock results or online model services."""
import time
import logging
from app.rules.context import enrich_service_context
from app.rules.decision import build_job_result

log = logging.getLogger(__name__)


def analyze_video(job_id, video_path, engine, extract_frame, deadline):
    if time.perf_counter() >= deadline:
        return {"job_id": job_id, "status": "failed", "error": "job_timeout"}
    result = engine.analyze_video(video_path).to_dict()
    result = enrich_service_context(result, video_path, engine.model, deadline)
    if "rule_context_summary" in result:
        log.info("Local cash-rule context summary: %s", result["rule_context_summary"])
    response = build_job_result(job_id, result, extract_frame)
    if time.perf_counter() >= deadline:
        return {"job_id": job_id, "status": "failed", "error": "job_timeout"}
    return response
