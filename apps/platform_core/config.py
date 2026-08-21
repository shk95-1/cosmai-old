"""Platform configuration: load it, validate it, or refuse to start.

Copy-adapted from ``experiments/integrated-p0/platform_core/config.py``. SEC-003's
rule is still the acceptance scenario, and its source is still
``docs/conventions/secret-setup.md``: a process that cannot resolve its
configuration exits with a non-retryable configuration failure and never
continues on an empty value or a fallback. A platform that silently substitutes a
default is one whose later security evidence means nothing, because nobody can
tell afterwards which configuration actually ran.

Two consequences shape this module, unchanged from P0-A.

* **A default is a documented value for an absent setting, never a repair for a
  rejected one.** ``COSMA_LEASE_SECONDS=0`` is an error, not a reason to use 30.
* **The report names settings, not the environment.** ``secret-setup.md`` lists
  dumping the environment on a configuration error as its own leak channel, so
  the message carries setting names and reasons, and includes an offending value
  only when the setting's name is not itself a candidate secret.

**What DP-032 changes.** P0-A's cluster was repository-local, passwordless, and
reachable only through a Unix socket directory (DP-006 D2); ``db_host`` was a
directory and there was no credential in sight. DP-032 D1/D4 move P1 onto a
dedicated database on a shared server, reached over loopback TCP with a
password: ``db_host`` is now a TCP host string, ``db_port`` is new, and
``db_password_ref`` is new — a *name* in the secret store, resolved at the point
of use by ``platform_core.secrets.resolve_credential``, never a value this
module touches. ``db_password_ref``'s own value is still just a ref name, but its
setting name reads as a secret under ``is_redacted_key``, so a rejected ref is
still withheld from the report by the same rule that protects every other
setting — over-cautious by construction, per the docstring below.

DP-032 D4 also widens the credential-ref naming rule ``secret-setup.md`` fixes
for source credentials (``COSMA_SRC_<SOURCE_ID>_<PURPOSE>``) to a second, sibling
family for database credentials: ``CREDENTIAL_REF_PATTERN`` accepts
``COSMA_SRC_*`` and ``COSMA_DB_*`` and nothing else. P0's own ``domain/outbound.py``
enforced the ``COSMA_SRC_`` half of this at the point an outbound profile was
read; P1 has no outbound-profile layer yet, so the check is enforced once, here,
at config load, and again in ``platform_core.secrets.resolve_credential`` at the
point of resolution — the same two-layer shape P0 used for the secret-store
location guard below.

``SETTINGS`` and ``CROSS_CHECKS`` are tables so that a later validator is an
entry rather than an edit. Two of the entries are security guards rather than
type checks, carried forward unchanged from P0-A:

* ``_api_host_literal`` and ``_api_bind_is_permitted_for_scope`` (SEC-002) together
  refuse an API bind address the operator's stated ``COSMA_API_BIND_SCOPE`` does not
  permit, instead of merely defaulting to loopback — split across a ``Setting`` parser
  and a ``CrossCheck`` because DP-035 D2 made the decision depend on two settings at
  once (see "What DP-035 D2 changes" below). This is about the operator API's own bind
  address, not the database TCP host DP-032 adds — the database is expected to be a
  real, non-loopback-in-general shared server, so neither function is ever applied to
  ``db_host``.
* ``secret_store_location_problem`` (SEC-001) refuses a secret store that
  resolves to somewhere inside the repository working tree. It is the
  application-startup half of the obligation ``docs/conventions/secret-setup.md``
  records; the test-session half lives in ``tests/conftest.py`` and calls this
  same function, so the two cannot drift.

**What DP-035 D2 changes.** SEC-002 relaxes from "loopback only, no exceptions" to
"loopback, or the unspecified address under an explicit opt-in": ``COSMA_API_BIND_SCOPE``
(``loopback`` default, or ``container``) gates whether ``COSMA_API_HOST`` may be the
wildcard address ``0.0.0.0``/``::``. This is a deliberate, recorded widening of the
threat model, not a loosening of it — the exposure boundary it moves is the process
bind, not the host-side surface: `cosmai-api` still publishes only `127.0.0.1:8100` on
the host under either scope (the stack compose file's own port mapping, unaffected by
this setting), and what actually changes under ``container`` scope is that the process
becomes reachable, unauthenticated, by every other container on the deploying fleet's
own ``db-net`` bridge network. DP-035's own Decision Packet records why that is accepted
(every ``db-net`` member is this operator's own fleet) and what would have to be true
before it stopped being safe (an untrusted workload joining ``db-net``, or the API being
published beyond host loopback) — this module enforces the mechanical half of that
decision; it does not re-argue it.

**Reconciliation (M1 Tasks 5-6).** Until now this module carried a minimal,
self-contained stand-in for P0's ``platform_core.errors``/``platform_core.obs``
modules — an inlined ``ConfigurationInvalidError``, log-level validation, and
the secret-aware redaction check this stage needs — because Tasks 3-4 built
configuration, secrets, connection, and migration only, with no error taxonomy
or structured logger yet to import from. Task 6 built the real
``platform_core.errors`` (the full five-class CONTRACT-JOB@0.1 table) and
Task 5 built the real ``platform_core.obs`` (structured logging, redaction,
correlation, metrics); this module now imports ``ConfigurationInvalidError``
from ``platform_core.errors`` and the log-level/redaction helpers from
``platform_core.obs.logging``/``platform_core.obs.redaction`` rather than
carrying its own copies. Behavior is unchanged except that the imported
``ConfigurationInvalidError`` also redacts its own summary text
(``PlatformError.__init__`` applies ``redact_text``) and its detail through
``ProtectedDetail`` (reachable at ``error.detail.for_protected_debug()`` rather
than the old ``error.for_protected_debug()``) — both strictly safer than the
stand-in's "store as given" behavior, and neither changes what any of this
module's own summaries or details expose (no setting name or reason text here
contains a ``key=value`` pattern for the text-masking rule to catch).

Nothing in this module opens a connection, and nothing in it opens the secret
store. SEC-003 requires cases a-e to fail before the database is touched, and the
cheapest way to guarantee that is for the configuration layer to have no database
code in it at all. SEC-001 requires the location guard to decide without reading
the store's **contents**, because reading a credential in order to validate where
it lives would be the leak the rule exists to prevent.
"""

from __future__ import annotations

import ipaddress
import os
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from platform_core.errors import ConfigurationInvalidError as ConfigurationInvalidError
from platform_core.obs.logging import DEFAULT_LEVEL, LOG_SUFFIX, require_known_level
from platform_core.obs.redaction import REDACTION_MARKER, is_redacted_key

PREFIX: Final = "COSMA_"

#: The path of the secret store, exported by ``scripts/with-secret-source.sh``.
#: This stage reads its **location** and never its contents, which is why it is
#: not a ``Setting`` and produces no configuration field.
SECRET_STORE_VARIABLE: Final = "COSMA_SECRET_SOURCE"

#: Where an operator is sent when the location guard refuses a store.
SECRET_SETUP_POINTER: Final = "docs/conventions/secret-setup.md"

#: The repository working tree this checkout lives in. ``config.py`` sits at
#: ``apps/platform_core/config.py``, two directories below the root — one
#: shallower than P0's ``experiments/integrated-p0/platform_core/config.py``.
#: ``tests/conftest.py`` computes the same root from its own location and a
#: test asserts the two agree, because a guard measuring the wrong tree would
#: pass everything.
WORKING_TREE_ROOT: Final[Path] = Path(__file__).resolve().parents[2]

#: ``COSMA_ADDON_DIR`` is read by ``addon_host.settings`` rather than here (DP-008
#: D1 keeps the add-on layer's settings in the add-on layer). Without this entry the
#: report would say the variable "is ignored", which is false, and a standing false
#: positive is worse than noise: SEC-003 case f exists to catch a **typo in a real
#: setting name**, and an operator who learns to skip the warning loses that.
#:
#: M1 deferred this entry (Task 3-4 report, deviation 5): M1 built no add-on host, so
#: there was nothing yet for the variable to serve, and ``docs/p1/M1-RECORD.md``
#: named M3 — this batch — as where it comes back. Restored verbatim from
#: ``experiments/integrated-p0/platform_core/config.py``.
ADDON_DIR_VARIABLE: Final = "COSMA_ADDON_DIR"

#: Variables this stage recognises but does not turn into a configuration field.
RECOGNIZED_UNUSED: Final[frozenset[str]] = frozenset({SECRET_STORE_VARIABLE, ADDON_DIR_VARIABLE})

DEFAULT_API_HOST: Final = "127.0.0.1"

#: DP-032 D4's second credential-ref key family, alongside P0's
#: ``COSMA_SRC_<SOURCE_ID>_<PURPOSE>``. Shared with ``platform_core.secrets``,
#: which imports this constant rather than defining its own copy.
CREDENTIAL_REF_PATTERN: Final = re.compile(r"^COSMA_(SRC|DB)_[A-Z0-9_]+$")

#: The default ``db_password_ref``: the runtime credential, not the migrator's.
#: A caller that needs the migrator's connects with
#: ``platform_core.db.connection.connect(role="migrator")``, which uses a fixed
#: ref of its own rather than this default.
DEFAULT_DB_PASSWORD_REF: Final = "COSMA_DB_RUNTIME"

#: ``EX_CONFIG`` from ``sysexits.h`` (also ``os.EX_CONFIG`` on POSIX). No
#: entrypoint exists yet in this milestone to exit with it, but the status is
#: fixed here so a future one does not have to invent it.
EX_CONFIG: Final = 78

# ``ConfigurationInvalidError``, ``require_known_level``/``LOG_SUFFIX``, and
# ``is_redacted_key``/``REDACTION_MARKER`` are imported above from
# ``platform_core.errors``/``platform_core.obs`` — see the reconciliation note
# in the module docstring. What SEC-001 through SEC-003 need from the error
# type (a class name, an operator-safe summary, protected detail, "not
# retryable") and from the level/redaction helpers (a canonical level name, the
# ``.jsonl`` suffix rule, the "does this name read as a secret" test) is now
# the real thing rather than a stand-in sized for a stage with nothing else to
# import from.

# --- settings machinery, unchanged in shape from P0 --------------------------


class _Rejected(Exception):
    """Internal: a parser's reason for refusing a value."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Setting:
    """One environment variable and how it becomes a configuration field."""

    name: str
    attribute: str
    parse: Callable[[str], Any]
    default: str | None = None

    @property
    def required(self) -> bool:
        return self.default is None


@dataclass(frozen=True)
class PlatformConfig:
    """Validated platform configuration. Every field is present and checked."""

    db_host: str
    db_port: int
    db_name: str
    db_user: str
    db_password_ref: str
    lease_seconds: int
    retry_base_ms: int
    retry_max_ms: int
    poll_ms: int
    api_host: str
    api_port: int
    #: DP-035 D2. ``"loopback"`` (default) or ``"container"``; gates whether ``api_host``
    #: may be the unspecified address. Never applied to ``db_host`` — the same reason
    #: ``_loopback_host`` is not, stated in the module docstring's SEC-002 bullet.
    api_bind_scope: str
    log_level: str
    #: Where both entrypoints write their structured log, or ``None`` for standard
    #: error. ``None`` is the ordinary case; a path is what makes the events of
    #: several processes reachable from one place (OPS-003).
    log_file: Path | None = None
    unrecognized_variables: tuple[str, ...] = ()

    def warnings(self) -> tuple[str, ...]:
        """Non-fatal findings an entrypoint should log at startup (SEC-003 case f)."""
        return tuple(
            f"unknown {PREFIX}-prefixed variable is ignored: {name}"
            for name in self.unrecognized_variables
        )


def _text(value: str) -> str:
    return value


def _positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        raise _Rejected("must be an integer") from None
    if number <= 0:
        raise _Rejected("must be greater than zero")
    return number


def _port(value: str) -> int:
    number = _positive_int(value)
    if number > 65535:
        raise _Rejected("must be a port number between 1 and 65535")
    return number


def _level(value: str) -> str:
    try:
        return require_known_level(value)
    except ConfigurationInvalidError as error:
        raise _Rejected(error.summary) from None


def _log_file(value: str) -> Path | None:
    """Where the structured log is written, or ``None`` for standard error."""
    if not value:
        return None
    path = Path(value).expanduser()
    if path.suffix != LOG_SUFFIX:
        raise _Rejected(
            f"must name a file ending in {LOG_SUFFIX}, because the repository ignores "
            "*.log and gate evidence has to stay reviewable"
        )
    if not path.parent.is_dir():
        raise _Rejected(
            f"must name a file in an existing directory, but {path.parent} is not one"
        )
    return path


def _api_host_literal(value: str) -> str:
    """Accept a literal IP address and refuse anything else (SEC-002, DP-035 D2).

    This guards the operator **API's** bind address only. DP-032 moves the
    *database* host to a real TCP address on a shared server (``_text`` below),
    which is deliberately not loopback-only; the two are different settings with
    different threat models and this parser is not reused for the database one.

    **Loopback-or-not is deliberately not decided here.** Until DP-035 D2 this
    function (then named ``_loopback_host``) refused any non-loopback value
    outright; whether a non-loopback value is ever acceptable now depends on a
    second setting, ``COSMA_API_BIND_SCOPE``, which a single-value ``Setting.parse``
    cannot see — so that half moved to ``_api_bind_is_permitted_for_scope`` below,
    a ``CrossCheck`` with access to both. What this parser alone still refuses,
    unconditionally, in every scope: a value that is not a literal IP address at
    all. SEC-002 has never accepted a host name for this setting, and that part
    of the rule needs no second setting to decide.
    """
    try:
        ipaddress.ip_address(value)
    except ValueError:
        raise _Rejected(
            "must be a literal IP address such as "
            f"{DEFAULT_API_HOST} or ::1, and a host name is not accepted"
        ) from None
    return value


_BIND_SCOPES: Final[frozenset[str]] = frozenset({"loopback", "container"})


def _bind_scope(value: str) -> str:
    """Accept ``loopback`` or ``container`` and refuse anything else (DP-035 D2).

    Refusing an unrecognised third value here — rather than falling back to
    whichever of the two is more permissive — is the same "no fallback for a
    rejected value" rule this module's docstring states for every other setting.
    """
    if value not in _BIND_SCOPES:
        raise _Rejected(f"must be one of {', '.join(sorted(_BIND_SCOPES))}")
    return value


def _credential_ref(value: str) -> str:
    """Accept a ``COSMA_SRC_*``/``COSMA_DB_*`` key name and refuse anything else.

    DP-032 D4: ``db_password_ref`` is a **name** in the secret store, never a
    value, and this refuses a malformed name (or a real value pasted by
    mistake) at config load rather than only failing later when
    ``resolve_credential`` looks it up — the same reasoning
    ``platform_core.secrets`` applies again at the point of resolution.
    """
    if not CREDENTIAL_REF_PATTERN.match(value):
        raise _Rejected(
            f"must be a secret-store key name matching {CREDENTIAL_REF_PATTERN.pattern}, "
            "and is never a value"
        )
    return value


SETTINGS: Final[Sequence[Setting]] = (
    # DP-032: a TCP host on the shared server, not P0-A's Unix-socket directory.
    Setting("COSMA_DB_HOST", "db_host", _text),
    Setting("COSMA_DB_PORT", "db_port", _port),
    Setting("COSMA_DB_NAME", "db_name", _text),
    Setting("COSMA_DB_USER", "db_user", _text),
    # A ref, not a value (DP-032 D4). Defaults to the runtime credential; the
    # migrator connects with a fixed ref of its own (platform_core.db.connection).
    Setting(
        "COSMA_DB_PASSWORD_REF", "db_password_ref", _credential_ref, default=DEFAULT_DB_PASSWORD_REF
    ),
    Setting("COSMA_LEASE_SECONDS", "lease_seconds", _positive_int, default="30"),
    Setting("COSMA_RETRY_BASE_MS", "retry_base_ms", _positive_int, default="100"),
    Setting("COSMA_RETRY_MAX_MS", "retry_max_ms", _positive_int, default="30000"),
    # How long a worker waits before asking an empty queue again.
    Setting("COSMA_POLL_MS", "poll_ms", _positive_int, default="200"),
    # Loopback, or — only under COSMA_API_BIND_SCOPE=container — the unspecified
    # address (SEC-002, DP-035 D2). The default applies when the variable is absent;
    # a stated, disallowed address is refused rather than replaced. Which addresses
    # are disallowed depends on api_bind_scope, decided by _api_bind_is_permitted_for_scope
    # below rather than by this parser alone — see _api_host_literal's own docstring.
    Setting("COSMA_API_HOST", "api_host", _api_host_literal, default=DEFAULT_API_HOST),
    # M-X2 (docs/agent-workflow/reviews/REVIEW-M2-M7.md): `8000` collides with
    # trend-radar's own live dashboard (DP-031 D3, `http://127.0.0.1:8000/api/v1`) — the
    # M7 demo ran the real platform API on `8100` with no stated reason and this default
    # never matched it. `8100` is the number recorded, now made the default rather than
    # left for every deployment to override to avoid a collision on the same host.
    Setting("COSMA_API_PORT", "api_port", _port, default="8100"),
    # DP-035 D2. `loopback` unless an operator explicitly opts into `container` —
    # see the module docstring's "What DP-035 D2 changes" paragraph.
    Setting("COSMA_API_BIND_SCOPE", "api_bind_scope", _bind_scope, default="loopback"),
    Setting("COSMA_LOG_LEVEL", "log_level", _level, default=DEFAULT_LEVEL),
    # Absent means standard error. The default is the empty string rather than
    # ``None`` because ``None`` is how this table spells "required"; a *stated*
    # empty value is still refused above, as every other setting's is.
    Setting("COSMA_LOG_FILE", "log_file", _log_file, default=""),
)

KNOWN_NAMES: Final[frozenset[str]] = frozenset(setting.name for setting in SETTINGS)

Problem = tuple[str, str]
"""(setting name, why it was rejected)."""

CrossCheck = Callable[[Mapping[str, Any], Mapping[str, str]], Problem | None]
"""(parsed values, the environment they came from) -> a problem, or ``None``."""


def _backoff_window_is_ordered(
    values: Mapping[str, Any], environment: Mapping[str, str]
) -> Problem | None:
    base = values.get("retry_base_ms")
    maximum = values.get("retry_max_ms")
    if base is None or maximum is None:
        return None
    if maximum < base:
        return ("COSMA_RETRY_MAX_MS", f"must be at least COSMA_RETRY_BASE_MS ({base})")
    return None


def _api_bind_is_permitted_for_scope(
    values: Mapping[str, Any], environment: Mapping[str, str]
) -> Problem | None:
    """SEC-002/DP-035 D2: decide the loopback-or-not half `_api_host_literal` could not.

    Loopback is permitted under every scope, unchanged from before DP-035. The
    unspecified address (``0.0.0.0``/``::``) is permitted only under ``container``
    scope. Every other address is refused under either scope — in particular, a
    routable non-loopback literal such as ``10.0.0.5`` is refused under ``container``
    scope exactly as it always was under the default: ``container`` widens what the
    *wildcard* address is for, not what any address is for.

    Runs only once both settings parsed cleanly; a value that already failed its own
    parser already has a problem recorded under its own setting name, and re-checking
    it here would only report the same misconfiguration twice under two names.
    """
    stated = values.get("api_host")
    scope = values.get("api_bind_scope")
    if stated is None or scope is None:
        return None
    address = ipaddress.ip_address(stated)
    if address.is_loopback:
        return None
    if scope == "container" and address.is_unspecified:
        return None
    return (
        "COSMA_API_HOST",
        "must be a loopback address; the wildcard/unspecified address is accepted "
        "only when COSMA_API_BIND_SCOPE=container (DP-035 D2), and every other "
        "non-loopback value is refused in every scope — P1 does not fall back to "
        f"loopback, but COSMA_API_HOST was {stated!r} under scope {scope!r}",
    )


def secret_store_location_problem(
    values: Mapping[str, Any], environment: Mapping[str, str]
) -> Problem | None:
    """Refuse a secret store whose resolved path lies inside the working tree.

    Unchanged from P0-A except for ``WORKING_TREE_ROOT``'s new depth. Three
    properties are the substance of SEC-001 and are easy to lose.

    * **The comparison is between resolved paths.** A path outside the tree whose
      target is a symbolic link into it is the case a naive check waves through.
      ``tests/conftest.py`` calls this function so the session guard and the
      startup guard cannot disagree about that.
    * **The store is never opened.** Location is the entire question.
    * **An unset variable is not a problem.** This stage resolves no credential
      itself; an absent store is a run with nothing to resolve, not a
      misconfigured one.
    """
    stated = environment.get(SECRET_STORE_VARIABLE, "").strip()
    if not stated:
        return None
    try:
        resolved = Path(stated).expanduser().resolve()
    except OSError:
        return None
    if resolved != WORKING_TREE_ROOT and WORKING_TREE_ROOT not in resolved.parents:
        return None
    return (
        SECRET_STORE_VARIABLE,
        "must name a path outside the repository working tree, but "
        f"{resolved} resolves inside {WORKING_TREE_ROOT} — "
        f"move the store outside the repository; see {SECRET_SETUP_POINTER}",
    )


CROSS_CHECKS: Final[Sequence[CrossCheck]] = (
    _backoff_window_is_ordered,
    _api_bind_is_permitted_for_scope,
    secret_store_location_problem,
)


def unrecognized_variables(environment: Mapping[str, str]) -> tuple[str, ...]:
    """The ``COSMA_``-prefixed names this stage does not know about."""
    return tuple(
        sorted(
            name
            for name in environment
            if name.startswith(PREFIX)
            and name not in KNOWN_NAMES
            and name not in RECOGNIZED_UNUSED
        )
    )


def load_config(environment: Mapping[str, str] | None = None) -> PlatformConfig:
    """Build a validated configuration, or raise ``ConfigurationInvalidError``.

    Every problem is collected before raising, so one restart shows an operator
    everything that is wrong rather than one item at a time.
    """
    env = os.environ if environment is None else environment
    problems: list[Problem] = []
    values: dict[str, Any] = {}

    for setting in SETTINGS:
        stated = env.get(setting.name)
        if stated is None:
            if setting.required:
                problems.append((setting.name, "is required but is not set"))
                continue
            given = setting.default
            assert given is not None
        else:
            given = stated.strip()
            if not given:
                problems.append((setting.name, "is set but empty; it must state a value"))
                continue
        try:
            values[setting.attribute] = setting.parse(given)
        except _Rejected as rejected:
            problems.append((setting.name, _reason_for(setting.name, given, rejected.reason)))

    for check in CROSS_CHECKS:
        problem = check(values, env)
        if problem is not None:
            problems.append(problem)

    if problems:
        raise ConfigurationInvalidError(_summary_of(problems), _detail_of(problems))

    values["unrecognized_variables"] = unrecognized_variables(env)
    return PlatformConfig(**values)


def _reason_for(name: str, given: str, reason: str) -> str:
    """Attach the offending value, unless the setting's name reads as a secret."""
    shown = REDACTION_MARKER if is_redacted_key(name) else repr(given)
    return f"{reason}, but was {shown}"


def _summary_of(problems: Iterable[Problem]) -> str:
    listed = "; ".join(f"{name} {reason}" for name, reason in problems)
    return f"invalid platform configuration: {listed}"


def _detail_of(problems: Iterable[Problem]) -> dict[str, Any]:
    return {"rejected": [{"setting": name, "reason": reason} for name, reason in problems]}
