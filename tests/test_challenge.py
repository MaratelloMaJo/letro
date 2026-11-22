"""Tests for the sanitized challenge scoring surface."""

import unittest

from letro.challenge import score_submission
from letro.generator import load_episode, reference_findings


class ChallengeTest(unittest.TestCase):
    def test_oracle_submission_scores_perfectly(self):
        episode = load_episode("episodes/dev/ep-0dc0a85bf7")
        result = score_submission(episode, reference_findings(episode))
        self.assertEqual(result["f1"], 1.0)
        self.assertEqual(result["tp"], len(episode.truth["issues"]))
        self.assertEqual(result["fp"], 0)
        self.assertEqual(result["fn"], 0)
        self.assertNotIn("issue_id", result)
        self.assertTrue(all(set(item) == {"index", "matched"} for item in result["findings"]))

    def test_empty_submission_is_valid_and_has_no_truth_ids(self):
        episode = load_episode("episodes/dev/ep-0dc0a85bf7")
        result = score_submission(episode, {"episode_id": episode.manifest["episode_id"], "findings": []})
        self.assertEqual(result["tp"], 0)
        self.assertNotIn("missed_issue_ids", result)


if __name__ == "__main__":
    unittest.main()
