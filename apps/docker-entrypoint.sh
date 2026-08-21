#!/bin/sh
# Dispatches the cosmai platform image on its container command. Each branch
# `exec`s the process entrypoint documented at the top of its own module:
#
#   migrate    python -m platform_core.db          (apps/platform_core/db/__main__.py)
#   api        python -m addon_host                (apps/addon_host/__main__.py — platform + domain surface)
#   worker     python -m addon_host.worker          (apps/addon_host/worker.py)
#   scheduler  python -m scheduler                  (apps/scheduler/__main__.py)
#
# `exec` replaces this shell with the Python process (pid 1), so `SIGTERM` from
# `docker stop`/compose reaches the process's own signal handler directly
# rather than a shell that would otherwise have to be taught to forward it.
#
# `api` and `worker` reuse `addon_host`'s entrypoints, not `platform_core`'s
# bare ones: `python -m platform_core.api`/`platform_core.worker` serve the
# source-neutral platform surface with no add-on layer, which is what P0-A's
# gate evidence measured and must keep meaning that; a real deployment needs
# the domain routes and the installed add-ons, which is exactly what
# `addon_host`'s pair adds on top (see each module's own docstring).

set -eu

case "${1:-}" in
  migrate)
    exec python -m platform_core.db
    ;;
  api)
    exec python -m addon_host
    ;;
  worker)
    exec python -m addon_host.worker
    ;;
  scheduler)
    shift
    exec python -m scheduler "$@"
    ;;
  *)
    echo "usage: ${0##*/} migrate|api|worker|scheduler [args...]" >&2
    exit 64
    ;;
esac
