# cosmai platform image — api / worker / scheduler / migrate, one image, one
# ENTRYPOINT dispatching on the container command (M8 deploy, see
# docs/p1/M8-DEPLOY-RECORD.md).
#
# Build context is this directory (`apps/`) — the stack compose builds it with
# `build: { context: ${COSMAI_REPO:-../cosmai}/apps, dockerfile: Dockerfile }`.
#
# **Why the copy preserves `apps/` as a subdirectory of `/app` rather than
# flattening it to `/app`.** `platform_core.secrets.secret_store_path` refuses a
# secret store that resolves inside `WORKING_TREE_ROOT`
# (`Path(__file__).resolve().parents[2]`, i.e. two directories above
# `platform_core/secrets.py`). Flattening `apps/*` directly into `/app` would put
# `secrets.py` at `/app/platform_core/secrets.py`, whose `parents[2]` is `/` —
# every absolute path has `/` as an ancestor, so the guard would refuse *every*
# secret-store location, including the one this image is told to use. Keeping the
# nesting (`/app/apps/platform_core/secrets.py`) makes `WORKING_TREE_ROOT`
# resolve to `/app`, an ordinary directory the mounted secret file
# (`/run/cosmai/env`, outside `/app`) is never inside of — exactly the same
# relationship the repository checkout has locally.
FROM python:3.13-slim

# uv, copied from its own distroless image rather than installed with pip —
# smaller layer, pinned version.
COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /uvx /usr/local/bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/tmp

WORKDIR /app/apps

# Dependencies first, so an application-code-only change does not invalidate
# this layer. `--no-install-project`: nothing here is installed as a package
# anyway (`[tool.uv] package = false`), this just seeds the dependency set
# before the source tree that would otherwise make `uv sync` reinstall on
# every layer change.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# The rest of the tree. `.dockerignore` (repository root of this context)
# excludes `.venv/`, `dashboard/node_modules/`, `.pytest_cache/`, `.mypy_cache/`,
# `.ruff_cache/`, `__pycache__/`, and `dashboard/` itself (built by
# `Dockerfile.dashboard`, not this image).
COPY . .
RUN uv sync --frozen --no-dev

# `uv run` re-checks the lock/sync state on every invocation; the venv is
# already synced above, so the runtime path calls the venv's python directly
# and skips that check.
ENV PATH="/app/apps/.venv/bin:${PATH}"

# Readable and executable by any uid — the stack compose runs this image as
# `user: "1000"` (the host user, not this image's build-time root), the same
# non-default-uid pattern the stack's tubedepth image already uses and for the
# same reason: no image-baked uid can be guaranteed to match the host's bind-mount
# owner on an unprivileged host. Nothing under `/app` is written to at runtime
# (the migrator writes to the database, not the filesystem; the one filesystem
# write path — `platform_core.secrets.write_credential` — targets the mounted
# secret file, not this tree), so root-owned-but-world-readable is sufficient;
# no `chown` is needed.
RUN chmod -R a+rX /app

COPY docker-entrypoint.sh /usr/local/bin/cosmai-entrypoint
RUN chmod a+rx /usr/local/bin/cosmai-entrypoint

ENTRYPOINT ["cosmai-entrypoint"]
CMD ["api"]
