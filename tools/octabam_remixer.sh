#!/bin/sh
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
#
# octabam_remixer.sh -- open octabam's remixer, updated to octabam's latest `main` first.
#
# The remixer runs from its OWN clone (default ~/Documents/octabam), never from refs/octabam:
# refs/octabam is this repo's pinned research harness (98 tools import it; REPITCH and
# SIDECHAIN's builders read from it), so it moves only by `tools/refs/sync.py`, on purpose.
#
# Every run: fetch, fast-forward to origin/main, update submodules, rebuild the toolchain
# only when setup.sh changed and re-provision Python only when pyproject/uv.lock changed
# (`uv sync --frozen`: `make emu-setup` minus letting a newer uv rewrite octabam's uv.lock,
# which would then read as a local edit and stop the updates),
# then `make remix`. It never discards anything: a clone with local edits, or one whose
# history has diverged, is left alone with a message and the remixer opens as it is.
#
# Usage:
#   sh tools/octabam_remixer.sh             # update, then open the remixer
#   sh tools/octabam_remixer.sh --no-open   # update only
#   OCTABAM_DIR=/path/to/clone sh tools/octabam_remixer.sh
#
# First time, if the clone does not exist yet, it is created and set up (several minutes):
# clone with submodules, `make setup`, `make emu-setup`, the stock OS copied from this
# repo's downloads/ (your own copy, gitignored there too), `make recon`.

set -eu

DIR=${OCTABAM_DIR:-"$HOME/Documents/octabam"}
URL=https://github.com/sambanks/octabam.git
HERE=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
OPEN=1
[ "${1:-}" = "--no-open" ] && OPEN=0

say() { printf '\033[1m[remixer]\033[0m %s\n' "$*"; }

if [ ! -d "$DIR/.git" ]; then
  say "no clone at $DIR -- creating it (one-time, several minutes)"
  git clone --recurse-submodules "$URL" "$DIR"
  cd "$DIR"
  make setup
  uv sync --frozen --extra emu
  mkdir -p downloads/extracted
  cp "$HERE/downloads/extracted/OCTATRACK_OS1.40C.syx" downloads/extracted/
  make recon
else
  cd "$DIR"
  if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
    say "local edits in $DIR -- not updating (commit or discard them to resume updates)"
  elif ! git fetch -q origin; then
    say "fetch failed (offline?) -- opening the current version"
  else
    old=$(git rev-parse HEAD)
    new=$(git rev-parse origin/main)
    if [ "$old" = "$new" ]; then
      say "up to date ($(git log -1 --format='%h %cs' HEAD))"
    elif ! git merge-base --is-ancestor "$old" "$new"; then
      say "history has diverged from origin/main -- not updating"
    else
      changed=$(git diff --name-only "$old" "$new")
      git merge -q --ff-only "$new"
      git submodule update -q --init --recursive
      say "updated $(git rev-parse --short "$old") -> $(git rev-parse --short "$new") ($(git rev-list --count "$old..$new") commits)"
      if printf '%s\n' "$changed" | grep -q '^scripts/setup\.sh$'; then
        say "setup.sh changed -- rebuilding the toolchain"
        make setup
      fi
      if printf '%s\n' "$changed" | grep -qE '^(pyproject\.toml|uv\.lock)$'; then
        say "Python dependencies changed -- re-provisioning .venv"
        uv sync --frozen --extra emu
      fi
    fi
  fi
fi

[ "$OPEN" = 1 ] && exec make remix
exit 0
