from __future__ import annotations

from dataclasses import dataclass

from .ups_nut import UpsSnapshot


@dataclass(frozen=True)
class UpsProblemSummary:
    count: int
    severity: str
    problems: tuple[str, ...]
    details: str


def summarize_ups_problems(
    snapshot: UpsSnapshot | None,
    *,
    nut_available: bool = True,
) -> UpsProblemSummary:
    problems: list[str] = []
    severities: list[str] = []

    def add(message: str, severity: str) -> None:
        problems.append(message)
        severities.append(severity)

    if not nut_available or snapshot is None:
        add("Данные ИБП через NUT недоступны.", "critical")
    else:
        if snapshot.on_battery:
            add("ИБП работает от батареи.", "warning")
        if snapshot.low_battery:
            add("Низкий заряд батареи.", "critical")
        if snapshot.overload:
            add("Перегрузка ИБП.", "critical")
        if snapshot.replace_battery:
            add("Требуется замена батареи ИБП.", "warning")
        if snapshot.bypass:
            add("ИБП работает в режиме bypass.", "warning")

        power_state_known = snapshot.line_power or snapshot.on_battery or snapshot.bypass
        if not power_state_known:
            add("Состояние питания ИБП не определено.", "warning")

    if "critical" in severities:
        severity = "critical"
    elif "warning" in severities:
        severity = "warning"
    else:
        severity = "ok"

    if problems:
        details = "\n".join(
            f"{index}. {message}"
            for index, message in enumerate(problems, start=1)
        )
    else:
        details = "Проблем не обнаружено."

    return UpsProblemSummary(
        count=len(problems),
        severity=severity,
        problems=tuple(problems),
        details=details,
    )
