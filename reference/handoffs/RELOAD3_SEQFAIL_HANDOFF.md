# RELOAD3 — HANDOFF: sequence reloads fail intermittently, and the toast lies

> **RESOLVED 2026-09-25 (Session 98). RELOAD3 is final.** Root cause: the chord's request bytes at
> `0x80006a50-55` (a RAM block the unit overwrites) were corrupted before the worker read them, so it
> reloaded a different, MIDI, track and its verify passed on that slice. Found with the `--diag` toast
> (§9-§10); fixed by moving the request into the patch's own cave (§11); the user reported every issue
> resolved. §3's hypotheses A/B/C were all wrong about *what* failed — the sequence copy itself was
> fine. Everything below is kept as the record of how it was found.

Written 2026-09-25 (Session 93) for a fresh session. Scope is **only** these two things:

1. `[PTN]`+`[TRACK n]` (and `[BANK]`+`[TRACK n]`) **often fails to reload the sequence**.
2. When it fails, the **success toast still appears** — so the message cannot be trusted.

Everything else in RELOAD3 is hardware-confirmed and out of scope.

---

## 1. The hardware facts (from the user, treat as ground truth)

* "Parts always reload well. However the sequence data does not always reload reliably.
  Most of the time it does."  **Later corrected to: failure is frequent and the pattern is
  indeterminate — do not assume it is rare.**
* When it fails: the toast says `TRK SEQ RELOADED`, **the grid LEDs do not change, and the
  trigs play back exactly as the LEDs indicate** — i.e. the *edited* sequence is what is
  playing. The CF-saved sequence was never loaded. **This rules out a display/redraw
  explanation** (an earlier theory of mine — it was wrong, see §5).
* The Part half always works. The Part is applied **synchronously in the key handler**
  (`PART_RELOAD`); the sequence is an **asynchronous storage job**. That asymmetry is
  structural, not incidental.
* SAVED = what is on the CF card (`<project>/bankNN.strd`), which is what the worker reads.

## 2. What is in the flashed build

`wip`, commit `d06d8ee`. Built artefacts:

```
out/OCTATRACK_OS1.40C_RELOAD3.syx   e823222f6090d63470959d7a1c5f6804d8ad2c6d401fefa39c6c9193fd3ae49a
out/OCTATRACK_RELOAD3.bin           915c476bea226bb26f39236a61a0cc5d9b58d5311fb731adc009c8c1c54d9b94
patch_reload3  2108 B @ 0x400d6500..0x400d6d3b ; 1703 bytes changed vs stock
```

Relevant pieces, all in `tools/patch_reload3.s`:

* the message is **deferred to completion**: the chord arms `rl_msg`, and `rl_done` (our
  detour on stock's doneFn success path) draws it. `rl_done` is reached only with
  `rl_own != 0`, and `rl_own` is set only at `rlj_setflag`, i.e. **after** the copy.
* a **self-verify**: `rlj_trk_copy` snapshots the 16 trig-mask bytes it wrote into
  `rl_vsnap` (in our cave, deliberately *not* SCRATCH), stores the in-slab offset in
  `rl_voff`, sets `rl_varm`. `rl_done` recomputes the live slab from `PLAY_BANK`/`ACT_PAT`
  and compares; a mismatch shows `SEQ RELOAD LOST / NOT RESTORED!`.

Cave symbols for the current build (**always re-read with `tools/cave_syms.py`; they move
on every source edit**):

```
rl_job 0x400d6928   rl_done 0x400d686e   rlj_setflag 0x400d6b5c   rl_openstrd 0x400d6ba8
rl_own 0x400d6c1c   rl_msg  0x400d6c20   rl_voff 0x400d6c22
rl_varm 0x400d6c26  rl_vsnap 0x400d6c28
```

## 3. ⚠️ THE KEY NEW OBSERVATION — and what it forces

**On a failing reload, `SEQ RELOAD LOST` does NOT fire.** The user sees the normal success
toast. Combine that with the code:

* the toast drew ⇒ `rl_own` was set ⇒ `rlj_setflag` ran ⇒ `FOPEN`, the header `FREAD`, every
  `PARSEPAT`, and `FWMEMCPY` all completed, and `rl_varm`/`rl_voff`/`rl_vsnap` were written.
* the verify passed ⇒ at doneFn time, the 16 bytes at
  `BLOB + PLAY_BANK*0x9b340 + ACT_PAT*0x8ed8 + rl_voff` **equalled `rl_vsnap`**.

Yet the user hears the edited sequence. Only three things can be true:

**(A) `rl_vsnap` itself held the EDITED data** — because `SCRATCH` did. Then `FWMEMCPY`
copied edited→live (a no-op), the snapshot recorded the edited bytes, and the verify
compared edited against edited and passed. **Everything is self-consistent and vacuous.**
This is the leading hypothesis: it explains the toast, the verify, the stale playback, and
the randomness in one mechanism, and it is the only one that needs no new failure mode.
Why SCRATCH might hold the wrong bytes:
  * `SCRATCH = OPEN_BUF + 0x7000 = 0x460aff60`, and `OPEN_BUF = 0x460a8f60` is a **stock**
    buffer. **All 14 stock users of it pass size `0x10000`** (e.g. `0x4008fbde`,
    `0x400916d4`) — so SCRATCH sits 28 KB *inside* stock's own 64 KB read window. On
    hardware, audio really does stream off the card and `.work` autosaves happen; stock
    file I/O can overwrite SCRATCH. This was identified in Session 92, measured once in the
    emulator as "no third-party writers during the job", and **dismissed too early** — the
    harness cannot produce card contention.
  * or `PARSEPAT` (`0x4008cebc`) returns >= 0 without writing what we expect (wrong pattern
    index, short read, version-word mismatch). `d5 = G_PAT` is captured at chord time.

**(B) the copy landed correctly and was overwritten AFTER doneFn.** The verify is
**immediate** — it cannot see a later overwrite. Nothing rules this out.

**(C) playback reads a region the reload does not update.** `tools/diag_reload3_readsrc.py`
measured the engine reading the **cold blob** (`0x4009d382`/`0x4009d386`, 25 reads) and
**zero** live-cache reads — but that was one 16-byte window, once, in the emulator. Weakest
of the three, not eliminated.

## 4. The next experiment (do this first)

**Make the toast print actual byte values.** It is the only instrument that works, because
the failure only exists on hardware. Two lines are available; show hex:

* line 1: the first 4 trig-mask bytes of `rl_vsnap` (what we believe the card said)
* line 2: the first 4 at the recomputed live slab (what is playing)

Then one flash settles (A) vs (C):

| toast shows | conclusion |
|---|---|
| both equal, and equal to the EDITED pattern | **(A)** — SCRATCH held the wrong data; the copy was a no-op. Fix the SCRATCH region (move it out of `OPEN_BUF`'s 64 KB window entirely) and/or verify `PARSEPAT`'s output before copying. |
| both equal, and equal to the CARD's trigs | **(C)** — the data is right where we look; playback reads elsewhere. Hunt the real read source with a wider read hook. |
| they differ | impossible with the current verify (it would have fired) — means the verify logic itself is wrong; re-derive it. |

Useful additions while in there: also print `ACT_PAT`, `PLAY_BANK` and `G_TRK` as used by
the worker, so a wrong-target can be seen directly rather than inferred.

For **(B)**, add a *deferred* re-verify: keep `rl_vsnap`/`rl_voff` live and re-compare on the
**next** chord (before arming), reporting "PREV RELOAD UNDONE" if the previous reload's bytes
are no longer present. That distinguishes "never landed" from "landed then lost" without
needing to catch the moment.

## 5. Dead ends — do NOT re-run these (all mine, all measured)

| theory | verdict |
|---|---|
| Redraw/`RDRAW` staleness (display not repainted) | **WRONG.** The user confirmed trigs *play back* matching the LEDs, so the data really is stale. `RDRAW` is now set on the sequence path anyway (harmless, keep). |
| `CUR_BANK` vs `ACT_PAT` mismatch (wrong bank targeted) | **Real defect, fixed** (`PLAY_BANK` at all 5 sites, commit `fa2cca0`), reproduced and A/B-verified in the emulator — **but it was not this bug**; the failure survived the fix. |
| `rl_done`/whole-bank-suppression accumulating across reloads | **Not reproduced.** 8× `[PTN]` and 4× `[BANK]` consecutive reloads clean, no drift in `G_KIND`/`rl_own`/layer depth/dispatch slots. This also *satisfies* the multi-reload gate the `rl_done` header has demanded since Session 80. |
| Emulator "hanging" / needing an octabam rollback | **WRONG.** It is simply **121–145× slower than realtime** (measured by A/B-ing a purpose-built pre-sync EMAC Unicorn: 7.24 vs 8.58 s per 60 ms slice). Boot is 4–7 min. Budget 30–40 min per diag. Do not roll back `refs/octabam`. |

## 6. Harness limits that matter here

* **The emulator never reproduces the bug.** Clean every way it has been asked: single
  reload; 8× `[PTN]`; 4× `[BANK]`; the user's own *empty → reload → LED on* design
  (`tools/diag_reload3_led.py`, `HAS_CONTENT` = `0x4009a464`) 4/4 on both chords.
* It **cannot fail a card read, stall one, or stream audio off the card** — the card is a
  file. This is exactly where the remaining hypotheses live.
* It **cannot drive the firmware's own edit path**: all four Session 84 strategies (plain
  trigs / REC+trigs / grid-mode+trigs / both) still move **zero** bytes. So "the user edits,
  then reloads" is *not* reproducible here, and the poke-based substitute is not equivalent.
* `stage_project` is not concurrency-safe — run diags sequentially.

## 7. Process warnings (earned the hard way this session)

* **Never hardcode cave addresses.** Use `tools/cave_syms.py`. The cave packs sequentially,
  so any size change shifts every later symbol, and a stale address returns a *plausible
  number* rather than failing. This fabricated a finding — "the worker never ran" and
  "`rl_own` left non-zero, the accumulating shape the `rl_done` header warns about" — from a
  byte of unrelated cave data, impersonating the exact bug being hunted.
* **Gate every diagnostic**, and make the gate prove the detector *could* fail. Gates caught
  three of my own bugs; ungated inference produced three wrong root causes.
* **Prefer the observable over the intermediate.** Byte-comparing the blob passed for days
  while the user's LED/playback observation was the thing that mattered. The user's test
  design (saved has a trig, active empty, check the LED) was better than mine.
* **Arm shared state before posting an async job.** A race I introduced: `rl_msg` was armed
  *after* `rl3_arm_n` posted the job, so a fast doneFn drew nothing and stranded the flag.
  `[PTN]` won that race in every emulator run and would have shipped broken.
* Do not claim a root cause from one suggestive trace. Two of mine were contradicted within
  minutes by a second measurement.

## 8. Hard constraints (from CLAUDE.md — non-negotiable)

* Hardware is **Octatrack MKI only**.
* Test data: **only real hardware-exported project files.** Never fabricate or hand-edit a
  `.work`/bank/project blob — ask the user to export one.
* Builds are **guarded binary patches**: assert the stock bytes overwritten, assert caves are
  free / non-overlapping / in-zone, round-trip through Elektron's tool.
* **Read `reference/kb/caves.md` before naming any cave address.** Two projects bricked units
  getting this wrong; a static "no references" scan is necessary but not sufficient.
* `refs/octabam` needs `tools/refs/local-patches/octabam-emu-samplebank-map.patch` applied or
  the emulator cannot boot our images at all (`UC_ERR_WRITE_UNMAPPED` in `gate_m6a`).
* Check `git config user.email` before committing.

---

## 9. Session 98 (2026-09-25) — the §4 experiment is BUILT. Flash it and read the hex.

**What was built.** `tools/build_reload3.py --diag` assembles the *same* `patch_reload3.s` with
`--defsym RL_DIAG=1`. Every success message (1/2/3, and the LOST override 4) is replaced by a
four-line block toast held for 6 s (`DIAG_DUR 0x168`), drawn through `rl3_toast2` at the
same point in `rl_done` where the message used to be drawn. **Nothing under test moves**:
SCRATCH, OPEN_BUF, the `0x80006a50` scratch bytes, the job flow, the verify and the
shipping detour sites are byte-for-byte the flashed build's (the non-diag build still hashes
`e823222f…` / `915c476b…`). Only cave-side captures were added, written at the moment each
value is read — never into SCRATCH.

```
out/OCTATRACK_OS1.40C_RELOAD3_DIAG.syx  a627a7fb88960824f8989ffd44eee0e185892e25655292c22636254d79caf260
out/OCTATRACK_RELOAD3_DIAG.bin          3f37367ceee8a1a8825be31b43934a56a69c13113358a544c9118a43d9995431
patch_reload3 (diag) 2824 B @ 0x400d6500..0x400d7007 ; 2201 bytes changed vs stock ; VERSTR 140C_RL3DG
```

Separate output files (`out/patch_reload3_diag.{o,elf,bin}`, `out/mainos_reload3_diag.bin`)
so the shipping ELF that `cave_syms.py` reads by default is never overwritten by a
diagnostic. Diag symbols come from `syms("out/patch_reload3_diag.elf")`.

**The toast, line by line** (one hex digit per index; bytes are the first 4 of the 16 trig-mask
bytes = steps 1–32, so put the test trig in that range):

```
P pppppppp S ssssssss    P = live track record BEFORE the copy (= what was playing / edited)
                         S = rl_vsnap = SCRATCH after the copy (what the worker believes the card said)
L llllllll K kkkkkkkk    L = live record at doneFn (what the verify compared)
                         K = the same record in the 0x1001614e live cache LIVE_REFRESH filled
C bptm W bptm D bp       bank/pattern/track/midi as the CHORD armed them (rl3_arm_n),
                         as the WORKER read them back from 0x80006a51/54/55,
                         PLAY_BANK/ACT_PAT as DONEFN saw them
Mn Vn Kn R rr            M = message that would have shown (1 TRK / 2 TRK+PART / 3 SAVE FIRST / 4 LOST)
                         V = verify (0 not armed / 1 pass / 2 fail)   K = G_KIND as the worker read it
                         R = low byte of the LAST PARSEPAT return
```

**Protocol on the unit** (the user's own design): saved pattern has a trig on step 1 of
track n (mask byte 0 = `01`), active pattern has that track empty (`00`). `[PTN]+[TRACK n]`,
read the toast, listen. Then chord **again without editing anything** and read the second
toast. Photograph both.

| toast shows | conclusion |
|---|---|
| `P 00…` `S 01…` `L 01…` `K 01…`, `C == W`, `V1`, but the grid/playback stay empty | **(C)** the copy landed where the verify looks; playback reads somewhere we do not update. Line 1's `K` says whether the live cache got it too. |
| `P 00…` `S 00…` `L 00…` `K 00…`, `V1` | **(A)** SCRATCH held the edited data; copy and verify were vacuous. Fix the SCRATCH region (out of OPEN_BUF's 64 KB window) and/or verify PARSEPAT's output before copying. |
| `C` ≠ `W` (track, midi, pattern or bank digit differs) | the `0x80006a5x` scratch was clobbered between chord and worker (kb/caves.md "Scratch RAM"). The verify passes on the slice the worker *did* write, so the shipping toast says RELOADED while track n is untouched. Fix: carry the request in the cave (or in the job's own mask) instead of `0x80006a50+`. |
| toast 1 `L 01…` and toast 2 `P 00…` (no edit in between) | **(B)** landed, then undone before the second chord. |
| `S 01…` but `L 00…` (would also be `V2`, `M4`) | the verify fired; the LOST message was right and the shipping build already reports it. |
| `R` non-zero / `K` ≠ 3 / `M` ≠ 1 on the [PTN] chord | the worker did not run the path we think it ran; start there. |

**Emulator gate** (`tools/diag_reload3_diagtoast.py`, one boot, three scenarios, every one
gated so a pass cannot be vacuous): **ALL GOOD, 47 checks.**
`clean` → `P 00000000 S 00000001 / L 00000001 K 00000001 / C 0030 W 0030 D 00 / M1 V1 K3 R 01`,
LED on, target restored. `wrongtrack` (G_TRK poked to 4 from the `rl_job` entry hook) →
`C 0030 W 0040`, **V1**, target track untouched — the shipping toast would have said
RELOADED. `scratch` (memcpy source masks zeroed) → `P=S=L=K=00000000`, **V1**, LED off —
the vacuous-verify signature of (A). So each row of the table above is a shape the toast
has actually been seen to produce, not a prediction. First run's `wrongtrack` failed its
own gate (the poke landed after the worker, which drains inside the key calls in the
emulator) — the injection moved into the `rl_job` hook; nothing about the build changed.

**Still true after this session:** the emulator has not reproduced the failure; this build
does not fix anything; it only makes the next flash decisive.

## 10. HARDWARE RESULT (2026-09-25) — the diag toast named it: the request bytes are clobbered

User, on the RL3DG build: a single trig on step 1 did **not** reproduce. Trigs on steps
1,3,5,7,9,11,13,15 **did**. "The only difference in the hex between the two was the W
field: `0000` when successful, `005B` when unsuccessful." (C, P/S/L/K pattern, M/V/K/R
otherwise the same shape; C taken as `0000`, i.e. audio track 1.)

Decoded: the worker read `G_TRK` (`0x80006a54`) as **5** (after its `andi #7`) and
`G_TMIDI` (`0x80006a55`) as a **non-zero byte ending in B**, so it took the MIDI branch
and copied **MIDI track 6's** region. The verify checks the slice the worker wrote, so it
passed and the toast said RELOADED while audio track 1 was untouched. This is the
"C ≠ W" row of §9 exactly, and the same shape the emulator produced when G_TRK was poked.

Observations, not yet explanations:
* The chord wrote the right values (C matched in both runs). Something overwrote
  `0x80006a54-55` between the chord and the worker's read in `rlj_trk`, which runs after
  the file open and all the PARSEPAT calls.
* The clobber is **content-dependent**: the alternating-step pattern has mask bytes of
  `0x55`, and `0x55 & 7 = 5`. Suggestive, not proven. It also means a clobber that writes
  zeros would be *invisible* on a track-1 test, which may be why the single-trig case
  looked fine.
* Side effect on every failing reload: MIDI track 6 (or whichever slice W names) was
  silently overwritten with its CF-saved version.

This is the Sessions 94-96 finding again (`0x80006a40+` is not ours on hardware), now for
RELOAD3. **Fix direction:** move `G_KIND/G_PAT/G_MENU/G_SEL/G_TRK/G_TMIDI` out of
`0x80006a50+` into the cave's own data (where `rl_own`, `rl_msg` and the diag captures
already live and demonstrably survive). Not built yet.

## 11. Session 98 — the FIX is built: the request bytes live in the cave

`G_KIND/G_PAT/G_TRK/G_TMIDI` are now four bytes of `patch_reload3.s`'s own data (after
`rl_kind`), found by symbol (`cave_syms`), never by address. `G_MENU/G_SEL` (picker-era,
unused) are gone. `build_reload3.py` asserts the blob references nothing in
`0x80006a40..0x80006abf`; that guard reports 11 references when run on the pre-fix source,
so it can fail. Nothing else changed: same detours, same copy, same verify, same toasts.

```
out/OCTATRACK_OS1.40C_RELOAD3.syx        51e342ba54bf5727f46d428de54d75f7e11444a0ffb3a7ce68506c59aeef6d6f
out/OCTATRACK_RELOAD3.bin                e83b20200c10a8a2aed2ab6396c10f15a99bda8deb208390713dcc80a1e2042f
out/OCTATRACK_OS1.40C_RELOAD3_DIAG.syx   89bb1bd10738a44c2f70dbb3b001f4a805ca69701531d8f5363c563cf7a596ae
out/OCTATRACK_RELOAD3_DIAG.bin           892d8db4fd17cfa578c67110a65e539b3eebb99b1c3f34021c188cee4bceb6e1
patch_reload3 2104 B @ 0x400d6500..0x400d6d37 (diag 2816 B)
```

Emulator gate: **ALL GOOD.** Diag build, 61 checks: the `oldscratch` replay (`03 07 55 55 55 5B` into `0x80006a50-55` before the worker reads) gives `C 0030 W 0030`, CF-saved bytes restored, LED on. The pre-fix build was redirected by the same hook timing. Shipping build: `diag_reload3_led.py -n 4`, 4/4 LED on, masks restored. Emulator evidence covers the logic only; the hardware test below is what closes this.

**Hardware test to close this:** the failing pattern (trigs on 1,3,...,15), reloaded
repeatedly. On the diag build every toast's `W` must equal `C`; on the shipping build the
edited track must audibly come back every time. Still open and unrelated to this fix:
whether anything else in the reload path depends on RAM the unit rewrites.

### 11a. More hardware W values (user, second RL3DG session)

Failing reloads also showed **W `0045`, `004F`, `003F`** besides `005B`. Worker-read track
= 5, 4, 4, 3; MIDI byte low nibble = B, 5, F, F — always non-zero, so every failure took
the MIDI branch and reloaded some MIDI track. Bank and pattern digits stayed 0.
**This weakens the "0x55 mask bytes → track 5" reading in §10**: the clobbering values
vary, so the writer is not simply copying that pattern's trig bytes. What stands is the
fact itself — the bytes at `0x80006a54-55` do not survive from chord to worker — and the
fix does not depend on who writes them or with what. (Pattern digit is a low nibble only;
a clobbered G_PAT reading ≥16 would most likely have failed the parse and shown stock's
error rather than a toast.)
