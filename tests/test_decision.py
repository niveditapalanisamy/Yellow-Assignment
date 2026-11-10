import unittest
from agent.decision import overall_release_status, RequirementStatus, ReleaseStatus


class DecisionTests(unittest.TestCase):
    def test_any_fail_blocks(self):
        self.assertEqual(overall_release_status([RequirementStatus.PASS, RequirementStatus.FAIL]), ReleaseStatus.BLOCKED)

    def test_insufficient_without_fail_needs_review(self):
        self.assertEqual(overall_release_status(['PASS', 'INSUFFICIENT_EVIDENCE']), ReleaseStatus.NEEDS_REVIEW)

    def test_all_pass_ready(self):
        self.assertEqual(overall_release_status(['PASS', 'PASS']), ReleaseStatus.READY)

    def test_empty_is_needs_review(self):
        self.assertEqual(overall_release_status([]), ReleaseStatus.NEEDS_REVIEW)

    def test_unknown_status_rejected(self):
        with self.assertRaises(ValueError):
            overall_release_status(['DONE'])
