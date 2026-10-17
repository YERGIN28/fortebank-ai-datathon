"""Artificial temporal contradictions; no video/model/ground-truth access."""
import copy
import unittest
from unittest.mock import patch

from app.rules.catalog import RULE_CATALOG
from app.rules.decision import decide_video
from app.rules.temporal import confirmed_time
from evaluation.test_ai4_rules import event_for, video


class TemporalTests(unittest.TestCase):
    def decide_counting(self, **changes):
        event = event_for('cash_counting_without_customer')
        event.update(start_sec=0, end_sec=20)
        for key, times in changes.items():
            event['condition_checks'][key]['evidence_timestamps_sec'] = times
        return decide_video(video(event))

    def test_disjoint_counting_and_absence_cannot_confirm(self):
        result = self.decide_counting(
            cash_is_identified=[1], direct_customer_cash_receipt=[1, 2],
            cashier_counts_received_cash=[3, 4], customer_zone_fully_visible=[14],
            customer_absent_during_counting=[15])
        self.assertEqual(result['status'], 'failed')
        self.assertNotIn('verdict', result)

    def test_overlapping_envelopes_do_not_prove_common_sample(self):
        result = self.decide_counting(cashier_counts_received_cash=[10, 14],
                                     customer_absent_during_counting=[12])
        self.assertEqual(result['status'], 'failed')

    def test_customer_zone_must_be_visible_at_counting_moment(self):
        result = self.decide_counting(customer_zone_fully_visible=[15])
        self.assertEqual(result['status'], 'failed')

    def test_cash_must_be_identified_at_counting_moment(self):
        result = self.decide_counting(cash_is_identified=[15])
        self.assertEqual(result['status'], 'failed')

    def test_receipt_may_precede_counting_without_sharing_frame(self):
        result = self.decide_counting(direct_customer_cash_receipt=[1, 2])
        self.assertEqual(result['verdict'], 'violation')
        self.assertEqual(result['violations'][0]['timecode_sec'], 12)

    def test_receipt_after_counting_is_unresolved(self):
        result = self.decide_counting(direct_customer_cash_receipt=[14, 15])
        self.assertEqual(result['status'], 'failed')

    def test_only_jointly_supported_timestamp_is_selected(self):
        result = self.decide_counting(cashier_counts_received_cash=[10, 12, 15])
        self.assertEqual(result['violations'][0]['timecode_sec'], 12)

    def test_no_arbitrary_two_second_temporal_tolerance(self):
        result = self.decide_counting(customer_absent_during_counting=[10.5, 12.5])
        self.assertEqual(result['status'], 'failed')

    def test_floating_point_roundoff_is_allowed(self):
        result = self.decide_counting(customer_absent_during_counting=[10.0000001, 12.0000001])
        self.assertEqual(result['verdict'], 'violation')

    def test_service_must_be_ongoing_at_departure_not_only_before(self):
        event = event_for('cashier_leaves_during_service')
        event['condition_checks']['customer_service_ongoing']['evidence_timestamps_sec'] = [10]
        self.assertEqual(decide_video(video(event))['status'], 'failed')

    def test_storage_receipt_completion_must_not_be_after_current_receipt(self):
        event = event_for('previous_cash_outside_storage')
        event['condition_checks']['previous_receipt_completed']['evidence_timestamps_sec'] = [15]
        self.assertEqual(decide_video(video(event))['status'], 'failed')

    def test_another_positive_survives_temporal_uncertainty(self):
        uncertain = event_for('cash_counting_without_customer')
        uncertain['condition_checks']['customer_absent_during_counting']['evidence_timestamps_sec'] = [15]
        result = decide_video(video(uncertain, event_for('cashier_leaves_during_service')))
        self.assertEqual(result['verdict'], 'violation')
        self.assertEqual(len(result['violations']), 1)

    def test_missing_or_invalid_policy_is_unresolved(self):
        name = 'cash_counting_without_customer'
        for policy in (None, {}, {'simultaneous': ['unprovided_fact'], 'after': []}):
            rule = copy.deepcopy(RULE_CATALOG[name])
            rule['temporal_policy'] = policy
            with self.subTest(policy=policy), patch.dict(RULE_CATALOG, {name: rule}):
                self.assertEqual(decide_video(video(event_for(name)))['status'], 'failed')

    def test_input_not_mutated(self):
        event = event_for('cash_counting_without_customer')
        original = copy.deepcopy(event)
        confirmed_time(RULE_CATALOG[event['type']], event['condition_checks'])
        self.assertEqual(event, original)


if __name__ == '__main__':
    unittest.main()
