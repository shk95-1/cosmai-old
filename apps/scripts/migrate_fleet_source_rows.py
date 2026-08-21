"""Idempotently repoint DP-035 D3's two fixed adapter targets to their fleet hostnames.

DP-035 D3: the registered source rows for `collector.trendradar.rest` and
`collector.tubedepth.rest` still carry the loopback literal M8-DEPLOY-RECORD deployed
them with (`outbound_profile.hosts: ["127.0.0.1"]`, port 8000/8080, `allow_loopback:
true`) — a hole the stack's `db-net` bridge network cannot reach, since a bridge
network does not forward a container's own loopback. This script rewrites exactly
those rows to the compose DNS aliases the two targets answer to on `db-net`
(`trend-radar-dashboard`, `tubedepth-api`), replacing `allow_loopback` with the new
per-source hole DP-035 D1 adds (`allow_fleet`) and leaving `scheme`, `port`,
`endpoints`, `credentials`, and `limits` exactly as the row already states them
(DP-035 D3: "Everything else ... stands").

**Idempotent by construction, not by a recorded marker.** `fleet_hostname_for` only
matches a row while its `source_id` is one of the two DP-035 D3 names *and* its
profile carries the exact loopback shape (`hosts == ["127.0.0.1"]`, the matching
fixed port); the rewrite changes `hosts` to the fleet hostname, so a second run finds
nothing left to match and reports zero rows changed. No "already migrated" flag is
written or read — the row's own new shape is the record, the same reason
`platform_core.db.migrate.apply_migrations` records applied *versions* rather than
trusting a caller to run a migration file at most once, except here it is the row
itself that carries that information rather than a bookkeeping table.

**Keyed on `(source_id, shape)`, not on shape alone.** `[측정]` REVIEW-TASK-012 F6:
an earlier version of this script matched any row whose profile happened to carry
`hosts == ["127.0.0.1"]` and `port` 8000 or 8080, regardless of which source it
belonged to — so a third, unrelated row registered on the same loopback port would
have been silently repointed to `trend-radar-dashboard`. `fleet_hostname_for` now
requires the row's own `source_id` to be `trendradar` or `tubedepth` (DP-035 D3's two
named sources) before it will even look at the shape. A row whose *shape* matches one
of the two fixed ports but whose `source_id` does not is never rewritten, and
`migrate()` prints a note naming it rather than passing over it in silence — an
operator reading the dry-run output learns about a same-shaped stranger instead of
only learning the row count.

**Not executed against `cosmai` by TASK-012.** `docs/agent-workflow/task-packets/
TASK-012-fleet-egress-and-container-bind.md` reserves the live cutover for the same
stop window as the stack's compose change; this script refuses to write against a
database named `cosmai` unless `--confirm-production` is also given alongside
`--execute`, so the same command that is safe to run early against a test database
cannot reach the production row by accident. Every row this script reads is printed
before and after whether or not `--execute` is given, so a dry run and a real run
report the same evidence and can be compared line for line.

**Nothing printed is a secret.** `outbound_profile.credentials[].ref` is a
secret-store *key name* (DP-018), never a value, so printing a row's `outbound_profile`
verbatim discloses nothing `collector.tubedepth.rest`'s own README does not already
print for the same profile shape.

Run from the `apps/` venv, pointed at the target database by the ordinary `COSMA_DB_*`
environment (`platform_core.config.load_config`):

    cd apps && .venv/bin/python -m scripts.migrate_fleet_source_rows [--execute]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from platform_core.config import PlatformConfig, load_config
from platform_core.db.connection import connect

#: DP-035 D3. The only two rewrites this script performs, keyed by the *source_id* each
#: fixed adapter target is registered under (`apps/addons/collector.trendradar.rest`,
#: `apps/addons/collector.tubedepth.rest`) — not by port alone; see the module
#: docstring's "Keyed on (source_id, shape)" paragraph (F6).
FLEET_TARGETS: Final[Mapping[str, tuple[int, str]]] = {
    "trendradar": (8000, "trend-radar-dashboard"),
    "tubedepth": (8080, "tubedepth-api"),
}

#: Every port a fixed adapter target answers on, regardless of which source_id
#: currently owns the row — used only to recognise a same-shaped stranger (F6) so
#: `migrate()` can name it in a printed note instead of passing over it in silence.
_KNOWN_PORTS: Final[frozenset[int]] = frozenset(port for port, _ in FLEET_TARGETS.values())

#: The loopback shape every row this script touches was registered with
#: (M8-DEPLOY-RECORD (a) D2's live measurement: `"hosts": ["127.0.0.1"]`).
_LOOPBACK_HOSTS: Final = ["127.0.0.1"]

#: The production database name this script refuses to write against without
#: `--confirm-production` — see the module docstring.
PRODUCTION_DB_NAME: Final = "cosmai"


def fleet_hostname_for(source_id: str, profile: Mapping[str, Any]) -> str | None:
    """The fleet hostname this row should move to, or `None` if it does not match.

    A match needs both halves: `source_id` must be one of the two DP-035 D3 names,
    *and* `profile` must carry the exact loopback shape registered for that name
    (`hosts == ["127.0.0.1"]`, its matching port). Neither half alone is enough — a
    `trendradar` row already migrated (a different `hosts` value) does not match, and
    neither does an unrelated row that merely happens to share a port (F6).
    """
    target = FLEET_TARGETS.get(source_id)
    if target is None:
        return None
    expected_port, fleet_hostname = target
    hosts = profile.get("hosts")
    port = profile.get("port")
    if hosts != _LOOPBACK_HOSTS or port != expected_port:
        return None
    return fleet_hostname


def shape_matches_a_known_port(profile: Mapping[str, Any]) -> bool:
    """Whether `profile` carries the loopback shape this script knows how to rewrite for
    *some* source_id — `hosts == ["127.0.0.1"]` and `port` one of the two fixed values —
    regardless of which row actually carries it.

    Used only to flag a row `fleet_hostname_for` refused for its `source_id` alone, so a
    same-shaped stranger (REVIEW-TASK-012 F6) is named in a printed note rather than
    silently skipped like an ordinary, unrelated row.
    """
    hosts = profile.get("hosts")
    port = profile.get("port")
    return hosts == _LOOPBACK_HOSTS and port in _KNOWN_PORTS


def migrated_profile(profile: Mapping[str, Any], fleet_hostname: str) -> dict[str, Any]:
    """`profile`, with `hosts` repointed and `allow_loopback` swapped for `allow_fleet`.

    `allow_loopback` is removed rather than left `false`: a stale key a future reader
    might mistake for a second, dormant grant is worse than no key at all. Every other
    key — `scheme`, `port`, `endpoints`, `credentials`, `limits` — is copied verbatim.
    """
    updated = dict(profile)
    updated["hosts"] = [fleet_hostname]
    updated.pop("allow_loopback", None)
    updated["allow_fleet"] = True
    return updated


def _print_profile(source_id: str, label: str, profile: Mapping[str, Any]) -> None:
    """One `[측정]`-style line: which row, which half, and its profile.

    `json.dumps` rather than the raw jsonb the driver already decoded, so the printed
    shape is stable across a dict's insertion order and reviewable without a second
    tool.
    """
    rendered = json.dumps(profile, sort_keys=True, ensure_ascii=False)
    print(f"{source_id} {label}: {rendered}")


def migrate(connection: psycopg.Connection[Any], *, execute: bool) -> int:
    """Rewrite every matching row; return how many needed it.

    Every matching row is read and printed whether or not `execute` is set — a dry run
    and a real run report the same before/after pair, so comparing the two output
    streams is how an operator checks a real run did exactly what the dry run promised.

    Two kinds of row are skipped with a printed note rather than silently passed over
    or allowed to crash the run (REVIEW-TASK-012 F6): a row whose `outbound_profile` is
    not a JSON *object* (`hosts`/`port` are Postgres jsonb, so a row could in principle
    hold an array or a scalar there — nothing in the schema forbids it, only convention
    does), and a row whose shape matches one of the two fixed ports but whose
    `source_id` is not one of the two DP-035 D3 names.
    """
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            "select source_id, outbound_profile from cosmai.source "
            "where outbound_profile is not null order by source_id"
        )
        rows = cursor.fetchall()

        changed = 0
        for row in rows:
            source_id = str(row["source_id"])
            raw_profile = row["outbound_profile"]
            if not isinstance(raw_profile, Mapping):
                print(
                    f"{source_id} skipped: outbound_profile is a "
                    f"{type(raw_profile).__name__}, not a JSON object — nothing rewritten"
                )
                continue
            profile: Mapping[str, Any] = raw_profile
            fleet_hostname = fleet_hostname_for(source_id, profile)
            if fleet_hostname is None:
                if shape_matches_a_known_port(profile):
                    print(
                        f"{source_id} skipped: outbound_profile has the loopback shape "
                        "of a fixed adapter target, but this source_id is not one of "
                        f"{sorted(FLEET_TARGETS)} — nothing rewritten (see this "
                        "script's module docstring, REVIEW-TASK-012 F6)"
                    )
                continue
            after = migrated_profile(profile, fleet_hostname)
            _print_profile(source_id, "before", profile)
            _print_profile(source_id, "after", after)
            changed += 1
            if execute:
                cursor.execute(
                    "update cosmai.source set outbound_profile = %s, updated_at = now() "
                    "where source_id = %s",
                    (Jsonb(after), source_id),
                )

    if changed == 0:
        print("nothing to do: no row carries the loopback shape this script rewrites")
    return changed


def parse_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.migrate_fleet_source_rows",
        description=(
            "Rewrite the trend-radar and tubedepth source rows' outbound_profile from "
            "the loopback literal to their fleet hostnames (DP-035 D3)."
        ),
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Write the rewritten profiles. Without this flag the script only prints "
        "what it would change and writes nothing (the default).",
    )
    parser.add_argument(
        "--confirm-production",
        action="store_true",
        help=f"Required in addition to --execute when COSMA_DB_NAME is "
        f"{PRODUCTION_DB_NAME!r}; TASK-012 reserves the live cutover for the stack's "
        "compose stop window.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Resolve configuration, then migrate. Returns the process exit status."""
    args = parse_arguments(argv)
    config: PlatformConfig = load_config()

    if (
        args.execute
        and config.db_name == PRODUCTION_DB_NAME
        and not args.confirm_production
    ):
        print(
            f"refusing to write: COSMA_DB_NAME is {PRODUCTION_DB_NAME!r} and "
            "--confirm-production was not given (see this script's module docstring)",
            file=sys.stderr,
        )
        return 1

    connection = connect(config, role="runtime")
    try:
        changed = migrate(connection, execute=args.execute)
        if args.execute:
            connection.commit()
        else:
            connection.rollback()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()

    verb = "migrated" if args.execute else "would migrate"
    print(f"{verb} {changed} row(s)")
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised as a process, not imported
    raise SystemExit(main())
