# collector.tubedepth.rest

A thin REST adapter for tubedepth (yt-scrapper), the YouTube domain service.
Target fixed by
[DP-031](../../../docs/decisions/DP-031-p1-collector-topology.md) D3 and its
2026-08-21 addendum: release tag **v1.0.0**, `X-API-Key` auth, 60
requests/minute. The address itself — originally the loopback literal
`http://127.0.0.1:8080` — is revised to `http://tubedepth-api:8080` by
[DP-035](../../../docs/decisions/DP-035-fleet-egress-and-container-bind.md) D3
once cosmai joins the fleet's `db-net` bridge network. This is one of the two
heavy, periodic collection targets DP-031 keeps external (the other is
`collector.trendradar.rest`); NAVER's three sources went the other way, as
internal direct collectors (DP-031 D2).

## What it collects

Incrementally pulls tubedepth's **artifacts feed** — what was actually
collected, as distinct from the job ledger of what was asked for
(`docs/api.md` at the target tag, `GET /v1/artifacts`):

1. `GET /v1/artifacts?since=<watermark>&limit=<page_limit>` — paged by
   tubedepth's own opaque keyset `cursor`, newest `fetched_at` first.
2. `GET /v1/artifacts/{digest}` — dereferences each kept row into one payload.
   One payload response is one Raw envelope and one Raw item; the bytes are
   stored verbatim, never re-parsed.

**Cursor.** `advance_cursor("artifacts", {"since": <fetched_at>})` where
`<fetched_at>` is the highest value this run processed — read off the first
artifact of the first page, since the feed is newest-first. This is this
add-on's own watermark and is unrelated to tubedepth's per-page pagination
`cursor`, which never survives past one run.

**`item_key = kind|target|fetched_at`.** `digest` is a content address, not an
observation identifier: two rows with different `fetched_at` can share one
digest when nothing changed between two collections (tubedepth's own
"observations"/"first_fetched_at" fields on the dereference response say the
same thing from the other side).

**404/409/410 on the dereference route are data, not failures**, and are
counted and skipped via `context.accept_status` rather than raised:

| status | meaning (docs/api.md) | this add-on's count |
|---|---|---|
| 404 | aged out of the 30-day artifact retention window | `aged_out` |
| 410 | retracted — the schema version that collected it was withdrawn | `retracted` |
| 409 | schema version never recorded, and the kind has withdrawn one; unattributable | `unattributed` |

**`since`/`until` need a timezone-offset timestamp on this target.**
`[측정]` The live instance (confirmed running **1.0.3**, three commits past
the v1.0.0 baseline tag — see "Deviations" below) refuses a naive `since`
with 422 `invalid_request` and requires an RFC 3339 offset. tubedepth's own
`fetched_at` values are always `Z`-suffixed, so a watermark round-tripped
from a previous response already satisfies this; nothing in this add-on
constructs a timestamp itself.

## Configuration

| field | type | required | meaning |
|---|---|---|---|
| `kinds` | string | no | comma-separated allowlist of tubedepth kinds (e.g. `video.metadata,video.transcript`); empty or absent means every kind. Filtered client-side after each page — `/v1/artifacts` accepts only one `kind=` value per request, and an allowlist is plural by nature. |
| `page_limit` | integer | no | rows requested per `/v1/artifacts` page, 1-500 (tubedepth's own bound); defaults to 50. Validated here because `[[config.field]]` cannot express a range (`docs/conventions/addon-authoring.md`, "설정 스키마가 표현하지 못하는 것"). |

## Credential

`needs_credential = true`; the operator-approved `outbound_profile.credentials`
entry must fill `X-API-Key` from a `COSMA_SRC_TUBEDEPTH_API_KEY`-shaped ref
(DP-018). `X-API-Key` **is** in `domain.outbound.PROTECTED_HEADERS`
(`apps/domain/outbound.py`) — the mechanism this add-on's task brief asked to
verify holds without any platform change:

```python
PROTECTED_HEADERS: Final[frozenset[str]] = frozenset(
    {"authorization", "cookie", "set-cookie", "proxy-authorization",
     "x-api-key", "x-ncp-apigw-api-key", "x-ncp-apigw-api-key-id"}
)
```

A live key was minted through tubedepth's own CLI (`tubedepth key create
--label cosmai-adapter`, run against the live instance's own database — see
"Live verification" below) and stored at `~/.config/cosmai/env` as
`COSMA_SRC_TUBEDEPTH_API_KEY=ytd_...`. The value is never printed by this
work, never committed, and does not appear in any fixture, log, or this file.

## The operator-approved outbound profile

M4x closed the two gaps below; DP-035 D3 then moved the target off loopback. This is
the profile shape a source row now registers to actually reach the live target on
`db-net`, not a hypothetical one:

```json
{
  "hosts": ["tubedepth-api"],
  "port": 8080,
  "scheme": "http",
  "allow_fleet": true,
  "endpoints": {
    "artifacts_list": {"path": "/v1/artifacts", "method": "GET"},
    "artifact_payload": {
      "path": "/v1/artifacts/{digest}",
      "method": "GET",
      "path_params": {"digest": "^[0-9a-f]{64}$"}
    }
  },
  "credentials": [{"header": "X-API-Key", "ref": "COSMA_SRC_TUBEDEPTH_API_KEY"}]
}
```

`scheme: "http"` is granted only because `allow_fleet` is also set — the same flag
that already admits a private, non-loopback fleet address at all
(`domain.outbound.resolve`, DP-035 D1); a host outside the fleet's private address
range with `scheme: "http"` is refused both there and again by
`domain.transport.SocketTransport` against the address it actually resolved.
`artifact_payload.path_params`
declares the one regex `{digest}` must match; `resolve` validates the value
`context.fetch("artifact_payload", {"digest": digest})` supplies, substitutes
it, and only then runs the same segment-by-segment containment every approved
path has always been checked with (M4x gap 2) — this add-on's own
`context.fetch` call, quoted in "Live verification" below, needed no change
to use either mechanism.

## Normalizer

None. RC-005 (normalizing tubedepth's payload shapes) is deferred — this
milestone ships the collector only. A `collector.tubedepth.rest` Raw item's
`payload` is the tubedepth `ArtifactPayloadView` JSON body verbatim
(`digest`, `kind`, `target`, `observations`, `first_fetched_at`, `fetched_at`,
`schema_version`, `current_schema_version`, `payload_fields`,
`current_fields`, `payload`), unread by anything downstream until RC-005 is
scheduled.

## Tests

**`[정정, 2026-08-21, m7-fixwave, M-X7]`** The paragraphs below described a
`tests/` layout under this add-on's own directory. That never matched this
tree's layout: every add-on's tests live under `apps/tests/`, not inside the
add-on's own directory (the same convention `apps/tests/test_collector_naver_blog.py`
and every other add-on's tests already follow), and `tests/test_handler_fixtures.py`
does not exist anywhere in this tree. Corrected to the real paths:

- `apps/tests/test_addon_collector_tubedepth.py` — the collector logic, called
  directly against a hand-built `CollectContext` (not through `addon_kit`'s
  fixture harness): watermark/cursor round-trip, `kinds` filtering, page-size
  validation, the 404/409/410 branches, the golden-path pagination and
  dereference sequence, and that the credential never appears in a `RawItem`
  or in any log line the add-on writes (`context.log` fields are inspected,
  not just its calls) — `addon_kit`'s harness can script only one status code
  per run (`docs/conventions/addon-authoring.md`, "하네스가 표현하지 못하는
  것"), which cannot express three different dereference outcomes in one
  page.
- `apps/tests/fixtures/collector.tubedepth.rest/` — a two-page
  `/v1/artifacts` response pair and three `/v1/artifacts/{digest}` payload
  responses, built from the shapes measured against the live instance
  2026-08-21 (one is the live `video.sponsor_segments` payload for
  `MfqI-W_JRQQ`, 74 bytes, itself public YouTube-derived metadata with an
  empty `segments` list — SponsorBlock data the source documents as
  CC BY-NC-SA 4.0).
- Conformance suite (`addon_kit.conformance`) and host-loading — see the
  batch report for the exact commands and results.

## Live verification

`[측정]` Confirmed live, 2026-08-21, against the running instance at
`127.0.0.1:8080` (unsandboxed shell; the default sandbox's loopback
isolation refuses the connection, matching spec §11's own note):

- `/healthz` reports `"version": "1.0.3"` at M4 finding time — **not
  v1.0.0**. `git log` on the target repository shows `v1.0.3` is `v1.0.0`
  plus two fix commits (`0767076`, `e2ead38`); the artifacts-feed routes this
  add-on depends on are unchanged between the two tags except for the
  `since`/`until` timezone-offset requirement noted above. Per DP-031 D3's
  own standing rule ("if a new release tag appears during the work, the
  adapter switches to that tag"), this add-on is written against the live
  1.0.3 behavior; the task brief's "baseline = v1.0.0" is the surface this
  add-on's design and docs cite, since the artifacts-feed contract itself did
  not change. `[측정]` At M4x's own live-smoke time the instance had moved
  again, to `1.1.0` — the artifacts-feed surface is still unchanged; recorded
  here rather than silently absorbed, the same way the 1.0.0→1.0.3 move was.
- A key was minted live via `tubedepth key create --label cosmai-adapter`
  (run from the target repository's own `uv run`, pointed at the live
  deployment's actual database over its published port,
  `127.0.0.1:5434` — the compose network hostname `shared-postgres` in the
  container's own env is not reachable from the host shell). Confirmed
  working: `GET /v1/artifacts` and `/v1/artifacts/{digest}` both answered
  200 with this key.

## M4x — the two platform gaps this add-on named, closed

M4 found and named two platform-level gaps rather than routing around them:
`domain.transport.SocketTransport` was HTTPS-only against a target that
serves plain HTTP by design, and `domain.outbound.resolve` had no per-request
path parameter for `GET /v1/artifacts/{digest}`. Both are now platform
mechanisms — `domain/outbound.py`'s `scheme`/`allow_loopback`/`allow_fleet` (the
latter DP-035 D1) and `path_params`, `domain/transport.py`'s loopback-or-fleet-checked
plain-HTTP path — and
this add-on needed **no handler code change** to use either: `handler.py`'s
`context.fetch(_ARTIFACT_PAYLOAD, {"digest": digest})` was already written to
the contract's intended shape (see "Design" above and the git history of this
file). What changed is the *operator-approved outbound profile* — "The
operator-approved outbound profile" above is the row that now actually
reaches the target — and `apps/tests/test_addon_collector_tubedepth.py`'s dereference-branch tests
still exercise `handler.py` directly against a hand-built `CollectContext`
(the harness-cannot-express-three-statuses-in-one-page reason given above,
unrelated to either gap).

`[측정]` Live smoke, 2026-08-21, one bounded `collect()` through the real
host worker (`platform_core.worker.Worker` via
`addon_host.worker.capability_registry`, real `SocketTransport`, a real
source row in `cosmai_test_5` with the profile above, cleaned up
afterward — nothing left in the database): **SUCCEEDED**, one attempt, one
page-plus-dereference pass bounded to a ~3-minute slice of the live feed
(this target's own retention window holds far more than one job's page
budget can afford in one pass; a real second-and-later run reads its own
watermark and stays this small on every ordinary run). 5 `artifacts_list`
pages, 224 `artifact_payload` dereferences — every one of them a plain-HTTP
request to `127.0.0.1:8080` admitted by `allow_loopback`, with `{digest}`
validated against `^[0-9a-f]{64}$` and substituted by `domain.outbound.resolve`
— 224 Raw items recorded, watermark advanced from `03:09:25.090879Z` to
`03:12:25.090879Z`, and (called directly, the way an operator action would)
`domain.store.seal_snapshot_from_raw` sealed a snapshot of all 224 items.
Counts only; no payload bytes are reproduced here.
