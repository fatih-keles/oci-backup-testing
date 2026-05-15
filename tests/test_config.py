from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from oci_backup_testing.config import AppConfig


class ConfigTests(unittest.TestCase):
    def test_supports_explicit_source_and_target_compartments(self):
        config = AppConfig.from_dict(
            {
                "source_compartment_id": "ocid1.compartment.oc1..source",
                "target_compartment_id": "ocid1.compartment.oc1..target",
            }
        )

        self.assertEqual(config.source_compartment_id, "ocid1.compartment.oc1..source")
        self.assertEqual(config.target_compartment_id, "ocid1.compartment.oc1..target")

    def test_keeps_legacy_single_compartment_config(self):
        config = AppConfig.from_dict(
            {
                "compartment_id": "ocid1.compartment.oc1..single",
            }
        )

        self.assertEqual(config.source_compartment_id, "ocid1.compartment.oc1..single")
        self.assertEqual(config.target_compartment_id, "ocid1.compartment.oc1..single")

    def test_state_retention_defaults(self):
        config = AppConfig.from_dict(
            {
                "compartment_id": "ocid1.compartment.oc1..single",
            }
        )

        self.assertEqual(config.state_retention.max_executions, 500)
        self.assertEqual(config.state_retention.max_age_days, 30)
        self.assertTrue(config.state_retention.prune_only_cleaned)


if __name__ == "__main__":
    unittest.main()
