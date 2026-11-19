"""The shipped verifier's technical criteria must all pass."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from letro.verify import (
    OPEN_FILES,
    ROOT,
    _digest,
    criterion_contract,
    criterion_data,
    criterion_reproducibility,
    criterion_reward,
)


class VerifyTests(unittest.TestCase):
    def assert_all(self, checks):
        failed = [f"{check.name}: {check.detail}" for check in checks if not check.passed]
        self.assertFalse(failed, "\n".join(failed))

    def test_contract(self):
        self.assert_all(criterion_contract())

    def test_data(self):
        self.assert_all(criterion_data([]))

    def test_reward(self):
        self.assert_all(criterion_reward())

    def test_reproducibility(self):
        self.assert_all(criterion_reproducibility())

    def test_digest_ignores_checkout_line_endings(self):
        index = json.loads(
            (ROOT / "episodes" / "index.json").read_text(encoding="utf-8")
        )
        entry = index["dev"][0]
        source = ROOT / entry["directory"]
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            for name in OPEN_FILES:
                data = (source / name).read_bytes().replace(b"\r\n", b"\n")
                (target / name).write_bytes(data.replace(b"\n", b"\r\n"))
            self.assertEqual(_digest(target), entry["open_files_sha256"])


if __name__ == "__main__":
    unittest.main()
