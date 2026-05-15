from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from oci_backup_testing.compute import _hostname_label


class ComputeTests(unittest.TestCase):
    def test_hostname_label_uses_unique_suffix_with_oci_limit(self):
        label = _hostname_label("ocitest", "bp2ia6xa")

        self.assertEqual(label, "ocites-bp2ia6xa")
        self.assertLessEqual(len(label), 15)

    def test_hostname_label_sanitizes_prefix_and_suffix(self):
        label = _hostname_label("OCI_Test", "abc_def")

        self.assertEqual(label, "oci-tes-abc-def")
        self.assertLessEqual(len(label), 15)


if __name__ == "__main__":
    unittest.main()
