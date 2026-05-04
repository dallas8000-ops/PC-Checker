"""Finding serialization (next_steps for UI / export)."""

from __future__ import annotations

import unittest

from pc_checker.finding import Finding
from pc_checker.state import finding_to_dict


class FindingTests(unittest.TestCase):
    def test_next_steps_roundtrip_dict(self) -> None:
        f = Finding("warn", "T", "D", next_steps=("a", "b"))
        d = finding_to_dict(f)
        self.assertEqual(d["next_steps"], ["a", "b"])

    def test_empty_next_steps_omitted(self) -> None:
        f = Finding("ok", "T", "D")
        d = finding_to_dict(f)
        self.assertNotIn("next_steps", d)


if __name__ == "__main__":
    unittest.main()
