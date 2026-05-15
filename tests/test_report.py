from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from oci_backup_testing.config import AppConfig
from oci_backup_testing.report import render_report, report_object_name


class ReportTests(unittest.TestCase):
    def test_report_object_name_uses_prefix_and_timestamp(self):
        config = AppConfig.from_dict(
            {
                "compartment_id": "ocid1.compartment.oc1..single",
                "report": {
                    "object_name_prefix": "reports/oci",
                },
            }
        )

        object_name = report_object_name(
            config,
            datetime(2026, 5, 15, 10, 20, 30, tzinfo=timezone.utc),
        )

        self.assertEqual(
            object_name,
            "reports/oci/oci-backup-validation-20260515T102030Z.html",
        )

    def test_report_object_name_uses_batch_id_when_available(self):
        config = AppConfig.from_dict(
            {
                "compartment_id": "ocid1.compartment.oc1..single",
                "report": {
                    "object_name_prefix": "reports/oci",
                },
            }
        )

        object_name = report_object_name(config, batch_id="batch-123")

        self.assertEqual(
            object_name,
            "reports/oci/oci-backup-validation-batch-batch-123.html",
        )

    def test_render_report_escapes_names_and_includes_status(self):
        config = AppConfig.from_dict(
            {
                "compartment_id": "ocid1.compartment.oc1..single",
                "report": {
                    "title": "Compliance <Report>",
                },
            }
        )
        html = render_report(
            config,
            [
                {
                    "source_display_name": "vg<prod>",
                    "source_volume_group_id": "ocid1.volumegroup.one",
                    "latest_backup_display_name": "Auto-backup via policy: gold on 2026-05-15",
                    "latest_backup_id": "ocid1.volumegroupbackup.one",
                    "latest_backup_time_created": "2026-05-15T00:00:00Z",
                    "restored_volume_group_display_name": "restore",
                    "restored_volume_group_id": "ocid1.volumegroup.restore",
                    "instance_display_name": "vm",
                    "instance_id": "ocid1.instance.one",
                    "boot_volume_id": "ocid1.bootvolume.one",
                    "boot_volume_size_in_gbs": 50,
                    "block_volume_ids": ["ocid1.volume.one"],
                    "block_volume_sizes_in_gbs": [100],
                    "volume_attachment_ids": ["ocid1.volumeattachment.one"],
                    "run_id": "run-1",
                    "validation": {
                        "passed": True,
                        "checks": [
                            {
                                "name": "restored_volume_group_available",
                                "resource_id": "ocid1.volumegroup.restore",
                                "passed": True,
                            },
                            {
                                "name": "instance_running",
                                "resource_id": "ocid1.instance.one",
                                "passed": True,
                            },
                            {
                                "name": "block_volume_attached",
                                "resource_id": "ocid1.volumeattachment.one",
                                "passed": True,
                            },
                        ],
                    },
                }
            ],
            batch={"batch_id": "batch-123", "created_at": "2026-05-15T00:00:00Z"},
        )

        self.assertIn("Compliance &lt;Report&gt;", html)
        self.assertIn("Batch: batch-123", html)
        self.assertIn("vg&lt;prod&gt;", html)
        self.assertIn("PASSED", html)
        self.assertIn("Volume Group Evidence", html)
        self.assertIn("VM Evidence", html)
        self.assertIn("Disk Evidence", html)
        self.assertIn("gold", html)
        self.assertIn("Restored boot volume", html)
        self.assertIn("50 GB", html)
        self.assertIn("100 GB", html)
        self.assertIn("Standards and Control Mapping", html)
        self.assertIn("Do not claim compliance with a framework", html)
        self.assertIn("NIST SP 800-53 Rev. 5", html)
        self.assertIn("CIS Controls v8.1 - Control 11", html)
        self.assertIn("Sama Rulebook", html)
        self.assertIn("Data Backup and Recoverability", html)
        self.assertIn("Sections 3.3.10-11", html)
        self.assertIn("periodic testing and validation", html)
        self.assertIn("NCA Essential Cybersecurity Controls", html)
        self.assertIn("Backup and Recovery Management", html)
        self.assertIn("Sections 2-9-3-3", html)
        self.assertIn("Periodic tests of backup&#x27;s recovery effectiveness", html)
        self.assertNotIn("max-width: 1180px", html)

    def test_render_report_uses_boot_volume_display_name_when_available(self):
        config = AppConfig.from_dict(
            {
                "compartment_id": "ocid1.compartment.oc1..single",
                "report": {
                    "title": "Compliance Report",
                },
            }
        )

        html = render_report(
            config,
            [
                {
                    "source_display_name": "vg",
                    "source_volume_group_id": "ocid1.volumegroup.one",
                    "latest_backup_display_name": "backup",
                    "latest_backup_id": "ocid1.volumegroupbackup.one",
                    "restored_volume_group_display_name": "restore",
                    "restored_volume_group_id": "ocid1.volumegroup.restore",
                    "instance_display_name": "vm",
                    "instance_id": "ocid1.instance.one",
                    "boot_volume_display_name": "boot-volume-from-backup",
                    "boot_volume_id": "ocid1.bootvolume.one",
                    "validation": {"passed": True},
                }
            ],
        )

        self.assertIn("boot-volume-from-backup", html)


if __name__ == "__main__":
    unittest.main()
