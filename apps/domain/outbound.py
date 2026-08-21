"""The outbound policy. Every obligation in `p0-security.md` §Outbound lives here.

Copy-adapted from ``experiments/integrated-p0/domain/outbound.py`` (M2 batch 2c). The only
change is where credential resolution comes from: ``platform_core.secrets`` rather than a
domain-local ``secrets.py`` — P1 already centralizes ``resolve_credential`` there (DP-032
D4's ``COSMA_DB_*``/``COSMA_SRC_*`` ref families share one resolver and one ref-shape
check), so this module reuses it instead of duplicating a second copy. Every rule, refusal,
limit, and the credential-attachment logic (DP-018) are otherwise verbatim.

`[결정]` DP-008 D4 puts all of them on the platform rather than on the add-on, and this
module is what "on the platform" means. An add-on names an endpoint; everything between
that name and a response is decided here.

**Policy is separated from transport on purpose.** `resolve` takes an endpoint name, a
source's approved profile, and parameters, and returns either a `PreparedRequest` or a
`Refusal` — without opening a socket, resolving a name, or reading a clock. Three things
follow:

* Every refusal is testable without a network. A test that must stand up a server to
  learn whether a host is allowed will eventually be skipped, and a security control
  nobody runs is not a control.
* The reason for a refusal is a value, not a log line, so an operator can be shown which
  rule refused rather than that something failed.
* The transport half stays small enough to read, which matters because it is the half
  that can leak.

The one place policy cannot be pure is DNS: whether a hostname resolves inside a blocked
range is only knowable by asking. `check_resolved_addresses` therefore takes the
addresses as an argument rather than looking them up, so the rule is testable and the
lookup is the caller's.

**Loopback and the test stub.** The address rule blocks loopback, which is also where a
local stub server lives, so a source profile may carry `allow_loopback`. It is a real
hole and it is guarded two ways: a test asserts no committed source sets it, and a
second asserts that with the flag off a loopback address is actually refused. The second
is not optional — an absence assertion with no positive control passes just as well
against a rule that checks nothing.

**Fleet and the footgun.** [DP-035](../../docs/decisions/DP-035-fleet-egress-and-container-bind.md)
D1 adds a second hole, `allow_fleet`, for the two fixed adapter targets on the deploying
fleet's own bridge network — reachable only by a private address, but a specific class of
one, not "any RFC 1918 range": Python's `ipaddress.is_private` is `True` for loopback,
link-local (the cloud metadata address `169.254.169.254` included), and the unspecified
address, as well as for ordinary RFC 1918 space, so a bare `is_private and allow_fleet`
pass would unlock all three of those in the same breath. `is_fleet_admissible` names the
exclusions explicitly, both `check_resolved_addresses` and `SocketTransport`'s
transport-time re-check call it rather than each spelling the exclusion list out, and the
two flags stay orthogonal: `allow_fleet` never admits loopback, `allow_loopback` never
admits a private address.

**M4x — two gaps two live adapters actually hit, closed the same way as everything above:
by rule, testable without a socket, belt-and-suspenders where DNS or an add-on's own input
is the part policy cannot see in advance.**

*Gap 1, plain HTTP for loopback or fleet.* `ALLOWED_SCHEMES` stays `https`-only for
redirects and for the general case; `OutboundProfile.scheme` lets a profile state
`"http"` instead, and `resolve` grants it alongside `allow_loopback` or `allow_fleet` —
the same two flags that are already the address rule's two holes, rather than a third
flag that could disagree with either. That is the validation half. `SocketTransport`
holds the other half: it refuses to speak plain HTTP to anything the DNS it actually
performed did not resolve to loopback (loopback scope) or to loopback-or-fleet-admissible
(fleet scope) — the check `resolve` cannot make without a socket.
`PreparedRequest.plain_http_scope` carries which of the two the profile actually granted,
decided by `resolve` once and never re-derived by the transport from the profile itself.

*Gap 2, path parameters.* An approved path may carry a `{name}` placeholder; the profile
declares one validation regex per placeholder in `path_params`. The add-on supplies the
value through `fetch`'s existing `params` — the same channel that has always carried a
query string or a body, so an add-on still names an endpoint and a question, never a
destination. `resolve` validates each placeholder's value against its declared pattern,
substitutes, and only then runs the same segment-by-segment containment every approved
path has always been checked with — now against the path a template actually resolved to.
An endpoint with no placeholder is unaffected: `_template_param_names` returns nothing for
it and every check above takes the branch it already took.
"""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Final
from urllib.parse import quote, urlencode, urlsplit

from platform_core.secrets import resolve_credential

__all__ = [
    "DEFAULT_LIMITS",
    "PROTECTED_HEADERS",
    "CredentialPart",
    "credential_headers",
    "OutboundProfile",
    "PreparedRequest",
    "Refusal",
    "RefusalReason",
    "check_resolved_addresses",
    "comparable_segments",
    "is_fleet_admissible",
    "resolve",
    "strip_protected_headers",
]


class RefusalReason(StrEnum):
    """Why a request was refused, as a value an operator surface can render.

    One member per rule in `p0-security.md` §Outbound, so that "which rule refused this"
    has an answer rather than a stack trace.
    """

    SOURCE_HAS_NO_PROFILE = "SOURCE_HAS_NO_PROFILE"
    ENDPOINT_NOT_DECLARED = "ENDPOINT_NOT_DECLARED"
    SCHEME_NOT_ALLOWED = "SCHEME_NOT_ALLOWED"
    HOST_NOT_ALLOWED = "HOST_NOT_ALLOWED"
    PORT_NOT_ALLOWED = "PORT_NOT_ALLOWED"
    PATH_NOT_ALLOWED = "PATH_NOT_ALLOWED"
    ADDRESS_RANGE_BLOCKED = "ADDRESS_RANGE_BLOCKED"
    TOO_MANY_REDIRECTS = "TOO_MANY_REDIRECTS"
    RESPONSE_TOO_LARGE = "RESPONSE_TOO_LARGE"
    PARAMETER_NOT_ALLOWED = "PARAMETER_NOT_ALLOWED"
    #: The two limits `ADVERSARIAL-REVIEW-2026-08-18.md` F1 found enforced nowhere. They
    #: are refusals rather than a quiet stop for the reason every other member here is one:
    #: an add-on that ran past its grant has not collected less, it has been refused, and a
    #: run that reported success at the limit would be indistinguishable from one that
    #: reached the end of the data.
    PAGE_LIMIT_EXCEEDED = "PAGE_LIMIT_EXCEEDED"
    RECORD_LIMIT_EXCEEDED = "RECORD_LIMIT_EXCEEDED"
    #: DP-020. The method is the operator's grant and the body is bounded by the platform,
    #: so both can be refused for the same reason every other member here exists: an add-on
    #: reached past what the source row approved.
    METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"
    REQUEST_TOO_LARGE = "REQUEST_TOO_LARGE"
    #: M4x platform gap 2 (path templates). An endpoint whose approved path carries a
    #: `{name}` placeholder needs that name supplied through `fetch`'s existing `params`
    #: channel — the add-on names the value, the profile still decides the destination.
    #: `MISSING` is an add-on that named no value for a placeholder the profile declares;
    #: `INVALID` is a value that does not match the profile's own declared regex for it.
    PATH_PARAMETER_MISSING = "PATH_PARAMETER_MISSING"
    PATH_PARAMETER_INVALID = "PATH_PARAMETER_INVALID"


@dataclass(frozen=True)
class Refusal:
    """A refused request. Carries the rule and enough detail to act on it.

    `summary` is written for an operator, and deliberately never quotes a parameter
    value: a query string is the one part of a request an add-on controls, so it is the
    one part that could carry something a log should not hold.
    """

    reason: RefusalReason
    summary: str
    detail: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PreparedRequest:
    """A request the policy has approved. Not yet sent.

    `host` is kept beside the URL so the caller can resolve exactly the name the policy
    approved. Re-parsing the URL to find it would leave room for the two to disagree.
    """

    url: str
    host: str
    port: int
    endpoint_ref: str
    #: DP-020 D1. From the profile, never from the add-on.
    method: str = "GET"
    #: DP-020 D2. From the add-on, exactly as `params` always has been. `None` for a `GET`.
    body: bytes | None = None
    #: M4x platform gap 1 (loopback HTTP). From the profile, never from the add-on — the
    #: same provenance `method` already has. `"https"` unless the profile explicitly
    #: declares `"http"`, which `resolve` only grants when `allow_loopback` or
    #: `allow_fleet` is also set.
    scheme: str = "https"
    #: DP-035 D1. Which of the two plain-HTTP holes this request was granted under:
    #: `"loopback"` unless the profile set `allow_fleet`, in which case `resolve` sets
    #: `"fleet"` — the wider of the two, since a fleet-scoped profile's own address rule
    #: already admits loopback as well. `SocketTransport._refuse_http_off_loopback` reads
    #: this rather than the profile's flags directly, so the transport-time re-check can
    #: never end up deciding a different scope than `resolve` already committed to. The
    #: default (`"loopback"`) is what every construction that predates this field — in
    #: this module's own tests and in every caller that builds a `PreparedRequest` by
    #: hand — keeps meaning, since `scheme` defaults to `"https"` for the same requests
    #: and this value is inert unless `scheme == "http"`.
    plain_http_scope: str = "loopback"


#: `p0-security.md` requires per-source limits; these are the values used when a profile
#: states none. Small on purpose: a source that needs more says so, and an unstated limit
#: that happens to be generous is how a bound stops bounding anything.
DEFAULT_LIMITS: Final[Mapping[str, Any]] = {
    "connect_timeout_s": 5.0,
    "read_timeout_s": 30.0,
    "max_response_bytes": 8 * 1024 * 1024,
    "max_redirects": 3,
    "max_pages": 20,
    "max_records": 5000,
    # DP-024. Bounds one local input an importer opens, and has nothing to do with the
    # network — it lives here because `Limits` is one object an add-on reads, not because
    # a dataset is a request.
    "max_input_bytes": 64 * 1024 * 1024,
    # The whole of one `fetch`, redirect hops and connection attempts included.
    # `ADVERSARIAL-REVIEW-2026-08-18.md` F5 is why it exists: the socket timeouts above
    # bound one `recv` each, so a server sending one byte per (timeout − ε) trips none of
    # them, and occupancy came out linear in `max_response_bytes` — the reviewer's
    # arithmetic put `DEFAULT_LIMITS` at about 38 days. This is the bound that does not
    # move with what it bounds.
    #
    # 60 seconds is chosen rather than derived. One honest hop against a slow but working
    # source costs `connect_timeout_s + read_timeout_s` = 35s, so this leaves room for a
    # redirect and no more; summing the per-hop limits over `max_redirects + 1` would give
    # 140s, which is the arithmetic of the worst case rather than a bound anyone wants. A
    # source that genuinely needs longer states it, and states it where an operator can
    # see what it is buying.
    "max_request_seconds": 60.0,
    # DP-020 D3. A body is the add-on's (D2), so it is the add-on's to get wrong, and a
    # limit written into a contract with no counter behind it is what
    # `ADVERSARIAL-REVIEW-2026-08-18.md` F1 was about. 64 KiB is far above the largest
    # documented DataLab body — five keyword groups of twenty keywords — and far below
    # anything that would make one request expensive to hold in memory.
    "max_request_bytes": 64 * 1024,
}

#: DP-020 D1. `GET` reads and `POST` reads-expressed-as-a-body; nothing that writes. A
#: write to a source is a different safety question and `p0-security.md` has not been asked
#: it, so the others are refused by name rather than passed through.
ALLOWED_METHODS: Final[frozenset[str]] = frozenset({"GET", "POST"})

#: Stripped from anything recorded. `p0-security.md` names the first two; the rest are
#: the shapes a provider credential takes in practice. Matched case-insensitively.
PROTECTED_HEADERS: Final[frozenset[str]] = frozenset(
    {
        "authorization",
        "cookie",
        "set-cookie",
        "proxy-authorization",
        "x-api-key",
        "x-ncp-apigw-api-key",
        "x-ncp-apigw-api-key-id",
    }
)

#: Only HTTPS. `p0-security.md` says "허용 HTTPS scheme"; http is not a narrower case of
#: that, it is a different one, and permitting it would make every other rule here
#: conditional on a transport nobody chose.
ALLOWED_SCHEMES: Final[frozenset[str]] = frozenset({"https"})


#: The shape `secret-setup.md` fixes for a secret-store key, and the same pattern the
#: `source_credential_ref_is_a_key_name` CHECK holds on the column. Repeated here because
#: DP-018 puts refs in a jsonb array that a column constraint cannot see inside.
_KEY_NAME: Final = re.compile(r"^COSMA_SRC_[A-Z0-9_]+$")


@dataclass(frozen=True)
class CredentialPart:
    """One part of a source's credential: a key name, and the header it fills.

    [DP-018](../../../docs/decisions/DP-018-credential-parts-and-attachment.md) D1. A part
    exists at all because the first real source needs two of them: DP-008 left
    `needs_credential` as one boolean and `source.credential_ref` as one column, and Naver
    API Hub wants `X-NCP-APIGW-API-KEY-ID` and `X-NCP-APIGW-API-KEY` together.

    `ref` is a **key name** and never a value. The whole of what may appear in a log line,
    a dashboard, or this dataclass's `repr` is the name.
    """

    header: str
    ref: str


def _as_bytes(body: object) -> bytes | None:
    """The body as the bytes that will actually be sent, or `None` if that is unknowable.

    `[측정]` **This exists because `len(body)` was the wrong quantity.**
    `ADVERSARIAL-REVIEW-2026-08-19.md` F1: `len` is a byte count only for `bytes`, and
    `http.client` accepts far more than that — any bytes-like via the buffer protocol, and
    any iterable of bytes, which it streams `Transfer-Encoding: chunked`. A one-element
    `list[bytes]` therefore measured **1** against a 64 KiB grant and put 1 MiB on the wire.
    DP-020 D3 claims the platform bounds the body; a bound that trusts the add-on's static
    typing to keep the shape simple is not the platform bounding anything.

    `bytes` remains the declared type and mypy still refuses the alternatives. This is what
    happens when one reaches here anyway — and the finding is the argument for having it:
    a `bytearray` is the natural way to assemble a body incrementally, and a helper
    annotated `-> bytes` that returns one satisfies the checker and not the runtime.

    **An unmeasurable body is refused rather than sent.** A generator cannot be sized without
    consuming it, and consuming it here would leave the caller an exhausted iterator — so the
    honest answer is that this guard cannot bound it, and DP-020 D3 says an unbounded body
    does not go out. `None` is that answer.
    """
    if isinstance(body, bytes):
        return body
    if isinstance(body, bytearray | memoryview):
        # Bytes-like: `http.client` sends these through the buffer protocol, and their
        # length is already a byte count. Copied to `bytes` so that what was measured is
        # what is sent — a `bytearray` the add-on still holds could change afterwards.
        return bytes(body)
    # An iterable of chunks, which `http.client` streams. Materialised here because a
    # sequence can be measured without being consumed; a generator cannot, and falls through
    # to the refusal below.
    if isinstance(body, list | tuple) and all(
        isinstance(chunk, bytes | bytearray | memoryview) for chunk in body
    ):
        return b"".join(bytes(chunk) for chunk in body)
    return None


#: A path-template placeholder: `{digest}`, not `{{digest}}` or `{}`. Matches Python's own
#: identifier grammar, since it is a name the profile's `path_params` dict is keyed by.
_TEMPLATE_PARAM: Final = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


def _template_param_names(path: str) -> frozenset[str]:
    """Every `{name}` placeholder an approved path declares, or `frozenset()` for none.

    M4x platform gap 2. A path with no placeholder behaves exactly as it always has —
    this is how "profile without template → unchanged behavior" holds without a second
    code path.
    """
    return frozenset(_TEMPLATE_PARAM.findall(path))


def _read_path_params(
    endpoint_name: str, path: str, declared: object
) -> dict[str, re.Pattern[str]]:
    """Read `path_params`, refusing a declaration that does not exactly cover the template.

    Every placeholder in `path` needs exactly one regex here and every regex here needs a
    placeholder in `path` — a name with no regex is a value nothing would validate before
    it becomes part of a request; a regex with no placeholder is dead configuration that
    would silently stop applying the day someone rewrote the path. Read at profile
    construction, like every other malformed-row check in this function: the row should
    never have been written, and an operator learns that at registration rather than on the
    add-on's first `fetch` of it.
    """
    template_names = _template_param_names(path)
    if declared is None and not template_names:
        return {}
    if not isinstance(declared, Mapping):
        raise ValueError(
            f"outbound_profile.endpoints[{endpoint_name!r}].path_params must be an object "
            "of parameter name -> validation regex"
        )
    declared_names = {str(key) for key in declared}
    if declared_names != template_names:
        raise ValueError(
            f"outbound_profile.endpoints[{endpoint_name!r}] declares path_params "
            f"{sorted(declared_names)} but its path {path!r} names {sorted(template_names)}; "
            "every {name} placeholder needs exactly one declared regex and no more"
        )
    patterns: dict[str, re.Pattern[str]] = {}
    for param_name, pattern in declared.items():
        try:
            patterns[str(param_name)] = re.compile(str(pattern))
        except re.error as error:
            raise ValueError(
                f"outbound_profile.endpoints[{endpoint_name!r}].path_params[{param_name!r}] "
                f"is not a valid regular expression: {error}"
            ) from error
    return patterns


def _read_endpoints(endpoints: Mapping[str, Any]) -> dict[str, Any]:
    """Read both endpoint shapes, refusing a method the platform does not grant.

    DP-020 D1. A `ValueError` and not a `Refusal`, like every other malformed-row check
    here: the row should never have been written, which is a different thing from a request
    being denied. Refusing at read time also means an operator learns at registration rather
    than on the first fetch of an endpoint they may not use for weeks.
    """
    read: dict[str, Any] = {}
    for name, entry in endpoints.items():
        if isinstance(entry, Mapping):
            method = str(entry.get("method", "GET")).upper()
            if method not in ALLOWED_METHODS:
                raise ValueError(
                    f"outbound_profile.endpoints[{name!r}] asks for method {method!r}; this "
                    f"platform grants only {', '.join(sorted(ALLOWED_METHODS))} (DP-020 D1)"
                )
            path = entry.get("path")
            if not isinstance(path, str) or not path:
                raise ValueError(
                    f"outbound_profile.endpoints[{name!r}] declares no path. An absent path "
                    "used to default to the empty string, which every path is inside — one "
                    "such endpoint granted the whole host as the redirect range for all the "
                    "others. State the path, or remove the endpoint."
                )
            path_params = _read_path_params(str(name), path, entry.get("path_params"))
            read[str(name)] = {"path": path, "method": method, "path_params": path_params}
        else:
            path = str(entry)
            if _template_param_names(path):
                raise ValueError(
                    f"outbound_profile.endpoints[{name!r}] uses a {{name}} path template but "
                    "is declared as a bare string; declare it as an object with 'path' and "
                    "'path_params' so every placeholder gets a validation regex"
                )
            read[str(name)] = path
    return read


def _read_credentials(profile: Mapping[str, Any]) -> tuple[CredentialPart, ...]:
    """Read the `credentials` array, refusing a part the platform cannot honour safely.

    Both refusals are `ValueError` rather than `Refusal`, because this is a row that should
    never have been written — the shape `from_row` already uses for a malformed `endpoints`
    value, and a different thing from a request being denied.

    **The header must be protected.** DP-018 D3, and the load-bearing half of the packet.
    `strip_protected_headers` is what keeps a credential out of
    `raw_envelope.response_headers`, and it works from a fixed list. A profile free to name
    any header could name one that is attached on the way out and recorded on the way back —
    a credential in Raw with every individual rule still satisfied. Tying attachment to that
    list makes "attached" and "stripped" one set by construction instead of by two people
    remembering.

    **The ref must be a key name.** The column's CHECK cannot see inside a jsonb array, so
    the same rule is stated where the array is read, and a real token pasted into a profile
    is refused rather than sent.
    """
    stated = profile.get("credentials")
    if not stated:
        return ()
    parts: list[CredentialPart] = []
    for entry in stated:
        header = str(entry["header"])
        ref = str(entry["ref"])
        if header.lower() not in PROTECTED_HEADERS:
            raise ValueError(
                f"outbound_profile.credentials names {header!r}, which is not a protected "
                "header; a credential may only fill a header that is stripped out of "
                f"recorded Raw (DP-018 D3). Protected: {', '.join(sorted(PROTECTED_HEADERS))}"
            )
        if not _KEY_NAME.match(ref):
            raise ValueError(
                "outbound_profile.credentials carries a ref that is not a secret-store key "
                "name; it must match COSMA_SRC_<SOURCE_ID>_<PURPOSE> and is never a value"
            )
        parts.append(CredentialPart(header=header, ref=ref))
    return tuple(parts)


def credential_headers(profile: OutboundProfile) -> dict[str, str]:
    """Resolve this source's credential into the headers one request will carry.

    Per request and never cached — `domain.secrets.resolve_credential` says why. A profile
    with no credential resolves nothing and therefore needs no secret store at all, which
    matters because most sources have none and none of them should be made to depend on a
    store existing.

    Raises rather than returning what it could resolve. `secret-setup.md` invariant 4: a
    partially-authenticated request is one a source may answer with `200` and an error body,
    which a collector would store as Raw and a normalizer would later read as data.
    """
    return {part.header: resolve_credential(part.ref).reveal() for part in profile.credentials}


@dataclass(frozen=True)
class OutboundProfile:
    """A source's approved outbound policy, as the `source` row stores it.

    Built from the operator-approved row and never from the add-on's manifest. The
    manifest's `[declares]` block is a request; this is the grant (DP-008 D4).
    """

    hosts: tuple[str, ...]
    endpoints: Mapping[str, str]
    port: int = 443
    limits: Mapping[str, Any] = field(default_factory=lambda: dict(DEFAULT_LIMITS))
    allowed_parameters: tuple[str, ...] | None = None
    allow_loopback: bool = False
    #: DP-035 D1. The fleet-network hole: an address that is private and not loopback,
    #: link-local, multicast, reserved, or unspecified — `is_fleet_admissible` names the
    #: exclusion list once for both this dataclass's own `check_resolved_addresses` and
    #: `SocketTransport`'s transport-time re-check. Orthogonal to `allow_loopback`: neither
    #: flag admits the other's range, and like it, never set by a committed source outside
    #: the two adapter manifests DP-035 D3 names.
    allow_fleet: bool = False
    #: M4x platform gap 1. `"https"` unless the profile states `"http"` — and `resolve`
    #: grants `"http"` only when `allow_loopback` or `allow_fleet` is also set, which are
    #: the same two flags `check_resolved_addresses` already uses to admit an address at
    #: all. One base value per profile rather than per endpoint: every fixed adapter target
    #: this platform has hosted so far speaks one scheme for every route it serves.
    scheme: str = "https"
    #: What this source authenticates with, and where each part goes (DP-018 D2). On the
    #: *profile* rather than in the add-on's manifest: an add-on naming its own header would
    #: be describing the wire format of a request DP-008 D4 forbids it to compose, which is
    #: one fact in two places that can disagree. The manifest's `needs_credential` is the
    #: request; this is the grant, exactly as it already is for hosts and endpoints.
    credentials: tuple[CredentialPart, ...] = ()

    def path_of(self, endpoint_ref: str) -> str | None:
        """The approved path for this name, whichever shape the row used.

        DP-020 D1 lets an entry be a bare string — the `GET` form every profile written
        before it uses — or an object carrying a method. Read here rather than normalised at
        construction so that a profile built directly in a test and one read from a row take
        the same path through this code.
        """
        entry = self.endpoints.get(endpoint_ref)
        if entry is None:
            return None
        if isinstance(entry, Mapping):
            return str(entry.get("path", ""))
        return str(entry)

    def method_of(self, endpoint_ref: str) -> str:
        """The method the operator granted for this name. `GET` unless the row says otherwise."""
        entry = self.endpoints.get(endpoint_ref)
        if isinstance(entry, Mapping):
            return str(entry.get("method", "GET")).upper()
        return "GET"

    def approved_paths(self) -> tuple[str, ...]:
        """Every approved path, for the redirect range. Both entry shapes, one tuple."""
        return tuple(
            path for name in self.endpoints if (path := self.path_of(name)) is not None
        )

    def path_params_of(self, endpoint_ref: str) -> Mapping[str, re.Pattern[str]]:
        """The declared validation regex for each `{name}` placeholder in this endpoint's
        approved path, or an empty mapping for an endpoint with no template.

        M4x platform gap 2. Populated by `_read_endpoints`/`_read_path_params` at profile
        construction, where every placeholder is already checked to have exactly one regex —
        so a name `resolve` looks up here is guaranteed present, never a `KeyError`.
        """
        entry = self.endpoints.get(endpoint_ref)
        if isinstance(entry, Mapping):
            patterns = entry.get("path_params", {})
            if isinstance(patterns, Mapping):
                return patterns
        return {}

    @classmethod
    def from_row(cls, profile: Mapping[str, Any] | None) -> OutboundProfile | None:
        """Read a `source.outbound_profile` jsonb value, or `None` if the source has none.

        A source with no profile is not an error here — a normalizer source is required
        to have none — but it cannot fetch, and `resolve` says so by name.
        """
        if not profile:
            return None
        endpoints = profile.get("endpoints") or {}
        if not isinstance(endpoints, Mapping):
            raise ValueError("outbound_profile.endpoints must be an object of name -> path")
        endpoints = _read_endpoints(endpoints)
        limits = dict(DEFAULT_LIMITS)
        limits.update(profile.get("limits") or {})
        allowed = profile.get("allowed_parameters")
        return cls(
            hosts=tuple(profile.get("hosts") or ()),
            endpoints=endpoints,
            port=int(profile.get("port", 443)),
            limits=limits,
            allowed_parameters=None if allowed is None else tuple(str(a) for a in allowed),
            allow_loopback=bool(profile.get("allow_loopback", False)),
            allow_fleet=bool(profile.get("allow_fleet", False)),
            credentials=_read_credentials(profile),
            scheme=str(profile.get("scheme", "https")),
        )


def resolve(
    endpoint_ref: str,
    profile: OutboundProfile | None,
    params: Mapping[str, str] | None = None,
    body: bytes | None = None,
) -> PreparedRequest | Refusal:
    """Turn an add-on's endpoint name into an approved request, or refuse it by rule.

    This is the whole of `p0-security.md`'s "임의 URL이 아니라 등록된 source_id를
    선택한다": the add-on supplies a name that must already be in the profile, so there
    is no input to this function that could become an arbitrary URL. A name the profile
    does not carry is refused before anything else is considered.
    """
    if profile is None:
        return Refusal(
            RefusalReason.SOURCE_HAS_NO_PROFILE,
            f"the source has no approved outbound profile, so {endpoint_ref!r} cannot be requested",
            {"endpoint_ref": endpoint_ref},
        )

    path = profile.path_of(endpoint_ref)
    if path is None:
        known = ", ".join(sorted(profile.endpoints)) or "none"
        return Refusal(
            RefusalReason.ENDPOINT_NOT_DECLARED,
            f"{endpoint_ref!r} is not an approved endpoint; approved endpoints are {known}",
            {"endpoint_ref": endpoint_ref, "approved": sorted(profile.endpoints)},
        )

    if not profile.hosts:
        return Refusal(
            RefusalReason.HOST_NOT_ALLOWED,
            f"the source's profile approves no host, so {endpoint_ref!r} cannot be requested",
            {"endpoint_ref": endpoint_ref},
        )
    host = profile.hosts[0]

    # M4x platform gap 1. The scheme is the profile's, exactly as the host and method
    # already are — an add-on names an endpoint, never a transport. `http` is granted only
    # alongside `allow_loopback` or `allow_fleet` (DP-035 D1): the same two flags
    # `check_resolved_addresses` already requires before it will admit an address at all,
    # so one flag each states one intention rather than a third that could disagree with
    # both. This is the "profile validation" half of the belt-and-suspenders rule;
    # `SocketTransport` holds the other half against the address DNS actually resolved.
    scheme = profile.scheme
    if scheme not in ("https", "http"):
        return Refusal(
            RefusalReason.SCHEME_NOT_ALLOWED,
            f"the profile declares scheme {scheme!r} for {endpoint_ref!r}, which this "
            "platform does not send",
            {"endpoint_ref": endpoint_ref, "scheme": scheme},
        )
    if scheme == "http" and not (profile.allow_loopback or profile.allow_fleet):
        return Refusal(
            RefusalReason.SCHEME_NOT_ALLOWED,
            "plain HTTP is only permitted when the source's profile sets allow_loopback "
            f"or allow_fleet; {endpoint_ref!r} would be requested over 'http' without "
            "either",
            {"endpoint_ref": endpoint_ref, "scheme": scheme},
        )

    # M4x platform gap 2. A `{name}` placeholder in the approved path is filled from the
    # add-on's existing `params` channel — the same one that has always carried "the
    # question" for a query string or a body. The add-on never composes the path: the
    # profile states which names it will accept and what pattern each must match, and only
    # those exact names are consumed here. Whatever `params` holds beyond them still becomes
    # a query string below, unchanged from before this gap existed.
    remaining_params: Mapping[str, str] | None = params
    template_names = _template_param_names(path)
    if template_names:
        regexes = profile.path_params_of(endpoint_ref)
        substitutions: dict[str, str] = {}
        for name in sorted(template_names):
            if params is None or name not in params:
                return Refusal(
                    RefusalReason.PATH_PARAMETER_MISSING,
                    f"{endpoint_ref!r} requires path parameter {name!r}, which was not "
                    "supplied",
                    {"endpoint_ref": endpoint_ref, "parameter": name},
                )
            value = params[name]
            pattern = regexes.get(name)
            if pattern is None or pattern.fullmatch(value) is None:
                # The value is never quoted, for the same reason every other `Refusal`
                # here never quotes one: it is the one part of a request an add-on
                # controls, and it is what a traversal attempt (`digest=../../admin`)
                # would otherwise put straight into a log line.
                return Refusal(
                    RefusalReason.PATH_PARAMETER_INVALID,
                    f"path parameter {name!r} for {endpoint_ref!r} does not match the "
                    "profile's declared pattern",
                    {"endpoint_ref": endpoint_ref, "parameter": name},
                )
            substitutions[name] = value
        for name, value in substitutions.items():
            path = path.replace("{" + name + "}", value)
        remainder = {k: v for k, v in params.items() if k not in template_names} if params else {}
        remaining_params = remainder or None

    if profile.allowed_parameters is not None and remaining_params:
        unexpected = sorted(set(remaining_params) - set(profile.allowed_parameters))
        if unexpected:
            # Names only. A value is the part an add-on controls.
            return Refusal(
                RefusalReason.PARAMETER_NOT_ALLOWED,
                f"parameters not approved for {endpoint_ref!r}: {', '.join(unexpected)}",
                {"endpoint_ref": endpoint_ref, "unexpected": unexpected},
            )

    # Runs against the *substituted* path when a template was used: this is the same
    # containment every approved path has always been checked with, applied to the final
    # path a template resolved to rather than to the literal `{name}` text — the belt this
    # gap needed and not a new rule. A traversal value fails validation above before it
    # would ever reach here; a permissive profile's declared regex is what this catches.
    if not path.startswith("/"):
        return Refusal(
            RefusalReason.PATH_NOT_ALLOWED,
            f"the approved path for {endpoint_ref!r} is not absolute",
            {"endpoint_ref": endpoint_ref},
        )

    if comparable_segments(path) is None:
        # A stored path that cannot be compared segment by segment would grant a range
        # `check_redirect` is unable to describe, so every redirect for this source would
        # be refused and nothing would say why. Refusing on the first fetch puts the
        # failure where an operator can act on it — see F4 in the review.
        return Refusal(
            RefusalReason.PATH_NOT_ALLOWED,
            f"the approved path for {endpoint_ref!r} carries a dot segment or an encoded "
            "separator, so the range it grants cannot be decided",
            {"endpoint_ref": endpoint_ref},
        )

    method = profile.method_of(endpoint_ref)
    if method not in ALLOWED_METHODS:
        return Refusal(
            RefusalReason.METHOD_NOT_ALLOWED,
            f"the profile grants method {method!r} for {endpoint_ref!r}, which this platform "
            f"does not send; granted methods are {', '.join(sorted(ALLOWED_METHODS))}",
            {"endpoint_ref": endpoint_ref, "method": method},
        )
    # DP-020 D4, both directions. A `GET` carrying a body is legal HTTP that many servers
    # ignore — a request the operator approved and the add-on did not get — and a `POST`
    # with none is an add-on that forgot the question it came to ask.
    if method == "GET" and body is not None:
        return Refusal(
            RefusalReason.METHOD_NOT_ALLOWED,
            f"{endpoint_ref!r} is approved for GET and a body was supplied; a body is only "
            "sent to an endpoint the profile grants POST",
            {"endpoint_ref": endpoint_ref, "method": method},
        )
    if method == "POST" and body is None:
        return Refusal(
            RefusalReason.METHOD_NOT_ALLOWED,
            f"{endpoint_ref!r} is approved for POST and no body was supplied",
            {"endpoint_ref": endpoint_ref, "method": method},
        )
    if body is not None:
        limit = int(profile.limits.get("max_request_bytes", DEFAULT_LIMITS["max_request_bytes"]))
        measured = _as_bytes(body)
        if measured is None or len(measured) > limit:
            # The body is the add-on's and could carry anything, so the refusal counts it and
            # never quotes it — the rule `Refusal` already applies to a query.
            size = -1 if measured is None else len(measured)
            return Refusal(
                RefusalReason.REQUEST_TOO_LARGE,
                f"the request body for {endpoint_ref!r} is {size} bytes and this source "
                f"grants {limit}"
                if measured is not None
                else f"the request body for {endpoint_ref!r} is not bytes this guard can "
                "measure, and an unmeasured body is not a bounded one",
                {"endpoint_ref": endpoint_ref, "limit": limit, "size": size},
            )
        # The measured bytes are what goes downstream, so the thing counted and the thing
        # sent cannot differ. `_hop` writes `request.body` and re-measures nothing.
        body = measured

    url = f"{scheme}://{host}:{profile.port}{quote(path, safe='/')}"
    # A `POST` asks its question in the body, so nothing goes in the URL as well: two places
    # for one fact is two places that can disagree, and only one of them is what was sent.
    # `remaining_params` has already had any path-template names removed above, so a value
    # consumed as a path segment is never also appended as a query parameter.
    if remaining_params and method == "GET":
        url = f"{url}?{urlencode(dict(remaining_params))}"
    return PreparedRequest(
        url=url,
        host=host,
        port=profile.port,
        endpoint_ref=endpoint_ref,
        method=method,
        body=body,
        scheme=scheme,
        # DP-035 D1. Decided once, here, from the profile the caller cannot influence —
        # never re-derived by the transport, which only ever reads this back.
        plain_http_scope="fleet" if profile.allow_fleet else "loopback",
    )


def check_redirect(
    location: str, profile: OutboundProfile, hops: int
) -> PreparedRequest | Refusal:
    """Revalidate a redirect destination under the same policy as the original request.

    `p0-security.md`: "HTTP redirect가 발생하면 destination을 같은 정책으로 다시
    검증한다." Same policy means the same function decides — a second, looser check
    written for redirects would be the hole.

    `[측정]` The function was the same and the *comparison* was not. Until 2026-08-18 the
    path test was `parts.path.startswith(approved)` on the raw path, and
    `ADVERSARIAL-REVIEW-2026-08-18.md` F4 walked out of the approved range twice over —
    once with dot segments the far end resolves and this function did not, once with a
    string prefix that is not a path prefix. `comparable_segments` is the repair, and its
    docstring carries the reasoning for refusing rather than normalizing.
    """
    if hops > int(profile.limits.get("max_redirects", DEFAULT_LIMITS["max_redirects"])):
        return Refusal(
            RefusalReason.TOO_MANY_REDIRECTS,
            f"the request exceeded {profile.limits.get('max_redirects')} redirects",
            {"hops": hops},
        )

    parts = urlsplit(location)
    if parts.scheme not in ALLOWED_SCHEMES:
        return Refusal(
            RefusalReason.SCHEME_NOT_ALLOWED,
            f"a redirect to scheme {parts.scheme or '(relative)'!r} is not allowed",
            {"scheme": parts.scheme},
        )
    if parts.hostname is None or parts.hostname not in profile.hosts:
        return Refusal(
            RefusalReason.HOST_NOT_ALLOWED,
            f"a redirect to host {parts.hostname!r} is not approved for this source",
            {"host": parts.hostname, "approved": list(profile.hosts)},
        )
    port = parts.port or 443
    if port != profile.port:
        return Refusal(
            RefusalReason.PORT_NOT_ALLOWED,
            f"a redirect to port {port} is not approved for this source",
            {"port": port, "approved": profile.port},
        )
    # A redirect is followed as a `GET` whatever the original method was: `303` says so,
    # and for `307`/`308` re-sending a body to a destination the add-on never named is a
    # request nobody approved. Refusing to carry it is the conservative half.
    if not _is_within_approved_range(parts.path, profile):
        return Refusal(
            RefusalReason.PATH_NOT_ALLOWED,
            "a redirect left the source's approved path range",
            {"path": parts.path},
        )
    return PreparedRequest(
        url=location, host=parts.hostname, port=port, endpoint_ref="(redirect)"
    )


#: Percent-encodings of `.` and `/`. A path is compared as text here and resolved by the
#: far end after decoding, so a comparison that ignored these would be comparing something
#: other than what the server will act on — which is exactly how `%2e%2e` walks out of an
#: approved range while a scan for `..` sees nothing.
_ENCODED_DOT: Final[tuple[str, ...]] = ("%2e", "%2E")
_ENCODED_SLASH: Final[tuple[str, ...]] = ("%2f", "%2F")


def comparable_segments(path: str) -> tuple[str, ...] | None:
    """The path's segments, or `None` if what the far end will resolve is not knowable.

    `ADVERSARIAL-REVIEW-2026-08-18.md` F4. The approved range used to be tested with
    `path.startswith(approved)` on the raw path, and `domain.transport` sends the URL
    verbatim. Two things got through, and the reviewer carried the first of them end to end
    over TLS into a body it had written as `{"secret": "THIS-PATH-WAS-NEVER-APPROVED"}`:

    * `/v1/items/../../admin/keys` — the far end removes dot segments as RFC 3986 §5.2.4
      requires, so the path this function reads is not the path the server acts on.
    * `/v1/items2/secret` — a string prefix, not a path prefix. `/v1/items2` is beside
      `/v1/items`, not under it.

    So: **refuse rather than normalize.** Resolving `..` here would mean predicting which
    of several defensible decodings the far end performs — nginx, Apache, and a bare
    application server do not agree about `%2f`, and being wrong in the permissive
    direction is the hole. A `Location` carrying a dot segment is unusual server behaviour;
    a redirect refused for it costs one collection, and the alternative costs the range.
    """
    if not path:
        # `()` here would be a prefix of every path, so an endpoint that reached
        # `approved_paths()` without one granted the entire host to every other endpoint's
        # redirects. `None` routes it to the same `continue` an uncomparable path takes:
        # one bad endpoint narrows nothing and widens nothing.
        return None
    lowered = path
    for encoded in _ENCODED_SLASH:
        if encoded in lowered:
            return None
    for encoded in _ENCODED_DOT:
        lowered = lowered.replace(encoded, ".")
    segments = tuple(lowered.split("/"))
    if any(segment in (".", "..") for segment in segments):
        return None
    # A trailing slash makes `/v1/items/` and `/v1/items` the same resource to every server
    # that matters, and an empty final segment would otherwise make them different ranges.
    if len(segments) > 1 and segments[-1] == "":
        segments = segments[:-1]
    return segments


def _is_within_approved_range(path: str, profile: OutboundProfile) -> bool:
    """Whether `path` is one of the approved paths or under one, compared by segment."""
    candidate = comparable_segments(path)
    if candidate is None:
        return False
    for approved in profile.approved_paths():
        granted = comparable_segments(approved)
        if granted is None:
            # `resolve` refuses such a source on its first fetch. Skipped rather than
            # treated as granting everything, so a defect in one endpoint cannot widen
            # the range the others grant.
            continue
        if candidate[: len(granted)] == granted:
            return True
    return False


def is_fleet_admissible(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Whether `address` is inside `allow_fleet`'s grant (DP-035 D1).

    Private, and not loopback, link-local, multicast, reserved, or unspecified. Named as
    its own function, rather than inlined at each of its two call sites, because both
    `check_resolved_addresses` below and `SocketTransport`'s transport-time plain-HTTP
    re-check (`domain.transport._refuse_http_off_loopback`) need the identical exclusion
    list — the same footgun `p0-security.md`'s loopback rule already had to name: Python's
    `ipaddress.is_private` is `True` for `127.0.0.0/8`, `169.254.0.0/16` (the cloud
    metadata address `169.254.169.254` included), and `0.0.0.0/8` as well as for ordinary
    RFC 1918 space, so a bare `is_private` check would admit all three ranges this
    function exists to keep excluded.

    `[확인 사실]` REVIEW-TASK-012 F2: the `is_multicast` clause is dead code against
    CPython 3.13's actual `ipaddress` tables — no address is both `is_private` and
    `is_multicast` (`IPv4Address`'s multicast range `224.0.0.0/4` and `IPv6Address`'s
    `ff00::/8` do not overlap either family's `_private_networks`), so `is_private`
    alone already refuses every multicast address and deleting `and not
    address.is_multicast` leaves every test in this tree green — the one mutation
    REVIEW-TASK-012's twelve did not kill. `[결정]` Kept anyway, as defence-in-depth
    against `ipaddress` semantics drifting across a Python version — the two other
    classes this module already carries an unreachable-clause precedent for
    (`is_reserved`, whose own "subsumed by private" case is recorded in
    `TestResolvedAddressRange.test_the_reserved_clause_is_subsumed_by_the_private_one`)
    make this the same shape rather than a new one. Naming it here is the fix
    REVIEW-TASK-012 asked for: the clause must not be allowed to read as load-bearing
    when nothing here currently exercises it as such.
    """
    return (
        address.is_private
        and not address.is_loopback
        and not address.is_link_local
        and not address.is_multicast
        and not address.is_reserved
        and not address.is_unspecified
    )


def check_resolved_addresses(
    host: str, addresses: Sequence[str], profile: OutboundProfile
) -> Refusal | None:
    """Refuse a hostname that resolves into a range `p0-security.md` blocks.

    Takes the addresses rather than resolving them, so the rule is testable without a
    resolver and without a network. The lookup belongs to the caller, which is also the
    only party that can do it at the right moment — a name checked once and connected to
    later is a rebinding hole, so the caller must connect to the address it checked.

    **Every address must pass.** A name resolving to one public and one loopback address
    is refused: taking the first, or any, would make the outcome depend on resolver
    ordering.
    """
    for raw in addresses:
        try:
            address = ipaddress.ip_address(raw)
        except ValueError:
            return Refusal(
                RefusalReason.ADDRESS_RANGE_BLOCKED,
                f"{host!r} resolved to something that is not an IP address",
                {"host": host},
            )
        if address.is_loopback and profile.allow_loopback:
            continue
        if profile.allow_fleet and is_fleet_admissible(address):
            continue
        if (
            address.is_loopback
            or address.is_private
            or address.is_link_local
            or address.is_multicast
            or address.is_reserved
            or address.is_unspecified
        ):
            return Refusal(
                RefusalReason.ADDRESS_RANGE_BLOCKED,
                f"{host!r} resolved into a blocked address range",
                {"host": host, "address": str(address)},
            )
    return None


def strip_protected_headers(headers: Mapping[str, str]) -> dict[str, str]:
    """Remove credential-bearing headers from anything about to be recorded.

    `p0-security.md`: "Network error와 HTTP response를 기록할 때 Authorization, Cookie와
    provider-protected header를 제거한다." Applied on the way *out* of the transport, so
    that what an add-on receives and what the Raw envelope stores have already lost them
    — rather than being trusted to lose them later.
    """
    return {k: v for k, v in headers.items() if k.lower() not in PROTECTED_HEADERS}
