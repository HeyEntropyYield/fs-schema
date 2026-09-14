# syntax=docker.io/docker/dockerfile-upstream:1.27-labs
# check=error=true
# https://docs.docker.com/build/buildkit/dockerfile-release-notes/

# No alpine: uv official images are musl; musl DNS breaks some builders
# (astral-sh/uv#8450, #16741). basedpyright/nodejs wheels are glibc.
# No ARG defaults: run.sh docker:build always passes PYTHON_VERSION / UV_VERSION
# from .python-version / .uv-version. Raw `docker build .` should fail, not drift.

ARG PYTHON_VERSION
ARG UV_VERSION
ARG UV_HTTP_TIMEOUT=120
ARG VIRTUAL_ENV=/.venv

FROM ghcr.io/astral-sh/uv:${UV_VERSION:-ERROR} AS uv
# COPY --from var exp not supported

FROM python:${PYTHON_VERSION:-ERROR}-slim-bookworm AS base
ARG PYTHON_VERSION
COPY --from=uv /uv /uvx /bin/
WORKDIR /app
ARG VIRTUAL_ENV
# UV_PYTHON must beat copied .python-version, else docker:matrix tags lie
# (3.11 image silently syncs CPython 3.10 from the file).
ENV UV_PYTHON=${PYTHON_VERSION} \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_LOCKED=1 \
    UV_PROJECT_ENVIRONMENT="$VIRTUAL_ENV"

ENTRYPOINT ["bash"]

# Allowlist [project] name/version/requires-python/dependencies + dependency-groups
# + tool.uv + build-system. ruff/pytest/comment churn does not bust the deps layer.
# tomli/tomli-w: py3.10 has no stdlib tomllib. Library image: all groups (test/debug).
FROM base AS pp-toml
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=scripts/pyproject_mvp.py,target=pyproject_mvp.py \
    --mount=type=bind,source=pyproject.toml,target=pyproject.in.toml \
  uv run --no-project --with tomli --with tomli-w --with docopt --with typing-extensions \
    ./pyproject_mvp.py -i pyproject.in.toml -o /pyproject.toml

FROM base AS dev
ARG UV_HTTP_TIMEOUT
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,from=pp-toml,source=/pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    uv sync --locked --no-install-project --all-groups \
 && chmod -R a+rwX /.venv

FROM dev AS prod
COPY . .
ARG UV_HTTP_TIMEOUT
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --all-groups \
 && chmod -R a+rwX /app /.venv

ENTRYPOINT ["./run.sh"]
CMD ["bash"]

FROM prod AS build
RUN ./run.sh pkg:build
