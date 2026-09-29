# repitch-kyoti rev 14 — session start prompt (paste as the first message)

Written Session 111 (2026-09-28). Everything below the line is the prompt.

> **FINAL — rev 16, hardware-confirmed 2026-09-29** (`tools/build_repitch_kyoti.py`, tier FINAL,
> `140C_RPK16`; Bugbuild `BUG_RPK16`). Rev 15 fixed the last trig crack (trigs on a frame
> boundary), rev 16 the TSTR switch that kept the other domain's PTCH/QUAN value and the QUAN
> pressed-turn speed (NOTES Session 112 continued (2)–(4)). This prompt was executed in Session 112; it is kept as the record of rev 14's brief.

---

Repo: ~/Documents/octatrack-kyoti-fw (Octatrack MKI OS 1.40C firmware mods, "OT Kyoti FW").
Task: build repitch-kyoti REV 14 — RPSP becomes the SP-1200's CHANNEL 1/2 (the SSM2044 dynamic
low-pass after rev 13's staircase), and both virtual-ADC tables go back to FULL fidelity.
Work through the gates below in order. Stop and ask me only at gate 1 (I pick the envelope by
ear) or if genuinely blocked. Do NOT do anything listed under "not in scope".

READ FIRST, in this order: CLAUDE.md (esp. "Concurrent sessions", explicit-path commits, and
"always say explicitly when a build exists"), START_HERE.md, NOTES.md "Session 110" and all of
"Session 111" including its "continued" entries, reference/handoffs/REPITCH_SP_CH12_SCOPE.md
(the design for this build — all of it, esp. §3, §3a, §4, §5, §6, §6a),
reference/handoffs/REPITCH_FIDELITY_SCOPE.md ("Implementation status" sections for rev 11–13).

WHERE THINGS STAND. Rev 13 (commit 5ff26e9) is flashed and working on my MKI
(out/OCTATRACK_OS1.40C_REPITCH_KYOTI_REV13.syx, sha256 571565e9…, OS VERSION 140C_RPK13).
RPCH and RPS9 sound great and are LOCKED: RPCH's output must stay sample-identical to rev 13;
RPS9's only permitted change is restoring rev 12's exact full table (below). RPSP is correct as
a drop-sample SP-1200 on its raw outputs 7/8 (Session 111 proved it against an independent
reference, tools/repitch_sp_reference.py), but my ears expect the channel 1/2 sound: the dynamic
SSM2044 filter that opens on each hit and closes as the sound decays.

REV 14 CHANGES (exactly these):
1. FULL-FIDELITY TABLES, both modes: undo rev 13's row packing. RPS9 = rev 12's exact table
   (16 stored half-rows x 16 taps = 256 words); RPSP = rev 13's retuned 12-tap design, all 16
   half-rows stored (192 words). Mirror symmetry stays (row 31-ph = row ph reversed). zqexp's
   odd-row interpolation goes; rev 12's plain mirror copy comes back.
2. TABLE STORAGE IN SPRING'S ORPHANED X MEMORY (no new donor): SPRING's payload loads five X
   data tables per core that only SPRING's code references — payload A X:0x89a4/0x89ec/0x8a34
   (72 words each), 0x8afc (116), 0x8b70 (384); payload B X:0x8464/0x84ac/0x84f4, 0x85bc,
   0x8630. NEVER touch the 27-word X:0x8cf0 (A) / X:0x87b0 (B): the next module uses it too.
   Rewrite those five modules' payload bytes (same load address and count; assert the stock
   bytes first, like the P cave) to carry RPS9 256 + RPSP 192 + the render half-table 81 = 529
   words; zqinit copies X->Y (runtime Y layout as rev 13). This frees P for the filter.
3. RPSP = CHANNEL 1/2: after the staircase render, an SSM2044-style 4-pole low-pass, resonance
   0 ("classic": Rossum QSG), cutoff = f_rest x 2^(depth x env), env = attack ~5 ms then decay,
   opened by each hit. Default: RPSP IS channel 1/2 (7/8 kept behind a build switch). Keep
   rev 13's band-limited render unless gate 1 shows the cheap box render is inaudible through
   the filter (the filter is dark between hits).
4. THE HIT SIGNAL, DSP-side if possible: trigs reach the DSP as per-track voice commands
   (trig_to_voice 0x400977cc; STATIC pos|0x10, FLEX pos|0x8010) and the OT's AMP envelope runs
   on the DSP. Preferred: key the filter off the OT's own AMP envelope level (as the SP's filter
   follows its channel GAIN), so ATK/HOLD/REL shape it. Fallback: a fixed AR started by the
   trig. ColdFire fallback (a toggle bit in the tagged increment, Q26 bit 4 = DSP y:$40 bit 2)
   only if the DSP route fails — the ColdFire cave has 12 bytes left, so ask me before that.

GATES:
- 0a X-TABLE CANARY: prove SPRING's five X ranges are untouched at runtime (fill after boot;
  project loads, FX changes on both buses, reverbs/delays, scenes) in ot_emu — static proof is
  already in NOTES. Report it; a hardware diagnostic can follow later.
- 0b HIT/ENVELOPE OBSERVABLES: with a PRIVATE copy of refs/octabam/tools/emu/ot_emu in your
  scratchpad (Session 110's RK_TRACE approach), find where the DSP holds each track's AMP
  envelope level/stage and the start command; confirm our hook (A P:0x40b / B P:0x20e) can read
  them in the same frame, and that retrigs, slices and p-locked starts show.
- 0c (optional, after the core): does TSNS (playback page 2) reach the DSP per track? If yes,
  map it to the initial cutoff (64 = classic), label unchanged. If it needs ColdFire, skip it.
- 1 MODEL + LISTENING (STOP HERE FOR ME): add the filter to tools/repitch_engine_model.py
  (float Engine + DspExact integer twin). Build 3 envelope candidates from the scope §1c:
  (A) follow the AMP envelope, (B) 5 ms attack / ~0.15 s decay AR, (C) the fast "~1 ms to
  ~250 Hz" reading; f_rest from the 1.0 kHz trim, depth to taste. Render isaak.wav
  (~/Desktop/isaak.wav) at 90/120 (0.75) and 120/120, plus a drum loop, through each, next to
  rev 13's 7/8. Put the WAVs in out/rev14_listen/ and ask me to pick. Also measure the box
  render vs the rev 13 render through the chosen filter.
- 2 DSP: implement in tools/patch_repitch_dsp.asm through tools/repitch_dsp_src.py ->
  tools/dsp_xasm.py ONLY (plain dsp_asm silently mis-encodes; NOTES Session 110). A short
  `move #<imm` to an accumulator is LEFT-aligned (Session 111 hit it) — use `#>`.
- 3 BUILD: KYOTI_ALLOW_WIP=1 python3 tools/build_repitch_kyoti.py; status() text -> rev 14;
  VERSTR -> "140C_RPK14". Keep out/OCTATRACK_OS1.40C_REPITCH_KYOTI_REV13.syx; copy the new one to
  out/OCTATRACK_OS1.40C_REPITCH_KYOTI_REV14.syx. Tell me plainly that a build exists, the file,
  its full sha256, and that it is NOT flashed.

BUDGET: P cave <= 675 words (SIDECHAIN3's first 388 donor words stay free); X: the five SPRING
tables only; Y: $A00-$FFF (SIDECHAIN3 owns $800-$9FF), filter state after $F40. Report DSP
instructions per sample for RPSP and RPS9 (rev 13: RPSP 125-137, RPS9 58 in the full firmware).

VERIFY (all must pass):
- python3 tools/repitch_dsp_engine_check.py -> 80/80 bit-exact vs the twin (now with the filter
  and a hit signal the probe must drive — extend tools/repitch_dsp_engine_probe.cpp to model it),
  mode switch 8/8 (poisoned undelivered frames stay).
- RPS9 output bit-identical to rev 12's RPS9 (rebuild db76906's mainos in a throwaway worktree
  if out/mainos_repitch_kyoti_rev12.bin is gone; symlink refs/octabam INSIDE its tracked refs/).
  RPCH identical to rev 13.
- Full firmware in ot_emu (shared binary, never rebuild it or libunicorn) with MY project: stage
  ~/Desktop/REPITCH + isaak.wav via refs/octabam/tools/emu/ot_emu/stage_card.py
  (--audio "$HOME/Desktop/isaak.wav:AUDIO/ELEKTRON/isaak.wav", --tree in your scratchpad);
  play pattern A02 with a --steps file containing `seq 0,1` PLUS --sequencer --internal-clock
  --dsp --main-level 64; T2 is the RPSP track; its part TSTR byte is 0x4017115c (4/5/6). Check:
  engine on every playing pass, filter opens on each hit (measure the spectral envelope per hit),
  levels sensible vs RPCH, no clicks, RPS9/RPCH as above. Also the MMTESTDT scenario of
  Session 111 (--poke 0x4017113e=<4|5|6> + BPM24 pokes; never the live lane 0x8000052c).
- tools/repitch_sp_reference.py: RPSP's pitched junk above the filter's resting cutoff should
  now be largely gone between hits; report junk-to-music per band vs rev 13.

DOCS: NOTES.md "Session 112"; a "rev 14" status note in REPITCH_SP_CH12_SCOPE.md and
REPITCH_FIDELITY_SCOPE.md; MERGE.md's DSP line (X tables now used, P cave size); the memory
index.

GIT: shared tree. `git config user.email` must be 273702472+Zac-Kyoti@users.noreply.github.com.
Stage EXPLICIT paths only, never `git add -A`; `git diff --cached` on shared files (NOTES.md,
MERGE.md) must hold only your edits; Thread: repitch. Commit; do NOT push unless I ask (6
repitch commits are already unpushed: `git log origin/main..HEAD`, rev 12 onward). When pushing: git fetch, rebase onto
origin/main, never force-push, never cherry-pick past another session's unpushed commit.

EXPLAIN TO ME in plain language what changed and how RPSP should sound vs rev 13, then list
what to test on hardware.

NOT IN SCOPE: a user-facing 7/8 <-> 1/2 selector; resonance control; channels 3-6; any change to
RPCH; any RPS9 change beyond restoring rev 12's full table; a sweepable RPS9 filter.
