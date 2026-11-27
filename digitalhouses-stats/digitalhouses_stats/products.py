from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REGISTRY_PATH = Path(__file__).with_name("product_registry.json")


@dataclass(frozen=True)
class ProductDefinition:
    identifier: str
    display_name: str
    telemetry_allowed: bool
    release: dict[str, str] | None


def _load_products() -> tuple[ProductDefinition, ...]:
    raw: dict[str, Any] = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    if raw.get("schema") != 1:
        raise RuntimeError("unsupported product registry schema")

    entries = raw.get("products")
    if not isinstance(entries, list) or not entries:
        raise RuntimeError("product registry must contain products")

    products: list[ProductDefinition] = []
    seen: set[str] = set()

    for entry in entries:
        if not isinstance(entry, dict):
            raise RuntimeError("invalid product registry entry")

        identifier = entry.get("id")
        display_name = entry.get("display_name")
        telemetry_allowed = entry.get("telemetry_allowed")
        release = entry.get("release")

        if not isinstance(identifier, str) or not identifier:
            raise RuntimeError("product registry id must be a non-empty string")
        if identifier in seen:
            raise RuntimeError(f"duplicate product registry id: {identifier}")
        if not isinstance(display_name, str) or not display_name:
            raise RuntimeError(f"missing display name for {identifier}")
        if not isinstance(telemetry_allowed, bool):
            raise RuntimeError(f"invalid telemetry_allowed for {identifier}")
        if release is not None and not isinstance(release, dict):
            raise RuntimeError(f"invalid release metadata for {identifier}")

        seen.add(identifier)
        products.append(
            ProductDefinition(
                identifier=identifier,
                display_name=display_name,
                telemetry_allowed=telemetry_allowed,
                release=release,
            )
        )

    return tuple(products)


PRODUCTS = _load_products()
PRODUCT_BY_ID = {product.identifier: product for product in PRODUCTS}
ALLOWED_PRODUCTS = frozenset(
    product.identifier for product in PRODUCTS if product.telemetry_allowed
)


def product_name(identifier: str) -> str:
    product = PRODUCT_BY_ID.get(identifier)
    return product.display_name if product is not None else identifier
