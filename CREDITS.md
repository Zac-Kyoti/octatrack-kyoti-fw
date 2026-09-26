# Credits & lineage

OT Kyoti FW **began as a fork of [`mxldyn/octamax`](https://github.com/mxldyn/octamax)**
by Maxolydian and stands on a wider body of Octatrack reverse-engineering work.
Nothing here would exist without the projects below.

## Direct lineage

- **[octamax](https://github.com/mxldyn/octamax)** — Maxolydian.
  The workspace this project is built on: the container/update-chain analysis, the
  reproducible guarded-patch/build pipeline, the code-cave detour method, the
  PERSONALIZE-menu mapping, and the first round of behaviour mods (lazy Part
  transitions, no BANK/PTN countdown, arp key scales, boot branding, LED dirty
  indicators). Those mod patch sources and the bundle builder (`build.py`) are
  kept in [`tools/attic/`](tools/attic/) for reverse-engineering
  cross-reference — they are not part of any OT Kyoti FW build — and the design
  notes are in [`reference/upstream-notes.md`](reference/upstream-notes.md).
  octamax ships no `LICENSE` file; this project exists under GitHub's Terms of
  Service and keeps octamax's stance — educational use only, no binaries
  redistributed.

## The harness this project verifies against

- **[sambanks/octabam](https://github.com/sambanks/octabam)** (Octabam, by
  **sambanks**) — **the single largest external dependency in this repo, and the
  reason most of what is here could be validated at all.** Octabam's own goal is
  original DSP56300 audio effects for the Octatrack MKII, but along the way it built
  the Octatrack emulation stack this project runs on, and tracks it as a first-class
  deliverable with its own documentation set. **98 of this project's 169 tools import
  it** — every emulator-validated build, bug repro and diagnostic here goes through
  it. Specifically:
  - **Route A**, the Unicorn-based ColdFire harness (`emu_rtos.py`, `emu_bringup.py`,
    `emu_card.py`) that boots our real patched image, mounts a CF card image, loads a
    project and runs the sequencer. This is what "emulator-validated" means in every
    build note in this repo, and it is octabam's code running from inside
    `refs/octabam/`.
  - Its **Unicorn EMAC patches** — without them the ColdFire's MAC unit decodes
    wrongly and our images do not boot correctly. `scripts/build_unicorn.sh`.
  - **`ot_emu`**, its independent C++ ColdFire + DSP56300 port, which renders real
    audio and runs ~11x faster than route A. Our native diagnostics are built on it.
  - **`dsp_host`**, its dsp56kEmu integration, and the pinned
    **[dsp56300/dsp56300](https://github.com/dsp56300/dsp56300)** core it vendors into
    `vendor/dsp56300` — the toolchain the SIDE-CHAIN COMPRESSOR was written and tested
    with. Our `tools/dsp56300_xcore/` dual-core harness is a thin shim over it.
  - Its **firmware documentation set** (`docs/firmware/KERNEL.md`, `DSP.md`,
    `CHIP.md`, `LEVEL_LAW.md`, `COLDFIRE_DELAY.md` and siblings) — an independent
    reading of the RTOS, the DSP protocol and the level law, distilled throughout
    `reference/kb/`.

  Octabam is also the closest thing this project has to a peer on method: the same
  "bring your own official OS, patch it, redistribute no binary" stance, the same
  guarded-build discipline, and a contributor ledger that credits its own upstreams
  properly. **MIT** for its own code and documentation; that does not extend to
  Elektron's firmware (not distributed there either) or to the repositories it
  vendors as submodules, which keep their own terms — `dsp56300` in particular is
  GPLv3, and `THIRD_PARTY.md` in octabam lists every transcribed DSP source.

## Tools this project builds on

- **[mischa85/elektron-firmware-tool](https://github.com/mischa85/elektron-firmware-tool)**
  — packs/unpacks the ELEK container and the `.bin`/`.syx` transports. Fetched
  into `vendor/` by `setup.sh` and patched locally
  (`tools/elektron-firmware-tool.patch`, two small changes documented in
  `sysex/README.md`). Keeps its own license.
- **[snugsound/OctaLib](https://github.com/snugsound/OctaLib)** — project/bank
  file-format reference used when cross-checking the on-CF data model.
- **aPLib** — the OS payload compression; implemented in
  `elektron-firmware-tool` from the public format description.

## Other Octatrack firmware-patching projects

The same "bring your own official OS, patch it, roll your own image, redistribute
no binary" approach — worth reading alongside this repo. (**octabam** belongs here
too, and has its own section above.)

- **[emuyia/ems-octakit](https://github.com/emuyia/ems-octakit)** (Octakit, by
  emuyia / junes) — a patcher for OS 1.40C that replaces the 4 Parts per Bank with
  **256 Kits per Project**. Open-sourced in 2026-09: its `runtime/abi.inc`
  (~500 named stock-firmware addresses for the Part / Kit / Bank / scene /
  LFO-designer / sequencer subsystems) and `runtime/firmware.json` (598
  SHA-guarded patch sites) are distilled into
  [`reference/kb/octakit-abi.md`](reference/kb/octakit-abi.md). MIT-licensed as of
  2026-09-12 (`20b0697`); still no official Elektron code/assets — same
  "bring your own OS" stance as this repo.
- **[bryantysinger/octa-bt-pt](https://github.com/bryantysinger/octa-bt-pt)**
  (Bryan_T) — a parameter-default patch tool for OS 1.40C (Python / Streamlit):
  customise the firmware's default values and generate a flashable image from
  your own copy of the official OS.
- **[bkkbrls-del/midisc](https://github.com/bkkbrls-del/midisc)** — added
  2026-09-16. MIDI-track scene A/B locks + XF morph for OS **1.40C** (the same
  base OS this project targets). A dense, HW-confirmed address map and a
  reusable part-save persistence + composition pattern, distilled into
  `reference/kb/memory-map.md` and `reference/kb/techniques.md`. Already
  vendored by octabam as a submodule (`modules/midi-scenes`).
  Its companion **[midisc-patcher](https://github.com/bkkbrls-del/midisc-patcher)**
  (added 2026-09-24) does the patching **in the browser** from the user's own stock
  OS — the automated form of the "ship a recipe, never a binary" posture
  [`FLASHING.md`](FLASHING.md) takes by hand.
- **[nordseele/octalab](https://github.com/nordseele/octalab)** (octalab, by
  **nordseele**) — added 2026-09-24. Creative helper functions (a groove pool after
  Ableton's, CAPTURE, GENERATOR, workflow shortcuts) added to stock **OS 1.40C**,
  **built and tested on an Octatrack MKI** — the same OS *and the same hardware
  revision* as this project, which no other upstream can claim. It publishes
  findings only (MIT), not firmware or source, and its
  [`docs/CAVES.md`](https://github.com/nordseele/octalab/blob/main/docs/CAVES.md)
  is the reason this project now has a cave ledger: it establishes **on hardware,
  at the cost of a MIDI-only recovery**, that the 27 KB of zeros at the tail of the
  image are written at runtime and cannot hold code. Distilled into
  [`reference/kb/caves.md`](reference/kb/caves.md),
  `reference/kb/memory-map.md`, `reference/kb/file-format.md` and
  `reference/kb/techniques.md`.
- **[markandrus/octemu](https://github.com/markandrus/octemu)** (octemu, by
  **markandrus**) — added 2026-09-24. A **QEMU-based Octatrack emulator** (ColdFire
  MCF54455 + dsp56300 + SDL2) with an emulated front panel, CF card and NVRAM, plus
  three ColdFire firmware customisations (a RECEIVE machine generalising NEIGHBOR;
  USB-MIDI completing a partial stock implementation; a UAC2 16-channel USB-Audio
  tap). Its `re/coldfire.syms` — 768 annotated ColdFire symbols — is an independent
  naming of much of the image and is distilled into
  `reference/kb/memory-map.md`. Own sources MIT; **its binaries combine
  incompatible licences and may not be redistributed** — build your own.
- **[repeat98/octamad](https://github.com/repeat98/octamad)** and
  **[repeat98/octamachine](https://github.com/repeat98/octamachine)**
  (**Jannik Aßfalg / repeat98**) — added 2026-09-24. Jannik contributes to octabam
  directly (Tape Echo, the ColdFire delay-routine protocol, the EMAC integer-vs-
  fractional `ACCext` finding); `octamad` additionally carries his stock-firmware
  **instruction profile** (`docs/STOCK_PROFILE.md`, branch `poly-machine`), which
  octabam records as never sent upstream and which is distilled into
  `reference/kb/techniques.md`. `octamachine` is a feasibility study for running
  Machinedrum firmware on Octatrack hardware — out of scope here except for its
  host-side statement of the Octatrack's own platform requirements.

## The DSP56300 emulator core

- **[dsp56300/dsp56300](https://github.com/dsp56300/dsp56300)** — added
  2026-09-16. The canonical, actively-developed Motorola/Freescale/NXP
  DSP56300-family emulator (GPLv3) — the actual upstream octabam vendors a
  pinned commit of into `vendor/dsp56300` — which is how this project gets it at
  all. Tracked directly (branch
  `dsp56300`, the active branch — not `main`) so this project can check its
  own DSP56300 questions against current upstream instead of octabam's
  vendored snapshot. See `reference/kb/dsp56300.md` for the currency gap this
  surfaced. The org's flagship consumer project,
  **[dsp56300/gearmulator](https://github.com/dsp56300/gearmulator)** (VST/AU/
  CLAP/LV2 emulations of the Access Virus, Waldorf microQ, Nord Lead and
  others — none of them the Octatrack), pulls this same repo in as a
  submodule; reviewed 2026-09-16 and not tracked separately since it adds
  nothing beyond that submodule for this project's purposes.

## Community reverse-engineering & documentation

- **emuyia / junes** — the Octakit (`ems-octakit`) source release attributes a
  large slice of the OS 1.40C Part/Kit/Bank/scene/sequencer address map, folded
  into `reference/kb/octakit-abi.md`.
- **sambanks** (`octabam`) — beyond the harness above, octabam's firmware docs and
  contributor ledger are a primary source throughout `reference/kb/`.
- **Bryan_T** (`octa-bt-pt`), **snugsound** (`OctaLib`),
  **mischa85** (`elektron-firmware-tool`), **bkkbrls-del** (`midisc`) — the
  prior-art repos whose findings are distilled, with per-fact attribution, into
  `reference/kb/*.md` (see `reference/EXTERNAL_RESEARCH.md`).
- **Elektronauts threads** that seeded specific findings here:
  - Octatrack CPU chip model — https://www.elektronauts.com/t/octatrack-cpu-chip-model/93304
  - Modifying Elektron firmware — https://www.elektronauts.com/t/modifying-elektron-firmware/36228
  - Plays-Free MIDI manual-trig stall (Bug 1) — documented on Elektronauts
    (thread 87588), 2019, MKI OS 1.30B.

## Legal reference

- EFF Coders' Rights — Reverse Engineering FAQ:
  https://www.eff.org/issues/coders/reverse-engineering-faq
- EU Directive 2009/24/EC Art. 5–6 (study/observe/test; decompilation for
  interoperability).

---

*"Elektron" and "Octatrack" are trademarks of Elektron Music Machines MAV AB,
used here only to identify the hardware under study. This project is
independent, unofficial, and not affiliated with or endorsed by Elektron.*
