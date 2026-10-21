"""Expose only the short human-editable YAML switch action tree."""
from __future__ import annotations
from collections.abc import Mapping
from .entity_options import current


def parse_configuration(options: Mapping, *, profile_path=None) -> dict:
    if profile_path is None:
        return current(options)
    return current(options, profile_path)
