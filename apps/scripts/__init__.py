"""Operational one-shot scripts, run by hand rather than imported.

Not a runtime dependency of anything under ``platform_core``/``domain``/``addon_host`` —
this package exists only so a script here is reachable as ``python -m scripts.<name>``
from the ``apps/`` venv, the same invocation shape ``platform_core.worker`` and
``scheduler`` already use for their own entrypoints.
"""

from __future__ import annotations
