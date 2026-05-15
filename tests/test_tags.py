from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from oci_backup_testing.config import TagSelector
from oci_backup_testing.tags import matches_tag


class DummyResource:
    def __init__(self, freeform_tags=None, defined_tags=None):
        self.freeform_tags = freeform_tags
        self.defined_tags = defined_tags


class TagTests(unittest.TestCase):
    def test_matches_freeform_tag_by_existence(self):
        resource = DummyResource(freeform_tags={"OCI-Backup-Testing": "yes"})
        selector = TagSelector(kind="freeform", key="OCI-Backup-Testing")
        self.assertTrue(matches_tag(resource, selector))

    def test_matches_freeform_tag_by_value(self):
        resource = DummyResource(freeform_tags={"OCI-Backup-Testing": "yes"})
        selector = TagSelector(kind="freeform", key="OCI-Backup-Testing", value="yes")
        self.assertTrue(matches_tag(resource, selector))

    def test_rejects_freeform_tag_wrong_value(self):
        resource = DummyResource(freeform_tags={"OCI-Backup-Testing": "no"})
        selector = TagSelector(kind="freeform", key="OCI-Backup-Testing", value="yes")
        self.assertFalse(matches_tag(resource, selector))

    def test_matches_defined_tag(self):
        resource = DummyResource(defined_tags={"Ops": {"OCI-Backup-Testing": "true"}})
        selector = TagSelector(
            kind="defined",
            namespace="Ops",
            key="OCI-Backup-Testing",
            value="true",
        )
        self.assertTrue(matches_tag(resource, selector))


if __name__ == "__main__":
    unittest.main()
