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

1. **Fetch + report first, cheaply:**
   ```
   python3 tools/refs/whatsnew.py --limit 0
   ```
   This just fetches and counts — tells you which of the ~8 repos in
   `refs/MANIFEST.toml` actually moved, with zero risk.

2. **For each repo that moved, pull it to tip** (this rewrites its
   `MANIFEST.lock` line — do not do this for a repo you don't intend to triage
   in this same session):
   ```
   python3 tools/refs/sync.py --update <repo>
   ```

3. **Read the actual diff, not just commit subjects.** For each pulled repo:
   ```
   git -C refs/<repo> log --oneline <old-hash>..HEAD      # old-hash from step 1's report
   git -C refs/<repo> show <hash>                          # for anything that looks relevant
   rg -n "<term>" refs/<repo>/                              # grep the checkout directly
   ```
   Check each repo's own docs first if it has them (`docs/`, `*.md` at the
   root) — most of these projects (octabam, ems-octakit, midisc) keep a
   running technical changelog that's faster to read than raw commits.

4. **Triage against this project's actual scope** (`COVERAGE.md`): ColdFire-side
   OS 1.40C behaviour on the **MKI**. A repo's own DSP-effect-tuning work,
   256-slot/kit schemes we haven't adopted, or synth-emulation work unrelated
   to the Octatrack (e.g. anything in `dsp56300/gearmulator` beyond the
   `dsp56300` core submodule) is legitimately "not for us" — say so explicitly
   rather than silently skipping it.

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
- Don't distill from a repo's forum/Discord-only findings without a
  fetchable source — note those as "see X's own doc that already folded it
  in" (e.g. Bryan T's live RE reaches this project via octabam's
  `docs/EXTERNAL.md`, not his own static repo).
