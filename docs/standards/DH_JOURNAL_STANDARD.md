# DH Journal Standard 1.0.2

**Status:** Normative for newly integrated Ingress journals; existing Apps migrate product by product.

## Architecture

DH Journal is a shared, bundled library, not a service, MQTT publisher, HA integration or Recorder destination. Canonical Python and browser code: `shared/dh_journal/dh_journal/`. Product-specific event codes and RU/EN message dictionaries belong to the product. Go products use the same contract and UI with a native storage adapter; implement it when migrating the first Go consumer.

Materialize the shared files into the product Docker context using `python scripts/vendor_dh_journal.py`. Generated files are not hand-edited. CI verifies snapshots and tests the canonical library. This preserves the existing product-scoped immutable release source, local HAOS builds, and independent installed versions. A library change requires a library version increment and explicit product version bumps for updated snapshots; no downloading code at runtime. CI validates all affected consumers. Future pinned older snapshots require an explicit versioned source verification policy before adoption.

## Storage and event contract

- Local SQLite under /data, append-only events; keep exactly the latest 3000 records at most (including lifecycle markers). No age-based retention, no adjustable limit. Every record available for viewing and export. Automatic oldest-first deletion after insertion.
- Stable event ID, UTC timestamp with milliseconds, severity, event code, bounded safe structured parameters. New events append in observed order. Restart markers display date/time, product name and product version; library version remains in structured technical details; graceful stop is recorded, never invent a stop after a crash. A fresh process always adds a start marker.
- Severity: DEBUG (🔍), INFO (ℹ️), SUCCESS (✅), PENDING (⏳), WARNING (⚠️), ERROR (❌), LIFECYCLE (🔄). DEBUG off by default, configurable via App parameters.
- No UPDATE of a previously recorded event. Related sent/confirmed/timeout steps may be separate events with the same correlation ID; operational command/outbox state remains independent. Existing specialized state and machine event contracts are not rewritten or replayed.
- Record meaningful transitions, actions and outcomes, not routine polling, uptime ticks or repeated unchanged results. No extra MQTT publications, HA entities, HA polls or telemetry.
- Pass explicitly allowlisted safe facts, never raw request bodies, tokens, passwords or secrets. Escape untrusted display strings as text; strip embedded newlines in rendered log fields. Journal errors cannot stop the app. Invalid events are rejected without raising into the producer; count rejected events and rate-limit internal diagnostics. Bound nesting, total nodes and UTF-8 size of each new stored event to 8192 bytes (including envelope); preserve complete fitting fields and mark truncation. On SQLite failure use a bounded RAM fallback, visibly indicate the failure; retry persistence on process restart, do not claim RAM history is durable. Clear is acknowledged only after SQLite commits deletion and the clear marker in one FULL-synchronous transaction. In RAM mode refuse clear (HTTP 409), preserve visible history and disable the clear control; never imply old disk history was removed.

## Full-screen Ingress

- Consistent LOG button at top right opens a full-width page inside Ingress, with a back control. Oldest at top, newest at bottom. Scroll to bottom on entry and while following; disable follow when scrolling back. Filter/search all 3000 retained events; compact colored rows, emoji and distinct restart separators.
- Automatic cursor-based refresh only while LOG page is visible; batch DOM insertion, create expanded details on demand, and skip unchanged rendering; no new HA/MQTT work. Reset cursor if generation changes (clear, restart, fallback). API returns oldest/newest/count/limit/storage and chronological new records.
- Search across localized message, event code, timestamp, parameters. Severity filter, copy entry, expandable safe details. Export always includes the full retained history, not only filtered rows. Explicit confirmation for journal-only clear; never clear product configuration or runtime state.
- UTF-8 text download: `<product_slug>_YYYY-MM-DD_HH-MM-SS.log`, local timestamp. Export uses selected language, includes timestamp, level, emoji, message and safe details, in chronological order. HA timezone (UTC fallback); store UTC.
- RU/EN selectors; translate all old and new events at presentation time via event codes and dictionaries. Localize known reason/state/operation values for display without modifying stored machine codes. Use one semantic emoji per row (an event-specific icon may override the severity icon). Unknown historical codes show the code and safe parameters, not fabricated text. Language change must not mutate storage.
- Ingress-only authorization, relative URLs, read-only GET for viewing/export and explicit JSON POST for clear. No external JS, CSS, services or runtime library installation.

## Rollout

System Globals is the pilot. Confirm Ingress behavior on HAOS before migration of Actions, Sync, Presence and Network; preserve existing history where feasible and never delete command/outbox state. The Go adapter is a separate migration deliverable. Existing non-Ingress apps are not required to add Ingress merely to satisfy this standard. Keep DH Events & Notifications Standard independent.
