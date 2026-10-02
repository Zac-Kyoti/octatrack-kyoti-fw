# KYOTI modules × Octakit — scope (2026-10-02)

> **STATUS: SCOPED, both stopgaps PUSHED, nothing reproduced, no build.**
> - Users report that octabam images with OCTAKIT and DIRECT_JUMP_KYOTI crash the OT.
> - Checking the other KYOTI modules found a second, certain crash in
>   RELOAD_FROM_PROJECT, and a fix in BATCH_BUGFIXES that silently does nothing under
>   Octakit (§3).
> - Both crashing modules now declare OCTAKIT a conflict: DJK in `a7a5291`, RELOAD in
>   `c9a66cf`, both on `origin/main`.
> - **They reach users only when Sam moves octabam's six KYOTI submodules off `7f80b85`**
>   (§6). The note asking him to was drafted 2026-10-02; whether he has done it is not
>   recorded here.
>
> **C** = read in source: her runtime `modules/octakit/upstream/runtime/*.S` @ `c6d3f39`,
> our `octabam-modules/*/*.s`, the stock image. **L** = inference, which Phase 1 has to
> confirm. File name kept, since both manifests point here.

## 0. Start here next time

1. Has Sam bumped? Run `git -C ~/Documents/octabam fetch && git -C ~/Documents/octabam ls-tree origin/main modules/direct-jump-kyoti/upstream`. A pin at `c9a66cf` or later means the stopgaps are live.
2. Phase 0 intake (§5): reporters' crash screens (ADDR!), module lists, projects.
3. RELOAD's bridge (§4, B-RL) is the small, well-understood one: do it first. DJK's (B-DJ)
   needs Phases 1–2 first.
4. Work in worktree `djk-octakit` (`../octatrack-kyoti-fw-djk-octakit`). Test octabam
   changes in a **scratch octabam worktree**, never by rebuilding the shared libunicorn (§7).

## 1. Why octabam lets users build these pairs

- In the REMIXER, both modules can be selected at once. **Before the stopgaps the octabam
  ledger called every pair CLEAN (C, octabam `8d0ad6f4`).** No byte is shared:
  - DJK's hooks are `0x400a1f72`, `0x400a221c`, `0x40043418` and the `[PTN]`-layer YES
    record at `0x400bf0be`. Its call targets are KPOST, PC send `0x4009e884`, COND_RESET
    `0x400a539c` and NOTIFY. None of these is among Octakit's 681 recipe sites.
  - `[PTN]+[YES]` does not collide with any Octakit gesture.
- **The ledger's pinned-return rule only checks substituting `Detour`s.** It cannot see a
  `Linked` unit that calls a pinned routine directly (§3, RELOAD), nor a module that
  writes state Octakit shadows (§2, DJK).
- Both classes are invisible to it. MIDI SCENES' Part Reload trap was the first instance
  (octabam `modules/kits-reload/README.md`, "The collision is not a byte").
- **Suggested to Sam:** make the ledger also scan each `Linked` unit's `jsr`/`jmp` targets
  against routines a `Runtime` replaces behind a caller check. That would have caught
  RELOAD, and BATCH_BUGFIXES' unreachable call.

## 2. DIRECT_JUMP_KYOTI — the mechanism

**Octakit turns a pattern switch into a checked transaction (C).** Parts become Kits held
in a pool of 64 "physical" slots, with a reference-counted descriptor and lease
("sidecar") system. A stock pattern switch runs through her wrappers at every step:

| step | stock site | her wrapper | what she checks / does |
|---|---|---|---|
| cue / publish / queue | `0x400a0570` schedule (callers `0x400a0eaa`, `0x400a101e`, `0x400a1040`, `0x4004a652`), queue commit `0x400a10c8`/`0x400a1498`, queued hand-off `0x400a06d6` | `gk_stock_pattern_schedule_prepare`, queue-commit entry/exit | Identifies the caller from its **return address**. `gk_workspace_prepare` acquires a physical slot for the pattern's Kit and **rewrites the pattern's Part byte (`+0x8e57`) to that slot**, in the blob and in the pattern mirror `0x1001614e`. Then it calls the light apply `0x40009e00` itself. |
| the switch, in the tick ISR | `0x400a4568..0x400a4856` (latch writes `0x46c7ff40` / `0x46c7ff62`, MIDI twin) | `sequencer-latch-begin/commit` `0x400a45a8`/`0x400a468c`; `midi-refresh-begin/commit` `0x400a475e`/`0x400a47f0` | Begin validates her shadow copies against stock state: `__gk_current_bank/pattern`, the descriptor, the physical cache, the pattern assignment, the `+0x8e57` byte, and ENGINE_BANK/PART. Then it opens a lease. Commit publishes ENGINE_APART **together with** the lease sidecar. |
| audio engine applies | `0x4000af24`, `0x4000b1d6` (light apply `0x40009e00`) | `gk_stock_audio_latch_gate`, `audio-pattern-part-load-commit` | `gk_audio_latch_ready`: if the latch and the sidecar disagree, she **skips** the apply. |
| scene A/B stores | `0x4000afc4`, `0x4000b0d2` | `gk_audio_latch_store_byte` | If the latch is not ready, she executes **`illegal`**. |
| UI messages | `0x4006214e` (case `0x10`), `0x400621a6..0x40062d1c` (case `0x13`, all of it, §3) | pattern-event-retry, part-event-publish | — |

Every inconsistency she detects ends at one of her `*_report_fatal` / `*_fatal` labels, an
`illegal` instruction, which shows on the unit as **`EXCEPTION … VEC:04`**.

Her tick patches (`0x400a1778..0x400a1e02`) sit in the function **before** the tick ISR
(`0x400a1e0c`). DJK's phase-D hook `0x400a1f72` and the stock re-landing body are not
patched by her (C).

**DJK bypasses all of it (C).**
- V7.0.1's `dj_handoff` is, by design, a value-for-value **replay of the stock writes in
  `0x400a4568..0x400a4856`** (DIRECTJUMP_V7_DESIGN.md §8): ENGINE_AFLAGS, ENGINE_ABANK,
  ENGINE_APART (read raw from `+0x8e57`), the MIDI twin, and COND_RESET. It does this
  without her begin/commit wrappers.
- `dl_commit` does ACT←PEND (`0x800065bd/be`) itself.

**Expected result (L):**
- After a jump, ENGINE_APART has no matching sidecar and her shadows still name the old
  pattern.
- The audio gate then either skips the Kit apply (wrong sound, no crash) or a later
  validation traps.
- Likely triggers: the first scene move, the next natural pattern change (latch begin finds
  `__gk_current_*` ≠ ACT), the next Kit load, the tick's descriptor release.
- **So the crash may come after the jump rather than on it.**

## 3. The other five KYOTI modules

Swept 2026-10-02: every `0x400xxxxx` address in each module's `.s` and `manifest.py`,
against Octakit's recipe sites. Then each hit was read.

| module | under Octakit | basis |
|---|---|---|
| **RELOAD_FROM_PROJECT** `[BANK]+[TRACK n]` | **Traps on first use, every time.** The Part half (`r3b_try_bank`) does `jsr 0x4004aab4` (stock Part RELOAD) from our unit. Her replacement `gk_stock_part_saved_to_working_reload` (`part_save_clear_reload.S`) accepts only returns `0x4002dd5c` (menu) / `0x4005e060` (FUNC+CUE). Anything else → `illegal`. Same class as midisc's crash. **Refused since `c9a66cf`.** | C |
| RELOAD `[PTN]+[TRACK n]` | Probably safe, unproven. It calls nothing she replaced, but: (a) LIVE_REFRESH `0x4000faf0` copies the cold blob to the pattern mirror `0x1001614e` and the bank's Part region to `0x100a4ece`, which she names as `GK_STOCK_WORKING_PART_MIRROR_BASE` and reads in `arranger.S` / `machine_selection.S`; (b) `rl_done` suppresses stock's whole-bank reload inside the case-0x14 job worker, where she redirects three calls (`bank-store-0` `0x40085806`, `project-reload-0` `0x4008584c`, `bank-reload-0` `0x4008589e`), between which our `rl_job` detour `0x40085864` sits. | L |
| RELOAD `PARTAPPLY` `0x40009094` | Dead code: only kind 3 (TRK SEQ) is ever armed (`rl3_arm_n`). Her `0x40009094` checks callers only while her lifecycle is quiesced. | C |
| **BATCH_BUGFIXES** PART_CHANGE_CARRYOVER_FIX | **Silently inert, no crash.** Its hooks `0x400621da` / `0x40062216` sit inside the stock "select Part" handler (case 0x13), which her `part-event-publish` takes over whole: jump at `0x400621a6`, rejoin at `GK_STOCK_PART_EVENT_DONE 0x40062d1c`. They never run, so the cave's `jsr 0x40001f18` (her `gk_stock_current_tuple_refresh`, six-caller whitelist → `illegal`) and `jsr 0x40009094` are never reached. Whether her Kit transition already does what the fix does (recorder cache, PICKUP re-seed/release) is unmeasured. | C (inert), L (bug status) |
| BATCH_BUGFIXES, the other two fixes | No Octakit site referenced. | C (static only) |
| MUTE_MODES, QUANTIZE_LIVE_REC_TOGGLE, ERASE_EMPTY_TRIGLESS_LOCKS | No Octakit site referenced. | C (static only) |

## 4. Options

| | what | for | against |
|---|---|---|---|
| **A** ✅ done | `conflicts=(("OCTAKIT", …),)` in DJK (`a7a5291`) and RELOAD (`c9a66cf`) | Stops new crash reports once Sam bumps | Takes both features away from Octakit users until a bridge exists |
| **B-RL** | A RELOAD bridge, `kits-reload`'s pattern: under Octakit, call `0x4004aab4` with a whitelisted return (`0x4005e060`, the FUNC+CUE site) and continue our post-work from a detour on that return site. Under Octakit the Part half *means* "reload the saved Kit", which is what her routine does. | Small, the pattern is proven on hardware (`OKMS2`) | Must coexist with `kits-reload`'s own handling of `0x4005e060` / `0x4005e062`, and with her `reload-shortcut-format` rejoin |
| **B-DJ** | A DJK bridge, selected only when both are present. It makes the landing run her transaction around the replayed writes, gates arming on her prepared Kit, and releases her lease when the cue is cancelled | Leaves V7's hardware-confirmed timing code untouched | Depends on her private globals (`gk_sequencer_latch_begin`, `gk_sequencer_latch_commit_part`, `gk_midi_refresh_begin`, …) and so is pinned to her version. Unknown whether an octabam `Linked` unit can link against a `Runtime`'s symbols (`runtime_build.py` has the table internally) |
| **C** | Restructure DJK so that its landing runs **stock's own switch block** instead of replaying it | Composes with every mod | Undoes V7's founding rule ("nothing enters the wrap-change body"). Means a full re-gate and new hardware runs. Shelved |
| **D** | Ask Em for supported entry points ("switch to bank/pattern now", "reload the current Kit") | Cleanest long term; her code, her invariants | Depends on her time; her README invites combining her repo as a submodule |

**Recommendation:** B-RL first. Then Phases 1–2 and B-DJ. Raise D with Em in parallel,
carrying the Phase 2 trail.

## 5. Work plan

**Phase 0: intake**
- [x] Stopgaps A, pushed. Sam's bump requested (§6).
- [ ] User: collect the crash reports. For each: the EXCEPTION screen (VEC, ADDR, D0, SP,
  CFW), the remix, its module list and octabam commit (or the image sha), what was done just
  before (DJ jump to a pattern on the same Kit or another Kit; DJ on but idle; scene move
  after a jump; a `[BANK]+[TRACK]` chord), and if possible the project.
- [ ] Map each reported ADDR to her symbol: build the reporter's remix, read her link map,
  find the matching `*_fatal` label. That names the check that failed before any emulation.
  `gk_stock_part_saved_to_working_reload_report_fatal` means RELOAD.

**Phase 1: reproduce under the port**
- Build a test remix with OCTAKIT + DJK (and one with OCTAKIT + RELOAD) next to
  `remixes/test/direct-jump-kyoti`, in a scratch octabam worktree.
- The stopgap conflicts must be lifted locally for this, e.g. a scratch copy of the
  manifest without them.
- Fixture: a real exported project, either the reporter's or one of the user's that
  Octakit migrates into Kits when it loads. Never a hand-made one.
- Drive it with `ot_emu`: `--sequencer`, the `key` verbs (local patch
  `octabam-ot-emu-steps-key.patch`), `--watch-pc` on every `illegal` in her runtime.
  RELOAD's trap can be shown like `kits-reload`'s: `--call` into the chord handler.
- DJK matrix:
  1. DJ ON idle
  2. jump with the same Kit
  3. jump with another Kit
  4. jump, then a natural change
  5. jump, then a scene move
  6. jump, then a Kit load / UNDO KIT
  7. re-cue during the arm window (V7.0.1's take-back path)
- RELOAD: both chords; then `[PTN]+[TRACK]` followed by a Kit save / reload / UNDO KIT and
  a power cycle, checking her Kit store and the `0x100a4ece` mirror.
- BATCH_BUGFIXES: confirm the carryover hooks never fire under Octakit, and whether the
  carryover bugs (recorder cache, PICKUP) exist on her Kit change.
- Exit: every trap reproduced and named. If one does not reproduce, build a diagnostic
  image (CLAUDE.md: when hardware and the emulator disagree, build a diagnostic, don't
  reason).

**Phase 2: measure the stock switch under Octakit** (V7.0.1's method)
- With DJ OFF, record her complete trail through one natural switch: same Kit, then another
  Kit. Record the order of calls and every change to her state (sidecars, descriptors
  ROOTS/READERS, physical cache, `__gk_current_*`, `__gk_pattern_queue_commit_prepared`,
  `+0x8e57`).
- Find **when the cued Kit becomes resident**: at cue time on the UI side (L), or at the
  wrap. This decides whether DJ's next-step landing always finds it ready.
- This trail is the spec for B-DJ.

**Phase 3: bridges**
- B-RL as in §4.
- B-DJ, in `dl_commit` / `dj_handoff`:
  - run her latch begin, then the stock writes (or let her commit publish them), then her
    latch commit;
  - MIDI refresh begin/commit around the MIDI twin;
  - keep her shadow in step with ACT←PEND;
  - arm only when her prepared Kit for PEND is ready;
  - on cancel and re-cue, release her lease through her schedule-abort path (`0x400a0728`).
- Schema: confirm with Sam how a `Linked` unit references `Runtime` symbols, or add that.
- When a bridge lands, the bridge module replaces the conflict, the way `kits-reload` did
  for midisc.

**Phase 4: gates**
- DJK oracle timing matrix (`diag_reflock` / `cmp_reflock`) on the Octakit image: all PASS,
  same as standalone.
- DJ-OFF identity against Octakit alone.
- Her `verify_octakit`, plus the Kit save / reload / copy / UNDO KIT sequences after jumps
  and reloads.
- A long random-jump soak: the unexplained KYOTI V1.0 DJ crash appeared only after a long
  session.

**Phase 5: hardware**
- Test image, a FLASHING.md §4 checklist, the user flashes it. Then the reporters.
- Status lines name what was confirmed.

## 6. octabam: the submodule bump (asked of Sam 2026-10-02)

- octabam pins all six KYOTI modules as separate submodules of this repo:
  `modules/<name>/upstream`, all at `7f80b85` as of octabam `8d0ad6f4`.
- Each octabam wrapper `modules/<name>/manifest.py` `runpy`s
  `upstream/octabam-modules/<name>/manifest.py` and adds octabam's
  category/author/proof fields.
- Asked: move all six to **`c9a66cf`**, `make check`, commit, and touch up the
  `direct-jump-kyoti` / `reload-from-project` wrapper docstrings. Those still say
  "pinned to `7f80b85`" and "one floating ROM cave".
- The bump also carries our Session 120 work: DJK and RELOAD as `Linked(dram=True)` (on HW
  from DRAM 2026-10-01, OBKYOTI6/7), MUTE_MODES `TableGrow insert_at=2`, DJK ↔ `DIRECT JUMP`
  conflict, RELOAD knob repaint.
- Checked before asking, against `a7a5291` in a scratch octabam worktree: registry loads
  all 67 modules, keys OK, `tools/remix/selftest.py` OK (every remix clean),
  `tools/verify/verify_docs.py` 0 problems.
- Then `c9a66cf` by direct manifest load: RELOAD + OCTAKIT refused, the six KYOTI modules
  clean, keys OK, no existing remix combining OCTAKIT with RELOAD or DJK.
- No image built: `make check` is Sam's.

## 7. How these checks were run (reuse)

```sh
# a module from THIS repo against octabam's ledger, without touching octabam's submodules
cd ~/Documents/octabam && PYTHONPATH=tools uv run --frozen python -c "
import pathlib; from remix import registry, ledger
m = registry._load_one(pathlib.Path('<worktree>/octabam-modules/<name>/manifest.py'))
print(ledger.check([m, registry.by_key('OCTAKIT')]) or 'CLEAN')"
```

- Full selftest on a bumped tree: `git worktree add --detach <scratch>/ob-bump origin/main`
  in `~/Documents/octabam`.
- Clone the six `modules/*/upstream` at the target commit, and `cp -R` the other
  submodules from the main clone.
- Symlink `.venv`, `vendor`, `downloads`, `out/raw` **read-only**. Never `make setup`
  there: that rebuilds the shared libunicorn.
- Then `PYTHONPATH=tools .venv/bin/python tools/remix/selftest.py` and
  `tools/verify/verify_docs.py`. Remove the worktree afterwards.
- Octakit's patch sites: `modules/octakit/upstream/runtime/firmware.json`, `patches[]`
  (`addr = 0x40000400 + offset`). Pinned returns: `abi.inc` `GK_STOCK_*_RETURN`.

## 8. Decisions for the user (open)

1. **Cued Kit not ready on the next step (B-DJ):** land one step later (timing still
   clock-locked, one step more latency), or fall back to a stock cue for that switch.
2. **Contact Em** with the Phase 2 trail, asking for review or entry points (option D)?
3. **Where the bridges live:** `octabam-modules/` here (modules of ours that name her
   runtime), or upstream in octabam next to `kits-reload` / `scenes-kits`.

## 9. Risks

- Her checks are deliberately strict, so a bridge must reproduce her protocol exactly. Any
  version of her runtime may change it. A bridge must pin her `interface_version` and stop
  the build when it moves (as `modules/octakit/manifest.py` does for `P1TOKEN`).
- If the Kit is not resident at cue time, B-DJ needs her own acquire path from the ISR. Her
  begin already runs in the ISR, so that is plausible (L).
- DJK's MIDI tracks are still not confirmed on hardware (START_HERE §6). Keep them out of
  the bridge's hardware claims until they are.
- PART_CHANGE_CARRYOVER_FIX being inert under Octakit may hide those bugs on Kit changes.
  Tell Em if Phase 1 shows they exist there.
