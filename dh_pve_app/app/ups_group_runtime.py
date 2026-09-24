from __future__ import annotations

from .diagnostic_events import DiagnosticEvent
from .machine_event_outbox import MachineEventOutbox
from .presentation_ups import UpsPresentationRouter
from .problems import ProblemState, ProblemTransition
from .ups_battery_events import UpsBatteryEventTracker
from .ups_event_context import (
    line_power_event_context,
    ups_snapshot_event_context,
)
from .ups_problem_events import semantic_ups_problem_event
from .ups_problems import UpsProblemEngine, transition_uses_status_event
from .ups_runtime import UpsRuntime
from .ups_status_events import UpsStatusEventTracker, semantic_status_events


class AdaptiveUpsRuntime(UpsRuntime):
    """UPS runtime that publishes independent retained presentation groups.

    The legacy monolithic path remains available when a bridge does not expose
    ``publish_ups_state_group`` so older unit fakes and compatibility callers
    keep their existing contract. Production MqttBridge uses this group path.

    App-owned UPS problem state is layered on top of the grouped path. It never
    changes NUT collection cadence or shutdown policy semantics. Diagnostic
    events are emitted only after the complete retained problem bundle succeeds.
    """

    def __init__(self, *args, **kwargs) -> None:
        self.machine_event_outbox: MachineEventOutbox | None = kwargs.pop(
            "machine_event_outbox", None
        )
        self.battery_event_tracker: UpsBatteryEventTracker | None = kwargs.pop(
            "battery_event_tracker", None
        )
        super().__init__(*args, **kwargs)
        self.presentation = UpsPresentationRouter(
            source_interval_seconds=self.config.poll_interval_seconds
        )
        self._last_group_payloads: dict[str, dict[str, object]] = {}
        self.problem_engine = UpsProblemEngine(
            object_id=self.config.name,
            object_name=self.config.name,
        )
        self.status_event_tracker = UpsStatusEventTracker()
        self._published_problem_ids: set[str] = set()
        self._pending_problem_transitions: list[ProblemTransition] = []
        self._problem_snapshot_dirty = False

    def _group_capable(self) -> bool:
        return callable(getattr(self.bridge, "publish_ups_state_group", None))

    def _problem_capable(self) -> bool:
        return all(
            callable(getattr(self.bridge, name, None))
            for name in (
                "publish_ups_problem_state",
                "publish_ups_problem_aggregate",
                "publish_ups_problem_presentation",
                "publish_ups_diagnostic_event",
            )
        )

    def _event_capable(self) -> bool:
        return callable(getattr(self.bridge, "publish_ups_diagnostic_event", None))

    def _semantic_events_enabled(self) -> bool:
        return self.machine_event_outbox is not None

    def _flush_machine_event_outbox(self) -> bool:
        outbox = self.machine_event_outbox
        if outbox is None:
            return True
        if not self._event_capable():
            return not outbox.pending()
        for pending in outbox.pending():
            if not self.bridge.publish_ups_diagnostic_event(pending.payload):
                return False
            outbox.acknowledge(pending.key)
        return True

    def _publish_groups(
        self,
        publications,
        *,
        collected_at: str,
        manual_refresh: bool = False,
    ) -> bool:
        publish = getattr(self.bridge, "publish_ups_state_group")
        publications = tuple(publications)
        diagnostics_publication = next(
            (publication for publication in publications if publication.group == "diagnostics"),
            None,
        )
        data_publications = tuple(
            publication for publication in publications if publication.group != "diagnostics"
        )

        for publication in data_publications:
            if not publish(publication.group, publication.payload):
                return False
            self._last_group_payloads[publication.group] = dict(publication.payload)

        if not data_publications and diagnostics_publication is None:
            return True

        if diagnostics_publication is not None:
            diagnostics = dict(diagnostics_publication.payload)
        else:
            diagnostics = dict(self._last_group_payloads.get("diagnostics", {}))

        profile_summary = self.presentation.profile_summary()
        diagnostics["app_profile"] = {
            "state": str(profile_summary.get("profile") or "normal"),
            "reason": profile_summary.get("reason"),
        }

        if data_publications:
            last = data_publications[-1]
            last_group = last.group
            last_reason = "manual_refresh" if manual_refresh else last.reason
            last_profile = last.profile.value
            group_count = len(data_publications)
        else:
            last = diagnostics_publication
            last_group = "diagnostics"
            last_reason = "manual_refresh" if manual_refresh else last.reason
            last_profile = last.profile.value
            group_count = 1

        diagnostics["last_publication"] = {
            "timestamp": collected_at,
            "group": last_group,
            "reason": last_reason,
            "profile": last_profile,
            "group_count": group_count,
        }

        if not publish("diagnostics", diagnostics):
            return False
        self._last_group_payloads["diagnostics"] = diagnostics
        return True

    def _problem_presentation_payload(self) -> dict[str, object]:
        aggregate = self.problem_engine.aggregate()
        return {
            "severity": aggregate.severity,
            "active": list(aggregate.active),
        }

    def _publish_problem_core(self, state: ProblemState) -> bool:
        return bool(
            self.bridge.publish_ups_problem_state(
                state.problem_id,
                state.active,
            )
        )

    def _publish_problem_aggregate_bundle(self) -> bool:
        aggregate = self.problem_engine.aggregate()
        if not self.bridge.publish_ups_problem_aggregate(aggregate.count):
            return False
        if not self.bridge.publish_ups_problem_presentation(
            self._problem_presentation_payload()
        ):
            return False
        return True

    def _publish_pending_problem_batch(self) -> bool:
        """Publish one coherent retained-state batch, then its Events.

        All changed binary states are retained before the aggregate/presentation
        snapshot is published. Only after that snapshot is coherent are Events
        emitted. Successfully emitted Events are removed from the pending queue,
        so a later Event failure never causes an earlier Event to be duplicated.
        """
        if not self._pending_problem_transitions:
            return True

        pending_ids = {
            transition.current.problem_id
            for transition in self._pending_problem_transitions
        }
        states = [
            transition.current
            for transition in self._pending_problem_transitions
        ]
        states.extend(
            state
            for state in self.problem_engine.states()
            if state.problem_id not in self._published_problem_ids
            and state.problem_id not in pending_ids
        )

        for state in states:
            if not self._publish_problem_core(state):
                return False
            if state.problem_id not in pending_ids:
                self._published_problem_ids.add(state.problem_id)

        if not self._publish_problem_aggregate_bundle():
            return False

        aggregate = self.problem_engine.aggregate()
        while self._pending_problem_transitions:
            transition = self._pending_problem_transitions[0]
            if self._semantic_events_enabled() and transition_uses_status_event(transition):
                self._published_problem_ids.add(transition.current.problem_id)
                self._pending_problem_transitions.pop(0)
                continue

            observed_at = self.now_iso()
            semantic_event = semantic_ups_problem_event(
                transition,
                observed_at=observed_at,
                context=(
                    ups_snapshot_event_context(self.last_snapshot)
                    if self.nut_available
                    else {}
                ),
            )
            if semantic_event is not None:
                _key, payload = semantic_event
                if not self.bridge.publish_ups_diagnostic_event(payload):
                    return False
            else:
                event = DiagnosticEvent.from_transition(
                    transition,
                    active_problem_count=aggregate.count,
                    observed_at=observed_at,
                )
                if not self.bridge.publish_ups_diagnostic_event(event.as_payload()):
                    return False
            self._published_problem_ids.add(transition.current.problem_id)
            self._pending_problem_transitions.pop(0)

        self._problem_snapshot_dirty = False
        return True

    def _flush_pending_problem_transitions(self) -> bool:
        if not self._problem_capable():
            return True
        return self._publish_pending_problem_batch()

    def _sync_current_problem_states(self) -> bool:
        if not self._problem_capable():
            return True

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
            if not self._publish_problem_aggregate_bundle():
                return False
            self._problem_snapshot_dirty = False
        return True

    def _observe_problem_snapshot(
        self,
        snapshot,
        *,
        nut_available: bool,
    ) -> bool:
        if not self._problem_capable():
            return True
        transitions = self.problem_engine.observe(
            snapshot,
            nut_available=nut_available,
        )
        self._pending_problem_transitions.extend(transitions)
        transitions_ok = self._flush_pending_problem_transitions()
        snapshot_ok = self._sync_current_problem_states()
        return bool(transitions_ok and snapshot_ok)

    def _republish_problem_snapshot(self) -> bool:
        if not self._problem_capable():
            return True
        self._published_problem_ids.clear()
        self._problem_snapshot_dirty = True
        return self._sync_current_problem_states()

    def _enqueue_semantic_events(self, snapshot, *, observed_at: str) -> bool:
        outbox = self.machine_event_outbox
        if outbox is None or not self._event_capable():
            return True

        context = ups_snapshot_event_context(snapshot)
        context.update(
            line_power_event_context(
                getattr(self, "line_power_statistics_tracker", None)
            )
        )

        status_event = self.status_event_tracker.observe(
            current_status=tuple(snapshot.normalized_status),
            current_raw_status=tuple(snapshot.status_tokens),
            observed_at=observed_at,
        )
        if status_event is not None:
            _key, payload = status_event
            for semantic_event in semantic_status_events(
                previous_status=tuple(payload["previous_status"]),
                current_status=tuple(payload["current_status"]),
                previous_raw_status=tuple(payload["previous_raw_status"]),
                current_raw_status=tuple(payload["current_raw_status"]),
                observed_at=observed_at,
                battery_charge_percent=snapshot.battery_charge_percent,
                battery_runtime_seconds=snapshot.runtime_seconds,
                context=context,
            ):
                outbox.enqueue(*semantic_event)

        battery_tracker = self.battery_event_tracker
        if battery_tracker is not None:
            for key, payload in battery_tracker.observe_discharge(
                on_battery=snapshot.on_battery,
                charge_percent=snapshot.battery_charge_percent,
                observed_at=observed_at,
            ):
                payload.update(context)
                outbox.enqueue(key, payload)
            for key, payload in battery_tracker.observe_charge_cycle(
                charger_status=snapshot.battery_charger_status,
                charge_percent=snapshot.battery_charge_percent,
                line_power=snapshot.line_power,
                raw_status_tokens=tuple(snapshot.status_tokens),
                observed_at=observed_at,
            ):
                payload.update(context)
                outbox.enqueue(key, payload)
        return True

    def _collect(self, *, force: bool = False, manual_refresh: bool = False) -> bool:
        if not self._group_capable():
            return super()._collect(force=force, manual_refresh=manual_refresh)

        # A pending semantic Event is older than any NUT sample we could read
        # now. Deliver it first so tracker state cannot advance past undelivered
        # machine semantics.
        if not self._flush_machine_event_outbox():
            return False

        # Complete an earlier retained problem/Event transaction before a new
        # NUT observation can create a later transition.
        if not self._flush_pending_problem_transitions():
            return False

        collected_at = self.now_iso()
        now = self.now_monotonic()
        try:
            snapshot = self.reader(self.config)
        except Exception as exc:
            self.nut_available = False
            error = f"{type(exc).__name__}: {exc}"
            self.log.warning("Не удалось прочитать UPS через NUT: %s", exc)
            payload = self._failure_payload(collected_at=collected_at, error=error)
            publications = self.presentation.route(
                payload,
                now=now,
                force=bool(force and not self._last_group_payloads),
                manual=False,
            )
            self._publish_groups(publications, collected_at=collected_at)
            self.sync_discovery(force=False)
            self._observe_problem_snapshot(None, nut_available=False)
            return False

        self.nut_available = True
        self.last_snapshot = snapshot
        history_changed = self._update_open_test_history(snapshot)
        previous_refresh = self.last_refresh
        if manual_refresh:
            self.last_refresh = collected_at

        payload = self._success_payload(snapshot, collected_at=collected_at)
        discovery_ok = self.sync_discovery(force=force or manual_refresh)
        publications = self.presentation.route(
            payload,
            now=now,
            # ``force=True`` is used by several existing UPS event paths. Only
            # startup needs to force all groups; later semantic changes are
            # detected by their own change-only groups.
            force=bool(force and not self._last_group_payloads),
            manual=manual_refresh,
        )
        state_ok = self._publish_groups(
            publications,
            collected_at=collected_at,
            manual_refresh=manual_refresh,
        )

        problem_ok = True
        if state_ok:
            problem_ok = self._observe_problem_snapshot(
                snapshot,
                nut_available=True,
            )

        semantic_ok = True
        if state_ok and problem_ok:
            semantic_ok = self._enqueue_semantic_events(
                snapshot,
                observed_at=collected_at,
            )
            if semantic_ok:
                semantic_ok = self._flush_machine_event_outbox()

        if state_ok:
            self._last_state_payload = payload
            if manual_refresh or history_changed:
                self._persist()
        elif manual_refresh:
            self.last_refresh = previous_refresh

        return bool(discovery_ok and state_ok and problem_ok and semantic_ok)

    def startup(self) -> bool:
        if not self._group_capable():
            return super().startup()
        cleanup_ok = True
        cleaner = getattr(self.bridge, "clear_legacy_ups_state", None)
        if callable(cleaner):
            cleanup_ok = bool(cleaner())
        return bool(cleanup_ok and super().startup())

    def republish_after_reconnect(self) -> bool:
        if not self._group_capable():
            return super().republish_after_reconnect()

        availability_ok = self.bridge.publish_ups_availability(True)
        if not self._last_group_payloads:
            self._refresh_auxiliary()
            self._refresh_policy_validation()
            return bool(availability_ok and self._collect(force=True))

        discovery_ok = self.sync_discovery(force=True)
        state_ok = True
        publish = getattr(self.bridge, "publish_ups_state_group")
        for group, payload in self._last_group_payloads.items():
            state_ok = bool(publish(group, payload)) and state_ok

        pending_ok = self._flush_pending_problem_transitions()
        problem_ok = pending_ok and self._republish_problem_snapshot()
        semantic_ok = self._flush_machine_event_outbox()
        return bool(
            availability_ok
            and discovery_ok
            and state_ok
            and problem_ok
            and semantic_ok
        )
