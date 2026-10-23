#!/bin/sh
# Non-ASCII bytes in the worktree. rg skips .git, gitignored paths, and binaries.

# (?-u:...) is bytes. Unicode mode drops a lone 0xFF.
non_ascii() {
  rg -n --hidden --no-heading --color never '(?-u:[\x80-\xFF])' "$1"
}

cd "$(dirname "$0")/.." || exit
non_ascii . >&2; [ "$?" -eq 1 ]; exit $?
