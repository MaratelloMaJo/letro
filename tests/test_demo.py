import unittest

from scripts.demo import story


class DemoTest(unittest.TestCase):
    def test_story_has_five_sections_in_order(self):
        self.assertEqual(
            story(),
            [
                "clean books",
                "naive reconciliation",
                "thorough audit",
                "permutation",
                "red team",
            ],
        )


if __name__ == "__main__":
    unittest.main()
