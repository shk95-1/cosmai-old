"""SEC-003/SEC-002/SEC-001 cases for ``platform_core.config``, copy-adapted.

Narrower than P0's ``tests/test_config.py``: no entrypoints exist yet in this
milestone (Tasks 3-4 build config, secrets, connection, and migration only), so
there is nothing to spawn as a subprocess and no ``EX_CONFIG`` exit status to
observe from outside. What carries forward is the case table's substance —
required settings missing, a rejected value never substituting a default, a
non-loopback API host refused, the secret-store tree guard — plus the two cases
DP-032 adds: a TCP database host/port instead of a socket directory, and a
``db_password_ref`` whose name must match ``CREDENTIAL_REF_PATTERN``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from platform_core.config import (
    CREDENTIAL_REF_PATTERN,
    DEFAULT_API_HOST,
    DEFAULT_DB_PASSWORD_REF,
    KNOWN_NAMES,
    RECOGNIZED_UNUSED,
    SECRET_SETUP_POINTER,
    SECRET_STORE_VARIABLE,
    WORKING_TREE_ROOT,
    ConfigurationInvalidError,
    PlatformConfig,
    load_config,
    secret_store_location_problem,
    unrecognized_variables,
)

IPV6_LOOPBACK = "::1"

UNRELATED_NAME = "COSMA_TYPO_LEASE_SECONDS"
UNRELATED_VALUE = "45"
FOREIGN_NAME = "SOME_UNRELATED_VARIABLE"
FOREIGN_VALUE = "value-that-must-not-be-dumped"
SECRET_MARKER = "marker-must-not-leak-42"


@pytest.fixture
def baseline() -> dict[str, str]:
    """A valid environment naming no running server, mutated one case at a time.

    Unlike P0's baseline, ``COSMA_DB_HOST`` names no filesystem path at all —
    DP-032 makes it a TCP host string, so there is nothing left to require to
    exist on disk.
    """
    return {
        "COSMA_DB_HOST": "127.0.0.1",
        "COSMA_DB_PORT": "5433",
        "COSMA_DB_NAME": "cosmai_test",
        "COSMA_DB_USER": "tester",
    }


def rejection(environment: dict[str, str]) -> ConfigurationInvalidError:
    with pytest.raises(ConfigurationInvalidError) as raised:
        load_config(environment)
    return raised.value


def reported_text(error: ConfigurationInvalidError) -> str:
    return " ".join(
        [
            str(error),
            repr(error),
            str(error.operator_view()),
            str(error.detail.for_protected_debug()),
        ]
    )


# --- baseline and DP-032's new fields ----------------------------------------


def test_a_valid_baseline_loads_with_documented_defaults(baseline: dict[str, str]) -> None:
    config = load_config(baseline)
    assert config.db_host == "127.0.0.1"
    assert config.db_port == 5433
    assert config.db_name == "cosmai_test"
    assert config.db_user == "tester"
    assert config.db_password_ref == DEFAULT_DB_PASSWORD_REF == "COSMA_DB_RUNTIME"
    assert config.lease_seconds == 30
    assert config.retry_base_ms == 100
    assert config.retry_max_ms == 30000
    assert config.api_host == DEFAULT_API_HOST == "127.0.0.1"
    assert config.api_port == 8100
    assert config.log_level == "INFO"
    assert config.unrecognized_variables == ()
    assert config.warnings() == ()


def test_stated_values_override_the_defaults(baseline: dict[str, str]) -> None:
    config = load_config(
        {
            **baseline,
            "COSMA_DB_PASSWORD_REF": "COSMA_SRC_EXAMPLE_TOKEN",
            "COSMA_LEASE_SECONDS": "5",
            "COSMA_API_HOST": IPV6_LOOPBACK,
        }
    )
    assert config.db_password_ref == "COSMA_SRC_EXAMPLE_TOKEN"
    assert config.lease_seconds == 5
    assert config.api_host == IPV6_LOOPBACK


# --- required env missing (SEC-003 cases a-b, widened to db_port/db_user) ----


@pytest.mark.parametrize(
    "name", ["COSMA_DB_HOST", "COSMA_DB_PORT", "COSMA_DB_NAME", "COSMA_DB_USER"]
)
def test_a_required_database_setting_missing_is_refused(
    baseline: dict[str, str], name: str
) -> None:
    del baseline[name]
    error = rejection(baseline)
    assert error.error_class == "CONFIGURATION_INVALID"
    assert not error.retryable
    assert name in error.summary
    assert "is not set" in error.summary


def test_a_required_setting_stated_empty_is_refused_not_defaulted(baseline: dict[str, str]) -> None:
    baseline["COSMA_DB_HOST"] = "   "
    error = rejection(baseline)
    assert "COSMA_DB_HOST" in error.summary
    assert "is set but empty" in error.summary


# --- db_port is a real port, not a socket directory --------------------------


@pytest.mark.parametrize("given", ["not-a-port", "0", "-1", "70000", "3.5"])
def test_db_port_rejects_a_non_port_value(baseline: dict[str, str], given: str) -> None:
    error = rejection({**baseline, "COSMA_DB_PORT": given})
    assert "COSMA_DB_PORT" in error.summary


def test_db_host_is_a_plain_string_with_no_filesystem_check(baseline: dict[str, str]) -> None:
    """DP-032: unlike P0-A, a TCP host need not exist as a local path."""
    config = load_config({**baseline, "COSMA_DB_HOST": "db.example.internal"})
    assert config.db_host == "db.example.internal"


# --- db_password_ref: DP-032 D4's ref-pattern check ---------------------------


@pytest.mark.parametrize(
    "given",
    [
        "not-a-ref-at-all",
        "COSMA_DB_",
        "COSMA_SRC_",
        "COSMA_API_TOKEN",
        "cosma_db_runtime",
        "a-real-looking-password-value",
    ],
)
def test_db_password_ref_pattern_violation_is_refused(baseline: dict[str, str], given: str) -> None:
    error = rejection({**baseline, "COSMA_DB_PASSWORD_REF": given})
    assert "COSMA_DB_PASSWORD_REF" in error.summary
    # The setting's name reads as a secret (contains "password"), so the offending
    # value is withheld even though a ref name is not itself a credential value.
    assert "[REDACTED]" in error.summary
    assert repr(given) not in error.summary


@pytest.mark.parametrize(
    "given", ["COSMA_DB_RUNTIME", "COSMA_DB_MIGRATOR", "COSMA_SRC_NAVER_BLOG_TOKEN"]
)
def test_db_password_ref_accepts_both_key_families(baseline: dict[str, str], given: str) -> None:
    config = load_config({**baseline, "COSMA_DB_PASSWORD_REF": given})
    assert config.db_password_ref == given
    assert CREDENTIAL_REF_PATTERN.match(given)


# --- no default is substituted for a rejected value ---------------------------


@pytest.mark.parametrize(
    ("name", "given"),
    [
        ("COSMA_LEASE_SECONDS", "0"),
        ("COSMA_RETRY_BASE_MS", "nope"),
        ("COSMA_API_PORT", "70000"),
        ("COSMA_LOG_LEVEL", "LOUD"),
        ("COSMA_DB_PASSWORD_REF", "not-a-ref"),
    ],
)
def test_no_default_is_substituted_for_a_rejected_value(
    baseline: dict[str, str], name: str, given: str
) -> None:
    error = rejection({**baseline, name: given})
    assert name in error.summary


def test_every_problem_is_named_in_one_report(baseline: dict[str, str]) -> None:
    del baseline["COSMA_DB_NAME"]
    error = rejection({**baseline, "COSMA_LEASE_SECONDS": "0", "COSMA_API_PORT": "0"})
    for name in ("COSMA_DB_NAME", "COSMA_LEASE_SECONDS", "COSMA_API_PORT"):
        assert name in error.summary
    rejected = error.detail.for_protected_debug()["rejected"]
    assert {item["setting"] for item in rejected} == {
        "COSMA_DB_NAME",
        "COSMA_LEASE_SECONDS",
        "COSMA_API_PORT",
    }


# --- unknown variable is reported, not fatal (SEC-003 case f) ----------------


def test_an_unknown_prefixed_variable_is_reported_and_not_fatal(baseline: dict[str, str]) -> None:
    config = load_config({**baseline, UNRELATED_NAME: UNRELATED_VALUE})
    assert config.unrecognized_variables == (UNRELATED_NAME,)
    warnings = config.warnings()
    assert len(warnings) == 1
    assert UNRELATED_NAME in warnings[0]


def test_a_variable_outside_the_prefix_is_not_even_reported(baseline: dict[str, str]) -> None:
    config = load_config({**baseline, FOREIGN_NAME: FOREIGN_VALUE})
    assert config.unrecognized_variables == ()


def test_the_known_and_recognized_names_do_not_overlap() -> None:
    assert not KNOWN_NAMES & RECOGNIZED_UNUSED
    assert unrecognized_variables(dict.fromkeys(RECOGNIZED_UNUSED, "x")) == ()
    assert unrecognized_variables(dict.fromkeys(KNOWN_NAMES, "x")) == ()


# --- the report never dumps the environment -----------------------------------


def test_the_report_names_settings_but_never_dumps_the_environment(
    baseline: dict[str, str],
) -> None:
    del baseline["COSMA_DB_HOST"]
    error = rejection(
        {
            **baseline,
            FOREIGN_NAME: FOREIGN_VALUE,
            UNRELATED_NAME: UNRELATED_VALUE,
            "COSMA_API_TOKEN": SECRET_MARKER,
        }
    )
    text = reported_text(error)
    assert "COSMA_DB_HOST" in text
    assert FOREIGN_VALUE not in text
    assert FOREIGN_NAME not in text
    assert SECRET_MARKER not in text
    assert baseline["COSMA_DB_USER"] not in text


# --- SEC-002: the operator API's loopback bind, unchanged from P0-A ----------


def test_the_default_bind_address_is_loopback(baseline: dict[str, str]) -> None:
    assert "COSMA_API_HOST" not in baseline
    config = load_config(baseline)
    assert config.api_host == DEFAULT_API_HOST


@pytest.mark.parametrize(
    "given", ["0.0.0.0", "::", "192.168.1.10", "10.0.0.5", "localhost", "example.com", ""]
)
def test_a_non_loopback_api_host_is_refused(baseline: dict[str, str], given: str) -> None:
    error = rejection({**baseline, "COSMA_API_HOST": given})
    assert error.error_class == "CONFIGURATION_INVALID"
    assert not error.retryable
    assert "COSMA_API_HOST" in error.summary


def test_the_wildcard_api_host_is_not_silently_corrected(baseline: dict[str, str]) -> None:
    wildcard = "0.0.0.0"
    error = rejection({**baseline, "COSMA_API_HOST": wildcard})
    assert wildcard in error.summary
    assert "does not fall back" in error.summary


def test_database_tcp_host_is_never_forced_to_loopback(baseline: dict[str, str]) -> None:
    """The database host is DP-032's shared server; SEC-002 must not reach it."""
    config = load_config({**baseline, "COSMA_DB_HOST": "10.0.0.5"})
    assert config.db_host == "10.0.0.5"


# --- DP-035 D2: COSMA_API_BIND_SCOPE and the container-bind opt-in -----------


def test_the_default_scope_is_loopback(baseline: dict[str, str]) -> None:
    assert "COSMA_API_BIND_SCOPE" not in baseline
    config = load_config(baseline)
    assert config.api_bind_scope == "loopback"


def test_the_default_scope_still_refuses_the_wildcard_address(baseline: dict[str, str]) -> None:
    """The positive control the packet names by name: the container opt-in must not have
    widened what the *default* scope accepts. Without `COSMA_API_BIND_SCOPE` stated at
    all, `0.0.0.0` is refused exactly as it was before this setting existed —
    `test_a_non_loopback_api_host_is_refused` above already covers this value as one of
    several; this asserts it on its own, under the name DP-035's acceptance criteria use."""
    assert "COSMA_API_BIND_SCOPE" not in baseline
    error = rejection({**baseline, "COSMA_API_HOST": "0.0.0.0"})
    assert "COSMA_API_HOST" in error.summary


@pytest.mark.parametrize("wildcard", ["0.0.0.0", "::"])
def test_container_scope_accepts_the_wildcard_address(
    baseline: dict[str, str], wildcard: str
) -> None:
    config = load_config(
        {**baseline, "COSMA_API_BIND_SCOPE": "container", "COSMA_API_HOST": wildcard}
    )
    assert config.api_bind_scope == "container"
    assert config.api_host == wildcard


def test_container_scope_still_refuses_a_routable_non_loopback_literal(
    baseline: dict[str, str],
) -> None:
    """`container` widens what the *wildcard* address is for, not what any address is
    for: a real fleet-network literal like `10.0.0.5` is not the unspecified address and
    stays refused."""
    error = rejection(
        {**baseline, "COSMA_API_BIND_SCOPE": "container", "COSMA_API_HOST": "10.0.0.5"}
    )
    assert "COSMA_API_HOST" in error.summary


def test_container_scope_still_accepts_loopback(baseline: dict[str, str]) -> None:
    """The control: `container` scope is a widening, not a replacement of the loopback
    case every other test in this module already exercises."""
    config = load_config(
        {**baseline, "COSMA_API_BIND_SCOPE": "container", "COSMA_API_HOST": DEFAULT_API_HOST}
    )
    assert config.api_host == DEFAULT_API_HOST


@pytest.mark.parametrize("given", ["Container", "LOOPBACK", "public", "", "0"])
def test_an_invalid_bind_scope_value_is_refused(baseline: dict[str, str], given: str) -> None:
    error = rejection({**baseline, "COSMA_API_BIND_SCOPE": given})
    assert "COSMA_API_BIND_SCOPE" in error.summary


def test_an_invalid_bind_scope_is_refused_even_with_an_otherwise_valid_host(
    baseline: dict[str, str],
) -> None:
    """A malformed scope is refused on its own account rather than silently treated as
    whichever scope happens to be more permissive for the host value given alongside it."""
    error = rejection(
        {**baseline, "COSMA_API_BIND_SCOPE": "public", "COSMA_API_HOST": DEFAULT_API_HOST}
    )
    assert "COSMA_API_BIND_SCOPE" in error.summary


# --- SEC-001: the secret-store tree guard, unchanged in behaviour ------------


def test_an_unset_store_is_not_a_configuration_error(baseline: dict[str, str]) -> None:
    assert SECRET_STORE_VARIABLE not in baseline
    config = load_config(baseline)
    assert isinstance(config, PlatformConfig)
    assert secret_store_location_problem({}, baseline) is None


def test_a_store_that_exists_in_the_repository_root_is_refused(
    baseline: dict[str, str],
) -> None:
    inside = WORKING_TREE_ROOT / ".tmp-task3-sec-001-store"
    inside.write_text("COSMA_DB_RUNTIME=not-a-real-value\n", encoding="utf-8")
    try:
        error = rejection({**baseline, SECRET_STORE_VARIABLE: str(inside)})
        assert error.error_class == "CONFIGURATION_INVALID"
        assert SECRET_STORE_VARIABLE in error.summary
        assert SECRET_SETUP_POINTER in error.summary
    finally:
        inside.unlink(missing_ok=True)


def test_a_store_outside_the_working_tree_is_accepted(
    baseline: dict[str, str], tmp_path: Path
) -> None:
    outside = tmp_path / "env"
    outside.write_text("COSMA_DB_RUNTIME=not-a-real-value\n", encoding="utf-8")
    outside.chmod(0o600)
    config = load_config({**baseline, SECRET_STORE_VARIABLE: str(outside)})
    assert isinstance(config, PlatformConfig)


def test_the_platform_and_a_fresh_measurement_agree_on_the_working_tree() -> None:
    assert Path(__file__).resolve().parents[2] == WORKING_TREE_ROOT
    assert (WORKING_TREE_ROOT / "AGENTS.md").is_file()


# --- immutability --------------------------------------------------------------


def test_the_configuration_is_immutable(baseline: dict[str, str]) -> None:
    config = load_config(baseline)
    with pytest.raises(AttributeError):
        config.lease_seconds = 1  # type: ignore[misc]
