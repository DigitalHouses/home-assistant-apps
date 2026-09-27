from __future__ import annotations

from collections.abc import Mapping


def unique_id_from_entity_id(entity_id: object) -> str | None:
    """Return the public unique_id derived from a canonical HA entity_id."""
    if not isinstance(entity_id, str) or "." not in entity_id:
        return None
    _domain, object_id = entity_id.split(".", 1)
    object_id = object_id.strip()
    if not object_id:
        return None
    return f"{object_id}_id"


def canonicalize_component_unique_ids(components: Mapping[str, object]) -> None:
    """Make every Discovery unique_id mechanically derivable from entity_id."""
    for component in components.values():
        if not isinstance(component, dict):
            continue
        unique_id = unique_id_from_entity_id(component.get("default_entity_id"))
        if unique_id is not None:
            component["unique_id"] = unique_id
