# KYOTI modules × Octakit — scope (2026-10-02)

> **STATUS: SCOPED, both stopgaps PUSHED, nothing reproduced, no build.**
> - Users report that octabam images with OCTAKIT and DIRECT_JUMP_KYOTI crash the OT.
> - Checking the other KYOTI modules found a second, certain crash in
>   RELOAD_FROM_PROJECT, and a fix in BATCH_BUGFIXES that silently does nothing under
>   Octakit (§3).
> - Both crashing modules now declare OCTAKIT a conflict: DJK in `a7a5291`, RELOAD in
>   `c9a66cf`, both on `origin/main`.
> - **They reach users only when Sam merges octabam PR #551**, which moves the six KYOTI
>   submodules from `7f80b85` to `77f132f` (§6). Updated and noted to Sam 2026-10-02
>   (`~/Documents/octabam-note-to-sam-3.md`); its merge is not recorded here.
>
> **C** = read in source: her runtime `modules/octakit/upstream/runtime/*.S` @ `c6d3f39`,
> our `octabam-modules/*/*.s`, the stock image. **L** = inference, which Phase 1 has to
> confirm. File name kept, since both manifests point here.

## 0. Start here next time

1. Has Sam merged #551? Run `gh pr view 551 -R sambanks/octabam --json state`, or
   `git -C ~/Documents/octabam fetch && git -C ~/Documents/octabam ls-tree origin/main modules/direct-jump-kyoti/upstream`.
   A pin at `77f132f` or later means the stopgaps are live.
2. Phase 0 intake (§5): reporters' crash screens (ADDR!), module lists, projects. Resolve
   an ADDR with §10.1.
3. **The detail a fix needs is §10:** her switch protocol site by site, her calling
   conventions and checks, and design notes for both bridges.
4. RELOAD's bridge (§4, B-RL; §10.5) is the small, well-understood one: do it first. DJK's (B-DJ)
   needs Phases 1–2 first.
5. Work in worktree `djk-octakit` (`../octatrack-kyoti-fw-djk-octakit`). Test octabam
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
| **B-RL** | A RELOAD bridge. First candidate: under OCTAKIT, call stock's whole FUNC+CUE handler `0x4005e038` instead of `jsr 0x4004aab4` + the repaint tail, so her caller and selector checks pass by construction. Fallback: `kits-reload`'s return-site pattern. Details §10.5. Under Octakit the Part half *means* "reload the saved Kit", which is what her routine does. | Small, the pattern is proven on hardware (`OKMS2`) | Must coexist with `kits-reload`'s own handling of `0x4005e060` / `0x4005e062`, and with her `reload-shortcut-format` rejoin |
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

## 6. octabam: the submodule bump (PR #551, updated 2026-10-02)

- octabam pins all six KYOTI modules as separate submodules of this repo:
  `modules/<name>/upstream`, all at `7f80b85` as of octabam `8d0ad6f4`.
- Each octabam wrapper `modules/<name>/manifest.py` `runpy`s
  `upstream/octabam-modules/<name>/manifest.py` and adds octabam's
  category/author/proof fields.
- The user's open **PR sambanks/octabam #551** (branch `Zac-Kyoti/octabam:kyoti-pins-8773713`)
  already bumped the six pins to `8773713`, with the shim docstrings and READMEs updated.
- 2026-10-02: commit `5f5d67d4` on that branch moves all six to **`77f132f`**. It updates
  the shim pin text and adds Octakit notes to the DJK / RELOAD / BATCH shim READMEs. The
  PR's title and description are updated to match.
- The branch name still says `8773713`; renaming a PR's branch would close the PR.
- Sam has the note (`~/Documents/octabam-note-to-sam-3.md`).
- The bump also carries our Session 120 work: DJK and RELOAD as `Linked(dram=True)` (on HW
  from DRAM 2026-10-01, OBKYOTI6/7), MUTE_MODES `TableGrow insert_at=2`, DJK ↔ `DIRECT JUMP`
  conflict, RELOAD knob repaint.
- Checked before asking, against `a7a5291` in a scratch octabam worktree: registry loads
  all 67 modules, keys OK, `tools/remix/selftest.py` OK (every remix clean),
  `tools/verify/verify_docs.py` 0 problems.
- Then `c9a66cf` by direct manifest load: RELOAD + OCTAKIT refused, the six KYOTI modules
  clean, keys OK, no existing remix combining OCTAKIT with RELOAD or DJK.
- At `77f132f`, in a scratch clone of the PR branch:
  - `make verify-shared REMIXES=<the eight KYOTI test remixes>` passes;
  - `make check-remix` passes on each of the eight;
  - `verify_dram_boot` passes for `direct-jump-kyoti`, `reload-from-project` and
    `kyoti-mute-jump` (the port built with `make emu-cf`);
  - `verify_set` was skipped (no project configured);
  - `make docs` output is unchanged.
- No module code changed since `8773713` (manifests and READMEs only), so #551's earlier
  hardware runs and all-six build still apply.

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

## 10. Research detail for the fix

Everything below was read 2026-10-02:
- her runtime at `c6d3f39` (`~/Documents/octabam/modules/octakit/upstream/runtime/`);
- octabam `8d0ad6f4`;
- the stock image `out/raw/section_3_MAIN_OS.bin` (objdump, base `0x40000400`).

All of it is **C** unless marked. Re-check her side if her pin moves: her symbols, stack
offsets and checks are hers to change.

### 10.1 Resolving a crash screen

- **Her runtime links at fixed addresses for a given version**, the same in every octabam
  remix. octabam's runtime cache, `~/Documents/octabam/out/cache/runtime/<sha256>` (JSON,
  key `symbols`, 3,855 entries from `m68k-elf-nm --defined-only`), resolves an ADDR
  directly.
- **Proof:** `gk_stock_part_saved_to_working_reload_report_fatal` = `0x45d167e0`, exactly
  the ADDR on midisc's OKMS1 crash screen.
  ```sh
  f=$(ls -t ~/Documents/octabam/out/cache/runtime/* | head -1)
  python3 -c "import json,sys; s=json.load(open('$f'))['symbols']; a=int(sys.argv[1],16); \
  print(max(((v,k) for k,v in s.items() if v<=a)))" 45D167E0
  ```
- VEC:04 = `illegal` = one of her fatal labels. The ones that matter here, at `c6d3f39`:

| ADDR | label | who triggers it |
|---|---|---|
| `0x45d167e0` | `gk_stock_part_saved_to_working_reload_report_fatal` | RELOAD `[BANK]+[TRACK]` (caller not whitelisted) |
| `0x45d167da` / `0x45d167dc` / `0x45d167e8` / `0x45d167ec` | part-reload transaction / interlock / context-corrupt / transaction-corrupt | a reload that got past the caller check but found her state corrupt |
| `0x45d18376` | `gk_sequencer_latch_begin_fatal` | the switch block's latch begin failed (DJK suspect) |
| `0x45d183be` / `0x45d183c0` / `0x45d183c2` | latch final-store / queue-commit-deferred / commit fatal | the switch block's latch commit failed (DJK suspect) |
| `0x45d1843a` / `0x45d1843c` / `0x45d1843e` | scene A / scene B / audio-latch store fatal | a scene move while the latch is not ready (DJK suspect) |
| `0x45d1525a`..`0x45d15260` | MIDI refresh begin / commit / consume / generic | the MIDI twin of the switch (DJK suspect) |
| `0x45d1d674`..`0x45d1d682` | sequencer tick return / snapshot / publish / release | descriptor release in her tick wrappers |
| `0x45d16a00`..`0x45d16a0c` | pattern transition pre/post engine, retry | the cue/schedule path |
| `0x45d2df86`..`0x45d2dfce` | pattern queue commit prepare/guard/defer/exit, arranger | the queue path |
| `0x45d199ac` | `gk_current_tuple_refresh_fatal` | a non-whitelisted call to `0x40001f18` (BATCH_BUGFIXES' carryover cave, unreachable under her) |
| `0x45d13cbc`..`0x45d13cc0` | engine part load / saved part reload | `0x40009094` from a non-whitelisted caller while quiesced |

### 10.2 Her constants and state (abi.inc)

- Status codes: `GK_OK` 0, `GK_ERR_INVALID` −1, `_UPDATING` −2, `_BUSY` −3, `_OVERFLOW` −4,
  `_UNDERFLOW` −5, `_CORRUPT` −6, `_RANGE` −7, `_EXHAUSTED` −8, `_IO` −9.
- `GK_ID_NONE` `0xff`. `GK_DESCRIPTOR_COUNT` 128.
- `__gk_lifecycle_state`: `GK_LIFECYCLE_ACTIVE` 0, `GK_LIFECYCLE_QUIESCED` `0x4b495451`.
  While quiesced (boot / project load) most wrappers fall through to stock.
- Descriptor, 16 B (`__gk_descriptors + id*16`): PAYLOAD +0 (long), ROOTS +8 (word),
  READERS +10 (word), KIT +12, PHYSICAL +13, SPILL +14, FLAGS +15. FLAGS bits: VALID
  `0x01`, COPYING `0x02`, SPILLED `0x04`, WORKSPACE `0x08`, DIRTY `0x10`, CLONING `0x20`,
  PROMOTING `0x40`.
- Physical cache entry, 4 B (`__gk_physical_cache + slot*4`): OWNER +0, KIT +1, STATE +2,
  RESERVED +3.
- **Physical slot = bank*4 + part**, so the 64 stock Part positions are her slots, and
  `__gk_physical_payload_table[slot]` is that slot's payload.
- `__gk_pattern_assignments[bank*16 + pattern]` = the pattern's Kit (0..255).
- Sidecars, at `__gk_lease_sidecars + offset`: one word each, high byte = old descriptor,
  low byte = new descriptor, `0xff` = none. ENGINE_CURRENT +0, SEQUENCER_LATCH,
  MIDI_REFRESH, AUDIO_* (+98/+146/+194/+210).
- Shadows: `__gk_current_bank` / `__gk_current_pattern` / `__gk_current_kit`. The only
  writer of the first two is the workspace commit (`workspace.S`), not the switch.
- `__gk_sequencer_latch_queue_handoff`: set by latch begin during a pattern switch. While
  set, her MIDI-refresh and audio wrappers take the hand-off path.
- Stock addresses she names that we also use: `GK_STOCK_SCHEDULER_STATE` `0x800065b8` (=
  DJK `TRANSPORT_L`, 1 = running); `GK_STOCK_SEQUENCER_PREVIOUS_PATTERN` `0x800065c1`
  (the word PREV_PAT<<8 | PREV_BANK); `GK_STOCK_SEQUENCER_CURRENT_BANK/PATTERN`
  `0x800065bd/be` (= DJK ACT_BANK/ACT_PAT); `GK_STOCK_SEQUENCER_LATCH_BANK/PART`
  `0x46c7ff40/62` (= DJK ENG_ABANK/ENG_APART); `GK_STOCK_PATTERN_ASSIGNMENT_TABLE`
  `0x400eb036` (+1 = blob `+0x8e57`); `GK_STOCK_WORKING_PART_MIRROR_BASE` `0x100a4ece`;
  `GK_STOCK_PATTERN_MIRROR_BASE` `0x1001614e`.
- Kit data, from Em via octabam's `modules/octakit/README.md`:
  - Kits keep the Part layout.
  - Saved Kit data: `__gk_canonical_payloads + kit*0x18b2`.
  - The working Kit is separate. A write goes `gk_workspace_prepare` →
    `gk_physical_acquire` → `gk_descriptor_store_byte` per byte →
    `gk_workspace_mark_dirty_pending` → `gk_workspace_commit_update` →
    `gk_descriptor_release`, all `.global`.

### 10.3 The stock switch block and her four wrappers

The block runs in the tick ISR. Stock reaches it on a real switch (`d6` = PEND ≠ ACT), after
PREV←ACT and ACT←PEND.

| site | stock instruction(s) displaced | her entry | continues at | what runs |
|---|---|---|---|---|
| `0x400a45a8` (8 B) | `moveq #1,%d4; move.l %d4,0x46c7fa80` (AFLAGS = 1), just after the `{0x14, part}` post (`0x400a459a..a6`) | `gk_stock_sequencer_latch_begin` | `0x400a45b0` | saves d0-d3/d5-d7/a0-a6 (**not d4**); `bsr gk_sequencer_latch_begin`; nonzero → `illegal` unless quiesced; then the displaced pair. |
| `0x400a468c` (6 B) | `move.b %d0,0x46c7ff62` (APART; d0 = `0x400eb036[off+1]`) | `gk_stock_sequencer_latch_commit` | `0x400a4692` | saves all; `bsr gk_sequencer_latch_commit_part` (d0 = part), which **itself** stores APART and publishes the sidecar under SR `0x2700`; nonzero → `gk_sequencer_latch_queue_commit_deferred`. Quiesced → the plain store. |
| `0x400a475e` (8 B) | `moveq #1,%d2; move.l %d2,0x46c76a22` (MIDI flag) | `gk_stock_midi_refresh_begin` | stock continue | if `__gk_sequencer_latch_queue_handoff` is set: passthrough; else `gk_midi_refresh_begin` (validates, `gk_selector_begin_physical`); failure → `illegal` unless quiesced. |
| `0x400a47f0` (6 B) | `move.b (%a0),0x46c7a934` (MIDI part) | `gk_stock_midi_refresh_commit` | stock continue | hand-off or quiesced → the plain store; else `gk_selector_commit_physical_part`, failure → `illegal`. |

**What `gk_sequencer_latch_begin` checks:**
1. It acquires the engine-current descriptor (`gk_sequencer_engine_acquire`).
2. Shadow checks, failing with CORRUPT (corrupt → release, return −6):
   - `__gk_workspace_descriptor` equals it;
   - `__gk_current_bank/pattern` ≤ 15, ENGINE_PART (`0x80001829`) ≤ 3;
   - ENGINE_BANK (`0x80001828`) == shadow bank;
   - the descriptor is VALID, WORKSPACE, not SPILLED or bit 7;
   - payload == its physical slot's payload, ROOTS and READERS > 0;
   - physical == bank*4 + ENGINE_PART;
   - the physical cache owner/kit match, state 0, reserved none;
   - `__gk_current_kit` and the pattern's assignment == the descriptor's kit;
   - the shadow pattern's blob `+0x8e57` == ENGINE_PART.
3. **If ACT (`0x800065bd/be`) ≠ the shadow**, the pattern-switch case: it runs
   `gk_sequencer_latch_queue_handoff_validate` (`audio_secondary.S`). That requires:
   - ACT bank/pattern ≤ 15;
   - `0x800065b8 == 1`;
   - when not a repeat, **the word at `0x800065c1` (PREV) == the shadow**.

   It then publishes the hand-off marker and returns OK.
4. Otherwise it opens the SEQUENCER_LATCH sidecar (`gk_selector_begin_update`).

**Audio side.** At `0x4000af24` stock tests AFLAGS. Her gate, when flags ≠ 0, calls
`gk_audio_latch_ready`:
- If `__gk_sequencer_latch_queue_handoff` is set, it defers to
  `gk_pattern_queue_audio_handoff_ready`.
- Otherwise it requires the latch sidecar low byte to be none, ENGINE_CURRENT == latch
  sidecar, latch bank/part == ENGINE_BANK/PART, and the descriptor valid at physical
  bank*4 + part.
- Not ready → jump to `GK_STOCK_AUDIO_LATCH_SKIP` `0x4000b266`, so the apply is
  **postponed** to a later frame.
- The apply itself is `jsr 0x40009e00` at `0x4000b1d8`, which her
  `audio-pattern-part-load-commit` replaces at `0x4000b1d6`.
- Scene A/B stores inside the apply path call `gk_audio_latch_store_byte`: not ready →
  `illegal`.

**At cue time** (`gk_stock_pattern_schedule_prepare`, `pattern.S`), for callers whose return
is one of `0x400a0eae` / `0x400a1022` / `0x400a1044` / `0x4004a658`, she:
1. prepares the workspace for the cued pattern's Kit (`gk_workspace_prepare` → physical
   slot);
2. writes the slot's part into the pattern's `+0x8e57` (blob and mirror);
3. calls the light apply `0x40009e00` herself, then `gk_workspace_commit_update`.

So **the incoming Kit is likely resident before the switch (L)**. Phase 2 must confirm it
for cues made during playback (`0x400a10c8` queue-commit path).

### 10.4 DJK against that protocol (B-DJ design notes)

- `dl_commit` (`patch_directjump_v7.s`) does PREV←ACT, ACT←PEND, then the `{0x15}` post,
  `dj_handoff`, and the `{0x11}` post.
- `dj_handoff` replays, in stock order:
  - `{0x14, part}` post;
  - ENG_AFLAGS `0x46c7fa80`, ENG_ATIME `0x800019e4`, ENG_ABANK `0x46c7ff40`, ENG_APART
    `0x46c7ff62`;
  - ENG_MFLAGS `0x46c7a120`, ENG_MTIME1 `0x46c76aa6`, ENG_MFLAG `0x46c76a22`, ENG_MTIME2
    `0x46c76aaa`, ENG_MBANK `0x46c7a850`, ENG_MPART `0x46c7a934`;
  - `COND_RESET(-1)`.
- **Its PREV/ACT state at that point is what her hand-off validation expects** (PREV ==
  her shadow, transport running). So the minimal bridge is her two calls in stock's
  positions:
  1. after the `{0x14}` post, **`jsr gk_sequencer_latch_begin`** (callee-saved
     d2-d7/a2-a5, result in d0);
  2. **if d0 ≠ 0, cancel the landing** and let stock cue it (no trap: we call her inner
     routine, not her `illegal`-ing wrapper);
  3. write AFLAGS / ATIME / ABANK as now;
  4. **`jsr gk_sequencer_latch_commit_part` with d0 = part** in place of the ENG_APART
     store (it stores APART itself). It clobbers a0; on failure, mirror her wrapper (the
     deferred path) or cancel;
  5. the MIDI half can stay as is, since her MIDI wrappers pass through while
     `__gk_sequencer_latch_queue_handoff` is set. Confirm under the port.
- Unknowns for Phase 2:
  - who clears the hand-off marker afterwards (`gk_pattern_queue_audio_handoff_ready`,
    `arranger.S`);
  - whether DJK's landing time (now, not now + one master step) upsets her audio
    hand-off;
  - V7.0.1's re-cue take-back (`da_recue`) against a Kit she prepared at cue time;
  - whether `+0x8e57` already holds her physical part when DJK reads it (it should, per
    10.3).
- **Symbols:** her addresses are fixed per version (10.1), but octabam's schema has no way
  yet for a `Linked` unit to import a `Runtime` symbol: `runtime_build.py` passes
  `symbols` only to the loader. Options: add that to the schema (ask Sam), or have the
  bridge's manifest read the cache / her ELF and emit `--defsym`. `defsym`s are
  **link-time** in octabam (S120), so `.ifdef` gates won't see them.

### 10.5 RELOAD against her Part reload (B-RL design notes)

**Our side**, `patch_reload3.s`:
- `r3b_try_bank` pushes CUR_PART (`0x80000003`) and does `jsr PART_RELOAD` (`0x4004aab4`).
- A verdict d0 = 0 means never saved, which gives "SAVE PART FIRST!".
- On success it runs `rl3_part_refresh` (`link.w %fp,#-8; jmp 0x4005e0a8`, the knob
  repaint tail of stock's FUNC+CUE handler).
- Then `rl3_arm_n` posts the sequence job.

**Her side**, `gk_stock_part_saved_to_working_reload` (`part_save_clear_reload.S`):
1. lifecycle must be active, else fatal;
2. **(sp) must be `0x4002dd5c` or `0x4005e060`**, else fatal;
3. the part arg ≤ 3;
4. **the selector check reads the return again**: FUNC+CUE return → part must == `0x80000003`;
   menu return → part must == `GK_STOCK_SELECTED_PART` `0x460d10c8`;
5. `gk_stock_current_context_validate_or_resume`, workspace bound, current Kit initialised;
6. `gk_stock_load_kit_transaction`.

It returns **d0 = 1** on success and 0 on a soft failure; CORRUPT is fatal. **RELOAD's
argument already satisfies the FUNC+CUE selector.**

**The stock FUNC+CUE handler** `0x4005e038` takes no arguments; it is a keymap handler,
pointed to from `0x400bf574` / `0x400bf8ce`:

| address | what it does |
|---|---|
| `0x4005e03c..54` | `link fp,#-32`; part = `0x80000003`; test the bank's saved bitmask (`*0x46c82456 + 0x95048`, bit part), else → `0x4005e0e2` ("SAVE PART FIRST!") |
| `0x4005e058..60` | push part, `jsr 0x4004aab4`, `addq #4,sp` |
| `0x4005e062..9a` | format "PART %d RELOADED" (`0x400b41aa`) or `0x400b41bb` via `0x40013a08` |
| `0x4005e09c..a4` | toast, 0x18 |
| `0x4005e0a8..` | the repaint tail RELOAD borrows |

Under Octakit, `0x4005e062` belongs to her (`reload-shortcut-format` → her formatter). When
MIDI SCENES is present, `kits-reload` overrides `0x4005e05a` and `0x4005e062` (§4 there).

**Bridge candidates:**
- **(a) Call the whole handler.** Under OCTAKIT, replace `jsr PART_RELOAD` +
  `rl3_part_refresh` with `jsr 0x4005e038`.
  - For: her checks pass by construction, and it composes with `kits-reload` and her
    formatter.
  - Against: her toast appears before RELOAD's own; RELOAD loses the saved/unsaved verdict
    (read the saved bit first ourselves, or read her result); the handler's d0 return is 1
    (kits-reload README).
- **(b) kits-reload's pattern.** Push `0x4005e060` as our return and get control back by
  detouring a return site. That collides with `kits-reload`'s own `0x4005e062` override:
  harder.

**(a) is the first thing to try.** The `[PTN]+[TRACK]` chord's open questions (10.3
mirrors, the case-0x14 job worker) are Phase 1 items.

### 10.6 Where else to look

- **Her sources:**
  - `sequencer_audio.S`: latch begin/commit, audio gate, scene stores;
  - `audio_secondary.S`: hand-off validation;
  - `audio_upstream.S`: queue commit deferral;
  - `midi_refresh.S`, `pattern.S` (schedule), `part_save_clear_reload.S`, `events.S`
    (`part-event-publish`), `track_refresh.S` (`0x40001f18`), `engine_load.S`
    (`0x40009094`).
- **Her recipe:** `runtime/firmware.json` `patches[]`, `addr = 0x40000400 + offset`;
  `writes[].data` is the replacement, usually `4ef9`/`4eb9` + her address.
- **octabam:**
  - `modules/kits-reload/{manifest.py,reload.s}`, the working bridge;
  - `modules/octakit/README.md` ("Calling the page-1 writer beside her": her
    `GK_TRACK_PARAMETER_TOKEN_ARMED` token pattern; Kit data);
  - `tools/remix/runtime_build.py`, symbols;
  - `tools/remix/schema.py`: `Runtime.pinned_returns`, `Detour.subst_return`, `Override`.
