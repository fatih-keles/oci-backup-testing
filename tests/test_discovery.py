from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from oci_backup_testing.discovery import (
    DiscoveryError,
    VolumeGroupPlan,
    filter_volume_group_plans,
)


def plan(name: str, ocid: str) -> VolumeGroupPlan:
    return VolumeGroupPlan(
        source_compartment_id="ocid1.compartment.oc1..source",
        source_volume_group_id=ocid,
        source_display_name=name,
        availability_domain="AD-1",
        latest_backup_id=f"{ocid}.backup",
        latest_backup_display_name=f"{name}-backup",
        latest_backup_time_created="2026-05-15T00:00:00+00:00",
    )


class VolumeGroupFilterTests(unittest.TestCase):
    def test_filters_by_source_volume_group_ocid(self):
        plans = [plan("vg-linux", "ocid1.volumegroup.one"), plan("vg-win", "ocid1.volumegroup.two")]

        selected = filter_volume_group_plans(plans, "ocid1.volumegroup.two")

        self.assertEqual([item.source_display_name for item in selected], ["vg-win"])

    def test_rejects_display_name(self):
        plans = [plan("vg-linux", "ocid1.volumegroup.one"), plan("vg-win", "ocid1.volumegroup.two")]

        with self.assertRaises(DiscoveryError):
            filter_volume_group_plans(plans, "vg-linux")

    def test_rejects_missing_ocid(self):
        plans = [plan("vg-linux", "ocid1.volumegroup.one")]

        with self.assertRaises(DiscoveryError):
            filter_volume_group_plans(plans, "ocid1.volumegroup.missing")


if __name__ == "__main__":
    unittest.main()
