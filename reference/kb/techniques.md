# Techniques worth borrowing — patch method, menu recipe, build pipeline

Cross-project method notes. Our own approach is in `README.md` §"Building" +
`START_HERE.md` §3; this file records what the other repos do differently and
what's worth adopting.

---

## octabam — module / remix build system

> source: `refs/octabam/README.md`, `docs/TOOLING.md`, `docs/HARNESS.md` @ `e1dcfa9` · fetched 2026-09-02

- **Module = one contribution; remix = a named selection composed into one image.**
  `modules/*/manifest.py` *is* the registry — adding a module is adding a directory.
- The build **refuses to start if two selected modules collide** — same FX id,
  ColdFire cave, hook site, private word, or buffer region — and names both.
  We do the equivalent with per-splice assertions (stock-byte check, cave
  free/non-overlap/in-range); octabam's *named registry of reserved regions* is
  the idea worth stealing if our patch count keeps growing (we're at ~6:
  trigscale, softmute, mutemode, directjump, arp, led…).
- Live "budget" reporting (free program words / spare cycles) printed by the build.
- octabam is **Claude-Code-developed too** (`refs/octabam/CLAUDE.md`) — its doc
  discipline (per-fact confidence markers, retracted values kept visible) is the
  same style as our `COVERAGE.md`; worth mirroring.

### Shared lineage — octabam ⇄ octamax ⇄ this repo

octabam's `docs/history/{NOTES,COVERAGE}.md` read like ancestors of ours (a
shelved live-bank-paging design lives on in all three lineages — ours is in
`reference/upstream-notes.md`). **octabam's ColdFire function names are directly
comparable to ours** — when RE'ing a new ColdFire area, grep `refs/octabam/docs/`
for the `FUN_4000xxxx` first, it may already be named and explained.

First sweep (2026-09-02): of ~140 `FUN_40xxxxxx` in octabam's docs, 27 are ones
we hadn't recorded — mostly the **SETTINGS-tree menu / screen-drawing** cluster
(`FUN_40064908` draw, `FUN_40064c18` open, `FUN_4005578c` key dispatch,
`FUN_40012bd8` text primitive) plus part/track teardown. Folded the menu cluster
into `memory-map.md` "UI / menu"; the rest listed there under "To import next".
octabam also gives the full `FUN_4006d57c` confirm-popup signature we use for
PERSONALIZE entries.

### WARNING: our emulator's fidelity is coupled to the `refs/octabam` clone

`tools/emu_rtos.py` runs octabam's script from **inside `refs/octabam/`**, against a
patched Unicorn built into that clone's `.venv`. **`sync.py --update octabam` therefore
updates our emulator**, silently.

Demonstrated 2026-09-24: the sync pulled octabam **PR #360** ("Unicorn EMAC: fix
MAC-with-load decode — Rx source, phantom dual, MASK reset"), which octabam derived from
**markandrus/octemu**'s report of three MAC-with-load decode defects in Unicorn's vendored
QEMU. The now-*more correct* EMAC changed a boot-time branch, reaching a stock zero-fill
loop (`lea 0x4f502c10,%a0` + `moveml`, 0xac480 iterations x 16 B, ~10.8 MB) that had never
executed under our harness — so `0x4f000000..0x50000000`, the external audio-sample SDRAM
bank, had to be mapped in `tools/emu_reload.py`. Nothing in our own patches changed.

**The operating rule:** after an octabam sync, re-run a known-good scenario first. A result
that changes after a sync is not automatically a regression in our patch — suspect the
emulator's new (usually better) arithmetic before suspecting the feature. Corollary: **an
emulator "green" from before a sync is not evidence for a build after it.**

### octabam `emu_rtos.py` — full-firmware emulator (route A)

> source: `refs/octabam/docs/RTOS_FORK.md` @ `47f6cc5` (2026-09-07)

Runs **the firmware's own scheduler**: the handoff trap, PIT0 ticking, all eleven
tasks, tasks posting to each other through the kernel, a real CompactFlash mount,
a real `LOAD PROJECT`, and the sequencer stepping a saved bank end-to-end (a step
trig fires at the right frame). Interrupts are modelled (INTC0/INTC1, forced
sources, ATA, PITs), so it shows *which task runs when* — key press → engine,
engine → DSP task, recorder-arm stage-then-promote. What it does **not** do: audio
(DSP stays in `dsp_host`).

**This is the tool NOTES L413 asked for** ("locate the knob→param editor … via
dynamic analysis"). Kernel/task/interrupt map is in `memory-map.md` "Kernel / RTOS".

**Wired up (Session 23): `tools/emu_rtos.py`** — a thin wrapper (no vendoring: it
runs `refs/octabam/tools/emu_rtos.py` in place with `--image` pointed at our
`section_3_MAIN_OS.bin`, same call as `build_sidechain2.py` ↔ `dsp_modmap.py`).
M6a / M6b verified on our image; M6c is slow (~10 s wall / 200 emulated ms).

⚠️ **Needs the EMAC-patched Unicorn** (Session 25 / octabam RTOS §10.16): stock
`unicorn 2.1.4` computes the ColdFire **fractional `macl`** as an unsigned product
`>> 32`; hardware's is signed, `<< 1` then `>> 31` — so every EMAC result under
stock Unicorn was *half* of hardware's, and octabam's `emu_rtos` now refuses route
A on it. The firmware's `2^31/N` reciprocal idiom (recorder block walk, PCM pool
`0x40095c46`, tempo/timing) only works with the fix, and ~5,600 EMAC-site
instructions run per sequencer frame so a Python shim isn't viable. Build once
(needs `cmake`):

    ( cd refs/octabam && PY=$(command -v python3) bash scripts/build_unicorn.sh )

It parks `libunicorn.2.dylib` in `refs/octabam/.venv/lib/unicorn-emac/` (gitignored)
where `emu_bringup` auto-detects it via `LIBUNICORN_PATH`; `emac_selftest` then
reports **OK**. Our `tools/emu_rtos.py` / `emu_plock.py` check for the dir and
print this command if it's missing. (Also fixed: MAC-vs-MSAC is *extension*-word
bit 8, not opcode bit 8 — stock added where the frame builder subtracts.)

Key injection: **`press_key_live(handler_addr, edge)`** calls any key handler as
`action(edge)` via `call_as_main` — parameterised, not just PLAY/REC/STOP. So the
Session-13 Phase-1 plan is: `--load-project` a bank with a p-locked step → into
LIVE REC running → `press_key_live(0x4005e25c, 1)` (`[NO]`) then the encoder
handler with a delta → `--watch-mem` the sequenced-data RAM (`[0x46c82456] +
pat*0x18b2`, near `+0x8f385`) to name the function that writes `0xFF` into the
p-lock record. Then RE that one function statically.

### octabam `tools/ot_emu` — the ColdFire PORT (C++), the audio-capable successor

> source: `refs/octabam/docs/COLDFIRE_PORT.md` (2705 lines) + `COLDFIRE_WORKORDER.md`
> @ `04b8512` (milestones O1–O12, 7–9 Sep 2026). confidence: **C** for what each
> milestone gates; **out of scope to adopt** unless a WIP blocker needs it.

`emu_rtos.py` (route A, Unicorn) is the **oracle** but costs ~120× real time, models
no audio, and stops at the DSP host port. `ot_emu` is octabam's rewrite: a headless
C++ Octatrack — Musashi ColdFire **V4e** (vendors `mc68k`, GPLv3; EMAC/`mov3q`/`mvs`
`mvz` as trap-and-emulate over frozen opcode tables), the MCF5445x PIT/INTC/eDMA/ESAI,
a CompactFlash image, and **both DSP56321 cores** (`dsp_host` folded in). ~39 M
inst/s ≈ 4.5× slower than real time, every claim gated against route A.

What it can do that route A / our `emu_rtos` cannot (as of O12):

- **boot to the RTOS handoff** (O1, PC `0x40000e46`, agrees with route A);
- **run the kernel + sequencer** with the cores live (O4/O6/O8) — the frame clock
  is the DSP's bank word, not a timer;
- **mount a card and `LOAD PROJECT`** (O7) — the mount needs a *delayed* INTRQ
  (instantaneous hangs the firmware);
- **render audio end-to-end** — ESAI input proven (O9), FLEX playback sample-exact
  (O10), a trig → voice → DSP → read-back path (O9b), and the one-aux bus
  **bit-identical to `dsp_host`** (O12);
- **reproduce a hardware audio bug and find its cause** (O11: the one-aux return
  never reached T8 because the stock dispatcher bumps `r7` **three times per
  track**, the third unconditional after FX2 — the `dsp_host` model had two).

Traps it establishes that bite our WIP work directly:

- **`dsp_host` pokes `r6` directly, so a page-2 param looks live locally even when
  the real unit publishes nothing** ("a slot can draw a knob and publish nothing",
  `PARAM_PAGES.md`). Our `emu_sc_dsp3.py` seeds `.mem` and pokes — passing it is
  **not** evidence the sidechain KEY/KEY FLT/KEY GAIN bytes reach `x:(r6+…)` on
  hardware. The publish path is in `memory-map.md` "Parameter value → the engine".
- **The part the emulated load applies is not the part that plays** — `ot_emu`'s
  load applies bank 1 / part 1; transport start re-applies the *saved* bank's
  pattern part and `0x4000c19c` rewrites the live lane from it. Cost octabam a
  whole O9c session measuring a track whose FX2 was silently `SEND`. Any fixture
  must write **every part of every bank** (`ot_project.py set-fx`, `stamp-slot`).
- **A part saved under an older slot layout feeds the new layout its old bytes and
  the sequencer stalls on the first play** — a 0–127 value sitting in what is now a
  count-3 select is the "value ≥ count used as an index" trap in *stored* form, and
  the schema cannot see stored data. After any change to a page-2 slot's
  count/position/meaning (our sidechain adds slots to COMPRESSOR; MUTE MODE relocates
  menu arrays), run `ot_project.py stamp-defaults` on the card before play.
- **Never rewrite emulated code in place** (a rewritten trampoline keeps its first
  translation in a long-running Unicorn) — relevant if we extend `emu_rtos` shims.

To use it we'd vendor `mc68k` + build (`make emu-cf`), same posture as
`vendor/dsp56300`. Worth it **only** if the Session-34 "LIVE-erase not tractable
headless" wall actually needs a scheduler-plus-audio emulator; for static RE and
the p-lock byte map, `emu_rtos` + `pattern-diff` still suffice.

### octabam `ot_project.py` — on-disk bank/project editor + differ

`pattern-trig` (write a step trig on disk), **`pattern-diff <A> <B> <bank>`**
(diff every step-mask between two saved projects → prints mask offset + changed
steps), `set_track_slot`, `set_machine_type`, `part-name`, `rigproj`/`stamp-defaults`.
`pattern-diff` turns "which bit is a recorder trig / trigless lock" into a
30-second hardware measurement — the Phase-0 lever for `file-format.md`'s p-lock map.

### Disassembling `section_3_MAIN_OS.bin` — the image loads at `0x40000400`

> source: `refs/octabam/tools/emu_bringup.py` (`BASE = ENTRY = 0x40000400`, "load
> base = 0x40000000 + 0x400 header"); our Session 27.

`out/raw/section_3_MAIN_OS.bin` byte 0 maps to **vaddr `0x40000400`**, not
`0x40000000`. So `vaddr = file_offset + 0x40000400`. Disassemble with:

```
m68k-elf-objdump -D -b binary -m m68k:5407 --adjust-vma=0x40000400 \
  --start-address=<vaddr> --stop-address=<vaddr> out/raw/section_3_MAIN_OS.bin
```

(`m68k-elf-*` is at `/opt/homebrew/bin/`.) Using `--adjust-vma=0x40000000` shifts
every function label 0x400 low **and** disassembles the wrong 0x400 bytes at any
given "vaddr" — it silently produces plausible-looking but wrong code (Session 26
lost a session to it). RAM addresses (`0x46xxxxxx`, `0x8000xxxx`) and code
immediates are read correctly regardless; only PC-space labels move. Cross-check
against emulator memory: `rt.uc.mem_read(vaddr, 16)` must equal
`file[vaddr - 0x40000400 : +16]`.

### Cave placement — the OS `.bss` tail is not free

> source: `refs/octabam/docs/FAILURE_MODES.md` @ `2f241e1` ("Line-F exception on [PROJECT]")

octabam pinned a cave at `0x40108800` (inside the OS image's last ~30 KB). A
static zero-check and a no-project emulator boot both passed — but that zero run
is **uninitialised OS data** (the PROJECT subsystem's RAM), and hitting PROJECT
threw a line-F exception. Their rule: caves live in **`0x400d2000..0x400d8000`**
(`SAFE_CAVE_CEIL = 0x400d8000`). Our builds already assert `< 0x400d7c3c` and sit
at `0x400d7400`+ — safely inside. Do not chase more cave space in the `0x4010xxxx`
tail.

**The real way past ~4 KB of cave: append a runtime.** ems-octakit reclaims a
multi-MB slice of the flex sample pool (4 two-byte constant patches in the
audio-page allocator, `0x40096f80–0x40097130`), appends an aPLib-packed blob to
the OS image, and hooks boot (~10 guarded splices) to unpack ~128 KB of linked
ColdFire code + MB of work RAM into it at `0x45d0dde0`. Hardware-proven. Full
mechanism + addresses + the cost (Octakit: 18.4 s of sample time; a KYOTI-sized
carve: sub-second) in [`octakit-abi.md`](octakit-abi.md) "The append-a-runtime
architecture". It buys **ColdFire** space only — nothing for the DSP.

## octamax (upstream) — the pipeline we inherited

`sysex/apply_patch.py`, the guarded code-cave detour method, the
PERSONALIZE-menu mapping (the octamax bundle builder `build.py` and its mod patch
sources are kept under `tools/attic/`). Track `whatsnew.py octamax` for new mods /
newly named functions to fold back.

### `emu_check.py` — Unicorn pre-flash gate (octamax `ec510e1`)

Unit-emulates individual firmware routines and **diffs a PATCHED image against
pristine STOCK** — "does this modified routine compute the same register/memory
effects as stock?". Catches the neutral-change / relocation-bug class without
flashing. Same idea as our per-feature `tools/emu_*.py`, but structured as a
reusable `CHECKS` list with a shared `Emu.call(entry, regs=, mem=, max_insn=)`
harness. Also `hookcheck` (`920c5c6`) — "fixed five analysis tools that gave
confident wrong answers", a caution worth heeding for our own emu scripts.
**Worth adopting the diff-vs-stock structure** if our emu scripts proliferate.

### PERSONALIZE persistence — the 'ANDY' battery-SRAM shadow (octamax `c78ff70`)

`0x800000xx` is volatile (boot re-images it). A toggle that must survive a power
cycle writes a shadow into the checksummed `'ANDY'` block at `0x100fff00` and the
build extends the block-restore `memcpy` length. Full mechanism + addresses in
`memory-map.md` "PERSONALIZE settings — persistence"; our port is Session 19
(`tools/patch_mutemode.s` + `build_mutemode.py`).

### OCTAMAX 2.x (`6ba0284`, Sep 2026) — not adopted, noted

Slice-playhead SRC>SLICES view (`patch_sliceview.s`), **dual-256 sample slots**
(a large DDR-relocation effort — `DUAL256.md`, "static pool reclaim"), persistent
PERSONALIZE toggles. The dual-256 relocation techniques (whole-block move of
operand refs only, combined-loop trampolines, boot-zero of the relocated region)
are the reference if we ever need to grow a stock table.

## Adding a whole menu SCREEN — the menu-state table (octabam)

> source: `refs/octabam/docs/MAINMENU.md` §9a @ `2f241e1` (2026-09-06)

For a new *screen* (not a PERSONALIZE row), octabam's "bus screen" grows the
**16-entry menu-state table at `0x400cbdac`** (stride `0x14`, entries
`{on_enter, on_exit, draw, key_handler, encoder_handler}`; a NULL member is
skipped `tstl %a0/beqs/jsr %a0@`). It's named by exactly **three `lea` immediates**
(`0x40064bd2`, `0x40064e34`, `0x400650e6`) and no pointer cell — so the same
relocate-and-repoint move as our PERSONALIZE arrays: copy `16*0x14` to a cave,
append a 17th, patch 3 operands, then point a menu action at state 17. Row
`+0x08` (menu-tree table `0x400cbcac`, separate) doubles as the selectable marker
(`0x40064f0a` / `0x40064fe8` skip rows with `+0x08 == 0`). This is the
lower-risk path when a feature needs its own page rather than a toggle.

## PERSONALIZE-menu entry recipe (ours, consolidated)

Used for MUTE MODE (`tools/patch_mutemode.s`) and DIRECT JUMP
(`tools/patch_directjump.s`):

1. Relocate the menu's 3 parallel arrays (labels / value-tables / handlers) to a cave.
2. Bump the item count (`moveq #15` → `#16`; note the MKI/MKII `0x46c8d18c` probe
   that makes it 15 vs 16 — patch the post-probe constant).
3. Splice the new entry at the chosen index.
4. State goes in a free work-RAM word `0x800000d4..df` — see `memory-map.md`
   "PERSONALIZE settings — persistence". **These words are volatile**: to survive
   a power cycle the setter must also write the `'ANDY'` shadow (`0x100fff00 +
   word − 0x80000070`) and the build must extend the 3 restore `pea 0x64` → `0x70`.
   MUTE MODE does this since Session 19; DIRECT JUMP (`0x800000a8`) does not yet.
5. Dialog construction via `FUN_4006d57c`.

## octa-bt-pt — Python image writer

Generates a flashable image from the user's own OS copy in Python. Cross-check its
checksum/section handling against our `build_*.py` as an independent
implementation (see `container-format.md`).

## ems-octakit — guarded patch recipe as data (open-sourced 2026-09)

> source: `refs/ems-octakit/{build.py,runtime/firmware.json,patcher/}` @ `ca3b527`

Same "bring your own OS, ship no binary" stance as us, but the patch set is a
**declarative recipe** (`runtime/firmware.json`), not code:

- **598 patch sites**, each `{offset, length, sha256, writes:[{offset,data}]}` —
  the `sha256` guards the stock bytes exactly like our per-splice assert, but
  machine-checkable and enumerable. Our asserts are inline in `patch_*.s`.
- **411 relocation ops** (`m68k-relocate` / `stock-copy`) rebuild the appended
  runtime from the user's stock image — every output byte is classified by origin
  (`sparse-public-write-v3`), so the repo provably contains no official code.
- Toolchain pinned in the recipe: `m68k-elf-gcc 16.1.0 -mcfv4e -Os`, Rust 1.97.1.
- Worth stealing if our patch count keeps growing: a single JSON manifest of
  `{addr, stock-sha, replacement}` that `build_*.py` consumes, instead of the
  guard logic living in each `.s`. Cross-refs the octabam "named registry of
  reserved regions" idea (above).

Full address map from its `abi.inc` → [`kb/octakit-abi.md`](octakit-abi.md).

## midisc — MIDI scene locks (1.40C, added 2026-09-16)

> source: `refs/midisc/{docs/TECH.md,tools/midisc/*.py}` @ `eb8b4bc` · fetched
> 2026-09-16 · **C** (HW-confirmed, shipping build `1.40MIDISC8`)

Address map + the XF-morph/persistence design distilled into
[`memory-map.md` "MIDI track scenes"](memory-map.md#midi-track-scenes--the-midisc-address-map-140c).
Notes specific to *how it composes with other patches* (relevant since we
already track the same kind of multi-patch composition question):

- **Code caves on stock 1.40C**, reusable coordinates for anything targeting
  the same OS build: `SAFE_CAVE 0x400D24D0..0x400D2CDC` (dirty/pack/unpack/
  save/xf_mix/plock trampoline/morph), `VOICE_RELOAD_CAVE 0x400D2E84..0x2EA0`,
  `CAVE2 0x400D2EE6..0x3020` (second zero gap after PLAYBACK string tables),
  `CODE2 0x400D6500..0x6600`, `STUB 0x400D7600..0x7C48`, `PROJECT_CAVE
  0x400E1EC4..0x2000`. **`CLEAR_CAVE` (`0x400C4302`) is UNSAFE for code** — a
  stock pointer table at `0x400ba8fa` refs into it; midisc only puts filter-UI
  data there, never Part-Clear logic. `SPARSE_CKPT_CAVE` (`0x400C1153`) is
  *also* unsafe — it sits inside a data table, not a real zero pad; an earlier
  midisc revision put code there and bricked on Part Reload. Cross-cave calls
  go through fixed **sentinel addresses** (`SENT_PACK`, `SENT_UNPACK`, …)
  patched post-link — the same "detour via a stable pointer, not a raw
  address" idea as our own `SENT_*` cave-boundary calls.
- **Composing with Octakit** (`refs/midisc/docs/TECH.md` "Compose with
  Octakit", checked against `sambanks/octabam` modules `midi-scenes` /
  `octakit` / `scenes-kits` and `emuyia/ems-octakit` pinned `ca3b527`): the
  two patches both want `STOCK_APPLY` (`0x40009094`); midisc's answer is to
  leave it **stock** and let Octakit own it alone, following along via
  hold/dial/pad hooks + Part Save/Reload + an `AFTER_PROJECT_LOAD` seed
  instead of body-hooking the shared entry point. General lesson for stacking
  our own mods on top of someone else's patched region: **prefer hooking
  the callers of a shared entry point over rewriting the entry point itself**
  — it's what let two independently-developed patches share one hook site
  without a merge conflict.
- **`part_window` seam** (`SEAM_CAVE`, `0x400D46E2`): a small trampoline
  (`IN d3=index → OUT a0=window, d1=stride`) that Octakit overrides to
  redirect "part index" to "kit payload base" — a clean pattern for one patch
  to let another patch redefine what "the current part" means, without
  either patch hard-coding the other's layout.
- **Do not force-push `main`** on this repo — octabam pins specific midisc
  commits as a submodule; a rewritten history there breaks octabam's build.

_(Extend as patterns recur.)_

---

## New methods adopted from the 2026-09-24 ingest

### The canary test — the gate our emulator diff cannot replace

> source: `refs/octalab/docs/CAVES.md` @ `e0dc56d`. confidence: **C**.

Our pre-flash gate (`emu_check.py` lineage, and now full-firmware emulation) proves
**the patch does what we meant**. It does **not** prove **the bytes we chose stay
ours** across a real session. Those are different questions, and the second one has
bricked two projects.

Before anything ships in a *new* region, on hardware: fill it with `0xA5` (or a 32-bit
counter, so a partial overwrite is visible) → flash → **use the unit normally for a full
session** (load a project, record, change patterns, save, power cycle, load again) →
dump and compare byte for byte. Survives → record the date and what was exercised.
Modified → it is live data; drop the claim.

Full ledger, the ranges already proven live, and the contested-cave ownership table:
**[`caves.md`](caves.md)** (new this session).

### Boot the patched image and walk the structure out of RAM

> source: `refs/octalab/docs/CAVES.md` @ `e0dc56d`, on octabam's
> `tools/verify_menushortcut.py`. confidence: **C**.

octabam's menu verifier **boots the patched image and walks the menu out of RAM using
the firmware's own layout** (`CONTROL_DESC 0x400cbd54`, count `+0x00`, rows ptr `+0x18`,
24-byte records). octalab's verdict on its own brick: *"MENUPROBE's crash was the cave
and nothing else — the record layout it wrote was right."*

The generalisation worth adopting: **a static byte-diff cannot distinguish "wrong
layout" from "right layout in the wrong place".** A RAM-side walk of the structure the
patch builds, under emulation, separates them before a flash. We already run full-firmware
emulation for behaviour; this is the same tool pointed at *data structure validity*.

### Declare each mod's byte range and assert non-overlap at build time

> source: `refs/octalab/docs/CAVES.md` @ `e0dc56d`, lifting octabam's `tools/remix/ledger.py`.

octalab has every module declare its sub-range in a `manifest` and **the build refuses
to place two overlapping modules**. The reason to automate rather than eyeball it:
silently overlapping machine code is *the* one class of bug that yields **a unit that
boots and then misbehaves** — no crash, and nothing an image diff flags.

`build_merged.py` composes 7 mods and tracks `FREE_START`; an explicit per-mod range
declaration plus an overlap assertion is the cheap version of the same guarantee.
→ `reference/MERGE.md`.

### Persisting feature state in the PROJECT file, not the battery block

> source: `refs/midisc/tools/midisc/memory_map.py` + `docs/TECH.md` @ `63ca127`. confidence: **C**.

Our only persistence mechanism so far is the `'ANDY'` battery-SRAM shadow (octamax
`c78ff70`, ported in Session 19) — which is **global**, one value for the unit.

midisc 8.2 does the other thing: a **project-scoped** setting. Its CC-filter flags are a
**packed byte at `0x460CA680`** (CLIP + 0xC80) with bits 0/1/2 = CC48/55/56, persisted
under a **project key `MIDISC_CC_FILT`** via load/save trampolines in two D-region pads
(`0x400D347E..CF`, 81 B; `0x400D352D..6F`, 66 B).

**When to reach for which:** battery block = a unit-wide preference (our PERSONALIZE
toggles). Project key = state that should travel with the project and differ between
projects. The second is the right shape for anything per-set.

⚠️ midisc records that **`PERSONALIZE A8/D8/DC` did not survive on hardware** for this
purpose — "do not claim". And their persist caves **bricked Project Save** in an earlier
revision (`PERSIST_PLAN.md`); the CC-filter feature is `ENABLE_MIDI_CTRL_FILTER = False`
and **on hold** in 8.2 for that reason. Treat project-file persistence as a real but
**unproven-for-us** route, and read their `PERSIST_PLAN.md` before attempting it.

### Two bug classes to check our own patches against

> source: `refs/midisc/docs/TECH.md` @ `63ca127` (the 8.1 → 8.2 deltas). confidence: **C** — these are shipped-and-fixed bugs, not speculation.

Both are shapes our patches can take, so they are worth a grep, not just a read.

1. **The missing per-track stride.** midisc 8.1's `xf_mix` LFO lock probes indexed
   `MSC[scene] + param` and **omitted `track*32`** — so **MIDI track 1's locks affected
   other tracks' LFO flats.** Fixed in 8.2 to `track*32 + param`. Any of our code that
   indexes a per-track array must carry the track stride; a bug here is silent and
   cross-talks between tracks rather than crashing.
2. **Clobbering the live encoder value on the write path.** 8.1 ran
   `build_voice_reload_d2` after `xf_mix`, overwriting the dialled `d2` from stored
   state before stock's `CC_TX` — so **unlocked params went silent / stuck**. 8.2 keeps
   the encoder's `d2` and leaves the reload cave in the image, unused. The rule: on a
   write path, the value the user is currently turning wins over any stored copy.

### Instruction-profile numbers for stock 1.40C — where the CPU time actually goes

> source: `refs/octamad/docs/firmware/STOCK_PROFILE.md` @ `ccb11fb` (branch
> `origin/poly-machine`), Jannik Aßfalg / repeat98, 23 Sep 2026. confidence: **L** —
> emulated instruction counts on one fixture, explicitly **not** cycles.

Exclusive **instructions per 16-sample frame**, on an 8×FLEX 120 BPM fixture (DELAY on
T1–T7, PLATE REV on T8 — *not* a no-effects fixture):

| CPU scope | insns/frame | share |
|---|---:|---:|
| Frame / control ISR | 10,719.9 | 26.21 % |
| Eight-track delay | 7,664.5 | 18.74 % |
| Sample analysis | 5,642.5 | 13.80 % |
| Voice renderer | 5,605.3 | 13.70 % |
| Correlation search | 2,195.9 | 5.37 % |

Verified extents (we re-checked the first against our own image — `0x4000d9ae` is the
`rte`): **frame ISR `0x4000aad0..0x4000d9b0`**, **voice rendering
`0x40007960..0x40008f82`**.

⚠️ **Read the caveats before quoting any of this.** These are *instructions*, not cycles
or utilisation; the emulated cadence (3,990 CPU insns/sample, 4,160 DSP) is assumed;
caches, bus contention and physical deadlines are not modelled faithfully enough for a
headroom claim — **do not convert with the hardware clock.** No hardware was flashed or
measured. Useful as a **relative** map of where cost sits when we judge whether a hook
is affordable, and nothing more.

Also from the same doc: **`FUN_4000c8a4` is not a function boundary** — it points inside
the frame ISR, even inside an operand at that exact address. Our
`tools/patch_partreapply.s` names it; see the correction in
[`memory-map.md`](memory-map.md) "Kernel / RTOS scheduler".

### Distributing a patch as a span diff — the midisc-patcher format

> source: `refs/midisc-patcher/patch.json` + `patcher.js` @ `1ce2245` · fetched 2026-09-24.
> confidence: **C** (read the shipped artefact).

`FLASHING.md` already takes the right posture — the user brings their own official OS and we
never redistribute an Elektron binary. midisc-patcher is that posture **as a single data
file**, and the format is worth copying because it is almost trivially small:

| field | value in theirs | why it matters |
|---|---|---|
| `stockSha256` | `164f3122…` | verifies the user supplied the right input **before** patching. Same image we and every tracked upstream use. |
| `mainOsSize` | `1112560` | second, cheap input check — byte-identical to our `out/raw/section_3_MAIN_OS.bin` |
| `patchedSha256` | `70df682f…` | **verifies the rebuild** — the user's output either matches bit-for-bit or the build is wrong |
| `spans` | 549 × `{offset, data}` (base64) | the entire patch as a byte-span diff |
| `name` / `splash` / `base` / `source` | `1.40MIDISC8.1` / `1.40MDIS81` / `1.40C` | provenance, and the splash string to expect on the unit |

Two things we do not currently give the user, both nearly free:

1. **A `patchedSha256` reproducibility gate.** Our builds are guarded splices that assert the
   stock bytes they overwrite, so a wrong input fails loudly — but we do not publish the
   expected *output* hash, so a user cannot confirm their rebuild matches ours. One line in
   each `build_*.py`.
2. **A single-file patch artefact.** `{stockSha256, patchedSha256, mainOsSize, spans[]}` is
   emittable from any of our builds (diff patched vs stock, coalesce runs) and is
   redistributable — it contains only *our* bytes, never Elektron's. That is the same
   licence-safe reasoning that keeps `refs/` out of git.

⚠️ Their browser patcher does the assembly client-side; we do **not** need the browser half to
adopt the format. The value is the manifest + the two hashes, not the UI.

