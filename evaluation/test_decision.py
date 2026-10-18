"""Synthetic contract tests, not measurements on real bank videos."""
import base64
import copy
import unittest
from pathlib import Path

from app.rules.decision import build_job_result, decide_video
from app.rules.catalog import RULE_CATALOG
from unittest.mock import patch


def observation(event_type="cashier_leaves_during_service"):
    return {
        "type": event_type, "start_sec": 10, "end_sec": 15,
        "description": "Synthetic observation", "evidence_timestamps_sec": [10, 15],
        "condition_checks": {
            "cashier_left_workplace": {"state": "observed", "evidence_timestamps_sec": [10]},
            "customer_service_ongoing": {"state": "observed", "evidence_timestamps_sec": [10, 15]},
        },
    }


def payload(*events):
    return {"status": "complete", "observations": list(events), "duration_sec": 20,
            "processed_windows": 2, "planned_windows": 2}


class DecisionTests(unittest.TestCase):
    def test_additional_cash_rules_need_every_condition(self):
        for event_type in ("cash_counting_without_customer", "previous_cash_outside_storage"):
            rule = RULE_CATALOG[event_type]
            event = observation(event_type)
            event["condition_checks"] = {
                name: {"state": "observed", "evidence_timestamps_sec": [12]}
                for name in rule["conditions"]
            }
            result = decide_video(payload(event))
            self.assertEqual(result["verdict"], "violation")
            self.assertEqual(result["violations"][0]["timecode_sec"], 12)
            self.assertIn("20", result["violations"][0]["description"])
            for name in rule["conditions"]:
                incomplete = copy.deepcopy(event)
                incomplete["condition_checks"].pop(name)
                self.assertEqual(decide_video(payload(incomplete))["status"], "failed")

    def test_visibility_failure_is_not_a_negative_verdict(self):
        for event_type in ("cash_counting_without_customer", "previous_cash_outside_storage"):
            rule = RULE_CATALOG[event_type]
            event = observation(event_type)
            event["condition_checks"] = {
                name: {"state": "observed", "evidence_timestamps_sec": [12]}
                for name in rule["conditions"]
            }
            event["condition_checks"][rule["visibility_conditions"][0]]["state"] = "refuted"
            self.assertEqual(decide_video(payload(event))["status"], "failed")
            event["condition_checks"][rule["visibility_conditions"][0]]["state"] = "observed"
            # Observable evidence that this is NOT a direct receipt excludes rule 20/1.
            name = "direct_customer_cash_receipt" if event_type == "cash_counting_without_customer" else "previous_receipt_completed"
            event["condition_checks"][name]["state"] = "refuted"
            self.assertEqual(decide_video(payload(event))["verdict"], "no_violation")

    def test_controller_rule_stays_review_only(self):
        event = observation("cash_processing_without_controller")
        event["condition_checks"] = {
            "internal_cash_processing": {"state": "observed", "evidence_timestamps_sec": [12]},
            "controller_absent": {"state": "observed", "evidence_timestamps_sec": [12]},
            "direct_customer_receipt_or_payout": {"state": "refuted", "evidence_timestamps_sec": [12]},
        }
        result = decide_video(payload(event))
        self.assertEqual(result["status"], "failed")
        self.assertNotIn("verdict", result)

    def test_explicit_exception_is_evaluated(self):
        rule = copy.deepcopy(RULE_CATALOG["cashier_leaves_during_service"])
        rule["exceptions"] = ["synthetic_exception"]
        with patch.dict(RULE_CATALOG, {"cashier_leaves_during_service": rule}):
            event = observation()
            self.assertEqual(decide_video(payload(event))["status"], "failed")
            event["condition_checks"]["synthetic_exception"] = {"state": "observed", "evidence_timestamps_sec": [12]}
            self.assertEqual(decide_video(payload(event))["verdict"], "no_violation")
            event["condition_checks"]["synthetic_exception"]["state"] = "refuted"
            self.assertEqual(decide_video(payload(event))["verdict"], "violation")

    def test_api_positive_with_synthetic_jpeg(self):
        jpeg = (Path(__file__).parent / "fixtures" / "synthetic.jpg").read_bytes()
        def extract(timestamp):
            return {"timestamp_sec": timestamp, "image_base64": base64.b64encode(jpeg).decode()}
        result = build_job_result("synthetic", payload(observation()), extract)
        self.assertEqual(set(result), {"job_id", "status", "verdict", "violations"})
        self.assertEqual(result["verdict"], "violation")
        event = result["violations"][0]
        self.assertEqual(set(event), {"type", "timecode_sec", "description", "evidence_frames"})
        self.assertTrue(1 <= len(event["evidence_frames"]) <= 3)
        self.assertEqual(base64.b64decode(event["evidence_frames"][0]["image_base64"]), jpeg)

    def test_positive_and_no_input_mutation(self):
        data = payload(observation())
        original = copy.deepcopy(data)
        result = decide_video(data)
        self.assertEqual(result["verdict"], "violation")
        self.assertEqual(result["violations"][0]["timecode_sec"], 10)
        self.assertIn("22", result["violations"][0]["description"])
        self.assertEqual(data, original)

    def test_empty_complete_and_neutral(self):
        for event_type in (None, "cash_handling", "cash_transfer", "document_transfer",
                           "object_transfer", "cash_drawer_opened", "cash_drawer_closed"):
            data = payload() if event_type is None else payload(observation(event_type))
            self.assertEqual(decide_video(data), {
                "status": "done", "verdict": "no_violation", "violations": []})

    def test_missing_checks_unknown_and_unverified_fail(self):
        for event_type in ("unknown", "new_event", "cash_left_unattended", "unauthorized_phone_use",
                           "cashier_leaves_during_service"):
            event = observation(event_type)
            event.pop("condition_checks")
            result = decide_video(payload(event))
            self.assertEqual(result["status"], "failed")
            self.assertNotIn("verdict", result)

    def test_refutation_requires_evidence(self):
        event = observation()
        event["condition_checks"]["customer_service_ongoing"]["state"] = "refuted"
        self.assertEqual(decide_video(payload(event))["verdict"], "no_violation")
        event["condition_checks"]["customer_service_ongoing"]["evidence_timestamps_sec"] = []
        self.assertEqual(decide_video(payload(event))["status"], "failed")

    def test_partial_timeout_and_missing_coverage(self):
        for status in ("partial", "timeout", "failed", None):
            data = payload(observation())
            data["status"] = status
            self.assertEqual(decide_video(data)["status"], "failed")
        data = payload(observation())
        data["processed_windows"] = 1
        self.assertEqual(decide_video(data)["status"], "failed")

    def test_invalid_times_and_checks(self):
        for value in (True, -1, float("nan"), float("inf"), "10", None):
            event = observation()
            event["start_sec"] = value
            self.assertEqual(decide_video(payload(event))["status"], "failed")
        event = observation()
        event["condition_checks"]["cashier_left_workplace"]["evidence_timestamps_sec"] = [30]
        self.assertEqual(decide_video(payload(event))["status"], "failed")

    def test_confirmed_plus_unknown_and_duplicates(self):
        result = decide_video(payload(observation(), observation(), observation("unknown")))
        self.assertEqual(result["verdict"], "violation")
        self.assertEqual(len(result["violations"]), 1)

    def test_api_rejects_missing_or_wrong_evidence(self):
        for frame in ({}, {"timestamp_sec": 10, "image_base64": "not-base64"},
                      {"timestamp_sec": 10, "image_base64": base64.b64encode(b"not jpeg").decode()},
                      {"timestamp_sec": 0, "image_base64": "anything"}):
            result = build_job_result("synthetic", payload(observation()), lambda t: frame)
            self.assertEqual(result["status"], "failed")
            self.assertNotIn("verdict", result)

    def test_api_negative_needs_no_frames(self):
        def unexpected(timestamp):
            raise AssertionError("No evidence required for a negative result")
        result = build_job_result("synthetic", payload(), unexpected)
        self.assertEqual(result, {"job_id": "synthetic", "status": "done",
                                  "verdict": "no_violation", "violations": []})


if __name__ == "__main__":
    unittest.main()
