# syntax=docker.io/docker/dockerfile-upstream:1.27-labs
# check=error=true
# https://docs.docker.com/build/buildkit/dockerfile-release-notes/

# Pins: .python-version (uv reads it) + versions/{ubuntu,uv,shellcheck,apt}
# run.sh docker:build passes UBUNTU_VERSION / PYTHON_VERSION / UV_VERSION.
# Raw `docker build .` should fail, not drift.
# No alpine: uv official images are musl; musl DNS breaks some builders
# (astral-sh/uv#8450, #16741). basedpyright / nodejs wheels are glibc.
# Venv at /.venv so a /app bind-mount cannot clobber it.

ARG UBUNTU_VERSION
ARG PYTHON_VERSION
ARG UV_VERSION
ARG UV_HTTP_TIMEOUT=120
ARG VIRTUAL_ENV=/.venv

FROM ghcr.io/astral-sh/uv:${UV_VERSION:-ERROR} AS uv

FROM ubuntu:${UBUNTU_VERSION:-ERROR} AS base
ARG PYTHON_VERSION
ARG VIRTUAL_ENV
ENV DEBIAN_FRONTEND=noninteractive \
    UV_PYTHON=${PYTHON_VERSION} \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_LOCKED=1 \
    UV_PROJECT_ENVIRONMENT="$VIRTUAL_ENV" \
    VIRTUAL_ENV="$VIRTUAL_ENV" \
    UV_PYTHON_INSTALL_DIR=/opt/uv-python
ENV PATH="${VIRTUAL_ENV}/bin:/usr/local/bin:$PATH"
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    --mount=type=bind,source=versions/apt,target=/tmp/apt \
  rm -f /etc/apt/apt.conf.d/docker-clean \
 && apt-get update \
 && xargs -a /tmp/apt apt-get install -y --no-install-recommends
COPY --link --from=uv /uv /uvx /bin/
WORKDIR /app
# Pin files + run.sh only (not COPY): changing src does not bust this layer.
RUN --mount=type=bind,source=run.sh,target=/opt/fs/run.sh \
    --mount=type=bind,source=versions,target=/opt/fs/versions \
    --mount=type=bind,source=.python-version,target=/opt/fs/.python-version \
  bash /opt/fs/run.sh setup:check-image @@ setup:shellcheck
ENTRYPOINT ["bash"]

# Allowlist [project] name/version/requires-python/dependencies + dependency-groups
# + tool.uv + build-system. ruff/pytest/comment churn does not bust the deps layer.
# tomli/tomli-w: py3.10 has no stdlib tomllib. Library image: all groups (test/debug).
# pyproject_mvp.py: PEP 723 inline deps (`uv run --script`).
FROM base AS pp-toml
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=scripts/pyproject_mvp.py,target=pyproject_mvp.py \
    --mount=type=bind,source=pyproject.toml,target=pyproject.in.toml \
  UV_LOCKED= uv run --script ./pyproject_mvp.py -i pyproject.in.toml -o /pyproject.toml

FROM base AS dev
ARG UV_HTTP_TIMEOUT
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,from=pp-toml,source=/pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    uv sync --locked --no-install-project --all-groups \
 && chmod -R a+rX /opt/uv-python \
 && chmod -R a+rwX /.venv

FROM dev AS prod
COPY --link . .
ARG UV_HTTP_TIMEOUT
RUN --mount=type=cache,target=/root/.cache/uv \
  uv sync --locked --all-groups \
 && chmod -R a+rwX /.venv

ENTRYPOINT ["./run.sh"]
CMD ["bash"]

FROM prod AS build
RUN ./run.sh pkg:build
