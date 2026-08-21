"""Collector for trend-radar 1.0.0's read-only dashboard JSON API.

Target originally fixed by DP-031 D3 at ``http://127.0.0.1:8000/api/v1``; DP-035 D3
revises the address to ``http://trend-radar-dashboard:8000/api/v1`` once cosmai joins
the fleet's ``db-net`` bridge network, where the loopback literal is unreachable.
Unauthenticated either way (``needs_credential = false``). Endpoint shapes and rules
are from
``service/trend-radar``'s own ``docs/api.md`` and
``src/trend_radar/dashboard/{api,queries}.py`` (read-only to this project — DP-031's
"heavy periodic collector, external implementation" is exactly this source), plus this
add-on's own live capture on 2026-08-21; see
``apps/tests/fixtures/public/collector.trendradar.rest/MANIFEST.md`` for what was
captured, hashed, and measured rather than assumed.

**`[측정]` A `captured_at` filter 500s on the live instance.** Every ISO 8601 encoding
tried against ``GET /api/v1/records/{table}?captured_at=...`` returned `500 Internal
Server Error`, while `source` and `board` (the other PK-column filters) return `200`
with a correctly echoed `filters` object. The reconstruction spec (§5.1) describes
exact-match collection on `source+board(when applicable)+captured_at`; this add-on
never sends `captured_at` as a request parameter because doing so does not work
against the live target. Instead it filters by `source` (and `board`, for
`rank_snapshot`, when the operator configures one), relies on the API's own
`captured_at DESC` row ordering (`queries.record_rows`), and stops reading a page once
it reaches a row at or before its own stored cursor for that (table, source) — the
same "read forward until you see what you already have" shape
`collector.naver.blog` uses for `start`, adapted to a server-side sort instead of an
add-on-chosen offset. `service/trend-radar` is read-only to this project (`AGENTS.md`)
and was not investigated further or modified; the 500 is recorded as a measured
property of the live target, not fixed here.

**Cursor.** One declared stream (`buckets`); `context.cursor` holds one JSON object
for both halves of the collection:

```
{"hour_bucket": {"<table>": {"<source>": "<ISO 8601 captured_at, the newest row this
                              add-on has already emitted for that table+source>"}}},
 "full_scan":   {"<table>": {"<source>": "<ISO 8601 retrieved_at of the last page of
                              this table+source's most recent complete re-page>"}}}
```

The reconstruction spec says "테이블별 마지막 처리 시간 버킷" (cursor: per-table last
processed bucket) — one entry per table. This add-on extends that one level, to
per-table-per-source, because trend-radar's own `/api/v1/health` sample
(`MANIFEST.md`) shows sources advancing independently: a table's cursor is not one
instant, it is one instant *per source that table collects from*. That is a local
representation choice (AGENTS.md: "local names, helper structure... remain
implementation choices"), not a change to what gets collected — it stays inside one
declared stream, so OQ-010 (whether the contract should ever hand an add-on more than
one cursor stream) is not reopened by this add-on; the composite value is what answers
DP-031's own note that this collector "plausibly needs one cursor per time-bucket
table" without needing a second stream to hold it.

`full_scan` is informational (`docs/api.md`/spec: `product`, `review`, `review_answer`,
`new_product` are re-paged in full on every run — duplicates are resolved at snapshot
seal by natural-key latest-wins, per spec §5.1); it is never read back to decide what
to fetch, only written so an operator can see when a table was last fully re-read.

**Raw mapping.** One API response page is one envelope (the platform's own rule, not
this add-on's). One row is one `RawItem`; `item_key` is the table name plus its
natural-key columns (`src/trend_radar/models.py`'s `NATURAL_KEY`, which
`src/trend_radar/storage/tables.py`'s primary keys mirror, verified against
`docs/api.md`'s ``filterable``) joined with ``"|"`` — the table name is included
because `item_key` is only unique *within one source* (`addon_api.results.RawItem`'s
own docstring) and this one source spans nine tables whose natural keys are not
mutually disjoint (`product` and `new_product` both key on `(source, product_key)`).

**Filters-echo verification.** `docs/api.md`: "Anything else in the query string is
ignored" — an unrecognized parameter is silently dropped, not rejected. Every
`/records/{table}` response echoes exactly the filters it actually applied
(`filters`), so before trusting a page this add-on compares that echo against what it
asked for and raises `AddonPermanent` — refusing the page rather than trusting it — on
any mismatch (`_verify_filters_echo`). This add-on only ever sends filters that
`docs/api.md` documents as PK columns (`source`, `board`), so no *live* mismatch is
expected; the defense exists for a future trend-radar release that renames or drops
one, per the spec's own framing of this as the source's "silent drop" behavior.

**No normalizer in this batch.** RC-005 registers `rank`/`review` `record_type`s as a
milestone; §6 of the spec keeps 1차 normalization to the existing three types. Raw rows
from this collector are browseable/exportable as Raw without one.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from addon_api import (
    AddonConfigInvalid,
    AddonPermanent,
    AddonTransient,
    CollectContext,
    CollectOutcome,
    FetchResponse,
    RawItem,
)

STREAM = "buckets"
ITEM_KEY_SEP = "|"

#: `docs/api.md`: `limit` caps at 1000 for `/records/{table}`.
API_PAGE_CAP = 1000
DEFAULT_PAGE_LIMIT = 500
#: `docs/api.md`: `limit` caps at 200 for `/runs`.
RUNS_LOOKBACK_CAP = 200
DEFAULT_RUNS_LOOKBACK = 50

RUNS_ENDPOINT = "runs"
SOURCES_ENDPOINT = "sources"

#: `src/trend_radar/models.py` `NATURAL_KEY`, mirrored by `storage/tables.py`'s
#: primary keys and `docs/api.md`'s per-table `filterable` list. Order fixed here
#: rather than read off the table so it stays a value this add-on owns and tests
#: against, not a live property of the target.
NATURAL_KEY: Mapping[str, tuple[str, ...]] = {
    "rank_snapshot": ("source", "board", "category_key", "product_key", "captured_at"),
    "price_point": ("source", "product_key", "captured_at"),
    "review_stats": ("source", "product_key", "captured_at"),
    "review_summary": ("source", "product_key", "rank", "captured_at"),
    "review_topic": ("source", "product_key", "topic_key", "captured_at"),
    "product": ("source", "product_key"),
    "review": ("source", "review_key"),
    "review_answer": ("source", "review_key", "question_key"),
    "new_product": ("source", "product_key"),
}

#: Spec §5.1: collected per source+board(when applicable)+captured_at, page-capped.
HOUR_BUCKET_TABLES: tuple[str, ...] = (
    "rank_snapshot",
    "price_point",
    "review_stats",
    "review_summary",
    "review_topic",
)
#: Spec §5.1: re-paged in full every scheduled run; duplicates resolved at seal time.
FULL_SCAN_TABLES: tuple[str, ...] = ("product", "review", "review_answer", "new_product")
ALL_TABLES: tuple[str, ...] = HOUR_BUCKET_TABLES + FULL_SCAN_TABLES


def _endpoint_for(table: str) -> str:
    return f"records_{table}"


class _Budget:
    """The page budget one run spends against `context.limits.max_pages`.

    Not a bound in itself — the platform is the bound (`Limits`'s own docstring) —
    just this add-on's own bookkeeping so it stops cleanly, with a cursor it can
    resume from, instead of running until the host refuses it (the same convenience
    `collector.naver.blog`'s `pages_fetched` check buys).
    """

    def __init__(self, max_pages: int) -> None:
        self._max_pages = max_pages
        self.pages_fetched = 0

    @property
    def exhausted(self) -> bool:
        return self.pages_fetched >= self._max_pages

    def spend(self) -> None:
        self.pages_fetched += 1


def run(context: CollectContext) -> CollectOutcome:
    tables = _require_tables(context)
    configured_sources = _optional_csv(context, "sources")
    boards = _optional_csv(context, "boards")
    page_limit = _require_page_limit(context)
    runs_lookback = _require_runs_lookback(context)

    cursor_state = _load_cursor(context.cursor)
    budget = _Budget(context.limits.max_pages)

    sources = configured_sources or tuple(_discover_sources(context, budget))
    run_high_water: Mapping[str, datetime] = {}
    if any(table in HOUR_BUCKET_TABLES for table in tables):
        run_high_water = _discover_run_high_water(context, budget, runs_lookback)

    raw_items: list[RawItem] = []
    processed: list[str] = []
    skipped_for_budget: list[str] = []

    for table in tables:
        if budget.exhausted:
            skipped_for_budget.append(table)
            continue
        if table in HOUR_BUCKET_TABLES:
            emitted = _collect_hour_bucket_table(
                context,
                table,
                sources,
                boards if table == "rank_snapshot" else (),
                page_limit,
                run_high_water,
                cursor_state,
                budget,
            )
        else:
            emitted = _collect_full_scan_table(
                context, table, sources, page_limit, cursor_state, budget
            )
        raw_items.extend(emitted)
        processed.append(table)

    context.advance_cursor(STREAM, cursor_state)

    more_available = budget.exhausted or bool(skipped_for_budget)
    context.log(
        "collect.run_complete",
        {
            "items_emitted": len(raw_items),
            "pages_fetched": budget.pages_fetched,
            "tables_processed": processed,
            "tables_skipped_for_budget": skipped_for_budget,
            "more_available": more_available,
        },
    )
    return CollectOutcome(
        items_emitted=len(raw_items),
        more_available=more_available,
        notes={
            "tables_processed": processed,
            "tables_skipped_for_budget": skipped_for_budget,
            "sources": list(sources),
        },
    )


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #


def _require_tables(context: CollectContext) -> tuple[str, ...]:
    raw = context.config_field("tables", "")
    if not isinstance(raw, str):
        raise AddonConfigInvalid("tables must be a comma-separated string", {"tables": raw})
    names = {part.strip() for part in raw.split(",") if part.strip()}
    if not names:
        return ALL_TABLES
    unknown = sorted(names - set(NATURAL_KEY))
    if unknown:
        raise AddonConfigInvalid(
            f"unknown table(s): {', '.join(unknown)}; known: {', '.join(ALL_TABLES)}",
            {"unknown": unknown},
        )
    # Fixed declared order, not operator order: keeps page-budget spend order stable
    # and testable regardless of how `tables` was written.
    return tuple(table for table in ALL_TABLES if table in names)


def _optional_csv(context: CollectContext, field: str) -> tuple[str, ...]:
    raw = context.config_field(field, "")
    if not isinstance(raw, str):
        raise AddonConfigInvalid(f"{field} must be a comma-separated string", {field: raw})
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def _require_page_limit(context: CollectContext) -> int:
    value = context.config_field("page_limit", DEFAULT_PAGE_LIMIT)
    if isinstance(value, bool) or not isinstance(value, int) or not (1 <= value <= API_PAGE_CAP):
        raise AddonConfigInvalid(
            f"page_limit must be an integer between 1 and {API_PAGE_CAP}", {"page_limit": value}
        )
    return value


def _require_runs_lookback(context: CollectContext) -> int:
    value = context.config_field("runs_lookback", DEFAULT_RUNS_LOOKBACK)
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not (1 <= value <= RUNS_LOOKBACK_CAP)
    ):
        raise AddonConfigInvalid(
            f"runs_lookback must be an integer between 1 and {RUNS_LOOKBACK_CAP}",
            {"runs_lookback": value},
        )
    return value


# --------------------------------------------------------------------------- #
# Cursor
# --------------------------------------------------------------------------- #


def _load_cursor(raw: Any) -> dict[str, dict[str, dict[str, str]]]:
    """Read `context.cursor`, or start empty. `None` means "never run" (contract)."""
    if raw is None:
        return {"hour_bucket": {}, "full_scan": {}}
    if not isinstance(raw, dict):
        raise AddonPermanent(f"resume cursor is not an object: {raw!r}", {"cursor": raw})
    return {
        "hour_bucket": _clean_cursor_half(raw.get("hour_bucket", {}), "hour_bucket", raw),
        "full_scan": _clean_cursor_half(raw.get("full_scan", {}), "full_scan", raw),
    }


def _clean_cursor_half(mapping: Any, name: str, whole: Any) -> dict[str, dict[str, str]]:
    if not isinstance(mapping, dict):
        raise AddonPermanent(f"resume cursor's {name!r} must be an object", {"cursor": whole})
    cleaned: dict[str, dict[str, str]] = {}
    for table, per_source in mapping.items():
        known_table = isinstance(table, str) and table in NATURAL_KEY
        if not known_table or not isinstance(per_source, dict):
            raise AddonPermanent(
                f"resume cursor's {name}[{table!r}] is malformed", {"cursor": whole}
            )
        row: dict[str, str] = {}
        for source, value in per_source.items():
            if not isinstance(source, str) or not isinstance(value, str):
                raise AddonPermanent(
                    f"resume cursor's {name}[{table!r}] entry is malformed", {"cursor": whole}
                )
            row[source] = value
        cleaned[table] = row
    return cleaned


# --------------------------------------------------------------------------- #
# Discovery: sources, and which sources have anything new
# --------------------------------------------------------------------------- #


def _discover_sources(context: CollectContext, budget: _Budget) -> Sequence[str]:
    if budget.exhausted:
        raise AddonPermanent("the page budget was exhausted before source discovery could run", {})
    budget.spend()
    response = context.fetch(SOURCES_ENDPOINT)
    body = _parse_json_object(response, "sources", SOURCES_ENDPOINT)
    sources = body.get("sources")
    if not isinstance(sources, list) or not all(isinstance(item, str) and item for item in sources):
        raise AddonPermanent(
            "GET /api/v1/sources did not return the documented {\"sources\": [...]} shape",
            {"endpoint": SOURCES_ENDPOINT, "body_keys": sorted(body)},
        )
    return sources


def _discover_run_high_water(
    context: CollectContext, budget: _Budget, runs_lookback: int
) -> dict[str, datetime]:
    """The newest `captured_at` each source appears with, over the last `runs_lookback` runs.

    Used only to *skip* a table+source with nothing new — never to decide what to
    request, and never trusted on its own past that: `_collect_one_pair` still walks
    rows and compares against the stored cursor itself. A source this misses (a run
    older than `runs_lookback`, or this call's own budget running out) is simply not
    skipped, which costs a wasted page rather than losing data.
    """
    if budget.exhausted:
        return {}
    budget.spend()
    response = context.fetch(RUNS_ENDPOINT, {"limit": str(runs_lookback)})
    body = _parse_json_object(response, "runs", RUNS_ENDPOINT)
    runs = body.get("runs")
    if not isinstance(runs, list):
        raise AddonPermanent(
            "GET /api/v1/runs did not return the documented {\"runs\": [...]} shape",
            {"endpoint": RUNS_ENDPOINT, "body_keys": sorted(body)},
        )
    high_water: dict[str, datetime] = {}
    for entry in runs:
        if not isinstance(entry, dict):
            continue
        captured_at = entry.get("captured_at")
        sources_csv = entry.get("sources")
        if not isinstance(captured_at, str) or not isinstance(sources_csv, str):
            continue
        try:
            when = datetime.fromisoformat(captured_at)
        except ValueError:
            continue
        for source in (part.strip() for part in sources_csv.split(",")):
            if source and (source not in high_water or when > high_water[source]):
                high_water[source] = when
    return high_water


# --------------------------------------------------------------------------- #
# Hour-bucket tables
# --------------------------------------------------------------------------- #


def _collect_hour_bucket_table(
    context: CollectContext,
    table: str,
    sources: Sequence[str],
    boards: Sequence[str],
    page_limit: int,
    run_high_water: Mapping[str, datetime],
    cursor_state: dict[str, dict[str, dict[str, str]]],
    budget: _Budget,
) -> list[RawItem]:
    emitted: list[RawItem] = []
    table_cursor = cursor_state["hour_bucket"].setdefault(table, {})
    for source in sources:
        existing_raw = table_cursor.get(source)
        existing = datetime.fromisoformat(existing_raw) if existing_raw is not None else None
        latest_known = run_high_water.get(source)
        if existing is not None and latest_known is not None and latest_known <= existing:
            context.log(
                "collect.bucket_skip_no_new_data",
                {"table": table, "source": source, "cursor": existing_raw},
            )
            continue

        board_list: Sequence[str | None] = list(boards) if boards else [None]
        high_water = existing
        completed_every_board = True
        for board in board_list:
            if budget.exhausted:
                completed_every_board = False
                break
            items, newest = _collect_one_pair(
                context, table, source, board, page_limit, existing, budget
            )
            emitted.extend(items)
            if newest is not None and (high_water is None or newest > high_water):
                high_water = newest
        if completed_every_board and high_water is not None:
            table_cursor[source] = high_water.isoformat()
    return emitted


def _collect_one_pair(
    context: CollectContext,
    table: str,
    source: str,
    board: str | None,
    page_limit: int,
    cutoff: datetime | None,
    budget: _Budget,
) -> tuple[list[RawItem], datetime | None]:
    """Page one (table, source[, board]) newest-first until a known row or an empty page.

    Returns the rows newer than `cutoff` and the newest `captured_at` seen, so the
    caller can advance that (table, source)'s cursor only once every board configured
    for it has been walked in this same run.
    """
    endpoint = _endpoint_for(table)
    base_params: dict[str, str] = {"source": source}
    if board is not None:
        base_params["board"] = board

    emitted: list[RawItem] = []
    newest: datetime | None = None
    offset = 0
    while not budget.exhausted:
        params = dict(base_params)
        params["limit"] = str(page_limit)
        params["offset"] = str(offset)
        budget.spend()
        response = context.fetch(endpoint, params)
        body = _parse_records_response(response, table, endpoint)
        _verify_filters_echo(body, base_params, table, endpoint)
        rows = body["rows"]
        if not rows:
            break

        page_new: list[Mapping[str, Any]] = []
        caught_up = False
        for row in rows:
            when = _row_captured_at(row, table)
            if cutoff is not None and when <= cutoff:
                caught_up = True
                break
            page_new.append(row)

        if page_new:
            items = [_to_raw_item(table, row, response) for row in page_new]
            context.emit_raw(items)
            emitted.extend(items)
            first_seen = _row_captured_at(page_new[0], table)
            if newest is None or first_seen > newest:
                newest = first_seen

        if caught_up:
            break
        echoed_limit = body.get("limit")
        if not isinstance(echoed_limit, int) or len(rows) < echoed_limit:
            break  # a short page is the last page (docs/api.md)
        offset += page_limit

    return emitted, newest


# --------------------------------------------------------------------------- #
# Full-scan (write-once) tables
# --------------------------------------------------------------------------- #


def _collect_full_scan_table(
    context: CollectContext,
    table: str,
    sources: Sequence[str],
    page_limit: int,
    cursor_state: dict[str, dict[str, dict[str, str]]],
    budget: _Budget,
) -> list[RawItem]:
    endpoint = _endpoint_for(table)
    table_cursor = cursor_state["full_scan"].setdefault(table, {})
    emitted: list[RawItem] = []
    for source in sources:
        if budget.exhausted:
            break
        offset = 0
        last_retrieved_at: str | None = None
        while not budget.exhausted:
            params = {"source": source, "limit": str(page_limit), "offset": str(offset)}
            budget.spend()
            response = context.fetch(endpoint, params)
            body = _parse_records_response(response, table, endpoint)
            _verify_filters_echo(body, {"source": source}, table, endpoint)
            rows = body["rows"]
            if not rows:
                break
            items = [_to_raw_item(table, row, response) for row in rows]
            context.emit_raw(items)
            emitted.extend(items)
            last_retrieved_at = response.retrieved_at
            echoed_limit = body.get("limit")
            if not isinstance(echoed_limit, int) or len(rows) < echoed_limit:
                break
            offset += page_limit
        if last_retrieved_at is not None:
            table_cursor[source] = last_retrieved_at
    return emitted


# --------------------------------------------------------------------------- #
# Response parsing, filters-echo, and Raw mapping
# --------------------------------------------------------------------------- #


def _parse_json_object(response: FetchResponse, label: str, endpoint: str) -> dict[str, Any]:
    """Classify `response` (contract 1.2) and return its parsed JSON object body."""
    status = response.status
    if status == 200:
        try:
            body = json.loads(response.body)
        except json.JSONDecodeError as error:
            raise AddonPermanent(
                f"{label} returned 200 with a body that is not valid JSON", {"endpoint": endpoint}
            ) from error
        if not isinstance(body, dict):
            raise AddonPermanent(
                f"{label} returned 200 with a JSON body that is not an object",
                {"endpoint": endpoint},
            )
        return body
    if status == 429 or status >= 500:
        raise AddonTransient(f"{label} returned {status}", _error_detail(response))
    if status in (401, 403):
        # This source declares `needs_credential = false`; kept for the same reason
        # `collector.naver.blog` keeps it — an unexpected auth rejection is still a
        # configuration failure, not a permanent one, per `p0-security.md`.
        raise AddonConfigInvalid(
            f"{label} rejected the request ({status}) though this source needs no credential",
            _error_detail(response),
        )
    raise AddonPermanent(f"{label} returned {status}", _error_detail(response))


def _parse_records_response(response: FetchResponse, table: str, endpoint: str) -> dict[str, Any]:
    body = _parse_json_object(response, f"records/{table}", endpoint)
    if body.get("table") != table:
        raise AddonPermanent(
            f"GET /api/v1/records/{table} answered for table {body.get('table')!r}",
            {"endpoint": endpoint},
        )
    if not isinstance(body.get("rows"), list):
        raise AddonPermanent(
            f"records/{table} response has no 'rows' array", {"endpoint": endpoint}
        )
    if not isinstance(body.get("filters"), dict):
        raise AddonPermanent(
            f"records/{table} response has no 'filters' object to verify the silent-drop "
            "defense against",
            {"endpoint": endpoint},
        )
    return body


def _verify_filters_echo(
    body: Mapping[str, Any], requested: Mapping[str, str], table: str, endpoint: str
) -> None:
    """Refuse the page if the echoed `filters` disagree with what was requested.

    `docs/api.md`: an unrecognized query parameter is silently dropped, not rejected.
    A silently dropped `source` or `board` would widen this page past what this add-on
    asked for and believes it received — the spec's own "silent-drop defense".
    """
    echoed = body["filters"]
    mismatches = {
        key: {"requested": value, "echoed": echoed.get(key)}
        for key, value in requested.items()
        if echoed.get(key) != value
    }
    if mismatches:
        raise AddonPermanent(
            f"records/{table} echoed different filters than requested; refusing the page "
            "rather than trusting it widened silently",
            {"endpoint": endpoint, "mismatches": mismatches},
        )


def _row_captured_at(row: Mapping[str, Any], table: str) -> datetime:
    value = row.get("captured_at")
    if not isinstance(value, str):
        raise AddonPermanent(f"a {table} row has no string captured_at", {"table": table})
    try:
        return datetime.fromisoformat(value)
    except ValueError as error:
        raise AddonPermanent(
            f"a {table} row's captured_at is not ISO 8601: {value!r}", {"table": table}
        ) from error


def _to_raw_item(table: str, row: Mapping[str, Any], response: FetchResponse) -> RawItem:
    key_columns = NATURAL_KEY[table]
    try:
        parts = [table, *(str(row[column]) for column in key_columns)]
    except KeyError as error:
        raise AddonPermanent(
            f"a {table} row is missing its natural-key column {error}", {"table": table}
        ) from error
    return RawItem(
        item_key=ITEM_KEY_SEP.join(parts),
        payload=json.dumps(row, sort_keys=True, ensure_ascii=False).encode("utf-8"),
        content_type="application/json",
        envelope_ref=response.envelope_ref,
    )


def _error_detail(response: FetchResponse) -> dict[str, Any]:
    return {"status": response.status}
