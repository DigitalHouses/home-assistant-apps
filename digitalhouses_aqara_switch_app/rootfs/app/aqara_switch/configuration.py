"""One YAML text field in Supervisor Options, validated as a rooms->switches tree.

Supervisor's two-level schema depth is insufficient for editable nested switch
profiles; therefore 'configuration_yaml' is a single lossless text field.
"""
from __future__ import annotations
from collections.abc import Mapping
import yaml
from .catalog import CatalogError, validate_config


def parse_configuration(options: Mapping) -> dict:
    raw = options.get("configuration_yaml")
    if not isinstance(raw, str) or not raw.strip():
        raise CatalogError("Supervisor configuration_yaml must be nonempty YAML")
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise CatalogError("Invalid configuration_yaml syntax") from exc
    return validate_config(data)


def encode_configuration(data: Mapping) -> str:
    validated = validate_config(data)
    return yaml.safe_dump(
        validated, allow_unicode=True, sort_keys=False, default_flow_style=False
    )


def replace_configuration(options: Mapping, data: Mapping) -> dict:
    if not isinstance(options, Mapping):
        raise CatalogError("Supervisor App Options must be a mapping")
    merged = dict(options)
    merged["configuration_yaml"] = encode_configuration(data)
    return merged
