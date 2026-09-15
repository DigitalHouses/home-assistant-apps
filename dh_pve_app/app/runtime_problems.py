from __future__ import annotations

import queue
from collections.abc import Mapping

from .diagnostic_events import DiagnosticEvent
from .problems import PveProblemEngine, ProblemState, ProblemTransition
from .runtime_dynamic import DynamicDiscoveryRuntime


class _RuntimeProblemEngine(PveProblemEngine):
    """Small runtime-facing view over the pure problem engine state."""

    def states(self) -> tuple[ProblemState, ...]:
        return tuple(self._states[key] for key in sorted(self._states))

    def threshold_key(self, problem_id: str) -> str | None:
        binding = self._numeric.get(problem_id)
        return binding.threshold_key if binding is not None else None


class ProblemAwareRuntime(DynamicDiscoveryRuntime):
    """Dynamic Discovery runtime with coherent retained problem publication.

    Problem evaluation never changes collection cadence. A diagnostic Event is
    emitted only after the complete related retained-state bundle succeeds.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.problem_engine = _RuntimeProblemEngine()
        self._published_problem_ids: set[str] = set()
        self._pending_problem_transitions: list[ProblemTransition] = []
        self._problem_snapshot_dirty = False

    @staticmethod
    def _metric_payload(state: ProblemState) -> dict[str, object]:
        return {
            "metric": state.metric,
            "value": state.value,
            "average": state.average,
        }

    def _presentation_payload(self) -> dict[str, object]:
        aggregate = self.problem_engine.aggregate()
        return {
            "severity": aggregate.severity,
            "summary": aggregate.summary,
            "active": list(aggregate.active),
        }

    def _publish_problem_core(self, state: ProblemState) -> bool:
        if not self.bridge.publish_problem_metric(
            state.problem_id,
            self._metric_payload(state),
        ):
            return False

        threshold_key = self.problem_engine.threshold_key(state.problem_id)
        if threshold_key is not None:
            threshold = state.threshold
            if threshold is None:
                try:
                    threshold = self.settings.get(threshold_key)
                except ValueError:
                    return False
            if not self.bridge.publish_setting_value(threshold_key, threshold):
                return False

        if not self.bridge.publish_problem_state(state.problem_id, state.active):
            return False
        return True

    def _publish_aggregate_bundle(self) -> bool:
        aggregate = self.problem_engine.aggregate()
        if not self.bridge.publish_problem_aggregate(aggregate.count):
            return False
        if not self.bridge.publish_problem_presentation(self._presentation_payload()):
            return False
        return True

    def _publish_transition(self, transition: ProblemTransition) -> bool:
        state = transition.current
        if not self._publish_problem_core(state):
            return False
        if not self._publish_aggregate_bundle():
            return False

        aggregate = self.problem_engine.aggregate()
        event = DiagnosticEvent.from_transition(
            transition,
            active_problem_count=aggregate.count,
        )
        if not self.bridge.publish_diagnostic_event(event.as_payload()):
            return False

        self._published_problem_ids.add(state.problem_id)
        self._problem_snapshot_dirty = False
        return True

    def _flush_pending_transitions(self) -> bool:
        while self._pending_problem_transitions:
            transition = self._pending_problem_transitions[0]
            if not self._publish_transition(transition):
                return False
            self._pending_problem_transitions.pop(0)
        return True

    def _sync_current_problem_states(self) -> bool:
        pending_ids = {
            transition.current.problem_id
            for transition in self._pending_problem_transitions
        }
        unpublished = [
            state
            for state in self.problem_engine.states()
            if state.problem_id not in self._published_problem_ids
            and state.problem_id not in pending_ids
        ]

        published_any = False
        for state in unpublished:
            if not self._publish_problem_core(state):
                return False
            self._published_problem_ids.add(state.problem_id)
            published_any = True

        if published_any:
            self._problem_snapshot_dirty = True

        if self._problem_snapshot_dirty:
            if not self._publish_aggregate_bundle():
                return False
            self._problem_snapshot_dirty = False
        return True

    def _problem_inputs(self, selected: tuple[str, ...]) -> dict[str, object]:
        result: dict[str, object] = {}
        for name in selected:
            state = self._subsystems.get(name)
            if state is None or not state.available or state.data is None:
                continue
            result[name] = self._jsonable(state.data)
        return result

    def run_collection(
        self,
        names: tuple[str, ...] | list[str] | None = None,
        *,
        force: bool = False,
        manual_refresh: bool = False,
    ) -> bool:
        # An Event for an earlier transition must never be overtaken by a new
        # observation. Retry its retained bundle first.
        pending_ok = self._flush_pending_transitions()
        if not pending_ok:
            return False

        selected = tuple(self.collectors) if names is None else tuple(names)
        state_ok = super().run_collection(
            selected,
            force=force,
            manual_refresh=manual_refresh,
        )

        inputs = self._problem_inputs(selected)
        transitions = self.problem_engine.observe(
            self.now_monotonic(),
            inputs,
            self.settings.as_dict(),
        )
        self._pending_problem_transitions.extend(transitions)

        transitions_ok = self._flush_pending_transitions()
        snapshot_ok = self._sync_current_problem_states()
        return state_ok and transitions_ok and snapshot_ok

    def _republish_problem_snapshot(self) -> bool:
        self._published_problem_ids.clear()
        self._problem_snapshot_dirty = True
        return self._sync_current_problem_states()

    def process_events(self) -> bool:
        handled = False

        if self.bridge.reconnect_requested.is_set():
            self.bridge.reconnect_requested.clear()
            self.republish_after_reconnect()
            self._flush_pending_transitions()
            self._republish_problem_snapshot()
            handled = True

        if self.bridge.refresh_requested.is_set():
            self.bridge.refresh_requested.clear()
            self.manual_refresh()
            handled = True

        while True:
            try:
                update = self.bridge.setting_updates.get_nowait()
            except queue.Empty:
                break

            transitions = self.problem_engine.reevaluate_threshold(
                update.key,
                update.value,
            )
            if transitions:
                self._pending_problem_transitions.extend(transitions)
                self._flush_pending_transitions()
            else:
                self.bridge.publish_setting_value(update.key, update.value)

            # Validation/application already happened in MqttEvents. Persist the
            # accepted app-owned threshold without touching Scheduler intervals.
            self._persist_runtime_state()
            handled = True

        return handled
