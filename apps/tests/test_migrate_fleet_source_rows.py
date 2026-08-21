"""`apps/scripts/migrate_fleet_source_rows.py`, closing REVIEW-TASK-012 F4.

F4: the row-migration script shipped with zero committed tests, so its idempotence
claim (AC6) rested entirely on an ad-hoc session — nothing in the repository would
notice if `fleet_hostname_for` or `migrated_profile` stopped being idempotent, or if
the F6 repair (keying on `source_id`, not shape alone) regressed. The pure-function
and fake-cursor classes below need no database, mirroring `test_outbound_policy.py`'s
own "policy is separated from transport on purpose" reasoning — a script whose rewrite
*decision* can only be exercised through a live connection is a script whose decision
logic eventually goes untested. `TestMigrateAgainstARealDatabase` is the one class that
does need one, for the one thing only a real round trip can show: that `Jsonb`
adaptation, the `updated_at = now()` clause, and the `cosmai_runtime` `UPDATE` grant
actually work together.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, cast

import psycopg
import pytest

from domain import DomainStore, SourceRow
from scripts.migrate_fleet_source_rows import (
    FLEET_TARGETS,
    fleet_hostname_for,
    migrate,
    migrated_profile,
    shape_matches_a_known_port,
)

TRENDRADAR_LOOPBACK_PROFILE = {
    "hosts": ["127.0.0.1"],
    "port": 8000,
    "scheme": "http",
    "allow_loopback": True,
    "endpoints": {"runs": "/api/v1/runs"},
    "credentials": [{"header": "X-API-Key", "ref": "COSMA_SRC_TRENDRADAR_TOKEN"}],
    "limits": {"max_pages": 2},
}

TUBEDEPTH_LOOPBACK_PROFILE = {
    "hosts": ["127.0.0.1"],
    "port": 8080,
    "scheme": "http",
    "allow_loopback": True,
    "endpoints": {"artifacts_list": "/v1/artifacts"},
}


class TestFleetHostnameFor:
    """The matching half: `(source_id, shape)`, not shape alone (REVIEW-TASK-012 F6)."""

    def test_a_trendradar_row_with_the_loopback_shape_matches(self) -> None:
        assert fleet_hostname_for("trendradar", TRENDRADAR_LOOPBACK_PROFILE) == (
            "trend-radar-dashboard"
        )

    def test_a_tubedepth_row_with_the_loopback_shape_matches(self) -> None:
        assert fleet_hostname_for("tubedepth", TUBEDEPTH_LOOPBACK_PROFILE) == "tubedepth-api"

    def test_an_already_migrated_row_no_longer_matches(self) -> None:
        """The idempotence mechanism itself: the rewritten `hosts` value is not the
        loopback literal, so a second look finds nothing — no marker needed."""
        migrated = migrated_profile(TRENDRADAR_LOOPBACK_PROFILE, "trend-radar-dashboard")
        assert fleet_hostname_for("trendradar", migrated) is None

    def test_a_trendradar_row_on_the_wrong_port_does_not_match(self) -> None:
        """Shape must match the *specific* fixed port registered for this source_id, not
        merely be one of the two known ports."""
        wrong_port = {**TRENDRADAR_LOOPBACK_PROFILE, "port": 8080}
        assert fleet_hostname_for("trendradar", wrong_port) is None

    def test_a_trendradar_row_on_a_non_loopback_host_does_not_match(self) -> None:
        wrong_host = {**TRENDRADAR_LOOPBACK_PROFILE, "hosts": ["10.0.0.5"]}
        assert fleet_hostname_for("trendradar", wrong_host) is None

    def test_a_foreign_source_id_with_the_matching_shape_does_not_match(self) -> None:
        """REVIEW-TASK-012 F6's case, at the pure-function level: a row shaped exactly
        like trend-radar's fixed target, registered under an unrelated source_id, is
        never rewritten — `migrate()`'s printed-note behavior for this case is covered
        separately, in `TestMigrateNotesAndSkips`."""
        assert fleet_hostname_for("some-other-local-api", TRENDRADAR_LOOPBACK_PROFILE) is None

    def test_an_unregistered_source_id_never_matches_regardless_of_shape(self) -> None:
        assert fleet_hostname_for("naver-blog", {"hosts": ["h"], "port": 1}) is None

    def test_the_two_named_targets_are_exactly_trendradar_and_tubedepth(self) -> None:
        """The positive control for the whole class: `FLEET_TARGETS` names exactly the
        two DP-035 D3 sources, so every refusal above is a refusal *despite* a real
        target existing, not because the table is empty."""
        assert set(FLEET_TARGETS) == {"trendradar", "tubedepth"}
        assert FLEET_TARGETS["trendradar"][0] == 8000
        assert FLEET_TARGETS["tubedepth"][0] == 8080


class TestShapeMatchesAKnownPort:
    """The helper `migrate()` uses to decide whether a source_id-refused row still
    deserves a printed note (REVIEW-TASK-012 F6)."""

    def test_the_loopback_shape_on_a_known_port_matches(self) -> None:
        assert shape_matches_a_known_port(TRENDRADAR_LOOPBACK_PROFILE) is True
        assert shape_matches_a_known_port(TUBEDEPTH_LOOPBACK_PROFILE) is True

    def test_an_unrelated_shape_does_not_match(self) -> None:
        assert shape_matches_a_known_port({"hosts": ["api.example.com"], "port": 443}) is False

    def test_the_loopback_host_on_an_unknown_port_does_not_match(self) -> None:
        assert shape_matches_a_known_port({"hosts": ["127.0.0.1"], "port": 9999}) is False


class TestMigratedProfile:
    """`hosts`/`allow_loopback`/`allow_fleet` change; everything else is untouched."""

    def test_hosts_is_repointed_to_the_fleet_hostname(self) -> None:
        after = migrated_profile(TRENDRADAR_LOOPBACK_PROFILE, "trend-radar-dashboard")
        assert after["hosts"] == ["trend-radar-dashboard"]

    def test_allow_loopback_is_removed_rather_than_set_false(self) -> None:
        after = migrated_profile(TRENDRADAR_LOOPBACK_PROFILE, "trend-radar-dashboard")
        assert "allow_loopback" not in after

    def test_allow_fleet_is_granted(self) -> None:
        after = migrated_profile(TRENDRADAR_LOOPBACK_PROFILE, "trend-radar-dashboard")
        assert after["allow_fleet"] is True

    def test_every_other_key_is_preserved_verbatim(self) -> None:
        after = migrated_profile(TRENDRADAR_LOOPBACK_PROFILE, "trend-radar-dashboard")
        assert after["scheme"] == "http"
        assert after["port"] == 8000
        assert after["endpoints"] == TRENDRADAR_LOOPBACK_PROFILE["endpoints"]
        assert after["credentials"] == TRENDRADAR_LOOPBACK_PROFILE["credentials"]
        assert after["limits"] == TRENDRADAR_LOOPBACK_PROFILE["limits"]

    def test_the_input_profile_is_not_mutated(self) -> None:
        """The positive control every rewrite-in-place bug needs: `migrate()` prints
        the `before` value after calling this, so a function that mutated its argument
        would make the printed "before" line lie."""
        original = dict(TRENDRADAR_LOOPBACK_PROFILE)
        migrated_profile(TRENDRADAR_LOOPBACK_PROFILE, "trend-radar-dashboard")
        assert original == TRENDRADAR_LOOPBACK_PROFILE


# --------------------------------------------------------------------------- #
# migrate() against a fake connection — no database, but the real per-row loop,
# including the two REVIEW-TASK-012 F6 skip-with-a-note paths.
# --------------------------------------------------------------------------- #


class _StubCursor:
    """The one method `migrate()` calls on a cursor, recording every `execute`."""

    def __init__(self, rows: Sequence[dict[str, Any]]) -> None:
        self._rows = list(rows)
        self.executed: list[tuple[str, tuple[Any, ...] | None]] = []

    def execute(self, query: str, params: tuple[Any, ...] | None = None) -> _StubCursor:
        self.executed.append((query, params))
        return self

    def fetchall(self) -> list[dict[str, Any]]:
        return self._rows

    def __enter__(self) -> _StubCursor:
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None


class _StubConnection:
    """The one method `migrate()` calls on a connection: `cursor(row_factory=...)`."""

    def __init__(self, rows: Sequence[dict[str, Any]]) -> None:
        self.cursor_used = _StubCursor(rows)

    def cursor(self, row_factory: Any = None) -> _StubCursor:
        return self.cursor_used


def _connection(rows: Sequence[dict[str, Any]]) -> psycopg.Connection[Any]:
    """A `_StubConnection` typed as `migrate()` expects, for callers that never touch
    anything but `.cursor()`."""
    return cast("psycopg.Connection[Any]", _StubConnection(rows))


class TestMigrateNotesAndSkips:
    def test_a_matching_row_is_migrated_and_the_update_is_issued(self) -> None:
        stub = _StubConnection(
            [{"source_id": "trendradar", "outbound_profile": TRENDRADAR_LOOPBACK_PROFILE}]
        )
        changed = migrate(cast("psycopg.Connection[Any]", stub), execute=True)
        assert changed == 1
        updates = [q for q, _ in stub.cursor_used.executed if q.strip().startswith("update")]
        assert len(updates) == 1
        assert updates[0].count("%s") == 2  # outbound_profile, source_id

    def test_a_dry_run_matches_but_issues_no_update(self) -> None:
        stub = _StubConnection(
            [{"source_id": "trendradar", "outbound_profile": TRENDRADAR_LOOPBACK_PROFILE}]
        )
        changed = migrate(cast("psycopg.Connection[Any]", stub), execute=False)
        assert changed == 1
        updates = [q for q, _ in stub.cursor_used.executed if q.strip().startswith("update")]
        assert updates == []

    def test_a_foreign_source_id_with_the_matching_shape_is_skipped_with_a_note(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """REVIEW-TASK-012 F6, through `migrate()` itself rather than the pure function
        alone: a same-shaped stranger is named in the output, never silently dropped —
        and, the positive control, never rewritten either."""
        rows = [
            {
                "source_id": "some-other-local-api",
                "outbound_profile": TRENDRADAR_LOOPBACK_PROFILE,
            }
        ]
        changed = migrate(_connection(rows), execute=True)
        assert changed == 0
        out = capsys.readouterr().out
        assert "some-other-local-api" in out
        assert "skipped" in out

    def test_a_row_shaped_like_neither_target_is_skipped_with_no_note(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The control for the case above: an ordinary, unrelated row produces no
        output at all — the note exists for the F6 case specifically, not for every
        row `migrate()` passes over."""
        rows = [
            {"source_id": "naver-blog", "outbound_profile": {"hosts": ["api.example.com"]}}
        ]
        changed = migrate(_connection(rows), execute=True)
        assert changed == 0
        out = capsys.readouterr().out
        assert "naver-blog" not in out

    def test_a_non_object_profile_is_skipped_with_a_note_instead_of_raising(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """REVIEW-TASK-012 F6's second half: `outbound_profile` is a bare `jsonb`
        column with no object constraint, so a row could hold a JSON array or scalar.
        Before this repair that raised `AttributeError: 'list' object has no attribute
        'get'`; now it is a skip with a printed note."""
        rows = [{"source_id": "malformed-row", "outbound_profile": ["not", "an", "object"]}]
        changed = migrate(_connection(rows), execute=True)  # must not raise
        assert changed == 0
        out = capsys.readouterr().out
        assert "malformed-row" in out
        assert "skipped" in out

    def test_a_scalar_profile_is_also_skipped_rather_than_raising(self) -> None:
        rows = [{"source_id": "scalar-row", "outbound_profile": "not-even-a-list"}]
        changed = migrate(_connection(rows), execute=True)  # must not raise
        assert changed == 0

    def test_a_mixed_batch_migrates_only_the_genuine_matches(self) -> None:
        """The composite case: one real match, one F6 stranger, one malformed row, one
        ordinary unrelated row, in one pass — only the first is rewritten."""
        rows: list[dict[str, Any]] = [
            {"source_id": "trendradar", "outbound_profile": TRENDRADAR_LOOPBACK_PROFILE},
            {"source_id": "some-other-local-api", "outbound_profile": TRENDRADAR_LOOPBACK_PROFILE},
            {"source_id": "malformed-row", "outbound_profile": ["not", "an", "object"]},
            {"source_id": "naver-blog", "outbound_profile": {"hosts": ["api.example.com"]}},
        ]
        changed = migrate(_connection(rows), execute=True)
        assert changed == 1

    def test_no_rows_at_all_reports_nothing_to_do(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        changed = migrate(_connection([]), execute=True)
        assert changed == 0
        assert "nothing to do" in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# migrate() against a real database — the one thing the fake cursor above cannot
# show: that Jsonb adaptation, `updated_at = now()`, and the cosmai_runtime UPDATE
# grant actually work together.
# --------------------------------------------------------------------------- #


def _a_source(source_id: str, outbound_profile: dict[str, Any] | None) -> SourceRow:
    return SourceRow(
        source_id=source_id,
        addon_id=f"collector.{source_id}",
        addon_version="0.1.0",
        kind="collector",
        config={},
        config_schema_version="1",
        credential_ref=None,
        outbound_profile=outbound_profile,
    )


class TestMigrateAgainstARealDatabase:
    """REVIEW-TASK-012 AC6: a real round trip, against `cosmai_test` — never `cosmai`
    (`domain_store`'s own `platform_config` fixture is pinned at the test database;
    `apps/tests/conftest.py`'s module docstring is why there is nothing here that
    could reach production).
    """

    def test_two_runs_migrate_exactly_the_matching_row_and_leave_the_other_alone(
        self, domain_store: DomainStore
    ) -> None:
        domain_store.register_source(
            _a_source("trendradar", dict(TRENDRADAR_LOOPBACK_PROFILE))
        )
        unrelated_profile = {"hosts": ["api.example.com"], "port": 443, "endpoints": {}}
        domain_store.register_source(_a_source("unrelated-source", dict(unrelated_profile)))

        changed_first_run = migrate(domain_store.connection, execute=True)
        assert changed_first_run == 1

        migrated = domain_store.read_source("trendradar")
        assert migrated is not None
        assert migrated["outbound_profile"]["hosts"] == ["trend-radar-dashboard"]
        assert migrated["outbound_profile"]["allow_fleet"] is True
        assert "allow_loopback" not in migrated["outbound_profile"]
        # Everything this script promises to leave alone, actually left alone.
        assert migrated["outbound_profile"]["port"] == 8000
        assert migrated["outbound_profile"]["scheme"] == "http"
        assert migrated["outbound_profile"]["endpoints"] == TRENDRADAR_LOOPBACK_PROFILE["endpoints"]

        still_unrelated = domain_store.read_source("unrelated-source")
        assert still_unrelated is not None
        assert still_unrelated["outbound_profile"] == unrelated_profile

        changed_second_run = migrate(domain_store.connection, execute=True)
        assert changed_second_run == 0
        # Idempotent through the database too, not merely in the pure function.
        assert domain_store.read_source("trendradar") == migrated

    def test_a_dry_run_against_the_database_changes_nothing(
        self, domain_store: DomainStore
    ) -> None:
        domain_store.register_source(
            _a_source("tubedepth", dict(TUBEDEPTH_LOOPBACK_PROFILE))
        )

        changed = migrate(domain_store.connection, execute=False)
        assert changed == 1

        untouched = domain_store.read_source("tubedepth")
        assert untouched is not None
        assert untouched["outbound_profile"]["hosts"] == ["127.0.0.1"]
        assert untouched["outbound_profile"]["allow_loopback"] is True
