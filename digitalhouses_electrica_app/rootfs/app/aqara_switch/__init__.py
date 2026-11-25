"""Pure configuration/discovery contract of DigitalHouses Aqara Switch App."""

from .catalog import (CatalogError, candidate_from_mqtt, import_new,
                      resolve_hardware, validate_config)

__all__ = ("CatalogError", "candidate_from_mqtt", "import_new",
           "resolve_hardware", "validate_config")
