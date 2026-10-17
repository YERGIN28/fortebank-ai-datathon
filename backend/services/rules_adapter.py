"""Public adapter supplied by the Rule Engine team."""
from app.rules.decision import build_job_result
from backend.media import extract_frame_base64


def run_rule_engine(inference_result: dict, file_path: str):
    result = build_job_result(
        "internal", inference_result,
        lambda seconds: extract_frame_base64(file_path, seconds),
    )
    if result["status"] != "done":
        raise RuntimeError(result.get("error", "Rule Engine failed"))
    return {"verdict": result["verdict"], "violations": result["violations"]}
