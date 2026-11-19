# Handoff: KYOTI V1.8BC + BLACKPYRAMIDS_303 one-per-core — hardware testing

Written 2026-11-18 for the next session. Continue in the worktree
`~/Documents/octatrack-kyoti-fw-kyoti-bp` (branch `kyoti-bp`, 8 commits ahead of origin/main
`cd788e9`, 7 behind; **nothing pushed, nothing promoted, nothing flashed yet**). Read CLAUDE.md
first, then this file, then NOTES.md's `2026-11-17 (kyoti-bp)` entries.

## 1. What exists

Two WIP test images, built in this worktree and gated in the emulator only.

| image | OS VERSION | file (CF card) | file (MIDI) | mainos |
|---|---|---|---|---|
| KYOTI V1.8BC | `KYOTI1.8BC` | `out/KYOTI_WIP/KYOTI_V1.8BC/OCTATRACK_KYOTI_V1.8BC.bin` `87e40e6d58fb368e5d910cea1b63a77d867d82556c1149e4e1827b5f0de9efe9` | `out/KYOTI_WIP/KYOTI_V1.8BC/OCTATRACK_OS1.40C_KYOTI_V1.8BC.syx` `48d10402f4cf578fd630804a08f64234801c7157f8199d3f0f23f233f37fea82` | `b3df205824c345ad62136bf54c087e1793c4352c3dfdc8810a5fa405bdbcb406` |
| BLACKPYRAMIDS_303 standalone (feature image, with the 3 bug fixes) | `140C_BP1PC` | `out/BLACKPYRAMIDS_303/OCTATRACK_BLACKPYRAMIDS_303.bin` `c97ff3a30764990c55118bdf0519d1605520919e14a73e334fcf68eec94c98d5` | `out/BLACKPYRAMIDS_303/OCTATRACK_OS1.40C_BLACKPYRAMIDS_303.syx` `0e10e65a90f447f010edc9b8942a328ad39641490da0e8dd81f54936466d5822` | `dfde2b5060452d428515e2ff5d580bee47b68d8e0ad7b3ef12ecc81a8637c79b` (unit `out/mainos_blackpyramids_303.bin` `62ac6e44…`) |

Rebuild commands (both WIP, refused without the opt-in):
`KYOTI_ALLOW_WIP=1 python3 tools/build_kyoti.py --clyps-bp` and
`KYOTI_ALLOW_WIP=1 KYOTI_VERSTR=140C_BP1PC python3 tools/build_blackpyramids_303.py`.

The image needed to MAKE the "two on a core" test project (pre-fix BLACKPYRAMIDS_303, the current
FINAL unit `5b7dfb2f…`), in the main checkout: `~/Documents/octatrack-kyoti-fw/out/OCTATRACK_BLACKPYRAMIDS_303.bin`
(`646fdb9c…`) or `~/Documents/octatrack-kyoti-fw/out/OCTATRACK_OS1.40C_BLACKPYRAMIDS_303.syx` (`9bd8a78f…`).
On it: T1 = BLKPYRAMD, TRACK COPY T1, TRACK PASTE onto T3, SAVE PROJECT. Keep that project for B6.

## 2. What the images contain (decided by the author)

- **KYOTI V1.8BC** = KYOTI V1.8C (MUTE_MODES, SIDECHAIN_COMPRESSOR, QUANTIZE_LIVE_REC_TOGGLE,
  ERASE_EMPTY_TRIGLESS_LOCKS, REC_TRIG_MUTE, VARISPEED, BATCH_BUGFIXES, CLYPS with DIRECT JUMP V7.3 built in)
  + BLACKPYRAMIDS_303. No RELOAD_FROM_PROJECT, no VARISPEED_EMUS, no separate DJ. Name chosen by the author:
  "KYOTI 1.8BC" (the OS VERSION field holds 10 chars, so `KYOTI1.8BC`; constant `BC_VERSTR`).
- SPRING REV and PLATE REV are both given up: SC (677 w) + the voice (936 / 932 w) + DARK's 35-word helper share
  SPRING+PLATE's 1,657 contiguous words per core (core 0: SC P:$1000..$12a5, voice $12a5..$164d, 9 spare; core 1:
  SC $0dc0..$1065, voice $1065..$1409, 13 spare). PLATE's ColdFire descriptor record stays stock.
- BP's ColdFire runtime is one unit of KYOTI's DRAM image (DJ 4,012 B, BP 41,716 B, Clyps 29,240 B last): 1,720
  arena pages (~10.3 MB of the sample pool; MEMORY page still reads 85.5 MB).
- ERASE_EMPTY_TRIGLESS_LOCKS skips BLKPYRAMD tracks (a 122-B wrapper `tools/patch_triglock_bp.s`, V1.8BC only).
- MUTE MODE DT-T fix (V1.8BC only flag in `tools/ot303/cf/control.c`): a muted BLKPYRAMD track starts no new
  note in OTFX-T / DT-T (the voice started notes before stock's voice bind, Modwerk #777 class).
- **One BLKPYRAMD per DSP core, on every path** (author: "two on one core must ALWAYS be refused, no crash
  possible"), in BOTH images:
  - TRACK PASTE refused whole (hooked at the paste wrapper 0x4002b988; VARISPEED owns 0x4002b654); the toast
    `ONE 303 PER CORE!`; the track keeps what it had.
  - Clyps FULL loads refused whole, Multi groups refused whole, temp reload and card/ORIG FULL loads gated
    (V1.8BC only; `tools/clyps/*` edits all inside `.ifdef BP_CLASH` / `BP_UITAIL`; Clyps FINAL 94e41a22 and
    V1.8C 9d1a29c9 byte-identical without the flags).
  - The safety net `bp_net` from the UI-loop tail 0x40062d1c (chained after Clyps' cl_uitail in V1.8BC): keeps
    the voice's current holder, else the lowest-numbered track; demotes the rest to FLEX with their pre-303
    values; clears stale signatures (no toast); loads flagged by the validator, repaired after two stable passes.
    Idle pass 54 instructions (was 525): fast path on bank / wake flag / 60-pass countdown / UI + engine Part /
    play + pending pattern / the active Part's machine bytes + 'O','T'. ~3,700 instructions a second.
  - Kept: the machine-chooser refusals and the DSP's first-claim-wins backstop.
  - Not refused (stock can't refuse it cleanly): stock UNDO of a paste; the net demotes it on its next pass.
  - octabam's and Modwerk's BP forms have NO protection beyond the chooser (read-only survey); not changed.

## 3. The hardware checklist (the author's, verbatim)

Write pass / fail / note per item; "not tried" is fine.

### A. KYOTI V1.8BC
Run V1.8C's usual checks first (Clyps, Direct Jump, Mute Modes, Side-chain Compressor, live-rec toggle, Rec Trig
Mute, Varispeed). Then:

1. **Boot.** OS VERSION reads `KYOTI1.8BC`. Power-cycle once now and once at the end.
2. **The voice on each core.** BlackPyramids on T2 (core 1) and T6 (core 0): play a line with notes, an ACC p-lock,
   a slide trig, and a trigless lock and a trigless trig after a note (both should tie). Turn every knob on both
   pages. Each sounds as on `140C_BP303`. Making a second BlackPyramids on T1–T4 is refused with
   `ONE 303 PER CORE!`.
3. **FX2 list.** No PLATE REV and no SPRING REV (13 entries, ending in DARK REV). DARK REV on T1 and T5 rings as on
   stock, also while a BlackPyramids and a keyed COMPRESSOR play. A project saved with PLATE or SPRING loads that
   FX2 as NONE.
4. **Side-chain Compressor.** A COMPRESSOR keyed from the same core and from the other core ducks, MON plays the
   key, and KBAS / KWID sweep. It also ducks when keyed *from* a BlackPyramids track, and when it sits *on* a
   BlackPyramids track keyed by a kick. No crackle with a voice on each core and keyed COMPRESSORs running. The
   risky case is a square voice (WAVE 127) on core 0 under heavy FX.
5. **Mute Modes on a BlackPyramids track**, each mode, muting while its line plays: OT: silent at once. OTFX: dry
   cut, the FX tail rings. OTFX-T: the note fades with the AMP release, and no new notes. DT-T: the sounding note
   finishes, then no new notes while muted (this image's fix). Unmuting brings the line back on its next note.
   Also SOLO another track in DT-T: the BlackPyramids track plays no notes.
6. **Trigless-lock erase.** On a BlackPyramids track, a tie with a CUT lock after a note: LIVE-erase the CUT lock
   ([NO] + CUT while live recording). The trigless lock stays lit and the tie holds. On a Flex or Static track, the
   emptied trigless lock disappears, as before.
7. **Clyps with a BlackPyramids track.** A FULL load ([FUNC] + trig) of a BlackPyramids slot onto a Flex track,
   and of a Flex slot onto the BlackPyramids track: the machine changes with the load and plays at the landing.
   A sequence-only load leaves the machine alone. ORIG restores.
8. **Direct Jump with a BlackPyramids track.** BlackPyramids on T2 in Part 1 only; jump between a Part 1 pattern
   and a Part 2 pattern and back. T2 changes machine at its first sounding trig after each jump; the voice stops
   and starts cleanly, in time.
9. **Project round trip.** SAVE PROJECT, power-cycle, LOAD PROJECT: the BlackPyramids tracks and their knobs come
   back. A jump, a Clyps load and a Mute Mode change still behave.
10. **One per core:** the B checks below, run on this image too. Then the Clyps refusals; each should show
    `ONE 303 PER CORE!` once, and nothing should change:
    - **Single FULL load.** BlackPyramids on T1 of the playing Part, and another pattern (on another Part) with
      BlackPyramids on T2 and T5. In Clyps on T2, [FUNC] + that pattern's trig is refused: T2 keeps its sequence
      and machine. Without [FUNC] (sequence only), it loads as normal.
    - **Group FULL load.** Make a [CUE] group of T2 + T5, then hold [CUE], hold [FUNC] and press that trig:
      refused whole, so T5 doesn't load either.
    - **T5 alone.** [FUNC] + that trig lands: T5 becomes BlackPyramids and plays.
    - **Temp reload.** With T5 a BlackPyramids, TRACK 5 + [YES]. Set T5 to Flex and make T6 a BlackPyramids. Then
      TRACK 5 + [NO] is refused: no `TEMP TRK RELOADED`, and T5 stays Flex.
    - **Not tested in the emulator.** ORIG TRK FULL, ORIG PTN+PART, and card reloads ([BANK] + [TRACK],
      [PTN] + [BANK] + trig) that would bring a second one back onto a core: all refused the same way.
    - **While playing.** A clashing FULL load cued during playback is refused at the press, not when it would land.

### B. BlackPyramids standalone (`140C_BP1PC`)
Run BlackPyramids' usual checks (voice, knobs, accents, slides, ties). Then the one-per-core checks; each refusal
should show `ONE 303 PER CORE!` exactly once:

1. **Paste onto the same core.** BlackPyramids on T1. TRACK COPY T1, select T3, TRACK PASTE: refused, and T3 keeps
   what it had. Pasting again on T3 is refused again.
2. **Paste onto the other core.** Select T5 and TRACK PASTE: allowed. T5 becomes a BlackPyramids with T1's knobs,
   and both play.
3. **Leftover marker.** With BlackPyramids on T2, copy a STATIC track's SRC page and paste it onto T2, so T2 is
   Static. Then make T1 a BlackPyramids (allowed). Copy a FLEX SRC page and paste it onto T2: T2 is a plain Flex
   track with the pasted values, not BlackPyramids. T1 still plays the voice, and there's no toast.
4. **Paste, then undo.** Make T3 a BlackPyramids, paste a Flex track onto T3, make T1 a BlackPyramids, then PASTE
   again on T3. If stock offers `UNDO TRACK` and it brings T3's BlackPyramids back, T3 turns straight back into
   Flex with the toast, and T1 keeps the voice. If stock pastes again instead, T3 just stays Flex.
5. **Part and pattern changes** between Parts with BlackPyramids on different tracks of the same core: nothing
   refused, no toast.
6. **A project with two on a core** (the one saved beforehand, §1). On LOAD PROJECT, the lower-numbered track keeps
   BlackPyramids, the other becomes Flex with its old Flex values, the toast shows once, and the Part is marked
   edited. Also try this on V1.8BC.
7. **Idle feel.** With a BlackPyramids on each core playing, encoders and page changes feel as responsive as on
   `140C_BP303`.

## 4. What the emulator covered and what it didn't

Covered (ALL GOOD on both images unless noted): paste T1->T3 refused / T1->T5 allowed; stale signature; load with
two; holder rule; Part switches (no false refusal); inactive Part caught at its cue and by the periodic pass;
Clyps single + group FULL refused, T5 alone lands, temp reload refused (V1.8BC); BP's own verify (only the core-1
DARK REV stopwatch line fails, identically on the old FINAL; PLATE line fails on V1.8BC by design); MUTE matrix;
SC levels 0.00 dB vs V1.8C FINAL (10 scenarios); DJ REF-LOCK c1 + RS1; Clyps UI ABCDY (50 checks); every other
FINAL rebuilds to its pin. Evidence: `out/bp1pc/`, `out/kbc/`.
NOT covered (only the unit can show these): stock UNDO bringing a second one back (A10/B4), a real card LOAD
PROJECT (B6), Clyps ORIG / card-reload FULL loads and a FULL load cued while running (A10), crackle / DSP overrun
(A4), anything audible.

## 5. When results come back

- **A fail:** reproduce in the emulator if possible; if the emulator and the unit disagree, build a diagnostic
  image (CLAUDE.md rule) rather than reasoning. Fix in this worktree, rebuild, re-gate, hand back a new image with
  its hash. Never promote with an open fail.
- **All pass, and the author says to promote** (only on the author's explicit word):
  1. Rebase/merge `kyoti-bp` onto current origin/main (7 behind now; mind NOTES union-merge and the
     never-cherry-pick rule); rebuild and confirm both images reproduce the flashed mainos hashes above.
  2. `tools/kyoti_status.py` FINAL: `build_kyoti.py` gets `mainos_kyoti_v1.8bc.bin`; `build_blackpyramids_303.py`
     (unit `62ac6e44…`) and `feature_image.py`'s `mainos_blackpyramids_303.bin` (`dfde2b50…`) replace their pins.
     The `--clyps-bp` mode then needs its WIP gate lifted the way `--clyps` / `--clyps-standalone` read their pins.
     Re-run every FINAL builder without the opt-in (never rebuild BP's octabam/Modwerk forms here).
  3. README: a KYOTI V1.8BC entry (what it is; SPRING + PLATE given up; one 303 per core; Hardware line naming
     what was confirmed), BLACKPYRAMIDS_303's entry gains the one-per-core sentence and its Hardware line; follow
     the README rule (catalogue only). BUILD_KYOTI.md, START_HERE §5/§6, FLASHING §4 results, NOTES entry.
  4. Push to main; copy the finals into the main checkout's out/ (replace the old BP final there) and verify against
     the pins.
  5. Tell the sessions that own the touched files: Clyps (`tools/clyps/*`, kyoti-m4-a3 was the manual/Clyps
     session) and the BlackPyramids session (`tools/ot303/*`, `tools/build_blackpyramids_303.py`).
  6. Ask the author whether to regenerate octabam's BlackPyramids module (`tools/ot303/octabam_module.py`) and send
     Sam a pin PR (the paste + safety-net parts only; octabam has no Clyps). Read the octabam PR checklist memory
     first, check the PR's state before pushing to its branch.

## 6. Rules for this thread

- BLACKPYRAMIDS_303 belongs to another session: only additive hooks, in THIS worktree; never edit or symlink into
  the ot303 / bp-* worktrees; never rebuild the shared libunicorn. BP's private DSP toolchain was copied into
  `out/ot303/` here.
- Clyps belongs to another session: Clyps edits only inside the `BP_CLASH` / `BP_UITAIL` ifdefs; CLYPS and V1.8C
  must stay byte-identical.
- Explicit-path commits with the right `Thread:` lines (ot303 / trkseq / kyoti-v1 / shared docs); never `git add -A`.
- Say plainly in every reply whether a new build exists, the exact file + sha256, and whether it is flashed.

## 7. Not part of this thread (open elsewhere)

- BlackPyramids' square wave on core 0 under the heaviest FX stack may overload: separate job (measure on the unit
  first, then a cheaper square path / SC idle skip; admission refusal as fallback; no quality degrade).
- VARISPEED_EMUS VEM11 (worktree `emus-guard`, image `140C_VEMG1` `d782ea56…`, not flashed): waiting on the
  author's A/B verdicts (https://claude.ai/artifact/87Xq1Xip4KUyN8iWUkf6kK) and six decisions.
- octabam #1160 (drop the "CHAIN AFTER: DIRECT" usage section) and Modwerk #1714 (Direct Jump Kyoti 0.2.0, draft):
  waiting on Sam / Jannik.
