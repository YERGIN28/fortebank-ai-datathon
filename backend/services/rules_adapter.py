"""Adapter for the team's current evaluation interface, without invented rules."""
from evaluation.run_rules import process_video as evaluate_video


class RuleEngineNotReady(RuntimeError):
    pass


def run_rule_engine(inference_result: dict, video_id: str):
    result = evaluate_video({**inference_result, "video_id": video_id})
    if result.get("verdict") == "needs_review":
        raise RuleEngineNotReady(
            "Rule Engine returned needs_review; final violation/no_violation decision is not implemented"
        )
    # The current team implementation has no final decision interface. Deliberately
    # require an explicit adapter update when that interface is agreed, rather than
    # guessing how candidates or a future response should become violations.
    raise RuleEngineNotReady("Rule Engine final decision interface must be agreed before use")
