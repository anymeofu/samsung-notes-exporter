import unittest

from sn_archive_exporter.visible_batch_state import empty_state, mark_seen


class VisibleBatchStateTests(unittest.TestCase):
    def test_mark_seen_deduplicates_fingerprints(self):
        state = empty_state(run_id="run", folder_path="TestTasting/커피")

        mark_seen(state, ["a", "b", "a"], batch_id="batch1")
        mark_seen(state, ["b", "c"], batch_id="batch2")

        self.assertEqual(state["seen_fingerprints"], ["a", "b", "c"])
        self.assertEqual(len(state["batches"]), 2)
        self.assertEqual(state["batches"][0]["new_fingerprint_count"], 2)
        self.assertEqual(state["batches"][1]["new_fingerprint_count"], 1)


if __name__ == "__main__":
    unittest.main()
