# DIRECT_JUMP_KYOTI × Octakit — scope (2026-10-02)

> **STATUS: SCOPE ONLY.** No build, nothing reproduced yet. Users report that an octabam image
> with both OCTAKIT and DIRECT_JUMP_KYOTI crashes the OT. This document explains why that is
> expected, and plans how to make the pair work. **C** = read in source (her runtime
> `modules/octakit/upstream/runtime/*.S` @ `c6d3f39`, our `patch_directjump_v7.s`, the stock
> image). **L** = inference, which Phase 1 has to confirm.

## 1. How users get this combination

- In the octabam REMIXER, both modules can be selected at once. **The octabam ledger reports
  the pair CLEAN (C, run 2026-10-02 against octabam `8d0ad6f4`).** No byte is shared:
  - DJK's hooks are `0x400a1f72`, `0x400a221c`, `0x40043418` and the `[PTN]`-layer YES record
    at `0x400bf0be`.
  - DJK's call targets are KPOST, PC send `0x4009e884`, COND_RESET `0x400a539c` and NOTIFY.
  - None of these is among Octakit's 681 recipe sites. DJK has no substituting detour, so the
    pinned-return check (the kind of collision `kits-reload` fixed) does not fire either.
  - `[PTN]+[YES]` does not collide with any Octakit gesture.
- The crash therefore comes from **shared runtime state**, not from bytes. The ledger cannot
  see this class of collision. The MIDI SCENES × Octakit Part Reload trap was the same kind of
  problem: octabam `modules/kits-reload/README.md`, "The collision is not a byte".

## 2. Mechanism

**Octakit turns a pattern switch into a checked transaction (C).** Parts become Kits held in
a pool of 64 "physical" slots, with a reference-counted descriptor and lease ("sidecar")
system. A stock pattern switch runs through her wrappers at every step:

| step | stock site | her wrapper | what she checks / does |
|---|---|---|---|
| cue / publish / queue | `0x400a0570` schedule (callers `0x400a0eaa`, `0x400a101e`, `0x400a1040`, `0x4004a652`), queue commit `0x400a10c8`/`0x400a1498`, queued hand-off `0x400a06d6` | `gk_stock_pattern_schedule_prepare`, queue-commit entry/exit | Identifies the caller from its **return address**. `gk_workspace_prepare` acquires a physical slot for the pattern's Kit and **rewrites the pattern's Part byte (`+0x8e57`) to that slot**. |
| the switch, in the tick ISR | `0x400a4568..0x400a4856` (latch writes `0x46c7ff40` / `0x46c7ff62`, MIDI twin) | `sequencer-latch-begin/commit` `0x400a45a8`/`0x400a468c`; `midi-refresh-begin/commit` `0x400a475e`/`0x400a47f0` | Begin validates her shadow copies against stock state: `__gk_current_bank/pattern`, the descriptor, the physical cache, the pattern assignment, the `+0x8e57` byte, and ENGINE_BANK/PART. Then it opens a lease. Commit publishes ENGINE_APART **together with** the lease sidecar. |
| audio engine applies | `0x4000af24`, `0x4000b1d6` (light apply `0x40009e00`) | `gk_stock_audio_latch_gate`, `audio-pattern-part-load-commit` | `gk_audio_latch_ready`: if the latch and the sidecar disagree, she **skips** the apply. |
| scene A/B stores | `0x4000afc4`, `0x4000b0d2` | `gk_audio_latch_store_byte` | If the latch is not ready, she executes **`illegal`**. |
| UI messages | `0x4006214e` (case `0x10`), `0x400621a6` (case `0x13`) | pattern-event-retry, part-event-publish | — |

Every inconsistency she detects ends at one of her `*_report_fatal` / `*_fatal` labels, an
`illegal` instruction, which shows on the unit as **`EXCEPTION … VEC:04`**.

**DIRECT_JUMP_KYOTI bypasses all of it (C).**
- V7.0.1's `dj_handoff` is, by design, a value-for-value **replay of the stock writes in
  `0x400a4568..0x400a4856`** (DIRECTJUMP_V7_DESIGN.md §8): ENGINE_AFLAGS, ENGINE_ABANK,
  ENGINE_APART, the MIDI twin, and COND_RESET. It does this without her begin/commit
  wrappers.
- `dl_commit` does ACT←PEND (`0x800065bd/be`) itself.

**Expected result (L):**
- After a DJ jump, ENGINE_APART has no matching sidecar and her shadows still name the old
  pattern.
- The audio gate then either skips the Kit apply (wrong sound, no crash) or a later validation
  fails and she traps.
- The first scene move is a likely trigger. So are the next natural pattern change (latch
  begin finds `__gk_current_*` ≠ ACT), the next Kit load, and the tick's descriptor release.
- **So the crash may come after the jump rather than on it.** Reports should say what
  happened just before the crash.

## 3. Options

| | what | for | against |
|---|---|---|---|
| **A** | Declare the conflict in `octabam-modules/direct-jump-kyoti/manifest.py`: `conflicts=(("OCTAKIT", …),)` | Stops new crash reports at once; one line | Takes DJ away from Octakit users until B lands; reaches users only when Sam bumps the submodule |
| **B** | A **bridge** module (octabam's pattern: `kits-reload`, `scenes-kits`), selected only when both are present. It makes DJK's landing run her transaction around the replayed writes, gates arming on her prepared Kit, and releases her lease when the cue is cancelled | Leaves V7's hardware-confirmed timing code untouched; costs nothing in images without Octakit | Depends on her private globals (`gk_sequencer_latch_begin`, `gk_sequencer_latch_commit_part`, `gk_midi_refresh_begin`, …) and so is pinned to her version, like the existing bridges. It is unknown whether an octabam `Linked` unit can link against a `Runtime`'s symbols (`runtime_build.py` has the symbol table internally) |
| **C** | Restructure DJK so that its landing runs **stock's own switch block** instead of replaying it. Any mod's wrappers (Octakit, PARTREAPPLY, midisc) then run on their own | Composes with everything | Undoes V7's founding rule ("nothing enters the wrap-change body", which shut out the V1–V5 failure modes). Means a full re-gate of the timing matrix and new hardware runs |
| **D** | Ask Em for a supported entry point, e.g. "switch to bank/pattern now, with the Kit transaction" | Cleanest long term; her code, her invariants | Depends on her time; her README invites combining her repo as a submodule |

**Recommendation:** A now. Then Phases 1–2 to prove the mechanism and measure the protocol,
then B. Raise D with Em in parallel, carrying the Phase 2 measurements, since a fixed entry
point would turn B into a thin wrapper. Keep C on the shelf.

## 4. Work plan

**Phase 0: stopgap and intake** (small)
- [ ] User: collect the crash reports. For each: the EXCEPTION screen (VEC, ADDR, D0, SP,
  CFW), the remix, its module list and octabam commit (or the image sha), what was done just
  before (jump to a pattern on the same Kit or another Kit; DJ on but idle; scene move after
  a jump), and if possible the project.
- [ ] A: add the `conflicts` entry, commit it here (thread `directjump`), ask Sam to bump.
- [ ] Map each reported ADDR to her symbol: build the reporter's remix, read her link map,
  find the matching `*_fatal` label. That names the check that failed before any emulation.

**Phase 1: reproduce under the port**
- Build a test remix with OCTAKIT + DIRECT_JUMP_KYOTI (alongside `remixes/test/direct-jump-kyoti`)
  in a **scratch octabam copy**. Reason: the shared libunicorn hazard; rebuilding it kills
  other sessions' runs.
- Fixture: a real exported project, either the reporter's or one of the user's that Octakit
  migrates into Kits when it loads. Never a hand-made one.
- Drive it with `ot_emu`: `--sequencer`, the `key` verbs (local patch
  `octabam-ot-emu-steps-key.patch`), `--watch-pc` on every `illegal` in her runtime.
- Matrix:
  1. DJ ON idle
  2. jump with the same Kit
  3. jump with another Kit
  4. jump, then a natural change
  5. jump, then a scene move
  6. jump, then a Kit load / UNDO KIT
  7. re-cue during the arm window (V7.0.1's take-back path)
- Exit: the trap reproduced and named, with what triggered it. If it does not reproduce,
  build a diagnostic image (CLAUDE.md: when hardware and the emulator disagree, build a
  diagnostic, don't reason).

**Phase 2: measure the stock switch under Octakit** (V7.0.1's method)
- With DJ OFF, record her complete trail through one natural switch: same Kit, then another
  Kit. Record the order of calls and every change to her state (sidecars, descriptors
  ROOTS/READERS, physical cache, `__gk_current_*`, `__gk_pattern_queue_commit_prepared`,
  `+0x8e57`).
- Find **when the cued Kit becomes resident**: at cue time on the UI side (L, from
  `gk_workspace_prepare` in schedule/queue-commit), or at the wrap. This decides whether
  DJ's next-step landing can always find it ready.
- This trail is the spec for the bridge.

**Phase 3: build the bridge (B)**
- In `dl_commit` / `dj_handoff`: run her latch begin, then the stock writes (or let her
  commit publish them), then her latch commit; MIDI refresh begin/commit around the MIDI
  twin; keep her shadow in step with ACT←PEND.
- Arming gate: arm only when her prepared Kit for PEND is ready. The policy when it is not
  ready is a user decision (§5).
- Cancel and re-cue: release her lease through the same path her schedule-abort uses
  (`0x400a0728`).
- Schema: confirm with Sam how a `Linked` unit references `Runtime` symbols, or add that.
  Decide where the bridge lives (§5).

**Phase 4: gates**
- DJK oracle timing matrix (`diag_reflock` / `cmp_reflock`) on the Octakit image: all PASS,
  same as standalone.
- DJ-OFF identity against Octakit alone.
- Her `verify_octakit`, plus the Kit save / reload / copy / UNDO KIT sequences after jumps.
- A long random-jump soak: the unexplained KYOTI V1.0 DJ crash appeared only after a long
  session.

**Phase 5: hardware**
- Test image, a FLASHING.md §4 checklist, the user flashes it. Then the reporters.
- Status lines name what was confirmed.

## 5. Decisions for the user

1. **Ship stopgap A now?** (recommended: yes)
2. **Cued Kit not ready on the next step:** land one step later (timing still clock-locked,
   one step more latency), or fall back to a stock cue for that switch.
3. **Contact Em** with the Phase 2 trail, asking for review or an entry point (option D)?
4. **Where the bridge lives:** `octabam-modules/` here (a third module of ours that names her
   runtime), or upstream in octabam next to `kits-reload` / `scenes-kits`.

## 6. Risks

- Her checks are deliberately strict, so a bridge must reproduce her protocol exactly. Any
  version of her runtime may change it. The bridge must pin her `interface_version` and
  stop the build when it moves (as `modules/octakit/manifest.py` does for `P1TOKEN`).
- If the Kit is not resident at cue time, B needs her own acquire path from the ISR. Her
  begin already runs in the ISR, so that is plausible (L).
- MIDI tracks under DJK are still not confirmed on hardware (START_HERE §6). Keep them out of
  the bridge's hardware claims until they are.
