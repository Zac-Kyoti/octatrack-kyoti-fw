---
name: pull-research
description: Scan every tracked upstream RE repo (refs/MANIFEST.toml) for new commits, pull the ones that moved, read what actually changed, and distill anything relevant into reference/kb/*.md with attribution — the full ingest pipeline, not just the "what's new" report. Use when the user asks to pull/check/sync/ingest new research from the contributors, or asks what's new upstream.
---

# Pull + distill upstream RE research

This is the ONE command for "go see what the other Octatrack RE projects have
found and fold it into our knowledge base." Do not stop at reporting — a run
that only lists new commits and doesn't touch `reference/kb/` has not done the
job the user is asking for. See `reference/KB_REFRESH.md` for the full concept
reference (repos, lock file, script list) if anything here is unclear.

## Why this exists

`tools/refs/whatsnew.py` / `refresh.sh` are deliberately **read-only** — they
fetch and report, never write `reference/kb/`. That's correct for them, but it
means running just those (or just `sync.py --update` on its own) leaves the
user's actual ask — "ingest it, distill it" — undone. On 2026-09-14 exactly
this happened: `sync.py --update` ran and advanced `refs/MANIFEST.lock` to the
branch tip, but nobody read the diff or wrote to `kb/` afterward — and because
`whatsnew.py` diffs against the lock (not a separate "last distilled" marker),
those un-triaged commits silently stopped showing up as new. **Never leave a
repo's lock line pointing past a commit you have not actually looked at.**

## Steps

0. **Look for repos we do not track yet — `whatsnew.py` structurally cannot.**
   ```
   sh tools/refs/contributors.sh
   ```
   Two blind spots, both of which cost real material before 2026-09-24: a
   contributor publishes a **new** repo (invisible to `whatsnew.py`, which only
   reads `MANIFEST.toml`), or an upstream repo **credits somebody we do not
   track**. The script does both passes; it prints candidates only. **Also read
   `refs/octabam/docs/firmware/CONTRIBUTIONS.md` by hand** — it is the
   ecosystem's dated credit ledger, and it is where `nordseele/octalab` and
   `markandrus/octemu` were found. The bottom of `refs/MANIFEST.toml` carries a
   "deliberately NOT tracked" block: check it before triaging a candidate again.

1. **Fetch + report first, cheaply:**
   ```
   python3 tools/refs/whatsnew.py --limit 0
   ```
   This just fetches and counts — tells you which of the **13** repos in
   `refs/MANIFEST.toml` actually moved, with zero risk.

2. **For each repo that moved, pull it to tip** (this rewrites its
   `MANIFEST.lock` line — do not do this for a repo you don't intend to triage
   in this same session):
   ```
   python3 tools/refs/sync.py --update <repo>
   ```

2a. **WARNING: syncing `octabam` can change OUR emulator's behaviour — plan for it.**
   `tools/emu_rtos.py` executes octabam's own script **from inside
   `refs/octabam/`**, against a patched Unicorn built into that clone's `.venv`.
   Advancing that clone therefore advances our emulator. Not theoretical: the
   2026-09-24 sync pulled octabam PR #360 ("Unicorn EMAC: fix MAC-with-load decode
   — Rx source, phantom dual, MASK reset", itself derived from markandrus/octemu's
   findings). The **more correct** EMAC changed a boot-time branch, which reached a
   stock zero-fill path that had never executed in our harness, which needed a
   previously-unmapped SDRAM region (`0x4f000000..0x50000000`) added to
   `tools/emu_reload.py`.
   **So: after an octabam sync, re-run a known-good emulator scenario before
   trusting any new result.** A changed result after a sync is not automatically a
   regression in our patch — check the sync first. Corollary: an emulator "green"
   from before a sync is not evidence for a build after it.

2b. **A dirty clone no longer aborts the run, but check what it saved.** `sync.py`
   now preserves local edits found in a clone to
   `tools/refs/local-patches/<repo>-local.patch` and resets the clone, and a repo
   that fails to sync keeps its **previous** lock line while the others proceed.
   If you see a `! local edits ... saved` line, decide whether that patch is still
   wanted (e.g. `octabam-emu-poke2.patch` is our own second-timed-poke probe for
   octabam's emulator).

3. **Read the actual diff, not just commit subjects.** For each pulled repo:
   ```
   git -C refs/<repo> log --oneline <old-hash>..HEAD      # old-hash from step 1's report
   git -C refs/<repo> show <hash>                          # for anything that looks relevant
   rg -n "<term>" refs/<repo>/                              # grep the checkout directly
   ```
   Check each repo's own docs first if it has them (`docs/`, `*.md` at the
   root) — most of these projects (octabam, ems-octakit, midisc) keep a
   running technical changelog that's faster to read than raw commits.

   **Three traps learned on 2026-09-24:**

   - **Diff by FILE, not by commit, on a fast mover.** For octabam's 397 commits,
     `git diff --numstat <old>..HEAD | awk` grouped by file found the new
     ColdFire doc set in one step. Reading 397 subjects would not have.
   - **Upstream reorganises.** octabam **deleted** `docs/firmware/RTOS_FORK.md`
     and `COLDFIRE_PORT.md` on 22 Sep; our KB cited both. A commit-pinned
     citation stays *valid* (the file existed at that commit) but a reader at tip
     hits a 404 — so when a cited file disappears, add a "where it lives now"
     pointer rather than rewriting the citation and losing the provenance. Check
     with `git -C refs/<repo> diff --name-status <old>..HEAD -- docs`.
   - **Material can live off `main`.** octabam's ledger said repeat98's
     `STOCK_PROFILE.md` "was not sent" upstream; it exists in `refs/octamad` only
     on branch `origin/poly-machine`. Use `git log --all --diff-filter=A -- '*NAME*'`
     to find it and `git show <hash>:<path>` to read it without checking it out.

4. **Triage against this project's actual scope** — the policy is `CLAUDE.md`
   "Scope of this project", not `COVERAGE.md` (which is the descriptive map of
   what is mapped so far). In short: OS 1.40C on the **MKI**, **both** the
   ColdFire control plane and the **DSP56300 signal plane** — this repo ships DSP
   assembly, so DSP mechanisms, module/dispatch maps, the toolchain, the emulator
   and any effect we touch or might donate are all IN scope. Legitimately "not for
   us": per-effect ear tuning of effects we do not ship, 256-slot/kit schemes we
   haven't adopted, and synth emulation unrelated to the Octatrack (e.g. anything
   in `dsp56300/gearmulator` beyond the `dsp56300` core submodule). Say so
   explicitly rather than silently skipping it.
   ⚠️ Entries in `UPSTREAM_INBOX.md` stamped "out of scope per COVERAGE.md" predate
   this correction — octabam's DSP-effect passes and the dsp56300 core commits among
   them. Re-triage one before treating it as settled.

4b. **Verify a load-bearing upstream claim against our own image before adopting
   it.** These repos are good but not infallible, and we have the image and the
   toolchain. On 2026-09-24 this caught a wrong function signature in octemu's
   `coldfire.syms` (`apply_part(part, pattern)` — it is `(bank, part)`), and
   turned two borrowed addresses into a confirmed root cause for the Session 49
   bug family by disassembling them. The recipe:
   ```
   m68k-elf-objdump -D -b binary -m m68k:cfv4e -EB --adjust-vma=0x40000400 \
     --start-address=0xADDR --stop-address=0xEND out/raw/section_3_MAIN_OS.bin
   ```
   Our image's sha256 starts `164f3122…` — the same one octabam, octalab, octemu
   and midisc all cite, so their addresses are directly comparable. Confirm that
   before trusting any of them (`shasum -a 256 out/raw/section_3_MAIN_OS.bin`).

5. **Distill what's relevant into the right `reference/kb/*.md` file(s).**
   Match the existing style in that file: dense prose/tables keyed by address,
   an attribution line `source: refs/<repo>/<path> @ <commit> · fetched
   <date>`, and a confidence marker (**C** disassembly/HW-confirmed / **L**
   likely / **?** speculative). Keep contradictions visible — never silently
   overwrite a prior value; note the disagreement instead.

6. **Log every repo you touched in `reference/UPSTREAM_INBOX.md`** — one line
   per repo per sync, dated, moved to "Distilled" with the target `kb/` file,
   or left in "Pending" with an explicit `[ TODO — <what's left> ]` if you
   ran out of scope for it. A repo whose lock you advanced but whose commits
   you didn't fully triage MUST get a Pending line — that's the rule that was
   missed on 2026-09-14.

7. **If a repo is new** (not yet in `refs/MANIFEST.toml`): add it there first
   (`url`, `branch` — check the repo's *actual* default branch, it is not
   always `main`, e.g. `dsp56300/dsp56300` defaults to branch `dsp56300`),
   `pin = "HEAD"`, `side`, one-line `use`. Then add it to
   `reference/EXTERNAL_RESEARCH.md`'s repo table and to `CREDITS.md`. Run
   `sync.py <name>` to do the first clone+pin.

8. **Update `reference/EXTERNAL_RESEARCH.md`'s per-repo summary line** if the
   distillation was substantial enough to be worth a future reader knowing
   about without opening `UPSTREAM_INBOX.md` — not for every minor sync.

9. **Summarize to the user**: which repos moved, what got distilled where,
   what was explicitly out of scope, what's still pending. Then ask before
   committing — this touches tracked files (`kb/`, `MANIFEST.lock`,
   `UPSTREAM_INBOX.md`, `EXTERNAL_RESEARCH.md`, `CREDITS.md`) and git commits
   are never made without the user asking, per this project's standing rule.

## What NOT to do

- Don't run `sync.py --update` (no name = all repos) and walk away — a fast
  mover like `octabam` (178 commits in 2 days, 2026-09-14→16) needs a
  deliberate decision about how deep to go, not a blind full pull.
- Don't treat "I fetched and it printed a report" as done. The report is
  step 1 of 9.
- Don't put a cave/scratch address into the KB as "free" on a static scan alone.
  A static scan is **necessary and not sufficient** — octalab proved on hardware
  that 27 KB of zeros with *zero* static references is written at runtime, and
  bricked a unit into MIDI-only recovery finding out. Anything cave-shaped goes
  through `reference/kb/caves.md` and its canary protocol.
- Don't distill from a repo's forum/Discord-only findings without a
  fetchable source — note those as "see X's own doc that already folded it
  in" (e.g. Bryan T's live RE reaches this project via octabam's
  `docs/EXTERNAL.md`, not his own static repo).
