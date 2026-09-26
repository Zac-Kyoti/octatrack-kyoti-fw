#!/usr/bin/env python3
"""Clone/fetch every repo in refs/MANIFEST.toml into refs/<name>/ and record the
resolved commit hashes in refs/MANIFEST.lock.

  python3 tools/refs/sync.py            # sync all to their pinned commit
  python3 tools/refs/sync.py OctaLib    # just one
  python3 tools/refs/sync.py --update   # ignore pins, check out each branch tip,
                                        # record the new hashes in MANIFEST.lock

A repo with pin = "HEAD" always tracks its branch tip. To freeze one, put a real
commit hash in its `pin` field in MANIFEST.toml.

The clones are a disposable cache: gitignored, never committed. Distil anything
useful into reference/kb/ with attribution + the commit hash from the lock file.
"""
from __future__ import annotations
import subprocess
import sys
import datetime as _dt
from pathlib import Path

from _manifest import REFS_DIR, LOCK, MANIFEST, load

# Durable home for local edits found in a (disposable) clone — see sync_one().
PATCH_DIR = REFS_DIR.parent / "tools" / "refs" / "local-patches"


def git(*args: str, cwd: Path | None = None) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def _rev_exists(cwd: Path, rev: str) -> bool:
    return subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", rev], cwd=cwd, capture_output=True
    ).returncode == 0


def sync_one(name: str, meta: dict[str, str], *, update: bool) -> tuple[str, str]:
    dest = REFS_DIR / name
    url, branch, pin = meta["url"], meta.get("branch", "HEAD"), meta.get("pin", "HEAD")
    if not (dest / ".git").exists():
        print(f"  clone {name} <- {url}")
        git("clone", "--quiet", url, str(dest))
    print(f"  fetch {name}")
    git("fetch", "--quiet", "--tags", "origin", cwd=dest)

    # verify the configured branch exists; fall back to the remote's default HEAD
    if not _rev_exists(dest, f"origin/{branch}"):
        git("remote", "set-head", "origin", "--auto", cwd=dest)
        branch = git("symbolic-ref", "--short", "refs/remotes/origin/HEAD", cwd=dest).split("/")[-1]
        print(f"  (branch fallback -> {branch})")

    target = f"origin/{branch}" if (update or pin == "HEAD") else pin

    # A clone is a disposable cache, but we do sometimes edit one (e.g. adding a
    # probe to octabam's emulator). Such an edit blocks `checkout` and used to abort
    # the WHOLE run, leaving later repos unsynced and the lock untouched. Preserve
    # the diff as a durable patch under tools/refs/local-patches/ (outside refs/, so
    # it survives a cache wipe and is committable), then reset and continue.
    dirty = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=dest, capture_output=True, text=True,
    ).stdout.strip()
    if dirty:
        PATCH_DIR.mkdir(parents=True, exist_ok=True)
        patch = PATCH_DIR / f"{name}-local.patch"
        diff = subprocess.run(["git", "diff", "HEAD"], cwd=dest,
                              capture_output=True, text=True).stdout
        if diff.strip():
            patch.write_text(diff)
            print(f"  ! local edits in refs/{name} saved -> {patch.relative_to(REFS_DIR.parent)}")
        git("reset", "--hard", "--quiet", "HEAD", cwd=dest)

    # ===== Session 92: the dirty-check above is NOT ENOUGH, and the gap is a trap. =====
    # It only sees UNCOMMITTED edits. A local fix that was COMMITTED -- e.g. onto a
    # branch, which is the careful thing to do and exactly what someone does when they
    # notice their work is "one git checkout away from being lost" -- leaves a CLEAN
    # working tree, sails past the check above, and is then silently un-applied by the
    # detach below. The commit is not deleted (its branch ref survives), so nothing
    # LOOKS lost; the clone simply stops carrying the fix, and whatever depended on it
    # breaks in a way that points nowhere near here.
    # This is not hypothetical: refs/octabam commit d5b84fb (branch emu/map-audio-sdram)
    # is REQUIRED for the emulator to boot this repo's firmware images at all -- without
    # it, boot dies with UC_ERR_WRITE_UNMAPPED inside gate_m6a -- and it was committed
    # onto a branch for exactly that "don't lose it" reason. So being more careful with
    # your work made it MORE likely to be dropped here. Close the gap: export any commit
    # that is not reachable from the target as a patch too, and say so loudly.
    extra = subprocess.run(
        ["git", "log", "--oneline", f"{target}..HEAD"],
        cwd=dest, capture_output=True, text=True,
    ).stdout.strip()
    if extra:
        PATCH_DIR.mkdir(parents=True, exist_ok=True)
        cpatch = PATCH_DIR / f"{name}-local-commits.patch"
        cdiff = subprocess.run(["git", "diff", target, "HEAD"], cwd=dest,
                               capture_output=True, text=True).stdout
        if cdiff.strip():
            cpatch.write_text(cdiff)
        n = len(extra.splitlines())
        print(f"  ! refs/{name}: {n} local commit(s) NOT in {target} -- the checkout "
              f"below will un-apply them:")
        for line in extra.splitlines():
            print(f"      {line}")
        print(f"    saved as -> {cpatch.relative_to(REFS_DIR.parent)}")
        print(f"    RE-APPLY with:  git -C refs/{name} apply "
              f"{cpatch.relative_to(REFS_DIR.parent)}")
        print(f"    (or keep them:  git -C refs/{name} checkout <branch>)")

    git("checkout", "--quiet", "--detach", target, cwd=dest)
    head = git("rev-parse", "HEAD", cwd=dest)
    subject = git("log", "-1", "--format=%s", cwd=dest)
    return head, subject


def main(argv: list[str]) -> int:
    update = "--update" in argv
    wanted = [a for a in argv if not a.startswith("-")]
    repos = load()
    if wanted:
        repos = {k: v for k, v in repos.items() if k in wanted}
        if not repos:
            print(f"no such repo(s): {wanted}", file=sys.stderr)
            return 2

    REFS_DIR.mkdir(exist_ok=True)
    failed: list[str] = []
    # No timestamp in the lock body — it is tracked, and a time-only diff on every
    # sync is noise. The wall-clock goes to refs/.last-sync (gitignored) instead.
    lock_lines = [
        "# Resolved by tools/refs/sync.py — do not edit by hand.",
        "",
    ]
    for name, meta in load().items():  # keep lock ordered like the manifest
        if name not in repos:
            prev = _prev_lock_line(name)  # untouched repo: keep its old lock line
            if prev:
                lock_lines.append(prev)
            continue
        print(f"[{name}]")
        try:
            head, subject = sync_one(name, meta, update=update)
        except subprocess.CalledProcessError as exc:
            # Keep the old lock line: the rule is never to advance a repo's lock past
            # material nobody looked at, and a failed sync looked at nothing.
            failed.append(name)
            err = (exc.stderr or "").strip().splitlines()
            print(f"  !! FAILED ({' '.join(exc.cmd)}): {err[-1] if err else exc}")
            prev = _prev_lock_line(name)
            if prev:
                lock_lines.append(prev)
            continue
        lock_lines.append(f'{name} = "{head}"  # {subject[:70]}')

    LOCK.write_text("\n".join(lock_lines) + "\n")
    stamp = _dt.datetime.now().isoformat(timespec="seconds")
    (REFS_DIR / ".last-sync").write_text(stamp + "\n")
    print(f"\nwrote {LOCK.relative_to(REFS_DIR.parent)}  ({stamp})")
    if failed:
        print(f"!! {len(failed)} repo(s) FAILED and kept their previous lock line: "
              f"{', '.join(failed)}")
        return 1
    return 0


def _prev_lock_line(name: str) -> str | None:
    if not LOCK.exists():
        return None
    for line in LOCK.read_text().splitlines():
        if line.startswith(f"{name} ="):
            return line
    return None


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
