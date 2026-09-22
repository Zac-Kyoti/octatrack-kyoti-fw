# Working in this repository

**This file is auto-loaded every session — `START_HERE.md` and `NOTES.md` are
not, so treat what's below as the guaranteed minimum, then go read them.**

## Before doing any RE, patch, or KB work

1. **`START_HERE.md`** — the real onboarding doc: read order, document map,
   which branch has the current frontier. Read it before anything else.
2. **`NOTES.md`** — jump to the newest `## Session N` (it's chronological
   from 2026-07; do not read top-to-bottom). `grep -nE '^## ' NOTES.md` for
   the index.
3. **`reference/kb/*.md`** — the distilled external-RE knowledge base
   (address map, file format, DSP, container, techniques). Check the file
   relevant to what you're touching before proposing anything; each fact
   carries its own source attribution.
4. **`reference/EXTERNAL_RESEARCH.md`** / **`reference/UPSTREAM_INBOX.md`** —
   what's tracked from the other Octatrack RE projects and what's pending
   distillation. `.claude/skills/pull-research/` is the one-command way to
   check upstream and fold anything new into `kb/`.

## Hard constraints (do not relearn these the hard way)

- **Hardware = Octatrack MKI only. No MKII.** Stock 1.40C is one image for
  both; the boot probe `0x46c8d18c` adapts it (MKI shows 15 PERSONALIZE
  items, no `LED BRIGHTNESS`). Any older note saying "MKII" predates this
  correction and is wrong.
- **Test data**: only real hardware-exported project files. Never fabricate
  or hand-edit a `.work`/bank/project blob — ask the user to export one.
- **Builds are guarded binary patches, never hand-assembled images**: every
  splice asserts the stock bytes it overwrites, asserts caves are free /
  non-overlapping / within the free zone, and round-trips through Elektron's
  own firmware tool.
- **Two branches, different state**: `main` is stable/hardware-tested only;
  `wip` is the active frontier. Check which one you're on — each branch's
  own `START_HERE.md` "Current frontier" section reflects its own state, not
  the other's.
- **macOS TCC**: `~/Documents` is protected; grant Full Disk Access to the
  actual running `claude` binary if a tool call fails with "Operation not
  permitted" on this path — see `START_HERE.md` §3 for the exact binary path.

Full detail, toolchain entry points, and the current frontier: `START_HERE.md`.
