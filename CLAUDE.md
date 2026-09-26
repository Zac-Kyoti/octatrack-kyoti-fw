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

## Scope of this project

**Both planes, on OS 1.40C, hardware MKI:** the **ColdFire** control plane *and* the
**DSP56300** signal plane. This repo ships DSP56300 assembly — the SIDE-CHAIN
COMPRESSOR's `KEY` input is hardware-confirmed — so the DSP is **not** out of scope,
and any older note saying "ColdFire-only" or "the DSP side is out of scope per
COVERAGE.md" predates that and is wrong.

In practice the DSP is a **second front pursued when a feature or bug needs it**, which
is how the side-chain happened. So when triaging an upstream repo's work:
- **In scope:** DSP mechanisms, dispatch/module maps, the toolchain and emulator, the
  level law and frame protocol, and any effect this project touches or might donate.
- **Not for us** (say so explicitly rather than skipping silently): per-effect ear
  tuning of effects this project does not ship, kit/slot schemes we have not adopted,
  and synth emulation unrelated to the Octatrack.

[`COVERAGE.md`](COVERAGE.md) is the map of what is actually mapped so far; it is
descriptive, and this section is the policy.

## Hard constraints (do not relearn these the hard way)

- **Never call a UI or kernel primitive from an engine/frame hook — and do not
  trust a note calling a site a "per-frame tick".** `0x400522ca`
  (`FUN_40052200`) crashed a real MKI on 2026-09-25: dead controls plus a loud
  persistent HF crackle, after QLREC drove a toast from it. `FUN_4005a2b8`
  (NOTIFY) and `FUN_40056bec` (close) both bottom out in **`FUN_40000c3c`, the
  kernel post/wake** — it masks to `0x2700`, marks a blocked task runnable and
  pokes the ready-list head `0x800068d8`. That is legal from a **key handler**,
  not from the engine frame path. **If you need "has N seconds passed", read the
  OS's own state** (`0x460d1e70` handle / `0x460d1e6c` countdown for a toast)
  instead of counting ticks yourself. NOTES "Session 93".
- **"Hardware-confirmed" must name what was confirmed.** QLREC carried
  "hardware-confirmed, final" for six sessions while containing the latent
  crash above: what was actually confirmed was *it did not hang during that
  flash*. A rare crash and a clean feature look identical at flash time. Write
  the specific observation into the status line, not the conclusion.
- **Scratch RAM at `0x80006a40+` is NOT reliable under live audio, and our
  emulator cannot tell you.** QLREC kept one magic longword at `0x80006a60`;
  on hardware it was already gone by the *next key press* (a diagnostic build
  reported it on screen), while it persisted perfectly in the emulator, which
  does not run the DSP/audio path for real. The block sits in the **DSP
  shared-RAM window**, and a static "no references" scan says nothing about
  runtime writes. **Proven twice:** RELOAD3's request bytes at `0x80006a54-55`
  were overwritten between a key chord and the storage job that read them, so it
  reloaded the wrong (MIDI) track and still reported success (Session 98).
  **Prefer keeping no private state at all** — read the state the OS already
  maintains. Both features now keep theirs in their own cave.
  ⚠️ DIRECT JUMP (`0x80006a40-4a`, `wip`) still keeps state there; its flag is
  re-armed every tick so a clobber would be invisible rather than absent.
  NOTES "Sessions 94-96", "Session 98".
- **When hardware and the emulator disagree, build a diagnostic, don't reason.**
  Both of these were settled by a build whose on-screen message *named* the
  failing condition, after theories that survived static analysis and emulation.
  The emulator's blind spots (no UI tick, no real DSP path) are exactly where the
  bugs lived, so "emulator ALL GOOD" is evidence about the logic, never about the
  machine. Say which one you mean.

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
