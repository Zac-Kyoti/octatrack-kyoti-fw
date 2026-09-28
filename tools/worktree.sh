#!/bin/bash
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
#
# One git worktree per concurrent session -- see CLAUDE.md "Concurrent sessions".
#
# Two Claude sessions editing ONE checkout cannot be kept apart by any rule: a repo-wide add in
# either one commits the other's half-finished work (10173b3, eb8f022). A worktree gives each
# session its own directory, its own branch and its own out/ (so builds cannot be confused
# either), while sharing the repository and the big untracked inputs.
#
#   tools/worktree.sh new <thread>     create ../octatrack-kyoti-fw-<thread> on branch <thread>
#   tools/worktree.sh publish          (inside a thread worktree) rebase onto origin/main, push to main
#   tools/worktree.sh status           every worktree, and how far each branch is ahead/behind
#   tools/worktree.sh remove <thread>  delete a thread's worktree (and its branch, if merged)
#
# Shared into each worktree by symlink (untracked, large, read-mostly): refs/<every clone>,
# vendor/, downloads/, ghidra_project/, out/raw/. Everything else under out/ is per-worktree.
set -euo pipefail

PRIMARY="$(git worktree list --porcelain | awk '/^worktree /{print $2; exit}')"
cmd="${1:-status}"

link_shared() {   # $1 = worktree dir
    local wt="$1"
    for d in "$PRIMARY"/refs/*/; do
        d="${d%/}"; [ -e "$wt/refs/$(basename "$d")" ] || ln -s "$d" "$wt/refs/$(basename "$d")"
    done
    for d in vendor downloads ghidra_project; do
        [ -e "$PRIMARY/$d" ] && [ ! -e "$wt/$d" ] && ln -s "$PRIMARY/$d" "$wt/$d"
    done
    mkdir -p "$wt/out"
    [ -e "$wt/out/raw" ] || ln -s "$PRIMARY/out/raw" "$wt/out/raw"
    git -C "$wt" config core.hooksPath tools/githooks
}

case "$cmd" in
  new)
    t="${2:?usage: tools/worktree.sh new <thread>}"
    wt="$(dirname "$PRIMARY")/$(basename "$PRIMARY")-$t"
    [ -e "$wt" ] && { echo "exists: $wt"; exit 1; }
    git -C "$PRIMARY" fetch -q origin
    if git -C "$PRIMARY" show-ref -q --verify "refs/heads/$t"; then
        git -C "$PRIMARY" worktree add "$wt" "$t"
    else
        git -C "$PRIMARY" worktree add -b "$t" "$wt" origin/main
    fi
    link_shared "$wt"
    echo
    echo "  worktree ready: $wt   (branch $t, own out/, shared refs/ vendor/ downloads/ out/raw/)"
    echo "  work and commit there; publish with:  (cd $wt && tools/worktree.sh publish)"
    ;;
  publish)
    br="$(git rev-parse --abbrev-ref HEAD)"
    [ "$br" = "main" ] && { echo "publish runs inside a thread worktree, not on main"; exit 1; }
    [ -z "$(git status --porcelain --untracked-files=no)" ] || { echo "commit or stash first:"; git status --short; exit 1; }
    git fetch -q origin
    git rebase origin/main || { echo; echo "  rebase stopped on a conflict: fix, 'git rebase --continue', then publish again"; exit 1; }
    git push origin "HEAD:main"
    echo
    echo "  published $br -> origin/main. Checkouts on main pick it up with:"
    echo "      git pull --rebase --autostash"
    ;;
  status)
    git fetch -q origin || true
    git worktree list
    echo
    for b in $(git for-each-ref --format='%(refname:short)' refs/heads); do
        printf "  %-14s ahead %s / behind %s of origin/main\n" "$b" \
            "$(git rev-list --count origin/main.."$b")" "$(git rev-list --count "$b"..origin/main)"
    done
    ;;
  remove)
    t="${2:?usage: tools/worktree.sh remove <thread>}"
    wt="$(dirname "$PRIMARY")/$(basename "$PRIMARY")-$t"
    git -C "$PRIMARY" worktree remove "$wt"
    git -C "$PRIMARY" branch -d "$t" 2>/dev/null && echo "  branch $t deleted (merged)" \
        || echo "  branch $t kept (not merged into the current branch -- check before deleting)"
    ;;
  *) sed -n '5,17p' "$0"; exit 1 ;;
esac
