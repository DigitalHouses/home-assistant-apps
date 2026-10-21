"""Read/write only this own Supervisor App Options endpoint."""
from __future__ import annotations
import json
import os
import urllib.request
from collections.abc import Mapping
from .catalog import CatalogError


class SupervisorOptions:
    def __init__(self, token: str | None = None, url: str = "http://supervisor",
                 timeout: float = 8.0):
        self.token = token if token is not None else os.getenv("SUPERVISOR_TOKEN", "")
        if not self.token:
            raise CatalogError("SUPERVISOR_TOKEN is missing")
        self.url, self.timeout = url.rstrip("/"), timeout

    def _request(self, route: str, payload: Mapping | None = None) -> dict:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(
            self.url + route,
            data=body,
            headers={"Authorization": "Bearer " + self.token,
                     "Content-Type": "application/json"},
            method="POST" if body is not None else "GET",
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as response:
            raw = response.read(1_048_577)
        if len(raw) > 1_048_576:
            raise CatalogError("Supervisor response exceeds limit")
        value = json.loads(raw)
        if not isinstance(value, dict) or value.get("result") != "ok":
            raise CatalogError("Supervisor rejected App Options request")
        return value

    def read(self) -> dict:
        obj = self._request("/addons/self/options/config").get("data")
        if not isinstance(obj, dict):
            raise CatalogError("Invalid own App Options")
        return obj

    def write(self, options: Mapping) -> None:
        self._request("/addons/self/options", {"options": dict(options)})
