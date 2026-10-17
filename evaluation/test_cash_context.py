"""Three-rule model adapter contract; synthetic facts only."""
import copy
import time
from types import SimpleNamespace
import unittest
from app.rules.catalog import RULE_CATALOG
from app.rules.context import RULE_TYPES, enrich_service_context
from app.rules.decision import decide_video
from evaluation.test_decision import payload, observation


def bundle(positive=None):
    return {name: [["o" if name == positive else "r", [0, 1]]
                   for _ in RULE_CATALOG[name]["conditions"]] for name in RULE_TYPES}


def reader_factory():
    reader = SimpleNamespace(duration=20, closed=False)
    reader.sample = lambda *args: [SimpleNamespace(timestamp_sec=10), SimpleNamespace(timestamp_sec=15)]
    reader.close = lambda: setattr(reader, "closed", True)
    return reader


class CashContextTests(unittest.TestCase):
    def test_all_three_rules_can_reach_final_positive(self):
        for rule_type in RULE_TYPES:
            data = payload(observation("cash_left_unattended"))
            original = copy.deepcopy(data)
            reader = reader_factory()
            model = SimpleNamespace(check_cash_rules_context=lambda *args: bundle(rule_type))
            enriched = enrich_service_context(data, "synthetic.mov", model, time.perf_counter()+60,
                                               lambda *args: reader)
            result = decide_video(enriched)
            self.assertEqual(result["verdict"], "violation")
            self.assertEqual(result["violations"][0]["type"], RULE_CATALOG[rule_type]["title"])
            self.assertEqual(data, original)
            self.assertTrue(reader.closed)

    def test_refuted_conditions_give_negative_without_unknowns(self):
        data = payload(observation("cash_left_unattended"))
        model = SimpleNamespace(check_cash_rules_context=lambda *args: bundle())
        enriched = enrich_service_context(data, "synthetic.mov", model, time.perf_counter()+60,
                                           lambda *args: reader_factory())
        self.assertEqual(decide_video(enriched)["verdict"], "no_violation")

    def test_unknowns_not_erased_by_narrow_rule_checks(self):
        model = SimpleNamespace(check_cash_rules_context=lambda *args: bundle())
        enriched = enrich_service_context(payload(observation("unknown")), "synthetic.mov", model,
                                           time.perf_counter()+60, lambda *args: reader_factory())
        self.assertEqual(decide_video(enriched)["status"], "failed")

    def test_cash_handling_triggers_broader_review(self):
        model = SimpleNamespace(check_cash_rules_context=lambda *args: bundle("previous_cash_outside_storage"))
        enriched = enrich_service_context(payload(observation("cash_handling")), "synthetic.mov", model,
                                           time.perf_counter()+60, lambda *args: reader_factory())
        self.assertEqual(decide_video(enriched)["verdict"], "violation")

    def test_bad_evidence_and_schema_fail_closed(self):
        for value in ({}, {name: [] for name in RULE_TYPES},
                      {name: [["o", []] for _ in RULE_CATALOG[name]["conditions"]] for name in RULE_TYPES},
                      {name: [["o", [True]] for _ in RULE_CATALOG[name]["conditions"]] for name in RULE_TYPES}):
            model = SimpleNamespace(check_cash_rules_context=lambda *args: value)
            reader = reader_factory()
            with self.assertRaises(ValueError):
                enrich_service_context(payload(observation("cash_handling")), "synthetic.mov", model,
                                       time.perf_counter()+60, lambda *args: reader)
            self.assertTrue(reader.closed)

    def test_budget_exhaustion_does_not_produce_clean_negative(self):
        def unexpected(*args):
            raise AssertionError("No GPU call after deadline")
        model = SimpleNamespace(check_cash_rules_context=unexpected)
        enriched = enrich_service_context(payload(observation("cash_handling")), "synthetic.mov", model,
                                           time.perf_counter()-1, lambda *args: reader_factory())
        self.assertEqual(decide_video(enriched)["status"], "failed")
        self.assertTrue(enriched["rule_context_summary"]["incomplete"])

    def test_adjacent_candidates_share_one_window(self):
        calls=[]
        model=SimpleNamespace(check_cash_rules_context=lambda *args: calls.append(1) or bundle())
        enriched = enrich_service_context(payload(observation("cash_handling"), observation("cash_transfer")),
                                           "synthetic.mov", model, time.perf_counter()+60,
                                           lambda *args: reader_factory())
        self.assertEqual(len(calls), 1)
        self.assertEqual(enriched["rule_context_summary"]["checked_windows"], 1)


if __name__ == "__main__":
    unittest.main()
