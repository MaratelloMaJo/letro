import unittest

from letro.bench import BenchResult, archive_size, measure, run_bench


class BenchTest(unittest.TestCase):
    def test_measure_returns_percentiles(self):
        result = measure("noop", lambda: None, repeats=3)
        self.assertIsInstance(result, BenchResult)
        self.assertEqual(result.verdict, "PASS")
        self.assertTrue(0.0 <= result.p50_ms <= result.p95_ms <= result.max_ms)

    def test_run_bench_covers_generation_reset_and_steps(self):
        operations = {item.operation for item in run_bench(seeds=1)}
        self.assertIn("generation", operations)
        self.assertIn("reset", operations)
        self.assertIn("100_steps", operations)

    def test_archive_size_is_positive_and_under_one_gb(self):
        size = archive_size()
        self.assertGreater(size, 0)
        self.assertLess(size, 1_000_000_000)
