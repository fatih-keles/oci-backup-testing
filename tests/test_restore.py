from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from oci_backup_testing.restore import restored_volume_group_display_name


class RestoreNamingTests(unittest.TestCase):
    def test_restored_volume_group_name_includes_source_display_name(self):
        name = restored_volume_group_display_name(
            "oci-restore-test",
            "vg-linux_test_instance",
            "ocid1.volumegroup.oc1.me-jeddah-1.examplew2ccla6q",
            "20260514115740",
        )

        self.assertEqual(
            name,
            "oci-restore-test-vg-linux_test_instance-w2ccla6q-20260514115740",
        )


if __name__ == "__main__":
    unittest.main()
