"""The socket half of the outbound guard: one hop, bounded, connected where it was checked.

Copy-adapted from ``experiments/integrated-p0/domain/transport.py`` (M2 batch 2c),
verbatim — nothing here touches the database or a schema, and its only local import
(``domain.outbound``) resolves the same way in this tree. Deadline semantics, the
one-hop/no-redirect-follow rule, and the read/write bound sequencing are unchanged.

`domain.outbound` is deliberately decidable without a socket — every rule there is a
function of a URL, a profile, and a list of addresses. This module is what is left over:
a name to resolve, a connection to make, bytes to read, and a clock to run out. It is
separate for the reason `outbound` states, which is that a policy testable only against a
live network is a policy nobody re-tests.

Three properties are this module's and not `outbound`'s.

**It connects to the address it checked.** `getaddrinfo` runs once, every address it
returned is put through :func:`~domain.outbound.check_resolved_addresses`, and the socket
is opened to one of *those* addresses with the approved hostname carried separately for
TLS and for `Host`. Checking a name and then connecting by name is a rebinding hole: the
second lookup can answer differently from the first, and nothing in a passing test would
show it.

**It follows no redirect.** One call is one hop. A `3xx` comes back with its `Location`
unfollowed, because revalidating a redirect is `outbound.check_redirect`'s and a transport
that quietly followed one would be a second, looser policy nobody wrote down.

**It stops.** One monotonic deadline bounds every connection attempt, the request write, and
every read; the size limit is enforced while reading rather than after. So `SEC-004`'s
"oversized/slow response는 bounded failure로 종료되고 worker를 무기한 점유하지 않는다" holds
against a server that never stops **sending**, one that never **starts**, and one that will
not **receive**.

`[측정]` All three halves were false at some point and the history is worth reading before
changing anything here. `ADVERSARIAL-REVIEW-2026-08-18.md` F5: the bound was a socket timeout,
which bounds each `recv`, while `_read_bounded` called `read(n)`, which blocks until *n* bytes
arrive — occupancy **linear in `max_response_bytes`**, about 38 days against `DEFAULT_LIMITS`.
`ADVERSARIAL-REVIEW-2026-08-19.md` F1: the deadline was armed *after*
`connection.request(...)`, so the write ran under the connect-time timeout alone — a `send()`
occupying 18.83s against a 0.5s budget. A bound that scales with the thing it bounds is not a
bound, and a bound that covers three of a request's four phases is not one either.

`[측정]` Two more multipliers sat on top of F5's and both are gone with it: `_connect`
applied `connect_timeout_s` per address, and the caller's redirect loop gave each hop its own
full read.

The TLS context is a constructor argument whose default is `ssl.create_default_context()`.
That is how a test reaches a stub with its own certificate authority without any source
row, profile field, or environment variable being able to widen the policy — a
*per-process* trust anchor rather than a *per-source* one. `tests/test_outbound_transport.py`
holds the positive control: the same stub under the default context fails to verify.

**M4x, plain HTTP — the second half of the belt-and-suspenders rule.** `domain.outbound`
grants `request.scheme == "http"` only when the profile set `allow_loopback` or
`allow_fleet` (DP-035 D1), and that grant is stated before a socket ever opens. It cannot
be the whole rule: both flags are things a profile *states*, and the address it is
actually about to connect to is only known after `resolve_addresses` runs — the same DNS
gap `outbound.py`'s own docstring names for `check_resolved_addresses`. So this module
holds the second check: before it will open a plain-HTTP connection, every address `send`
resolved must itself be loopback (loopback scope) or loopback-or-fleet-admissible (fleet
scope), regardless of what the profile claims. Which scope applies is read off
`request.plain_http_scope` — decided once by `resolve` and never re-derived here from the
profile's flags, so this module cannot end up disagreeing with the decision that granted
`"http"` in the first place. A name that answered loopback once and something else the
second time is exactly the rebinding hole this module's own opening paragraph already
refuses to create for TLS; the same connect-to-what-was-checked discipline applies here
without a certificate to fall back on.
"""

from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, Final, Protocol

from domain.outbound import (
    DEFAULT_LIMITS,
    OutboundProfile,
    PreparedRequest,
    Refusal,
    RefusalReason,
    check_resolved_addresses,
    is_fleet_admissible,
    strip_protected_headers,
)

__all__ = [
    "SocketTransport",
    "Transport",
    "TransportLimits",
    "TransportResponse",
    "TransportUnavailable",
    "resolve_addresses",
]


class TransportUnavailable(Exception):
    """The request could not be completed. Not a policy refusal — a failed attempt.

    Kept apart from `Refusal` because they retry differently and an operator acts on
    them differently. A refusal means the request was never allowed and never will be
    until configuration changes; this means the network, the name service, or the far
    end did not cooperate this time.
    """

    def __init__(self, summary: str, detail: Mapping[str, Any] | None = None) -> None:
        super().__init__(summary)
        self.summary = summary
        self.detail: Mapping[str, Any] = dict(detail or {})


@dataclass(frozen=True)
class TransportLimits:
    """What bounds this one hop.

    Plain numbers rather than `addon_api.Limits`: `tests/environment/test_addon_layer_direction.py`
    forbids `domain` from importing `addon_api`, and that rule is the reason Raw persistence
    does not move when the add-on contract version does. `addon_host` translates.
    """

    connect_timeout_s: float = float(DEFAULT_LIMITS["connect_timeout_s"])
    read_timeout_s: float = float(DEFAULT_LIMITS["read_timeout_s"])
    max_response_bytes: int = int(DEFAULT_LIMITS["max_response_bytes"])
    max_request_seconds: float = float(DEFAULT_LIMITS["max_request_seconds"])

    #: The instant, on `time.monotonic`'s clock, by which this request must be over.
    #:
    #: An absolute instant rather than a duration, because the caller may be spending one
    #: budget across several hops: `addon_host.capabilities` pins this before the first
    #: request and hands the same value to every redirect, so the chain cannot cost
    #: `max_redirects + 1` times the bound. `None` means "start the budget now", which is
    #: what a single-hop caller wants and what `starting_now` supplies.
    #:
    #: Monotonic, so a system clock adjustment mid-request cannot extend or collapse it.
    deadline: float | None = None

    @classmethod
    def from_profile(cls, profile: OutboundProfile) -> TransportLimits:
        limits = {**DEFAULT_LIMITS, **profile.limits}
        return cls(
            connect_timeout_s=float(limits["connect_timeout_s"]),
            read_timeout_s=float(limits["read_timeout_s"]),
            max_response_bytes=int(limits["max_response_bytes"]),
            max_request_seconds=float(limits["max_request_seconds"]),
        )

    def starting_now(self) -> TransportLimits:
        """The same bounds with the deadline pinned, unless a caller already pinned one.

        Idempotent on purpose: a caller spending one budget over several hops calls this
        once and passes the result down, and a hop calling it again must not be handed a
        fresh budget — which is exactly the multiplier F5 measured.
        """
        if self.deadline is not None:
            return self
        return replace(self, deadline=time.monotonic() + self.max_request_seconds)

    def remaining(self) -> float:
        """Seconds left, or a negative number once the budget is spent."""
        assert self.deadline is not None, "the budget was never started"
        return self.deadline - time.monotonic()


@dataclass(frozen=True)
class TransportResponse:
    """One hop's result. Headers already stripped, body already bounded.

    `location` is lifted out of the headers rather than left for the caller to find, so
    that "was this a redirect" is answered the same way every time. It is carried
    unvalidated on purpose: validating it is `outbound.check_redirect`'s, and a transport
    that pre-screened it would be deciding policy.
    """

    status: int
    headers: Mapping[str, str]
    body: bytes
    location: str | None = None
    addresses: tuple[str, ...] = field(default_factory=tuple)


class Transport(Protocol):
    """One hop. Returns a response, refuses by rule, or raises because it could not.

    A protocol because the capability layer must be testable without a network, and
    because the thing being tested there — buffering, atomicity, the count cross-check —
    is not this.
    """

    def send(
        self,
        request: PreparedRequest,
        profile: OutboundProfile,
        headers: Mapping[str, str] | None = None,
        limits: TransportLimits | None = None,
    ) -> TransportResponse | Refusal: ...


def resolve_addresses(host: str, port: int) -> tuple[str, ...]:
    """Every address `host` resolves to right now, as strings.

    Separate from the check so a test can supply addresses the local resolver would
    never return — which is the only way to exercise the blocked ranges without owning
    a domain that points at them.
    """
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as error:
        raise TransportUnavailable(
            f"{host!r} could not be resolved", {"host": host}
        ) from error
    return tuple(dict.fromkeys(str(info[4][0]) for info in infos))


#: Read in pieces so the size limit can stop a body mid-flight. Small enough that an
#: 8 MiB limit is not overshot by a meaningful amount, large enough not to syscall per row.
_CHUNK: Final = 64 * 1024


def _refuse_http_off_loopback(
    request: PreparedRequest, addresses: Sequence[str]
) -> Refusal | None:
    """The transport-time half of the plain-HTTP rule. `None` means proceed.

    `domain.outbound.resolve` already refused a plain-HTTP request unless the profile set
    `allow_loopback` or `allow_fleet` — but that is a claim about the profile, made before
    any name was resolved. This is the claim checked against what `getaddrinfo` actually
    returned, which is the only place either half of the belt-and-suspenders rule can be
    checked against reality: `check_resolved_addresses` runs immediately before this and
    already requires the matching flag for any address in it that is loopback or
    fleet-admissible, but an address outside both classes is never blocked by that rule at
    all when it is public (`p0-security.md` blocks *private* ranges, not every non-loopback
    host) — so without this, a source with `allow_loopback = true` (or `allow_fleet =
    true`) and `scheme = "http"` in its profile could ask for a request to a hostname
    resolving anywhere public, and there would be no `SocketTransport`-level check left to
    refuse it.

    Which range is admissible here is `request.plain_http_scope`, not the profile's flags
    directly: `resolve` already decided `"fleet"` iff the profile set `allow_fleet`, and
    re-reading the flags here instead would let this function's decision drift from that
    one. Loopback scope requires every address to be loopback, unchanged from before DP-035;
    fleet scope requires every address to be loopback *or* fleet-admissible, since a
    fleet-scoped profile's own address rule already admits loopback as well (the flags are
    a widening, not a swap).
    """
    for raw in addresses:
        try:
            address = ipaddress.ip_address(raw)
        except ValueError:
            return Refusal(
                RefusalReason.ADDRESS_RANGE_BLOCKED,
                f"{request.host!r} resolved to something that is not an IP address",
                {"host": request.host},
            )
        if address.is_loopback:
            continue
        if request.plain_http_scope == "fleet" and is_fleet_admissible(address):
            continue
        return Refusal(
            RefusalReason.SCHEME_NOT_ALLOWED,
            f"plain HTTP was refused for {request.endpoint_ref!r}: {request.host!r} "
            f"resolved to {address!s}, which is not loopback"
            + (" or fleet-admissible" if request.plain_http_scope == "fleet" else ""),
            {"endpoint_ref": request.endpoint_ref, "host": request.host,
             "address": str(address)},
        )
    return None


class SocketTransport:
    """The real one. HTTPS by default, one hop, and it never looks a name up twice.

    Plain HTTP is the one exception, and only when `request.scheme == "http"` — which
    `domain.outbound.resolve` sets only for a profile that declared `allow_loopback` or
    `allow_fleet`, and which `send` re-checks (against `request.plain_http_scope`) against
    the addresses this module itself resolved before it ever reaches `_connect`. Every
    other property this docstring already claimed is unchanged for that path: one hop, no
    redirect followed, one deadline for the whole request.
    """

    def __init__(self, context: ssl.SSLContext | None = None) -> None:
        self._context = context or ssl.create_default_context()

    def send(
        self,
        request: PreparedRequest,
        profile: OutboundProfile,
        headers: Mapping[str, str] | None = None,
        limits: TransportLimits | None = None,
    ) -> TransportResponse | Refusal:
        bounds = (limits or TransportLimits.from_profile(profile)).starting_now()
        addresses = resolve_addresses(request.host, request.port)
        if not addresses:
            raise TransportUnavailable(
                f"{request.host!r} resolved to no address", {"host": request.host}
            )
        refusal = check_resolved_addresses(request.host, addresses, profile)
        if refusal is not None:
            return refusal
        if request.scheme == "http":
            refusal = _refuse_http_off_loopback(request, addresses)
            if refusal is not None:
                return refusal
        return self._hop(request, addresses, headers or {}, bounds)

    def _hop(
        self,
        request: PreparedRequest,
        addresses: Sequence[str],
        headers: Mapping[str, str],
        bounds: TransportLimits,
    ) -> TransportResponse | Refusal:
        connection = self._connect(request, addresses, bounds)
        try:
            # `Host` is set from the approved hostname because the socket was opened to
            # an address: without this the request would announce the IP it dialled and
            # a name-based virtual host would answer the wrong site.
            sent = {"Host": request.host, "Accept-Encoding": "identity", **dict(headers)}
            if request.body is not None:
                # DP-020 D5. The platform names the media type; the add-on supplies bytes
                # and never a `Content-Type`, so one source cannot claim an encoding the
                # guard has no rule for. `Content-Length` is `http.client`'s.
                sent["Content-Type"] = "application/json"
            # Armed **before** the write, not after. `ADVERSARIAL-REVIEW-2026-08-19.md` F1:
            # this call used to follow `connection.request(...)`, so sending the body ran
            # under the connect-time socket timeout and not the deadline — a `send()`
            # occupying 18.83s against a 0.5s budget. A server that accepts a connection and
            # then stops reading blocks the write in the kernel's send buffer, which is the
            # write-side twin of the read-side stall F5 removed.
            _arm(connection.sock, bounds, request)
            # The method is `request.method` and not a literal, which is the whole of
            # DP-020 D1 at this layer: it came from the operator-approved profile, through
            # `outbound.resolve`, and no add-on input reaches it.
            connection.request(request.method, _path_of(request.url), body=request.body,
                               headers=sent)
            # Re-armed after the write, because the read is a fresh wait against the same
            # deadline and the write may have spent most of it.
            _arm(connection.sock, bounds, request)
            response = connection.getresponse()
            body, overflowed = _read_bounded(
                response, bounds.max_response_bytes, connection.sock, bounds, request
            )
            if overflowed:
                return Refusal(
                    RefusalReason.RESPONSE_TOO_LARGE,
                    f"the response exceeded {bounds.max_response_bytes} bytes and was abandoned",
                    {"endpoint_ref": request.endpoint_ref, "limit": bounds.max_response_bytes},
                )
            return TransportResponse(
                status=response.status,
                headers=strip_protected_headers(dict(response.getheaders())),
                body=body,
                location=response.getheader("Location"),
                addresses=tuple(addresses),
            )
        except (TimeoutError, OSError, http.client.HTTPException) as error:
            raise TransportUnavailable(
                f"the request to {request.endpoint_ref!r} did not complete",
                {"endpoint_ref": request.endpoint_ref, "cause": type(error).__name__},
            ) from error
        finally:
            connection.close()

    def _connect(
        self, request: PreparedRequest, addresses: Sequence[str], bounds: TransportLimits
    ) -> http.client.HTTPSConnection | http.client.HTTPConnection:
        """Open a socket to a checked address, with TLS verified against the approved name
        — or, for the loopback-only exception M4x adds, no TLS at all.

        The socket is built here and handed to the connection already wrapped (or, for
        plain HTTP, already connected), rather than letting the connection dial: letting
        `HTTPSConnection` dial would use one string for the address, the SNI, and the
        `Host` header, and those are the same value only when no address check happened.
        Assigning `.sock` is what makes either connection class skip its own `connect()`.

        `request.scheme` reaching here at all means `send` already ran both belts:
        `domain.outbound.resolve` granted `"http"` only alongside the profile's
        `allow_loopback` or `allow_fleet`, and `_refuse_http_off_loopback` has already
        confirmed every address in `addresses` is admissible for the scope that grant
        chose. Nothing here re-decides that policy — it only chooses which connection
        class to build.
        """
        plain = request.scheme == "http"
        last: Exception | None = None
        for address in addresses:
            # Per address, so a name resolving to several unreachable addresses used to
            # cost `connect_timeout_s` each. The budget is the whole request's, so the
            # second address gets whatever the first one left. F5 names this multiplier.
            remaining = bounds.remaining()
            if remaining <= 0:
                raise TransportUnavailable(
                    f"the request to {request.endpoint_ref!r} ran out of time before a "
                    "connection was open",
                    {"endpoint_ref": request.endpoint_ref, "budget_s": bounds.max_request_seconds},
                ) from last
            raw: socket.socket | None = None
            try:
                raw = socket.create_connection(
                    (address, request.port), timeout=min(bounds.connect_timeout_s, remaining)
                )
                if plain:
                    sock: socket.socket = raw
                else:
                    sock = self._context.wrap_socket(raw, server_hostname=request.host)
                sock.settimeout(bounds.read_timeout_s)
            except (TimeoutError, OSError, ssl.SSLError) as error:
                last = error
                if raw is not None:
                    raw.close()
                continue
            if plain:
                http_connection: http.client.HTTPSConnection | http.client.HTTPConnection = (
                    http.client.HTTPConnection(
                        request.host, request.port, timeout=bounds.read_timeout_s
                    )
                )
            else:
                http_connection = http.client.HTTPSConnection(
                    request.host, request.port, timeout=bounds.read_timeout_s,
                    context=self._context,
                )
            http_connection.sock = sock
            return http_connection
        raise TransportUnavailable(
            f"no checked address for {request.host!r} accepted a connection",
            {"host": request.host, "addresses": list(addresses),
             "cause": type(last).__name__ if last else None},
        ) from last


def _arm(
    sock: socket.socket | None, bounds: TransportLimits, request: PreparedRequest
) -> None:
    """Point the socket at whichever comes first, the read timeout or the deadline.

    Called before every blocking step rather than once at connect time. A socket timeout
    set once bounds each `recv`, which is precisely the bound
    `ADVERSARIAL-REVIEW-2026-08-18.md` F5 showed a drip-feeding server walks straight
    through; re-arming means no single wait can outlast the request's whole budget.
    """
    remaining = bounds.remaining()
    if remaining <= 0:
        raise TransportUnavailable(
            f"the request to {request.endpoint_ref!r} exceeded its {bounds.max_request_seconds}s "
            "budget",
            {"endpoint_ref": request.endpoint_ref, "budget_s": bounds.max_request_seconds},
        )
    if sock is not None:
        sock.settimeout(min(bounds.read_timeout_s, remaining))


def _read_bounded(
    source: http.client.HTTPResponse,
    limit: int,
    sock: socket.socket | None,
    bounds: TransportLimits,
    request: PreparedRequest,
) -> tuple[bytes, bool]:
    """Read at most `limit` bytes, and say whether there were more.

    One byte past the limit is requested on purpose. Reading exactly `limit` cannot tell a
    body that ended at the limit from one that was cut at it, and "we do not know whether
    this is complete" is not a state Raw may hold — losslessness is the claim Raw makes.

    **`read1`, not `read`.** `ADVERSARIAL-REVIEW-2026-08-18.md` F5: `read(n)` blocks until
    *n* bytes have arrived, so a server sending one byte at a time keeps a single call
    inside this loop for as long as it likes while every `recv` completes promptly and no
    socket timeout ever fires. `read1` returns whatever has arrived, which puts the loop
    back in charge of when to stop — and `_arm` on each pass is what makes stopping happen.
    The cost is one iteration per arriving chunk instead of per 64 KiB; a drip-feeding
    server is the only case where that is many, and it is the case being refused.
    """
    chunks: list[bytes] = []
    remaining = limit + 1
    while remaining > 0:
        _arm(sock, bounds, request)
        chunk = source.read1(min(_CHUNK, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    body = b"".join(chunks)
    if len(body) > limit:
        return b"", True
    return body, False


def _path_of(url: str) -> str:
    """The origin-form request target: everything from the path on.

    Taken from the URL `outbound.resolve` built rather than reassembled, so the bytes that
    were approved are the bytes that are sent.
    """
    without_scheme = url.split("://", 1)[-1]
    slash = without_scheme.find("/")
    return "/" if slash < 0 else without_scheme[slash:]
