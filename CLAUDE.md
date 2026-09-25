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
   (address map, file format, DSP, container, techniques, **caves**). Check
   the file relevant to what you're touching before proposing anything; each
   fact carries its own source attribution.
4. **`reference/EXTERNAL_RESEARCH.md`** / **`reference/UPSTREAM_INBOX.md`** —
   what's tracked from the other Octatrack RE projects and what's pending
   distillation. `.claude/skills/pull-research/` is the one-command way to
   check upstream and fold anything new into `kb/`.

## Hard constraints (do not relearn these the hard way)

- **Choosing an address for new code? Read `reference/kb/caves.md` FIRST.**
  Not "if it seems relevant" — always, before naming a cave address. Two
  projects have bricked units into MIDI-only recovery getting this wrong, and
  the trap is counter-intuitive: **27 KB of zeros at the tail of the image
  (`0x401087e4..`, `0x4010cdd1..`) has ZERO static references and is still
  written at runtime.** A static scan showing "no references" is *necessary and
  not sufficient* — only a canary run settles it. The 6 KB cave we build in is
  contested by four other projects and is effectively full; when it runs out
  the answers are in that file (append-a-runtime, or a CF-card payload), not a
  new region.
- **A borrowed address or signature is a claim, not a fact — verify it against
  our own image before relying on it.** Every upstream we track cites the same
  MAIN OS (`section_3_MAIN_OS.bin`, sha256 `164f3122…`), so their addresses are
  directly comparable *and* sometimes wrong: on 2026-09-24 a borrowed function
  signature was wrong (`apply_part(part, pattern)`; it is `(bank, part)`) and a
  "this word is referenced in stock" warning turned out to be unsubstantiated.
  Thirty seconds of `m68k-elf-objdump -D -b binary -m m68k:cfv4e -EB
  --adjust-vma=0x40000400 --start-address=… out/raw/section_3_MAIN_OS.bin` is
  the difference. Mark a fact **C** on our own reading, not on someone's label.
- **`sync.py --update octabam` silently changes OUR emulator.**
  `tools/emu_rtos.py` runs octabam's script from inside `refs/octabam/` against
  a Unicorn patched in that clone's `.venv`. After any octabam sync, re-run a
  known-good scenario before trusting a new result — and **an emulator "green"
  from before a sync is not evidence for a build after it.**
  **The clone also needs a local patch to boot our images at all**:
  `tools/refs/local-patches/octabam-emu-samplebank-map.patch` (the external
  audio-sample SDRAM bank; without it boot dies `UC_ERR_WRITE_UNMAPPED` in
  `gate_m6a`). A sync un-applies it — `sync.py` now prints the re-apply command,
  and `tools/refs/local-patches/README.md` explains why the lock still pins the
  upstream commit rather than the local one.

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
