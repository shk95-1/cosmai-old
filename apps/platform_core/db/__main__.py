"""The migration process entrypoint: ``python -m platform_core.db`` (M8 deploy).

Written for the container ``migrate`` command (`apps/Dockerfile`): a one-shot
process that applies every unapplied file under ``platform_core.db.migrations``
through a migrator connection, reports what it did, and exits. Nothing here is
new policy — it is the same three calls ``apps/tests/conftest.py``'s
``migrator_connection`` fixture and ``apps/tests/test_migrate.py`` already
exercise (``load_config`` → ``connect(role="migrator")`` →
``apply_migrations``) — wired as a process rather than a fixture, because a
deploy needs a command that exits, not a pytest fixture.

Same shape as the other P1 entrypoints (`platform_core.api`, `platform_core.worker`,
`scheduler`): configuration is resolved first and a refusal is fatal
(``EXIT_CONFIGURATION_INVALID``), a driver failure is classified rather than
left as a raw traceback, and the process reports what happened as one JSON
object on standard output before exiting — the same "report on the way out"
convention ``platform_core.worker`` uses for its shutdown report, sized down to
what a one-shot applier has to say (the versions it applied, or none if the
schema was already current).
"""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence

from platform_core.config import load_config
from platform_core.db.connection import connect
from platform_core.db.migrate import apply_migrations
from platform_core.errors import PlatformError
from platform_core.obs.logging import StructuredLogger

EXIT_OK = 0

#: The same split every other P1 entrypoint makes: a bind/connect failure that
#: a supervisor may retry versus a configuration error that will not resolve
#: on its own.
EXIT_UNAVAILABLE = 1
EXIT_CONFIGURATION_INVALID = 78

REPORT_EVENT = "migrate.report"


def main(argv: Sequence[str] | None = None) -> int:
    """Resolve configuration, apply migrations, report, exit. No arguments."""
    del argv  # nothing on the command line; every setting is environment-sourced
    try:
        config = load_config()
    except PlatformError as invalid:
        StructuredLogger().error(
            "migrate.configuration_invalid",
            error_class=invalid.error_class.value,
            error_summary=invalid.summary,
        )
        return EXIT_CONFIGURATION_INVALID

    logger = StructuredLogger.resolved(config.log_file, config.log_level)
    try:
        for warning in config.warnings():
            logger.warning("migrate.configuration_warning", detail=warning)
        try:
            connection = connect(config, role="migrator")
        except PlatformError as failure:
            logger.error(
                "migrate.connect_failed",
                error_class=failure.error_class.value,
                error_summary=failure.summary,
            )
            return (
                EXIT_CONFIGURATION_INVALID
                if failure.error_class.value == "CONFIGURATION_INVALID"
                else EXIT_UNAVAILABLE
            )
        try:
            applied = apply_migrations(connection)
        finally:
            connection.close()
        logger.info("migrate.applied", versions=applied)
        report = {"event": REPORT_EVENT, "applied": applied}
        sys.stdout.write(json.dumps(report, ensure_ascii=False) + "\n")
        sys.stdout.flush()
        return EXIT_OK
    finally:
        logger.close()


if __name__ == "__main__":  # pragma: no cover - exercised as a process, not imported
    sys.exit(main())
