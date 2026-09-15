from __future__ import annotations

from dataclasses import dataclass

from .ups_nut import UpsSnapshot


@dataclass(frozen=True)
class UpsProblemSummary:
    count: int
    severity: str
    problems: tuple[str, ...]
    details: str


@dataclass(frozen=True)
class UpsProblemObservation:
    problem_id: str
    active: bool
    severity: str
    message: str
    label: str


def ups_problem_observations(
    snapshot: UpsSnapshot | None,
    *,
    nut_available: bool = True,
) -> tuple[UpsProblemObservation, ...]:
    """Return decision-ready UPS problem states from the canonical health policy.

    When NUT is unavailable, snapshot-derived problem states are deliberately
    omitted rather than forced OFF. This lets callers preserve the last known
    retained state until authoritative UPS data becomes available again.
    """
    if not nut_available or snapshot is None:
        return (
            UpsProblemObservation(
                problem_id="nut_unavailable",
                active=True,
                severity="critical",
                message="Данные ИБП через NUT недоступны.",
                label="NUT",
            ),
        )

    power_state_known = snapshot.line_power or snapshot.on_battery or snapshot.bypass
    return (
        UpsProblemObservation(
            problem_id="nut_unavailable",
            active=False,
            severity="critical",
            message="Данные ИБП через NUT недоступны.",
            label="NUT",
        ),
        UpsProblemObservation(
            problem_id="on_battery",
            active=snapshot.on_battery,
            severity="warning",
            message="ИБП работает от батареи.",
            label="Работа от батареи",
        ),
        UpsProblemObservation(
            problem_id="low_battery",
            active=snapshot.low_battery,
            severity="critical",
            message="Низкий заряд батареи.",
            label="Низкий заряд батареи",
        ),
        UpsProblemObservation(
            problem_id="overload",
            active=snapshot.overload,
            severity="critical",
            message="Перегрузка ИБП.",
            label="Перегрузка ИБП",
        ),
        UpsProblemObservation(
            problem_id="replace_battery",
            active=snapshot.replace_battery,
            severity="warning",
            message="Требуется замена батареи ИБП.",
            label="Замена батареи ИБП",
        ),
        UpsProblemObservation(
            problem_id="bypass",
            active=snapshot.bypass,
            severity="warning",
            message="ИБП работает в режиме bypass.",
            label="Режим bypass",
        ),
        UpsProblemObservation(
            problem_id="power_state_unknown",
            active=not power_state_known,
            severity="warning",
            message="Состояние питания ИБП не определено.",
            label="Состояние питания ИБП",
        ),
    )


def summarize_ups_problems(
    snapshot: UpsSnapshot | None,
    *,
    nut_available: bool = True,
) -> UpsProblemSummary:
    active = tuple(
        observation
        for observation in ups_problem_observations(
            snapshot,
            nut_available=nut_available,
        )
        if observation.active
    )
    problems = tuple(observation.message for observation in active)
    severities = tuple(observation.severity for observation in active)

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
        problems=problems,
        details=details,
    )
