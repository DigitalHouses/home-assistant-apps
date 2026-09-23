from __future__ import annotations

import re


COUNTRY_RE = re.compile(r"^[A-Z]{2}$")


def country_from_cloudflare(value: str | None) -> str:
    if not value:
        return "XX"

    country = value.strip().upper()

    # Cloudflare special values: XX = unknown, T1 = Tor network.
    # We deliberately keep only ISO-like country codes in storage.
    if country in {"XX", "T1"}:
        return "XX"

    if COUNTRY_RE.fullmatch(country) is None:
        return "XX"

    return country
