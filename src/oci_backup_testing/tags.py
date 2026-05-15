from __future__ import annotations

from typing import Any

from .config import TagSelector


def matches_tag(resource: Any, selector: TagSelector) -> bool:
    """Return true when an OCI SDK model has the selected tag."""
    value = get_tag_value(resource, selector)
    if value is None:
        return False
    return selector.value is None or str(value) == selector.value


def get_tag_value(resource: Any, selector: TagSelector) -> Any | None:
    """Return the selected tag value from an OCI SDK model, or None when absent."""
    if selector.kind == "freeform":
        tags = getattr(resource, "freeform_tags", None) or {}
        return tags.get(selector.key)

    defined_tags = getattr(resource, "defined_tags", None) or {}
    namespace_tags = defined_tags.get(selector.namespace or "", {}) or {}
    return namespace_tags.get(selector.key)
