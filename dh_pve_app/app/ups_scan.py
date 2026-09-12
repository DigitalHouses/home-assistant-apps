from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .config import UpsConfig
from .state_store import StateStore
from .ups_nut import NutReadError, list_ups


@dataclass(frozen=True)
class UpsScanOutcome:
    result: str
    last_scan: str
    count: int
    names: tuple[str, ...]
    selected_name: str | None
    selection_changed: bool
    error: str | None = None

    def payload(self) -> dict[str, object]:
        return {
            "result": self.result,
            "last_scan": self.last_scan,
            "count": self.count,
            "names": list(self.names),
            "selected_name": self.selected_name,
            "error": self.error,
        }


class UpsScanner:
    """Manual UPS provisioning state for one dh_pve_app instance."""

    def __init__(
        self,
        config: UpsConfig,
        state_store: StateStore,
        *,
        now_iso: Callable[[], str],
        list_reader: Callable[[UpsConfig], tuple[str, ...]] = list_ups,
    ) -> None:
        self.config = config
        self.state_store = state_store
        self.now_iso = now_iso
        self.list_reader = list_reader

    def selected_name(self) -> str | None:
        value = self.state_store.load().get("selected_name")
        if isinstance(value, str):
            value = value.strip()
            if value:
                return value
        return None

    def _save_selected(self, name: str) -> None:
        state = self.state_store.load()
        state["selected_name"] = name
        self.state_store.save(state)

    def scan(self) -> UpsScanOutcome:
        last_scan = self.now_iso()
        current = self.selected_name()

        try:
            names = tuple(dict.fromkeys(name.strip() for name in self.list_reader(self.config) if name.strip()))
        except NutReadError as exc:
            return UpsScanOutcome(
                result="NUT недоступен",
                last_scan=last_scan,
                count=0,
                names=(),
                selected_name=current,
                selection_changed=False,
                error=str(exc),
            )

        if not names:
            return UpsScanOutcome(
                result="UPS не найден",
                last_scan=last_scan,
                count=0,
                names=(),
                selected_name=current,
                selection_changed=False,
            )

        if len(names) > 1:
            return UpsScanOutcome(
                result="Обнаружено несколько UPS",
                last_scan=last_scan,
                count=len(names),
                names=names,
                selected_name=current,
                selection_changed=False,
            )

        selected = names[0]
        changed = selected != current
        if changed:
            self._save_selected(selected)

        return UpsScanOutcome(
            result=f"UPS найден: {selected}",
            last_scan=last_scan,
            count=1,
            names=names,
            selected_name=selected,
            selection_changed=changed,
        )
