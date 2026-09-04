from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class DatabaseAdapter(ABC):
    @abstractmethod
    def fast_metrics(self, hour_cutoff: float | None = None) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def medium_metrics(self, hour_cutoff: float) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def slow_metrics(self, yesterday_start: float, today_start: float) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def static_metrics(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def top_entities(self, since_ts: float | None) -> list[tuple[str, int]]:
        raise NotImplementedError

    @abstractmethod
    def data_directory(self) -> str:
        raise NotImplementedError
