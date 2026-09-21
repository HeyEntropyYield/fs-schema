#!/usr/bin/env bash
# run.sh
# shellcheck disable=SC2119,SC2120,SC2016

# Host uv = lock/sync/version. After sync, cmds use .venv/bin (no uv run).
# versions/uv pins the uv binary for GHA and Docker; host uv uses required-version.
# Host range: [tool.uv] required-version. uv reads .python-version.

readonly PROJECT_NAME=fs-schema
readonly IMAGE_NAME="${PROJECT_NAME}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly ROOT_DIR
if [ -n "${UV_PROJECT_ENVIRONMENT:-}" ]; then
  VENV_BIN="$UV_PROJECT_ENVIRONMENT/bin"
else
  VENV_BIN="$ROOT_DIR/.venv/bin"
fi
readonly VENV_BIN
_pin(){ tr -d '[:space:]' < "$ROOT_DIR/${1:?}"; }
DEFAULT_PYTHON="$(_pin .python-version)"
readonly DEFAULT_PYTHON
UV_PIN="$(_pin versions/uv)"
readonly UV_PIN
SHELLCHECK_PIN="$(_pin versions/shellcheck)"
readonly SHELLCHECK_PIN
UBUNTU_PIN="$(_pin versions/ubuntu)"
readonly UBUNTU_PIN
# Pinned CI binaries beat distro copies (GHA ubuntu-24.04 apt shellcheck is 0.9).
PATH="${HOME:-/tmp}/.local/bin:/usr/local/bin:$PATH"
# Local tox/docker only. GHA matrix = package classifiers (baipp).
readonly PYTHON_VERSIONS="3.10 3.11 3.12 3.13 3.14"

_BRANCH="$(git -C "$ROOT_DIR" branch --show-current 2>/dev/null | tr '/' '-' ||:)"
readonly _BRANCH
readonly BRANCH="${_BRANCH:-local}"

# @describe Usual path + command list
help(){
  cat <<'EOF'
Dev:
  ./run.sh setup:install-pre-commit
  ./run.sh uv:venv:sync
  ./run.sh pretty / check / tests
  ./run.sh docs:serve

Maintainer:
  ./run.sh pkg:bump VERSION
  ./run.sh release:check
  ./run.sh release:tag
  ./run.sh gh:ci [ref]
  ./run.sh gh:docs [ref]
  ./run.sh gh:publish:testpypi [ref]
  ./run.sh gh:publish:pypi
  ./run.sh gh:release
  ./run.sh release:testpypi
  ./run.sh release:pypi

Lock: edit pyproject.toml, then ./run.sh uv:lock
MRE: ./run.sh docker:check / docker:test

Commands:
EOF
  awk '
    /^## .+/ { sub(/^##/,"",$0); print $0 }
    /^# @describe / { d=$0; sub(/^# @describe /,"",d) }
    /^[A-Za-z0-9_.:-]+\(\)/ {
      n=$0; sub(/\(\).*/,"",n)
      if (d != "" && n !~ /(^|:)_/) printf "  %-28s %s\n", n, d
      d=""
    }
  ' "$0"
}

# @describe Read or update the package version and lockfile
pkg:version(){ uv version "$@"; }

# @describe Update version, lockfile, & commit
# @arg version! PEP 440 package version
pkg:bump(){
  _require_clean || return $?
  [ $# -eq 1 ] || { : "usage: ./run.sh pkg:bump VERSION"; return 2; }
  uv version "$1" || return $?
  git add pyproject.toml uv.lock || return $?
  git commit -m "v$(uv version --short)" && return 0
  printf 'fix errors and commit: git commit -m "v$(uv version --short)"\n'
  return 1
}

# @describe Build sdist and wheel into dist/
pkg:build(){ uv build --no-sources --clear "$@"; }

main(){ pkg:version || return $?; help || return $?; echo -e '\nChain: `./run.sh fn1 arg1 @@ fn2 arg1`'; }

## Setup

# @describe Install git hooks (once per clone; sync first)
setup:install-pre-commit(){
  _need_venv || return $?
  pre-commit install --hook-type pre-commit --hook-type commit-msg --hook-type pre-push || return $?
}

# @describe Install pinned shellcheck if not found
setup:shellcheck(){
  local dest arch
  if command -v shellcheck >/dev/null \
     && [ "$(shellcheck --version | awk '/^version:/{print $2; exit}')" = "$SHELLCHECK_PIN" ]; then
    return 0
  fi
  dest=/usr/local/bin
  [ "$(id -u)" -eq 0 ] || { dest="${HOME:-/tmp}/.local/bin"; mkdir -p "$dest"; }
  arch="$(uname -m)"; [ "$arch" = arm64 ] && arch=aarch64
  curl -fsSL "https://github.com/koalaman/shellcheck/releases/download/v${SHELLCHECK_PIN}/shellcheck-v${SHELLCHECK_PIN}.linux.${arch}.tar.xz" \
    | tar -xJ -C "$dest" --strip-components=1 --wildcards '*/shellcheck'
}

# @describe Assert /etc/os-release and apt pkgs match pinned versions
setup:check-image(){
  local got pkg
  got="$(. /etc/os-release && printf '%s' "$VERSION_ID")"
  [ "$got" = "$UBUNTU_PIN" ] || { : "os $got != pin $UBUNTU_PIN (versions/ubuntu)"; return 1; }
  while read -r pkg; do
    [ -n "$pkg" ] || continue
    dpkg-query -W "$pkg" >/dev/null 2>&1 || { : "missing apt $pkg (versions/apt)"; return 1; }
  done < "$ROOT_DIR/versions/apt"
}

# @describe Checks all host deps present
setup:check-installs(){
  local ret=0
  _has_cmd uv || ret=$?
  _has_cmd docker || ret=$?
  _need_shellcheck || ret=$?
  command -v act >/dev/null || echo "act not on PATH (optional; ./run.sh ci:_act)"
  command -v gh >/dev/null || echo "gh not on PATH (optional; remote maintainer commands)"
  return "$ret"
}

## Dep management

# @describe Sync .venv from uv.lock (no resolve)
uv:venv:sync(){ uv sync --locked "$@" || return $?; }

# @describe Write uv.lock. Edit pyproject.toml by hand first (no uv add)
# @option -U --upgrade              Upgrade all packages
# @option --upgrade-package <spec>  One pkg, or pkg==ver
# @arg rest~ extra uv lock args
uv:lock(){ uv lock "$@" || return $?; }

# @describe Re-create uv.lock from scratch, ignore current pins
# @arg rest~ extra uv lock args
uv:lock:bootstrap(){
  printf 'version = 1\nrevision = 3\nrequires-python = ">=%s"\n' "$DEFAULT_PYTHON" > uv.lock
  uv lock "$@" || return $?
}

## Dev: checks

# @describe ruff check + shellcheck
lint(){
  _need_venv || return $?
  ruff check src tests examples scripts "$@" || return $?
  _need_shellcheck || return $?
  shellcheck -x "$ROOT_DIR/run.sh" "$ROOT_DIR/scripts/beartype" || return $?
}

# @describe basedpyright
typecheck(){ _need_venv || return $?; basedpyright "$@" || return $?; }

# @describe pre-commit + docs build
check(){
  _need_venv || return $?
  pre-commit run --all-files "$@" || return $?
  docs:build || return $?
}

# @describe pytest against the installed package
tests(){ _need_venv || return $?; python -I -m pytest "$@" || return $?; }

## Dev: formatters

# @describe ruff format
fmt(){ _need_venv || return $?; ruff format src tests examples scripts "$@" || return $?; }

# @describe fmt + ruff check --fix
pretty(){ fmt || return $?; lint --fix "$@" || return $?; }

## Docs

# @describe Refresh docs/run-help.txt from ./run.sh help
docs:_sync-help(){
  local target="$ROOT_DIR/docs/run-help.txt" temporary
  temporary="$(mktemp)" || return $?
  if "$ROOT_DIR/run.sh" help > "$temporary" 2>&1 && cat "$temporary" > "$target"; then
    rm -f "$temporary"
    return 0
  fi
  rm -f "$temporary"
  return 1
}

# @describe Build the docs site into site/
docs:build(){
  _need_venv || return $?
  docs:_sync-help || return $?
  zensical build --clean "$@" || return $?
}

# @describe Serve docs locally
docs:serve(){
  _need_venv || return $?
  docs:_sync-help || return $?
  zensical serve "$@" || return $?
}

# @describe Run docs.yml locally via act
# @arg rest~ extra act args
docs:_deploy(){ _workflow_local docs.yml "$@" || return $?; }

## CI / maintainer

# @describe Run test.yml locally via act (check -> build wheel -> test wheel -> coverage)
# @arg rest~ extra act args
ci:_act(){ _workflow_local test.yml "$@" || return $?; }

# @describe GHA helper: tox for PYTHON_VERSION (or .python-version) vs --installpkg
# @arg rest~ tox args
ci:_test(){
  local py="${PYTHON_VERSION:-$DEFAULT_PYTHON}"
  _need_venv || return $?
  tox run -e "$py" "$@" || return $?
}

# @describe GHA helper: combine coverage artifacts and report
ci:_coverage(){
  _need_venv || return $?
  coverage combine || return $?
  coverage html --skip-covered --skip-empty || return $?
  if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
    coverage report --format=markdown >> "$GITHUB_STEP_SUMMARY" || return $?
  fi
  coverage report || return $?
  _coverage_badge || return $?
}

# @describe Write shields.io endpoint JSON from the combined coverage total
_coverage_badge(){
  local pct
  pct="$(coverage report --format=total)" || return $?
  COVERAGE_PCT="$pct" python -c '
import json, os
from pathlib import Path
pct = int(round(float(os.environ["COVERAGE_PCT"])))
color = "brightgreen" if pct >= 95 else "yellow" if pct >= 80 else "red"
Path("coverage.json").write_text(
    json.dumps({"schemaVersion": 1, "label": "coverage", "message": f"{pct}%", "color": color}) + "\n",
    encoding="utf-8",
)
'
}

# @describe Local tox matrix (no act). skip_missing_interpreters in tox.
# @arg rest~ extra tox args
ci:tox(){
  local envs
  envs="$(echo "$PYTHON_VERSIONS" | tr ' ' ',')"
  _need_venv || return $?
  tox run -e "$envs" "$@" || return $?
  ci:_coverage || return $?
}

# @describe Run scripts/release.py under the beartype launcher
# @arg rest~ release.py argv
_release(){ _need_venv || return $?; "$ROOT_DIR/scripts/beartype" "$ROOT_DIR/scripts/release.py" "$@"; }

# @describe Build, inspect, and clean-install both local artifacts
release:check(){
  local version
  _need_venv || return $?
  release:_check-ref || return $?
  check || return $?
  ci:tox || return $?
  rm -rf dist
  pkg:build || return $?
  twine check dist/* || return $?
  check-wheel-contents dist/*.whl || return $?
  version="$(_release version)" || return $?
  _release smoke "dist/fs_schema-$version-py3-none-any.whl" --expected "$version" || return $?
  _release smoke "dist/fs_schema-$version.tar.gz" --expected "$version" || return $?
}

# @describe Validate version metadata and HEAD commit provenance
# @option --release Require HEAD to be the matching version-only commit
release:_check-ref(){ _release check-ref "$@"; }

# @describe Validate commits introduced by BASE..HEAD
# @arg base! Excluded base commit; 40 zeroes means a new ref
# @arg head Included head commit; defaults to HEAD
release:_check-range(){ _release check-range "$@"; }

# @describe Require an exact vVERSION tag for HEAD's package version and subject
# @arg tag Tag name to validate; defaults to vVERSION
release:_check-tag(){ _release check-tag "$@"; }

# @describe Create annotated vVERSION tag at clean release HEAD
release:tag(){
  local version tag
  _need_venv || return $?
  _require_clean || return $?
  release:_check-ref --release || return $?
  version="$(_release version)" || return $?
  tag="v$version"
  git show-ref --tags --verify --quiet "refs/tags/$tag" && { : "tag $tag already exists"; return 1; }
  git tag -a "$tag" -m "$tag" || return $?
  release:_check-tag "$tag" || { git tag -d "$tag" >/dev/null; return 1; }
  : "created $tag; push it with: git push origin $tag"
}

# @describe Require local version not behind an index. exists vs unpublished on stdout.
# @arg target[pypi|testpypi]!
release:_check-version(){ _release check-version "$@"; }

# @describe Print the latest release CHANGELOG.md section
release:_notes(){ _release notes; }

# @describe yes if the current package version is a PEP 440 pre-release
release:_is-prerelease(){ _release is-prerelease; }

# @describe Download from an index, clean-install, and exercise public API
# @arg target[pypi|testpypi]!
# Retries: TestPyPI simple index lags the upload API. 12 × 10s. `set +x` in
# `_publish_local` hides the loop unless we log attempts.
release:_verify(){
  local attempt err=""
  _need_venv || return $?
  for attempt in {1..12}; do
    : "release:_verify $*: attempt $attempt/12"
    err="$(_release smoke-index "$@" 2>&1)" && return 0
    [ "$attempt" -eq 12 ] || sleep 10
  done
  : "$err"
  return 1
}

# @describe Run local TestPyPI release
release:testpypi(){ _publish_local testpypi; }

# @describe Run local tagged PyPI release
release:pypi(){ _publish_local pypi; }

# @describe Dispatch and watch remote test.yml
# @arg ref branch, tag, or SHA; defaults to current branch
gh:ci(){ _workflow_remote test.yml "${1:-$BRANCH}"; }

# @describe Dispatch and watch remote docs.yml
# @arg ref branch, tag, or SHA; defaults to current branch
gh:docs(){ _workflow_remote docs.yml "${1:-$BRANCH}"; }

# @describe Dispatch, test, publish, and verify through gh
# @arg ref branch, tag, or SHA; defaults to current branch
gh:publish:testpypi(){
  local ref="${1:-$BRANCH}"
  _require_remote_head "$ref" || return $?
  release:_check-ref --release || return $?
  release:_check-version testpypi || return $?
  _workflow_remote publish.yml "$ref" target=testpypi || return $?
}

# @describe Create gh release for current vVERSION tag
gh:release(){
  local version tag notes extra=() assets=()
  _need_venv || return $?
  _has_cmd gh || return $?
  gh auth status >/dev/null || return $?
  _require_release_tag || return $?
  version="$(_release version)" || return $?
  tag="v$version"
  notes="$(mktemp)" || return $?
  _release notes > "$notes" || { rm -f "$notes"; return 1; }
  pre="$(_release is-prerelease)" || { rm -f "$notes"; return 1; }
  [ "$pre" = yes ] && extra=(--prerelease)
  [ -f "$ROOT_DIR/coverage.json" ] && assets=("$ROOT_DIR/coverage.json")
  if gh release view "$tag" >/dev/null 2>&1; then
    : "GitHub Release $tag exists"
    if [ "${#assets[@]}" -gt 0 ]; then
      gh release upload "$tag" "${assets[@]}" --clobber || { rm -f "$notes"; return 1; }
    fi
    rm -f "$notes"
    return 0
  fi
  gh release create "$tag" --verify-tag --notes-file "$notes" "${extra[@]}" "${assets[@]}" || { rm -f "$notes"; return 1; }
  rm -f "$notes"
}

# @describe Dispatch, test, publish, and verify prod release through gh
gh:publish:pypi(){
  local tag
  _require_release_tag || return $?
  tag="v$(_release version)" || return $?
  release:_check-version pypi || return $?
  _workflow_remote publish.yml "$tag" target=pypi || return $?
}

## Docker

# @describe Host-uid docker run flags + /tmp scratch
# Unquoted: docker run $(./run.sh docker:_flags) img
docker:_flags(){
  echo --init --rm \
    -u "$(id -u):$(id -g)" \
    -e HOME=/tmp \
    -e COVERAGE_FILE=/tmp/coverage
}

# @describe Build image
# @arg stage[dev|prod|build]  Dockerfile --target. Unset -> final stage
# @arg rest~                  Extra docker-build args
# @env PYTHON_VERSION         Override .python-version pin
# @env UV_VERSION             Override versions/uv pin
docker:build(){
  local stage="" py uvv version target_arg=()
  case "${1:-}" in
    ""|-*) ;;
    *) stage=$1; shift ;;
  esac
  py="${PYTHON_VERSION:-$DEFAULT_PYTHON}"
  uvv="${UV_VERSION:-$UV_PIN}"
  version="$BRANCH${stage:+-$stage}-py${py}"
  [ -n "$stage" ] && target_arg=(--target "$stage")
  docker build \
    --build-arg UBUNTU_VERSION="$UBUNTU_PIN" \
    --build-arg PYTHON_VERSION="$py" \
    --build-arg UV_VERSION="$uvv" \
    "${target_arg[@]}" \
    -t "$IMAGE_NAME:$version" "$@" "$ROOT_DIR" || return $?
  echo "$IMAGE_NAME:$version"
}

# Host tree at /app. Image venv is /.venv; tmpfs hides host .venv.
# DOCKER_IT=1 → -it (docker:shell).
docker:_run(){
  local img extra=() stage=$1
  shift
  img="$(docker:build "$stage")" || return $?
  [ -n "${DOCKER_IT:-}" ] && extra+=(-it)
  # shellcheck disable=SC2046
  docker run $(docker:_flags) "${extra[@]}" --entrypoint ./run.sh \
    -v "$ROOT_DIR":/app --tmpfs /app/.venv -w /app "$img" "$@" || return $?
}

# @describe GHA Checks job (same ./run.sh chain)
# @arg rest~ extra ./run.sh check args
# @env PYTHON_VERSION Override .python-version pin
docker:check(){
  docker:_run dev uv:venv:sync @@ release:_check-ref @@ check "$@"
}

# @describe Build prod image + ./run.sh tests
# @alias docker:tests
# @arg rest~ pytest args
# @env PYTHON_VERSION Override .python-version pin
docker:test(){
  local img
  img="$(docker:build prod)" || return $?
  # shellcheck disable=SC2046
  docker run $(docker:_flags) "$img" tests "$@" || return $?
}
docker:tests(){ docker:test "$@"; }

# @describe Dev shell. Host tree at /app, host uid
# @arg rest~ extra bash args
# @env PYTHON_VERSION Override .python-version pin
docker:shell(){
  [ -t 0 ] && [ -t 1 ] && DOCKER_IT=1
  docker:_run dev "$@"
}

# @describe Dangling image / buildx prune
docker:prune(){
  docker images -a | awk '/<none>/{system("docker rmi "$$3)}' || return $?
  docker buildx prune -af --filter "until=36h" || return $?
  docker builder prune -f --filter "until=36h" || return $?
}

# @describe docker:test for each PYTHON_VERSIONS (local MRE; GHA uses baipp matrix)
# @env PYTHON_VERSION set per loop from PYTHON_VERSIONS
docker:matrix(){
  local py failed=""
  for py in $PYTHON_VERSIONS; do
    PYTHON_VERSION="$py" docker:test || failed="$failed $py"
  done
  if [ -n "$failed" ]; then
    : "docker:matrix failed:$failed"
    return 1
  fi
}

# # Utilities

# @describe Return 0 if cmd is on PATH
# @arg cmd!
_has_cmd(){ command -v "$1" &>/dev/null; ternary_err "$?" "${GRN}${1} ok$DEF" "${RED}ERROR: missing ${1}$DEF"; }

# @describe PATH shellcheck must match versions/shellcheck
_need_shellcheck(){
  local got
  setup:shellcheck || return $?
  _has_cmd shellcheck || return $?
  got="$(shellcheck --version | awk '/^version:/{print $2; exit}')"
  [ "$got" = "$SHELLCHECK_PIN" ] || { : "shellcheck $got != pin $SHELLCHECK_PIN"; return 1; }
}

# @describe Put .venv/bin on PATH, or fail if missing
_need_venv(){
  local -; set +x
  if [ ! -x "$VENV_BIN/python" ]; then
    : "no .venv; ./run.sh uv:venv:sync"
    return 1
  fi
  PATH="$VENV_BIN:$PATH"
}

# @describe Run a workflow locally via act
# @arg workflow! yaml basename under .github/workflows/
# @arg rest~ extra act args
_workflow_local(){
  local wf=".github/workflows/$1"
  shift
  _has_cmd act || return $?
  act workflow_dispatch -W "$wf" "$@" || return $?
}

# @describe Dispatch a GitHub workflow and watch the resulting run
# @arg workflow! workflow file name
# @arg ref! branch, tag, or SHA
# @arg rest~ key=value fields for workflow_dispatch
_workflow_remote(){
  local workflow="$1" ref="$2" before run_id key value
  shift 2
  _has_cmd gh || return $?
  gh auth status >/dev/null || return $?
  before="$(gh run list --workflow "$workflow" --limit 1 --json databaseId --jq '.[0].databaseId // 0')" || return $?
  local fields=()
  for key in "$@"; do
    value="${key#*=}"
    key="${key%%=*}"
    fields+=(--raw-field "$key=$value")
  done
  gh workflow run "$workflow" --ref "$ref" "${fields[@]}" || return $?
  for _ in {1..30}; do
    run_id="$(gh run list --workflow "$workflow" --commit "$(git rev-parse "$ref^{commit}")" --limit 1 --json databaseId --jq '.[0].databaseId // 0')" || return $?
    [ "$run_id" != 0 ] && [ "$run_id" != "$before" ] && break
    sleep 2
  done
  if [ "$run_id" = 0 ] || [ "$run_id" = "$before" ]; then
    : "could not find dispatched $workflow run"
    return 1
  fi
  gh run watch "$run_id" --compact --exit-status || return $?
}

# @describe Fail unless the working tree is clean
_require_clean(){
  [ -z "$(git status --porcelain)" ] || { : "working tree is not clean"; return 1; }
}

# @describe Fail unless HEAD is a tagged release commit present on origin
_require_release_tag(){
  local version tag remote
  _require_clean || return $?
  version="$(_release version)" || return $?
  tag="v$version"
  release:_check-tag "$tag" || return $?
  remote="$(git ls-remote origin "refs/tags/$tag^{}" | cut -f1)" || return $?
  [ -n "$remote" ] || remote="$(git ls-remote origin "refs/tags/$tag" | cut -f1)" || return $?
  [ "$remote" = "$(git rev-parse HEAD)" ] || { : "remote $tag does not point to HEAD"; return 1; }
}

# @describe Fail unless REF is HEAD and origin/REF matches HEAD
# @arg ref!
_require_remote_head(){
  local ref="$1" remote
  _require_clean || return $?
  [ "$(git rev-parse "$ref^{commit}")" = "$(git rev-parse HEAD)" ] || { : "$ref does not point to HEAD"; return 1; }
  remote="$(git ls-remote origin "refs/heads/$ref" | cut -f1)" || return $?
  [ "$remote" = "$(git rev-parse HEAD)" ] || { : "remote branch $ref does not point to HEAD"; return 1; }
}

# @describe Local uv publish + smoke-index verify
# @arg target[pypi|testpypi]!
# @env UV_PUBLISH_TOKEN PyPI API token (pypi-...)
_publish_local(){
  local -; set +x
  local target="$1" publish_url check_url version tag status
  _need_venv || return $?
  _require_clean || return $?
  if [ "$target" = pypi ]; then
    _has_cmd gh || return $?
    gh auth status >/dev/null || return $?
    _require_release_tag || return $?
    publish_url=https://upload.pypi.org/legacy/
    check_url=https://pypi.org/simple/
  else
    publish_url=https://test.pypi.org/legacy/
    check_url=https://test.pypi.org/simple/
  fi
  release:_check-ref --release || return $?
  release:check || return $?
  status="$(_release check-version "$target")" || return $?
  printf '%s\n' "$status"
  if [[ "$status" == *" unpublished "* ]]; then
    [ -n "${UV_PUBLISH_TOKEN:-}" ] || { : "UV_PUBLISH_TOKEN is required for local publication"; return 1; }
    case "$UV_PUBLISH_TOKEN" in
      pypi-*) ;;
      *) : "UV_PUBLISH_TOKEN must be a PyPI API token (starting with pypi-), not a GitHub PAT"; return 1 ;;
    esac
    uv publish --publish-url "$publish_url" --check-url "$check_url" dist/* || return $?
  elif [[ "$status" == *" exists "* ]]; then
    : "already on $target, skip publish"
  else
    : "unexpected check-version: $status"
    return 1
  fi
  release:_verify "$target" || return $?
  if [ "$target" = pypi ]; then
    gh:release || return $?
  fi
}

# # Re-used utilities

# @describe Rewrite @@ to && for ./run.sh chaining
_chain_ats(){ sed -r -e "s/^ *@@//g" -e "s/@@/ \&\& /g"; }

# shellcheck disable=SC2034 # unused variable
decl_colors(){ local -; set +x; DEF=$'\e[0m'; RED=$'\e[91m'; GRN=$'\e[92m'; BLU=$'\e[94m'; }
decl_colors

ternary_err(){ if [ "$1" -eq 0 ]; then : "${2:-}"; else : "${3:-}"; fi; return "$1"; }
ternary_eval(){ if [ "$1" -eq 0 ]; then eval "${2:-}"; else eval "${3:-}"; fi; return "$1"; }

eval_verbose(){ _eval_verbose "$1" ; ternary_err $? "${GRN}Done$DEF" "${RED}ERROR $?$DEF"; }

# @describe eval with set -x
# @arg cmdline!
# shellcheck disable=SC2027,SC2086
_eval_verbose(){ eval "__trace_start=${#FUNCNAME[@]}; local -; set -x; "$1"; "; }

# Reserve enough spaces for the deepest expected call stack.
__trace_spaces="$(printf '%*s' 100 '')"
readonly __trace_spaces
__trace_start=0 # The root parent funcname's indent
# FUNCNAME[0] = current fn, length ~= fn-call depth
# shellcheck disable=SC2016
readonly __PS4='+${__trace_spaces:0:${#FUNCNAME[@]}-$__trace_start} '

# ./run.sh fn1 arg1 @@ fn2 arg1
# ./run.sh -> main
# Internals (`:_` / `_foo`) stay hidden from help, but eval dispatch still runs them.
if ! (return 0 2>/dev/null); then
  set -uo pipefail
  # Filter xtrace only. Piping fd 2 reorders uv/pre-commit logs on GHA.
  exec {__xtrace_fd}> >(grep -vF -e 'local -' -e 'set +x' >&2)
  BASH_XTRACEFD=$__xtrace_fd
  PS4=$__PS4
  if [ $# -eq 0 ]; then
    main; exit $?
  elif [[ "$1" == "-h" || "$1" == "--help" || "$1" == "help" ]]; then
    shift; help "$@"; exit $?
  else
    ARGS=$(echo "$*" | _chain_ats)
  fi
  eval_verbose "$ARGS"; exit $?
fi
