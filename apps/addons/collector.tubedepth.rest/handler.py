"""collector.tubedepth.rest — incremental pull from tubedepth's artifacts feed.

Target: tubedepth (yt-scrapper) v1.0.0, originally `http://127.0.0.1:8080` per
[DP-031](../../../docs/decisions/DP-031-p1-collector-topology.md) D3 and its
2026-08-21 addendum, address revised to `http://tubedepth-api:8080` by
[DP-035](../../../docs/decisions/DP-035-fleet-egress-and-container-bind.md) D3 once
cosmai joins the fleet's `db-net` bridge network. See this add-on's README.md for the
design this implements and for two platform-level gaps this add-on cannot work around
by itself (`domain.transport.SocketTransport` is HTTPS-only against a service that
serves plain HTTP; `domain.outbound.resolve` has no per-request path parameter, which
the payload-dereference route needs).

Design (spec Section 5.2):

- `GET /v1/artifacts?since=<watermark>&limit=` paged by tubedepth's own opaque
  keyset `cursor`, newest-`fetched_at`-first (confirmed by reading
  `src/tubedepth/api/application.py` at the target tag: the query orders by
  `Artifact.fetched_at.desc(), Artifact.identifier.desc()`).
- `GET /v1/artifacts/{digest}` dereferences each kept row into one Raw item:
  one payload response is one envelope and one item, payload bytes verbatim.
- This add-on's own cursor (`advance_cursor("artifacts", ...)`) is the
  highest `fetched_at` this run has processed — the first artifact on the
  first page fetched, because the feed is newest-first. It is unrelated to
  tubedepth's own per-page pagination cursor, which never leaves this run.
- `item_key = kind|target|fetched_at` — `digest` is a content address, not an
  observation identifier (two different `fetched_at` rows can share one
  digest when nothing changed).
- 404 (aged out of the 30-day retention window), 409 (schema version never
  recorded and the kind has withdrawn one) and 410 (retracted) on the
  dereference route are `context.accept_status` data outcomes, counted and
  skipped rather than treated as failures.
- `since`/`until` on this target require an RFC 3339 timestamp with a
  timezone offset (measured against the live instance, tubedepth 1.0.3: a
  naive `since` is refused with 422 `invalid_request`); tubedepth's own
  `fetched_at` is always `Z`-suffixed, so a watermark round-tripped from a
  previous response already satisfies this.
"""

from __future__ import annotations

import json
from typing import Any

from addon_api.context import CollectContext, FetchResponse
from addon_api.errors import AddonConfigInvalid, AddonOutputInvalid, AddonPermanent, AddonTransient
from addon_api.results import CollectOutcome, RawItem

_ARTIFACTS_LIST = "artifacts_list"
_ARTIFACT_PAYLOAD = "artifact_payload"
_STREAM = "artifacts"

_DEFAULT_PAGE_LIMIT = 50
_MIN_PAGE_LIMIT = 1
_MAX_PAGE_LIMIT = 500


def run(context: CollectContext) -> CollectOutcome:
    kinds = _kinds_allowlist(context)
    page_limit = _page_limit(context)
    watermark = _watermark_of(context.cursor)

    items_emitted = 0
    aged_out = 0
    retracted = 0
    unattributed = 0
    skipped_by_kind = 0
    pages = 0
    highest_seen: str | None = None

    list_params: dict[str, str] = {"limit": str(page_limit)}
    if watermark is not None:
        list_params["since"] = watermark

    page_cursor: str | None = None
    while True:
        page_params = dict(list_params)
        if page_cursor is not None:
            page_params["cursor"] = page_cursor

        response = context.fetch(_ARTIFACTS_LIST, page_params)
        if response.status != 200:
            _raise_for_status(response, "GET /v1/artifacts")
        body = _decode_json(response, "GET /v1/artifacts")
        artifacts = body.get("artifacts")
        if not isinstance(artifacts, list):
            raise AddonOutputInvalid(
                "GET /v1/artifacts did not return an 'artifacts' list",
                {"body_keys": sorted(body.keys()) if isinstance(body, dict) else None},
            )
        pages += 1

        if pages == 1 and artifacts:
            # Newest-first: the very first row of the very first page is the highest
            # `fetched_at` this run will see, however many pages follow it.
            first = artifacts[0]
            highest_seen = str(first["fetched_at"])

        for artifact in artifacts:
            kind = str(artifact["kind"])
            if kinds is not None and kind not in kinds:
                skipped_by_kind += 1
                continue
            target = str(artifact["target"])
            fetched_at = str(artifact["fetched_at"])
            digest = str(artifact["digest"])

            payload_response = context.fetch(_ARTIFACT_PAYLOAD, {"digest": digest})
            if payload_response.status == 404:
                context.accept_status(
                    payload_response,
                    "digest aged out of tubedepth's 30-day artifact retention window "
                    "(GET /v1/artifacts/{digest} docs/api.md)",
                )
                aged_out += 1
                continue
            if payload_response.status == 410:
                context.accept_status(
                    payload_response,
                    "artifact retracted: the schema version that collected it has been "
                    "withdrawn by the source",
                )
                retracted += 1
                continue
            if payload_response.status == 409:
                context.accept_status(
                    payload_response,
                    "schema version was never recorded for this row and the kind has "
                    "withdrawn a version, so it cannot be attributed; skipped rather than "
                    "guessed (run tubedepth backfill-schema-versions upstream to repair)",
                )
                unattributed += 1
                continue
            if payload_response.status != 200:
                _raise_for_status(payload_response, "GET /v1/artifacts/{digest}")

            # One payload response is one envelope and one Raw item, bytes verbatim —
            # the platform already recorded `payload_response.body` as the envelope;
            # this add-on carves exactly one item from it and does not re-encode it.
            item = RawItem(
                item_key=f"{kind}|{target}|{fetched_at}",
                payload=payload_response.body,
                content_type="application/json",
                envelope_ref=payload_response.envelope_ref,
                notes={"digest": digest},
            )
            context.emit_raw([item])
            items_emitted += 1

        page_cursor = body.get("cursor")
        if page_cursor is None:
            break

    if highest_seen is not None:
        context.advance_cursor(_STREAM, {"since": highest_seen})

    context.log(
        "collect.artifacts_summary",
        {
            "pages": pages,
            "items_emitted": items_emitted,
            "aged_out": aged_out,
            "retracted": retracted,
            "unattributed": unattributed,
            "skipped_by_kind": skipped_by_kind,
            "watermark_in": watermark,
            "watermark_out": highest_seen,
        },
    )
    return CollectOutcome(
        items_emitted=items_emitted,
        more_available=False,
        notes={
            "aged_out": aged_out,
            "retracted": retracted,
            "unattributed": unattributed,
            "skipped_by_kind": skipped_by_kind,
            "pages": pages,
        },
    )


def _kinds_allowlist(context: CollectContext) -> frozenset[str] | None:
    raw = context.config_field("kinds")
    if not isinstance(raw, str) or not raw.strip():
        return None
    names = frozenset(name.strip() for name in raw.split(",") if name.strip())
    return names or None


def _page_limit(context: CollectContext) -> int:
    raw = context.config_field("page_limit", _DEFAULT_PAGE_LIMIT)
    if not isinstance(raw, int) or isinstance(raw, bool):
        raise AddonConfigInvalid(
            "page_limit must be an integer", {"source_id": context.source_id}
        )
    if not (_MIN_PAGE_LIMIT <= raw <= _MAX_PAGE_LIMIT):
        raise AddonConfigInvalid(
            f"page_limit must be between {_MIN_PAGE_LIMIT} and {_MAX_PAGE_LIMIT} "
            "(tubedepth refuses anything outside that range with 422 invalid_request)",
            {"source_id": context.source_id, "page_limit": raw},
        )
    return raw


def _watermark_of(cursor: Any | None) -> str | None:
    """The stored `since` value, or `None` on a first run.

    `advance_cursor` always writes `{"since": <fetched_at>}`; anything else stored
    under this stream's cursor is not this add-on's own writing and is refused
    rather than guessed at.
    """
    if cursor is None:
        return None
    since = cursor.get("since") if isinstance(cursor, dict) else None
    if not isinstance(since, str):
        raise AddonOutputInvalid(
            "the stored cursor for the 'artifacts' stream is not this add-on's "
            "{'since': <fetched_at>} shape",
            {"cursor": cursor if isinstance(cursor, (dict, str, int, float, bool)) else None},
        )
    return since


def _decode_json(response: FetchResponse, label: str) -> dict[str, Any]:
    try:
        decoded = json.loads(response.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AddonPermanent(
            f"{label} did not return valid JSON: {error}",
            {"endpoint_ref": response.endpoint_ref, "status": response.status},
        ) from error
    if not isinstance(decoded, dict):
        raise AddonPermanent(
            f"{label} returned a JSON value that is not an object",
            {"endpoint_ref": response.endpoint_ref, "status": response.status},
        )
    return decoded


def _raise_for_status(response: FetchResponse, label: str) -> None:
    """Classify a non-2xx response tubedepth's own error taxonomy (docs/api.md).

    401/403 never happen for a well-formed `X-API-Key` header, but a missing,
    malformed, unknown or revoked key all answer 401 `unauthenticated` — the
    operator's row is what needs fixing, and no retry changes that (DP-018 D5).
    429 is the 60/req-per-minute budget; 5xx is tubedepth's own upstream/parse
    failure taxonomy (`parse_mismatch`, `upstream_error`, `not_configured`) —
    all worth retrying later. Anything else 4xx (422 `invalid_request` from a
    malformed query this add-on built) is a defect in this add-on, not the
    operator's to fix by retrying.
    """
    status = response.status
    if status in (401, 403):
        raise AddonConfigInvalid(
            f"{label} rejected the configured credential (status {status})",
            {"endpoint_ref": response.endpoint_ref, "status": status},
        )
    if status == 429 or status >= 500:
        raise AddonTransient(
            f"{label} returned {status}",
            {"endpoint_ref": response.endpoint_ref, "status": status},
        )
    raise AddonPermanent(
        f"{label} returned {status}",
        {"endpoint_ref": response.endpoint_ref, "status": status},
    )
