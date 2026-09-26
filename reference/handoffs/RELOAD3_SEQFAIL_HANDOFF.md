# RELOAD3 — HANDOFF: sequence reloads fail intermittently, and the toast lies

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
