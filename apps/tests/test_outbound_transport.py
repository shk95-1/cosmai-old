"""The socket half of the guard, against a real server — and `collector.naver.blog` on it.

`test_outbound_policy.py` covers everything `domain.outbound` can decide without a socket,
which is most of it. What is left needs one: a name that resolves, a connection that opens,
bytes that keep arriving, and a clock that runs out. `SEC-004` is entirely in that half —
"oversized/slow response는 bounded failure로 종료되고 worker를 무기한 점유하지 않는다" is
not a claim a pure function can make.

**The known obstacle, decided in advance.** `EXP-003` records it: the DNS rule blocks
loopback, so a local stub is unreachable through the production path unless something is
relaxed. What is relaxed is the per-source `allow_loopback` flag, and the experiment record
fixed the price in advance — **two** tests, not one. `TestLoopbackIsOnlyReachableByFlag`
holds both: with the flag off a loopback address is actually refused, and no source in the
repository sets it. The first is the positive control without which the second proves
nothing.

**The certificate.** The stub speaks real TLS with a certificate generated per session, and
`SocketTransport` takes its `ssl.SSLContext` as a constructor argument. That is a
*per-process* trust anchor and not a per-source one: no `source` row, profile field, or
environment variable can widen it, and `test_the_default_context_rejects_this_stub` is the
control proving the trust is doing work rather than being absent.

Copy-adapted from `experiments/integrated-p0/tests/test_outbound_transport.py` (M2 batch
2c). One class is **not** carried over: P0's `TestTheInstalledCollectorRunsThroughThePlatform`
ran the installed `addons/collector.naver.blog` through `JobRunner`, the capability layer,
this transport, a socket, and the database — every one of those except this module's own
`domain.transport` is M3 (`addon_host`) or M4 (the add-on itself) work that does not exist
in this tree yet. That class, its two fixtures (`domain`, `ncp_store`), and its two helpers
(`register_stub_source`, `run_the_installed_collector`) are omitted rather than stubbed;
`docs/p1/M2-RECORD.md` names the omission and the M3/M4 batches it belongs to. Every other
class here needs only `domain.outbound`/`domain.transport` and the stub server below, which
this tree's `domain` package (this batch) already provides.
"""

from __future__ import annotations

import json
import ssl
import subprocess
import threading
import time
from collections.abc import Iterator
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

from domain.outbound import (
    DEFAULT_LIMITS,
    OutboundProfile,
    PreparedRequest,
    Refusal,
    RefusalReason,
    resolve,
)
from domain.transport import (
    SocketTransport,
    TransportLimits,
    TransportUnavailable,
    _refuse_http_off_loopback,
)

#: The repository root two levels up from this file (``apps/tests/``), not three as in
#: P0's ``experiments/integrated-p0/tests/`` — one directory shallower.
REPO_ROOT = Path(__file__).resolve().parents[2]

#: Small enough that a test can exceed it in one write, and nowhere near a real limit.
SMALL_BODY_LIMIT = 2048
#: The stub sleeps far longer than this, so a bounded failure is the only way out.
SHORT_READ_TIMEOUT = 1.0

#: `ADVERSARIAL-REVIEW-2026-08-18.md` F5's server: one that never stops sending, as opposed
#: to `/v1/slow`, which never starts. Each byte arrives well inside any socket timeout, so
#: no per-`recv` bound can ever trip — which was the finding. Sized so that a run without a
#: total deadline takes seconds rather than the review's arithmetical 38 days, and so that
#: the RED state of these tests is observable rather than a hang.
DRIP_BYTES = 2000
DRIP_INTERVAL = 0.005
#: Well under the time a drip of `DRIP_BYTES` takes, and well over a local round trip.
SHORT_REQUEST_BUDGET = 0.5

BLOG_PAGE_SIZE = 10

#: The two headers Naver API Hub authenticates with, per
#: https://guide.ncloud-docs.com/docs/apihub-overview (fetched 2026-08-18). The stub demands
#: both, so the end-to-end case exercises DP-018's attachment rather than assuming it.
NCP_HEADERS = ("X-NCP-APIGW-API-KEY-ID", "X-NCP-APIGW-API-KEY")

NCP_ID_REF = "COSMA_SRC_NAVER_BLOG_STUB_CLIENT_ID"
NCP_SECRET_REF = "COSMA_SRC_NAVER_BLOG_STUB_CLIENT_SECRET"
NCP_ID_VALUE = "stub-client-id"
NCP_SECRET_VALUE = "stub-client-secret"


# --------------------------------------------------------------------------- #
# A real HTTPS stub
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="session")
def certificate(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    """A self-signed certificate for `localhost`, generated once per session.

    `openssl` rather than a library because neither `cryptography` nor `trustme` is a
    dependency of this experiment, and adding one to reach a stub would be a dependency
    the deliverable does not need.
    """
    directory = tmp_path_factory.mktemp("tls")
    key, cert = directory / "stub.key", directory / "stub.pem"
    subprocess.run(
        [
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
            "-keyout", str(key), "-out", str(cert), "-days", "1",
            "-subj", "/CN=localhost", "-addext", "subjectAltName=DNS:localhost",
        ],
        check=True,
        capture_output=True,
    )
    return key, cert


class StubHandler(BaseHTTPRequestHandler):
    """Four behaviours, one per rule that needs a live server to be exercised."""

    protocol_version = "HTTP/1.1"

    #: Every authenticated `/blog` request's credential headers, so a test can assert the
    #: platform sent them rather than assert that the request merely succeeded. A class
    #: attribute because `BaseHTTPRequestHandler` is instantiated per request.
    seen_credentials: list[dict[str, str]] = []

    #: Every POST body the stub received, so a test can assert the platform sent the bytes
    #: the add-on composed rather than assert the request merely succeeded.
    seen_bodies: list[bytes] = []

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's spelling
        """The DataLab shape: a JSON body in, a `results` array out.

        `/search-trend/v1/search` and `/shopping/v1/categories` are both POST-with-a-body on
        the real API Hub, which is the whole reason DP-020 exists.
        """
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        self.seen_bodies.append(body)
        if urlsplit(self.path).path == "/v1/stall":
            # Accept the connection and never read the body. The client's write fills the
            # kernel send buffer and then blocks — which is the only way to observe whether
            # the write phase is under a deadline at all.
            time.sleep(SHORT_READ_TIMEOUT * 30)
            return
        if urlsplit(self.path).path == "/v1/drip":
            # The same never-ending response as the GET case. F5's deadline is not a
            # GET-only property, and a stub that answered a POST promptly would make the
            # assertion about that vacuous.
            self._drip()
            return
        if urlsplit(self.path).path != "/search-trend/v1/search":
            self._bytes(b"not found", status=404)
            return
        if self.headers.get("Content-Type") != "application/json":
            # DP-020 D5: the platform sets this, so a stub that accepted anything would
            # make the assertion about it vacuous.
            self._json({"errorCode": "SE01", "errorMessage": "bad content type"}, 400)
            return
        try:
            asked = json.loads(body)
        except json.JSONDecodeError:
            self._json({"errorCode": "SE01", "errorMessage": "bad body"}, 400)
            return
        self._json(
            {
                "startDate": asked.get("startDate"),
                "endDate": asked.get("endDate"),
                "timeUnit": asked.get("timeUnit"),
                "results": [
                    {
                        "title": group["groupName"],
                        "keywords": group["keywords"],
                        "data": [{"period": asked.get("startDate"), "ratio": 100.0}],
                    }
                    for group in asked.get("keywordGroups", [])
                ],
            }
        )

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's spelling
        # `[측정]` Read here too, since 2026-08-19. `seen_bodies` was appended only in
        # `do_POST`, so `test_a_get_endpoint_still_sends_no_body` asserted an emptiness the
        # stub could not have disturbed — `ADVERSARIAL-REVIEW-2026-08-19-MUTATION.md` B7
        # made every GET carry a body and the assertion stayed green.
        length = int(self.headers.get("Content-Length", "0"))
        if length:
            self.seen_bodies.append(self.rfile.read(length))
        parts = urlsplit(self.path)
        match parts.path:
            case "/v1/items":
                self._json({"items": [{"id": 1}, {"id": 2}], "next": 3})
            case "/v1/huge":
                self._bytes(b"x" * (SMALL_BODY_LIMIT * 4))
            case "/v1/slow":
                time.sleep(SHORT_READ_TIMEOUT * 6)
                self._bytes(b"late")
            case "/v1/drip":
                self._drip()
            case "/v1/redirect":
                self.send_response(302)
                self.send_header("Location", "https://elsewhere.example.net/v1/items")
                self.send_header("Content-Length", "0")
                self.end_headers()
            case "/blog":
                missing = [
                    name for name in NCP_HEADERS if not self.headers.get(name)
                ]
                if missing:
                    # What the real gateway does with an unauthenticated request, as far as
                    # the docs describe it. `401` and not `200`-with-an-error-body, because
                    # this stub must not be *kinder* than the source it stands in for.
                    self._json({"errorCode": "SE01", "errorMessage": "unauthenticated"}, 401)
                    return
                self.seen_credentials.append(
                    {name: self.headers[name] for name in NCP_HEADERS}
                )
                self._json(self._blog_page(parse_qs(parts.query)))
            case _:
                self._bytes(b"not found", status=404)

    @staticmethod
    def _blog_page(query: dict[str, list[str]]) -> dict[str, Any]:
        """The documented Naver blog-search shape: one full page, then an empty one.

        Matches the vendor documentation rather than a capture — no capture of this source
        exists, which `addons/collector.naver.blog` says in its own module docstring.
        """
        start = int(query.get("start", ["1"])[0])
        if start > 1:
            return {"total": BLOG_PAGE_SIZE, "start": start, "display": 0, "items": []}
        return {
            "total": BLOG_PAGE_SIZE,
            "start": start,
            "display": BLOG_PAGE_SIZE,
            "items": [
                {"title": f"post {n}", "link": f"https://blog.example.com/{n}"}
                for n in range(BLOG_PAGE_SIZE)
            ],
        }

    def _drip(self) -> None:
        """A complete, honest `Content-Length`, delivered one byte at a time.

        Nothing here is malformed: the response is well-formed HTTP and every byte arrives
        promptly. What it never does is *finish*. `OSError` is swallowed because the client
        giving up is the outcome under test, and the broken pipe that follows is its
        shadow rather than a second failure.
        """
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(DRIP_BYTES))
        self.end_headers()
        try:
            for _ in range(DRIP_BYTES):
                self.wfile.write(b"x")
                self.wfile.flush()
                time.sleep(DRIP_INTERVAL)
        except OSError:
            pass

    def _json(self, body: object, status: int = 200) -> None:
        self._bytes(json.dumps(body).encode("utf-8"), status, "application/json")

    def _bytes(self, body: bytes, status: int = 200, kind: str = "text/plain") -> None:
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        # A header the guard must strip on the way out. Its absence downstream is checked
        # against the presence of Content-Type, so "nothing was recorded" cannot pass.
        self.send_header("Set-Cookie", "session=must-not-be-recorded")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        """Silent. The suite's output is the evidence, and a request log is not part of it."""


@pytest.fixture(scope="session")
def stub(certificate: tuple[Path, Path]) -> Iterator[int]:
    """A TLS server on loopback, on whatever port the OS gives. Yields the port."""
    key, cert = certificate
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile=cert, keyfile=key)
    server = ThreadingHTTPServer(("127.0.0.1", 0), StubHandler)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield int(server.server_address[1])
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture
def trusting(certificate: tuple[Path, Path]) -> SocketTransport:
    _, cert = certificate
    context = ssl.create_default_context(cafile=str(cert))
    return SocketTransport(context)


@pytest.fixture(scope="session")
def http_stub() -> Iterator[int]:
    """A plain-HTTP server on loopback, no TLS at all — the shape a live loopback-only
    target like tubedepth actually serves (its own `docs/api.md`: "There is no TLS
    here"). M4x gap 1. `StubHandler` is reused unchanged; only the transport wrapping the
    `stub` fixture applies is left off.
    """
    server = ThreadingHTTPServer(("127.0.0.1", 0), StubHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield int(server.server_address[1])
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def a_loopback_http_profile(port: int, **overrides: Any) -> OutboundProfile:
    values: dict[str, Any] = {
        "hosts": ["127.0.0.1"],
        "endpoints": {"items": "/v1/items"},
        "port": port,
        "scheme": "http",
        "allow_loopback": True,
    }
    values.update(overrides)
    read = OutboundProfile.from_row(values)
    assert read is not None
    return read


def a_profile(port: int, **overrides: Any) -> OutboundProfile:
    values: dict[str, Any] = {
        "hosts": ["localhost"],
        "endpoints": {
            "items": "/v1/items",
            "huge": "/v1/huge",
            "slow": "/v1/slow",
            "drip": "/v1/drip",
            "hop": "/v1/redirect",
            "blog": "/blog",
        },
        "port": port,
        "limits": {},
        "allow_loopback": True,
    }
    values.update(overrides)
    return OutboundProfile(
        hosts=tuple(values["hosts"]),
        endpoints=values["endpoints"],
        port=values["port"],
        limits={**OutboundProfile(hosts=(), endpoints={}).limits, **values["limits"]},
        allow_loopback=values["allow_loopback"],
    )


def prepared(profile: OutboundProfile, endpoint: str = "items", **params: str) -> Any:
    request = resolve(endpoint, profile, params or None)
    assert not isinstance(request, Refusal), request
    return request


# --------------------------------------------------------------------------- #
# It reaches a real server
# --------------------------------------------------------------------------- #


class TestARealRoundTrip:
    def test_an_approved_endpoint_comes_back_with_its_bytes(
        self, stub: int, trusting: SocketTransport
    ) -> None:
        profile = a_profile(stub)
        response = trusting.send(prepared(profile), profile)

        assert not isinstance(response, Refusal), response
        assert response.status == 200
        assert json.loads(response.body)["next"] == 3
        # `localhost` may resolve to both families. Every address it returned was checked,
        # and the socket was opened to one of those and to nothing else.
        assert "127.0.0.1" in response.addresses

    def test_a_protected_header_never_reaches_the_caller(
        self, stub: int, trusting: SocketTransport
    ) -> None:
        profile = a_profile(stub)
        response = trusting.send(prepared(profile), profile)

        assert not isinstance(response, Refusal)
        assert not any(k.lower() == "set-cookie" for k in response.headers)
        # The control: the same response's ordinary headers *did* survive, so the assertion
        # above is about stripping and not about an empty mapping.
        assert any(k.lower() == "content-type" for k in response.headers)

    def test_a_redirect_comes_back_unfollowed(
        self, stub: int, trusting: SocketTransport
    ) -> None:
        """One call is one hop. Revalidating the destination is the caller's."""
        profile = a_profile(stub)
        response = trusting.send(prepared(profile, "hop"), profile)

        assert not isinstance(response, Refusal)
        assert response.status == 302
        assert response.location == "https://elsewhere.example.net/v1/items"

    def test_the_default_context_rejects_this_stub(self, stub: int) -> None:
        """The control for every test above: the trust is doing work.

        Without this, a `SocketTransport` that verified nothing would pass all of them.
        """
        profile = a_profile(stub)
        with pytest.raises(TransportUnavailable):
            SocketTransport().send(prepared(profile), profile)


# --------------------------------------------------------------------------- #
# SEC-004 — bounded failures
# --------------------------------------------------------------------------- #


class TestBoundedFailures:
    def test_an_oversized_response_is_refused_by_rule(
        self, stub: int, trusting: SocketTransport
    ) -> None:
        """`SEC-004`, the size half. Enforced while reading, not after."""
        profile = a_profile(stub, limits={"max_response_bytes": SMALL_BODY_LIMIT})
        outcome = trusting.send(prepared(profile, "huge"), profile)

        assert isinstance(outcome, Refusal)
        assert outcome.reason is RefusalReason.RESPONSE_TOO_LARGE

    def test_a_body_inside_the_limit_is_not_refused(
        self, stub: int, trusting: SocketTransport
    ) -> None:
        """The control. A transport that refused everything would pass the test above."""
        profile = a_profile(stub, limits={"max_response_bytes": SMALL_BODY_LIMIT})
        outcome = trusting.send(prepared(profile), profile)

        assert not isinstance(outcome, Refusal)

    def test_a_slow_response_ends_within_its_read_timeout(
        self, stub: int, trusting: SocketTransport
    ) -> None:
        """`SEC-004`, the time half: the worker is not occupied indefinitely.

        The assertion is on elapsed wall-clock, not on the exception alone. A transport
        that failed after the stub finished sleeping would raise the same exception and
        occupy the worker for the whole six seconds.
        """
        profile = a_profile(stub)
        bounds = TransportLimits(read_timeout_s=SHORT_READ_TIMEOUT)

        started = time.monotonic()
        with pytest.raises(TransportUnavailable):
            trusting.send(prepared(profile, "slow"), profile, limits=bounds)
        elapsed = time.monotonic() - started

        assert elapsed < SHORT_READ_TIMEOUT * 3, f"the read ran for {elapsed:.1f}s"


class TestAServerThatNeverStopsSending:
    """`ADVERSARIAL-REVIEW-2026-08-18.md` F5.

    This module's docstring claimed `SEC-004` held *"against a server that never stops
    sending as well as one that never starts"*, and only the second half was tested. The
    first was false: `_read_bounded` called `source.read(n)`, which blocks until *n* bytes
    arrive, while `settimeout` bounds each underlying `recv`. A server emitting one byte
    per (timeout − ε) trips neither bound, and occupancy is linear in the body limit — the
    reviewer measured 8.1s against a 1.0s read timeout with a 20-byte limit, and put
    `DEFAULT_LIMITS` at roughly 38 days.

    Two changes make the claim true and both are asserted below: reads take whatever has
    arrived rather than waiting for a full chunk, and one monotonic deadline bounds the
    whole request rather than each `recv`.
    """

    def test_a_drip_ends_at_the_request_budget_rather_than_at_the_body_limit(
        self, stub: int, trusting: SocketTransport
    ) -> None:
        profile = a_profile(stub)
        bounds = TransportLimits(
            read_timeout_s=SHORT_READ_TIMEOUT,
            max_request_seconds=SHORT_REQUEST_BUDGET,
        )

        started = time.monotonic()
        with pytest.raises(TransportUnavailable):
            trusting.send(prepared(profile, "drip"), profile, limits=bounds)
        elapsed = time.monotonic() - started

        # The assertion is wall-clock, because the exception alone is what the *old* code
        # eventually raised too — after reading the whole drip.
        assert elapsed < SHORT_REQUEST_BUDGET * 4, f"the request ran for {elapsed:.1f}s"

    def test_the_budget_does_not_scale_with_the_body_limit(
        self, stub: int, trusting: SocketTransport
    ) -> None:
        """The finding's shape, stated as a property: occupancy was linear in
        `max_response_bytes`, and a bound that moves with the thing it bounds is not one.

        A body limit 100× larger must not buy the far end 100× the time.
        """
        profile = a_profile(stub)
        bounds = TransportLimits(
            read_timeout_s=SHORT_READ_TIMEOUT,
            max_request_seconds=SHORT_REQUEST_BUDGET,
            max_response_bytes=SMALL_BODY_LIMIT * 100,
        )

        started = time.monotonic()
        with pytest.raises(TransportUnavailable):
            trusting.send(prepared(profile, "drip"), profile, limits=bounds)
        elapsed = time.monotonic() - started

        assert elapsed < SHORT_REQUEST_BUDGET * 4, f"the request ran for {elapsed:.1f}s"

    def test_an_ordinary_response_is_unaffected_by_the_deadline(
        self, stub: int, trusting: SocketTransport
    ) -> None:
        """The positive control. A deadline that refused everything would pass both
        assertions above, and this is a local round trip well inside the budget."""
        profile = a_profile(stub)
        bounds = TransportLimits(max_request_seconds=SHORT_REQUEST_BUDGET * 20)

        outcome = trusting.send(prepared(profile), profile, limits=bounds)

        assert not isinstance(outcome, Refusal)
        assert outcome.status == 200

    def test_an_expired_budget_refuses_before_a_socket_is_opened(
        self, stub: int, trusting: SocketTransport
    ) -> None:
        """A deadline already in the past costs no connection at all — which is what makes
        it a bound across redirect hops rather than a per-hop timeout."""
        profile = a_profile(stub)
        bounds = TransportLimits(deadline=time.monotonic() - 1.0)

        with pytest.raises(TransportUnavailable):
            trusting.send(prepared(profile), profile, limits=bounds)


# --------------------------------------------------------------------------- #
# The flag, and its price
# --------------------------------------------------------------------------- #


class TestLoopbackIsOnlyReachableByFlag:
    """`EXP-003`'s known obstacle, with the two tests it fixed in advance."""

    def test_with_the_flag_off_a_loopback_address_is_actually_refused(
        self, stub: int, trusting: SocketTransport
    ) -> None:
        profile = a_profile(stub, allow_loopback=False)
        outcome = trusting.send(prepared(profile), profile)

        assert isinstance(outcome, Refusal)
        assert outcome.reason is RefusalReason.ADDRESS_RANGE_BLOCKED

    #: Where the flag could actually be *set*. Prose is excluded deliberately: a `.md` file
    #: cannot set a flag, and the review documents discuss it by name, so including them
    #: would make this guard a list of documents rather than a control.
    SCANNED_SUFFIXES = (".py", ".ts", ".tsx", ".toml", ".sql", ".json", ".yaml", ".yml", ".sh")

    #: Build output is derived, not authored. `dist-*/` holds a bundle of `src/`, so an
    #: occurrence there is already reported against the source it came from.
    #: `.worktrees/` holds the batch-mode lane worktrees — gitignored scratch checkouts of
    #: this same repository, so scanning them double-counts every authored occurrence.
    SKIPPED_PARTS = ("__pycache__", ".git", ".venv", "node_modules", ".worktrees")

    #: Relative-path *prefixes* skipped as a whole subtree — distinct from `SKIPPED_PARTS`,
    #: which drops a file the instant any single part matches, anywhere in the path.
    #: `.claude/worktrees/` is the harness's own scratch checkouts of this repository
    #: (`EnterWorktree`'s default location; `[측정]` REVIEW-TASK-012 F1 found one at
    #: `.claude/worktrees/<name>/apps/domain/outbound.py` mid-review, unrelated to this
    #: task, and it turned this scan red — a nested worktree does not show up in
    #: `git status`, so the scan was reading content nothing in this repository's own
    #: history put there) and belongs excluded for the same double-counting reason as
    #: `.worktrees`. The rest of `.claude/` does not: `[측정]` REVIEW-TASK-012's
    #: re-review, O1: skipping all of `.claude` as a `SKIPPED_PARTS` entry silently
    #: stopped this scan from ever reaching `.claude/settings.json`, a tracked,
    #: scanned-suffix file — putting a whole directory in `SKIPPED_PARTS` is "skip
    #: every file under this name anywhere in the tree", which is too blunt for a
    #: directory this repository also keeps real, scanned content in.
    SKIPPED_PREFIXES = ((".claude", "worktrees"),)

    def test_no_source_or_add_on_in_the_repository_sets_it(self) -> None:
        """The flag exists for tests. If it ever appears elsewhere, this names the file.

        `[측정]` `ADVERSARIAL-REVIEW-2026-08-19-MUTATION.md` M1 measured what this used to
        miss. The scan was `EXPERIMENT_ROOT.rglob("*.py")`, so planting the flag in
        `addons/collector.naver.blog/addon.toml`, in `domain/migrations/0002_domain.sql`, in
        a `README.md`, or anywhere under the repository-root `tests/` was **GREEN** — and an
        `addon.toml` and a migration are two of the places it could most plausibly be set for
        real. `dashboard/src/api.ts` and `domain-view.tsx` had carried it all along,
        unscanned.

        Widened to the whole repository over the suffixes a flag can be set in, rather than
        to one more directory, because the previous shape's failure was that it named its
        subjects.

        `[측정]` Run from inside `.worktrees/<name>/apps/` (an M4/M2/M3/M5/M6 lane
        worktree), `REPO_ROOT` correctly resolves to that worktree's own root — but that
        root's *own* absolute path necessarily contains a `.worktrees` path segment (it
        lives inside the main checkout's `.worktrees/` directory). Checking
        `path.parts` — the *absolute* path — against `SKIPPED_PARTS` therefore excluded
        every file the scan found, from every worktree, unconditionally: `found` was
        always empty. `[정정, 2026-08-21, m7-fixwave, M-R3]` This did **not** pass
        vacuously — replayed with the bug reintroduced, this test's own positive
        control (`assert Path("apps/domain/outbound.py") in found`, below) failed
        loudly, because an empty `found` cannot contain that path. Only the *other*
        assertion (`set(found) <= permitted`) would have passed vacuously on its own —
        the positive control is exactly what stopped that vacuity from being silent,
        which is the property a positive control exists to have. Fixed by checking the
        parts of each file's path *relative to `REPO_ROOT`* instead, which is what
        `SKIPPED_PARTS` was always meant to filter (a nested `.worktrees/` *inside* the
        tree being scanned) and never depends on where that tree itself happens to sit
        on disk.
        """
        found = []
        for path in REPO_ROOT.rglob("*"):
            if not path.is_file() or path.suffix not in self.SCANNED_SUFFIXES:
                continue
            rel = path.relative_to(REPO_ROOT)
            if any(part in self.SKIPPED_PARTS for part in rel.parts):
                continue
            if any(rel.parts[: len(prefix)] == prefix for prefix in self.SKIPPED_PREFIXES):
                continue
            if any(part.startswith("dist") for part in rel.parts):
                continue
            if "allow_loopback" in path.read_text("utf-8", errors="ignore"):
                found.append(rel)
        found = sorted(found)
        permitted = {
            # P0's own tree, read-only and unchanged — still real files this scan finds.
            Path("experiments/integrated-p0/domain/outbound.py"),
            # Reads the flag back to an operator; never sets one. Added 2026-08-19 after
            # this guard caught the new file, which is what it is for — the entry is made
            # deliberately rather than the scan being widened.
            Path("experiments/integrated-p0/addon_host/api.py"),
            # The same, on the screen. Registered 2026-08-19 when the scan was widened past
            # `*.py`; both had held the name since the domain surface was written and
            # nothing had ever looked.
            Path("experiments/integrated-p0/dashboard/src/api.ts"),
            Path("experiments/integrated-p0/dashboard/src/domain-view.tsx"),
            Path("experiments/integrated-p0/tests/test_outbound_policy.py"),
            Path("experiments/integrated-p0/tests/test_outbound_transport.py"),
            # Sets it, deliberately: the operator-loop scenario reaches a loopback stub
            # through the production path, which is the same price EXP-003 fixed in
            # advance for the transport tests. Registered here rather than the scan being
            # widened, so the flag stays a thing someone had to write down.
            Path("experiments/integrated-p0/tests/test_operator_loop.py"),
            # M2 batch 2c's copy-adapted P1 tree — the same three roles, one level shallower
            # (``apps/`` rather than ``experiments/integrated-p0/``).
            Path("apps/domain/outbound.py"),
            Path("apps/tests/test_outbound_policy.py"),
            Path("apps/tests/test_outbound_transport.py"),
            # M2 batch 2d's domain API: the same read-only display role
            # ``experiments/integrated-p0/addon_host/api.py`` already holds above —
            # ``profile_view`` reads the flag back to an operator and never sets one.
            Path("apps/domain/api.py"),
            # M4x's Gap 1 (plain HTTP for loopback): the module docstring and
            # ``_refuse_http_off_loopback``'s own docstring explain the flag's role in the
            # transport-layer re-check; the flag is read (``profile.allow_loopback``), never
            # set, by this module.
            Path("apps/domain/transport.py"),
            # M5's P1 dashboard reaching this flag for the first time — the same read-only
            # display role ``experiments/integrated-p0/dashboard/src/api.ts`` already holds
            # above. ``allow_loopback: boolean`` is a response-type field the outbound
            # profile view renders back to an operator; the dashboard never constructs or
            # submits an outbound profile itself.
            Path("apps/dashboard/src/api/types.ts"),
            # TASK-012 (DP-035 D3). The idempotent row migration script sets it,
            # deliberately: it reads a registered row's stored ``allow_loopback`` grant and
            # replaces it with ``allow_fleet`` (see the sibling scan below for that flag's
            # own occurrence here). Registered rather than the scan being narrowed, the same
            # way ``test_operator_loop.py`` above was.
            Path("apps/scripts/migrate_fleet_source_rows.py"),
            # REVIEW-TASK-012 F4's repair: this script's own test fixtures carry an
            # ``allow_loopback: true`` loopback-shaped profile (the exact row shape the
            # script rewrites) and assert the flag is gone afterward.
            Path("apps/tests/test_migrate_fleet_source_rows.py"),
        }
        assert set(found) <= permitted, f"allow_loopback appeared in {set(found) - permitted}"
        # The control: the scan can find things. An empty result would satisfy the subset
        # assertion above just as well, and would mean the scan read nothing.
        assert Path("apps/domain/outbound.py") in found

    def test_the_scan_reaches_the_file_types_a_flag_could_be_set_in(self) -> None:
        """The control. A scan that matched nothing would pass the case above.

        Asserted per suffix rather than in total, because the defect M1 found was exactly a
        suffix the scan never opened.
        """
        reached = set()
        for path in REPO_ROOT.rglob("*"):
            if not path.is_file() or path.suffix not in self.SCANNED_SUFFIXES:
                continue
            rel = path.relative_to(REPO_ROOT)
            if any(part in self.SKIPPED_PARTS for part in rel.parts):
                continue
            if any(rel.parts[: len(prefix)] == prefix for prefix in self.SKIPPED_PREFIXES):
                continue
            reached.add(path.suffix)
        for required in (".py", ".toml", ".sql", ".ts", ".tsx"):
            assert required in reached, f"the scan opened no {required} file"


class TestFleetIsOnlyReachableByFlag:
    """DP-035 D1's second hole, scanned the same way `TestLoopbackIsOnlyReachableByFlag`
    scans `allow_loopback` above — same `SCANNED_SUFFIXES`/`SKIPPED_PARTS`/
    `SKIPPED_PREFIXES` discipline, the same positive control (the scan must find
    `apps/domain/outbound.py`).

    `allow_fleet`'s permitted set is smaller and newer than `allow_loopback`'s: this task's
    own code and tests, plus DP-035 D3's two named exceptions —
    `collector.trendradar.rest/addon.toml` and `collector.tubedepth.rest/addon.toml` —
    which document, in a `#` comment, the grant their operator-approved source rows must
    carry. Never a `[declares]` key: DP-035 D4 is exactly the reason (`addon_api.manifest`'s
    parser ignores an unknown `[declares]` key silently, so the grant lives in the row and
    not in the manifest). Because the set is exhaustively known rather than merely bounded,
    this asserts equality rather than the containing scan's subset — "those two paths and
    no more".
    """

    SCANNED_SUFFIXES = (".py", ".ts", ".tsx", ".toml", ".sql", ".json", ".yaml", ".yml", ".sh")
    #: Same discipline as `TestLoopbackIsOnlyReachableByFlag.SKIPPED_PARTS` above.
    SKIPPED_PARTS = ("__pycache__", ".git", ".venv", "node_modules", ".worktrees")
    #: Same discipline as `TestLoopbackIsOnlyReachableByFlag.SKIPPED_PREFIXES` above
    #: (REVIEW-TASK-012 F1, then narrowed by O1 in the same review's re-pass): only
    #: `.claude/worktrees/` is harness scratch; `.claude/settings.json` and the rest of
    #: `.claude/` stay scanned.
    SKIPPED_PREFIXES = ((".claude", "worktrees"),)

    def test_the_flag_appears_in_exactly_this_tasks_code_tests_and_two_named_manifests(
        self,
    ) -> None:
        found = []
        for path in REPO_ROOT.rglob("*"):
            if not path.is_file() or path.suffix not in self.SCANNED_SUFFIXES:
                continue
            rel = path.relative_to(REPO_ROOT)
            if any(part in self.SKIPPED_PARTS for part in rel.parts):
                continue
            if any(rel.parts[: len(prefix)] == prefix for prefix in self.SKIPPED_PREFIXES):
                continue
            if any(part.startswith("dist") for part in rel.parts):
                continue
            if "allow_fleet" in path.read_text("utf-8", errors="ignore"):
                found.append(rel)
        found = sorted(found)
        permitted = {
            Path("apps/domain/outbound.py"),
            Path("apps/domain/transport.py"),
            Path("apps/tests/test_outbound_policy.py"),
            Path("apps/tests/test_outbound_transport.py"),
            # DP-035 D3's own named exceptions.
            Path("apps/addons/collector.trendradar.rest/addon.toml"),
            Path("apps/addons/collector.tubedepth.rest/addon.toml"),
            # This task's own idempotent row migration script: it writes the flag into a
            # registered row's stored profile, which is the mechanism DP-035 D3 names for
            # the cutover — not an accidental occurrence, so it belongs in the permitted
            # set rather than being caught as one.
            Path("apps/scripts/migrate_fleet_source_rows.py"),
            # REVIEW-TASK-012 F4's repair: this script's own committed tests, whose
            # fixtures and assertions name the flag directly (`allow_fleet=True` in a
            # migrated profile, `FLEET_TARGETS`, `fleet_hostname_for`'s own tests).
            Path("apps/tests/test_migrate_fleet_source_rows.py"),
        }
        assert set(found) == permitted, (
            f"unexpected occurrences: {set(found) - permitted}; "
            f"missing expected occurrences: {permitted - set(found)}"
        )
        # The control: the scan can find things. An empty result on both sides would
        # satisfy the equality assertion above just as well as a correct one.
        assert Path("apps/domain/outbound.py") in found

    def test_the_scan_reaches_the_file_types_a_flag_could_be_set_in(self) -> None:
        """The control. A scan that matched nothing would pass the case above."""
        reached = set()
        for path in REPO_ROOT.rglob("*"):
            if not path.is_file() or path.suffix not in self.SCANNED_SUFFIXES:
                continue
            rel = path.relative_to(REPO_ROOT)
            if any(part in self.SKIPPED_PARTS for part in rel.parts):
                continue
            if any(rel.parts[: len(prefix)] == prefix for prefix in self.SKIPPED_PREFIXES):
                continue
            reached.add(path.suffix)
        for required in (".py", ".toml"):
            assert required in reached, f"the scan opened no {required} file"


# --------------------------------------------------------------------------- #
# DP-020 — a POST with a body, over a real socket
# --------------------------------------------------------------------------- #


TREND_BODY = json.dumps(
    {
        "startDate": "2026-08-01",
        "endDate": "2026-08-07",
        "timeUnit": "date",
        "keywordGroups": [{"groupName": "수분크림", "keywords": ["수분크림"]}],
    },
    ensure_ascii=False,
).encode("utf-8")


def a_trend_profile(port: int, **overrides: Any) -> OutboundProfile:
    values: dict[str, Any] = {
        "hosts": ["localhost"],
        "endpoints": {"trend": {"path": "/search-trend/v1/search", "method": "POST"}},
        "port": port,
        "allow_loopback": True,
    }
    values.update(overrides)
    read = OutboundProfile.from_row(values)
    assert read is not None
    return read


class TestAPostWithABody:
    """DP-020, over a socket. `_hop` sent `"GET"` hardcoded until 2026-08-18, so two of the
    three selected Naver endpoints were unreachable by construction."""

    def test_the_body_the_add_on_composed_is_what_the_server_received(
        self, stub: int, trusting: SocketTransport
    ) -> None:
        StubHandler.seen_bodies.clear()
        profile = a_trend_profile(stub)
        request = resolve("trend", profile, body=TREND_BODY)
        assert not isinstance(request, Refusal), request

        outcome = trusting.send(request, profile)

        assert not isinstance(outcome, Refusal), outcome
        assert StubHandler.seen_bodies[-1] == TREND_BODY

    def test_the_response_comes_back_parsed_as_the_datalab_shape(
        self, stub: int, trusting: SocketTransport
    ) -> None:
        """The positive control: the request was not merely delivered, it was understood."""
        profile = a_trend_profile(stub)
        request = resolve("trend", profile, body=TREND_BODY)
        assert not isinstance(request, Refusal)

        outcome = trusting.send(request, profile)

        assert not isinstance(outcome, Refusal)
        assert outcome.status == 200
        body = json.loads(outcome.body)
        assert body["results"][0]["title"] == "수분크림"
        assert body["results"][0]["data"][0]["ratio"] == 100.0

    def test_the_platform_sets_the_media_type(
        self, stub: int, trusting: SocketTransport
    ) -> None:
        """DP-020 D5. The stub answers `400` on any other media type, so this asserts the
        header was sent rather than asserting it was constructed."""
        profile = a_trend_profile(stub)
        request = resolve("trend", profile, body=TREND_BODY)
        assert not isinstance(request, Refusal)

        outcome = trusting.send(request, profile)

        assert not isinstance(outcome, Refusal)
        assert outcome.status == 200

    def test_a_get_endpoint_still_sends_no_body(
        self, stub: int, trusting: SocketTransport
    ) -> None:
        """The control on the other side. A transport that had started sending bodies to
        everything would still pass every assertion above.

        `[측정]` This was itself vacuous until 2026-08-19: the stub recorded bodies only in
        `do_POST`, so no GET could ever have added one. `do_GET` now reads and records, and
        the case below is the control proving the recorder works on this path.
        """
        StubHandler.seen_bodies.clear()
        profile = a_profile(stub)

        outcome = trusting.send(prepared(profile), profile)

        assert not isinstance(outcome, Refusal)
        assert StubHandler.seen_bodies == []

    def test_the_stub_would_have_noticed_a_body_on_a_get(
        self, stub: int, trusting: SocketTransport
    ) -> None:
        """The recorder's own control. Sends a GET carrying a body directly — bypassing
        `resolve`, which refuses one — so that the emptiness asserted above is an emptiness
        the stub was capable of disturbing."""
        StubHandler.seen_bodies.clear()
        profile = a_profile(stub)
        request = prepared(profile)
        smuggled = replace(request, body=b"sneak")

        trusting.send(smuggled, profile)

        assert StubHandler.seen_bodies == [b"sneak"]

    def test_a_post_is_bounded_by_the_same_request_budget(
        self, stub: int, trusting: SocketTransport
    ) -> None:
        """F5's deadline is not a GET-only property. A `POST` to a drip-feeding server has
        to end at the budget too."""
        profile = a_trend_profile(
            stub, endpoints={"drip": {"path": "/v1/drip", "method": "POST"}}
        )
        request = resolve("drip", profile, body=b"{}")
        assert not isinstance(request, Refusal)
        bounds = TransportLimits(
            read_timeout_s=SHORT_READ_TIMEOUT, max_request_seconds=SHORT_REQUEST_BUDGET
        )

        started = time.monotonic()
        with pytest.raises(TransportUnavailable):
            trusting.send(request, profile, limits=bounds)

        assert time.monotonic() - started < SHORT_REQUEST_BUDGET * 4


class TestTheRequestWriteIsUnderTheDeadlineToo:
    """`ADVERSARIAL-REVIEW-2026-08-19.md` F1, second half.

    `[측정]` F5 put a monotonic deadline across the whole request and this module's docstring
    said so. It bounded the connection attempts and every read — and not the **write**,
    because `_arm` was called *after* `connection.request(...)`. The reviewer measured a
    `send()` occupying **18.83s against a 0.5s budget**, which is F5's own shape (occupancy
    linear in the payload) reappearing on the side F5 never covered.

    The two halves are one finding: a large body is what makes the write slow, and the byte
    bound that was supposed to prevent one counted the wrong quantity. Both are fixed, and
    this is the half a socket can show.
    """

    def test_the_deadline_is_armed_before_any_byte_of_the_request_is_written(
        self, stub: int, trusting: SocketTransport
    ) -> None:
        """Ordering, recorded as a sequence rather than as a presence.

        `[측정]` A first version of this asserted only that the socket timeout was re-armed,
        and it **passed against the defect** — `_connect` arms the socket too, so "was
        `settimeout` called" is true either way. What failed was an *order*, so the order is
        what is recorded: every `settimeout` and the moment the request is written, in the
        sequence they happened.
        """
        profile = a_trend_profile(stub)
        request = resolve("trend", profile, body=TREND_BODY)
        assert not isinstance(request, Refusal)
        events: list[str] = []

        original_connect = SocketTransport._connect

        def watching(self: Any, req: Any, addresses: Any, bounds: Any) -> Any:
            connection = original_connect(self, req, addresses, bounds)
            sock = connection.sock
            assert sock is not None
            settimeout = sock.settimeout
            send_request = connection.request

            def record_timeout(value: float | None) -> None:
                events.append("arm")
                settimeout(value)

            def record_request(*args: Any, **kwargs: Any) -> Any:
                events.append("write")
                return send_request(*args, **kwargs)

            sock.settimeout = record_timeout  # type: ignore[method-assign]
            connection.request = record_request  # type: ignore[method-assign]
            return connection

        SocketTransport._connect = watching  # type: ignore[method-assign, assignment]
        try:
            trusting.send(request, profile, limits=TransportLimits(max_request_seconds=30.0))
        finally:
            SocketTransport._connect = original_connect  # type: ignore[method-assign]

        assert "write" in events, "the request was never written"
        assert events.index("arm") < events.index("write"), (
            f"the deadline was armed after the write: {events}"
        )

    def test_a_post_to_a_server_that_will_not_drain_ends_at_the_budget(
        self, stub: int, trusting: SocketTransport
    ) -> None:
        """The wall-clock half, against a server that accepts the connection and then stops
        reading. Without the write under the deadline, this blocks in the kernel's send
        buffer until the connect-time timeout, which is a different and larger number."""
        profile = a_trend_profile(
            stub,
            endpoints={"stall": {"path": "/v1/stall", "method": "POST"}},
            # Granted deliberately: what this case measures is how long a *permitted* body
            # may occupy the worker, which is a different bound from how large it may be.
            limits={**DEFAULT_LIMITS, "max_request_bytes": 8_000_000},
        )
        request = resolve("stall", profile, body=b"x" * 4_000_000)
        assert not isinstance(request, Refusal), request
        bounds = TransportLimits(
            connect_timeout_s=10.0,
            read_timeout_s=10.0,
            max_request_seconds=SHORT_REQUEST_BUDGET,
        )

        started = time.monotonic()
        with pytest.raises(TransportUnavailable):
            trusting.send(request, profile, limits=bounds)
        elapsed = time.monotonic() - started

        assert elapsed < SHORT_REQUEST_BUDGET * 8, f"the write ran for {elapsed:.1f}s"

    def test_an_ordinary_post_is_unaffected(
        self, stub: int, trusting: SocketTransport
    ) -> None:
        """The positive control. A deadline armed too aggressively would refuse every POST,
        and both assertions above would still pass."""
        profile = a_trend_profile(stub)
        request = resolve("trend", profile, body=TREND_BODY)
        assert not isinstance(request, Refusal)

        outcome = trusting.send(request, profile, limits=TransportLimits())

        assert not isinstance(outcome, Refusal)
        assert outcome.status == 200


# --------------------------------------------------------------------------- #
# M4x gap 1 — plain HTTP, granted only to a destination the transport itself
# resolved and checked as loopback.
# --------------------------------------------------------------------------- #


class TestPlainHttpForLoopback:
    """The transport-time half of the belt-and-suspenders rule.
    `tests/test_outbound_policy.py::TestScheme` holds the other half —
    `domain.outbound.resolve` refusing `scheme="http"` for a profile with no
    `allow_loopback`. This class is that flag's counterpart to
    `TestLoopbackIsOnlyReachableByFlag` above: a positive control that plain HTTP to a
    real loopback server actually works, and the refusal it would otherwise pass
    vacuously against.
    """

    def test_loopback_http_reaches_a_real_plain_server(self, http_stub: int) -> None:
        profile = a_loopback_http_profile(http_stub)
        request = resolve("items", profile)
        assert isinstance(request, PreparedRequest)
        assert request.scheme == "http"
        assert request.url.startswith("http://")

        response = SocketTransport().send(request, profile)

        assert not isinstance(response, Refusal), response
        assert response.status == 200
        assert json.loads(response.body)["next"] == 3

    def test_a_protected_header_is_still_stripped_over_plain_http(
        self, http_stub: int
    ) -> None:
        """The credential-hygiene guarantee does not depend on TLS being the transport;
        `strip_protected_headers` runs on every response regardless of scheme."""
        profile = a_loopback_http_profile(http_stub)
        request = resolve("items", profile)
        assert isinstance(request, PreparedRequest)

        response = SocketTransport().send(request, profile)

        assert not isinstance(response, Refusal)
        assert not any(k.lower() == "set-cookie" for k in response.headers)

    def test_a_non_loopback_address_is_refused_by_the_transport_even_if_the_profile_says_yes(
        self,
    ) -> None:
        """The belt this gap adds. `allow_loopback = True` on the profile is a claim the
        profile makes before any name is resolved; this checks it against the address
        `resolve_addresses` actually returned, for a hand-built request that bypasses
        `domain.outbound.resolve` the same way `test_the_stub_would_have_noticed_a_body_
        on_a_get` above bypasses it to reach the transport directly. No network I/O:
        `93.184.216.34` is a literal address, so `getaddrinfo` resolves it locally and the
        refusal fires before any connection is attempted.
        """
        profile = a_loopback_http_profile(80, hosts=["93.184.216.34"])
        request = PreparedRequest(
            url="http://93.184.216.34:80/v1/items",
            host="93.184.216.34",
            port=80,
            endpoint_ref="items",
            scheme="http",
        )

        outcome = SocketTransport().send(request, profile)

        assert isinstance(outcome, Refusal)
        assert outcome.reason is RefusalReason.SCHEME_NOT_ALLOWED

    def test_https_to_the_same_kind_of_loopback_target_is_unaffected(
        self, stub: int, trusting: SocketTransport
    ) -> None:
        """The control for the whole gap: the existing TLS stub and fixture, untouched by
        anything above, still round-trip exactly as `TestARealRoundTrip` already proves."""
        profile = a_profile(stub)
        response = trusting.send(prepared(profile), profile)

        assert not isinstance(response, Refusal)
        assert response.status == 200


# --------------------------------------------------------------------------- #
# DP-035 D1 — the transport-time half of the fleet scope.
# --------------------------------------------------------------------------- #


def _http_request(scope: str, host: str = "example") -> PreparedRequest:
    """A hand-built plain-HTTP request carrying `scope`, bypassing `resolve` the same way
    `TestPlainHttpForLoopback.test_a_non_loopback_address_is_refused_by_the_transport_
    even_if_the_profile_says_yes` already does — so this can supply an address list
    directly rather than needing a real listener to answer one."""
    return PreparedRequest(
        url=f"http://{host}/v1/items",
        host=host,
        port=80,
        endpoint_ref="items",
        scheme="http",
        plain_http_scope=scope,
    )


class TestFleetScopePlainHttpReCheck:
    """DP-035 D1's transport-time half, unit-tested against supplied address lists rather
    than through a stub. A private fleet address cannot be stood up as a reachable stub on
    this machine the way a loopback one can (`TestPlainHttpForLoopback` above uses a real
    `http_stub`), so this calls `_refuse_http_off_loopback` directly — the same function
    `SocketTransport.send` calls, with no socket involved either way.
    """

    def test_a_fleet_admissible_address_is_permitted_under_fleet_scope(self) -> None:
        outcome = _refuse_http_off_loopback(_http_request("fleet"), ["10.0.0.5"])
        assert outcome is None

    def test_loopback_is_still_permitted_under_fleet_scope(self) -> None:
        """Fleet scope widens rather than replaces: loopback stays admissible too, since a
        fleet-scoped profile's own address rule already admits it."""
        outcome = _refuse_http_off_loopback(_http_request("fleet"), ["127.0.0.1"])
        assert outcome is None

    @pytest.mark.parametrize(
        "address", ["169.254.169.254", "224.0.0.1", "240.0.0.1", "0.0.0.0"]
    )
    def test_a_blocked_range_is_refused_even_under_fleet_scope(self, address: str) -> None:
        outcome = _refuse_http_off_loopback(_http_request("fleet"), [address])
        assert isinstance(outcome, Refusal), address
        assert outcome.reason is RefusalReason.SCHEME_NOT_ALLOWED

    def test_a_fleet_address_is_refused_under_loopback_scope(self) -> None:
        """The regression the packet names: a private address is still refused when the
        request's own `plain_http_scope` is `"loopback"`, whatever the profile that built
        it claimed — `resolve` is what decides the scope once, and nothing here re-derives
        a wider one from a profile it never sees."""
        outcome = _refuse_http_off_loopback(_http_request("loopback"), ["10.0.0.5"])
        assert isinstance(outcome, Refusal)
        assert outcome.reason is RefusalReason.SCHEME_NOT_ALLOWED

    def test_loopback_is_still_permitted_under_loopback_scope(self) -> None:
        """The positive control for the case above: loopback scope is not simply broken by
        this class's own setup."""
        outcome = _refuse_http_off_loopback(_http_request("loopback"), ["127.0.0.1"])
        assert outcome is None

    def test_something_that_is_not_an_address_is_refused_under_fleet_scope_too(self) -> None:
        outcome = _refuse_http_off_loopback(_http_request("fleet"), ["not-an-ip"])
        assert isinstance(outcome, Refusal)
        assert outcome.reason is RefusalReason.ADDRESS_RANGE_BLOCKED
