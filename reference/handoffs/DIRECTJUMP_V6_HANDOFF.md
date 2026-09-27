# DIRECT JUMP V6 — handoff (Session 106 → next session)

Written 2026-09-27 at the end of Session 106, for a fresh session picking this up.
Read this file, then `NOTES.md` Sessions 105–106, then `reference/AR_SEQUENCER_ENGINE.md`
§3 and §6. `reference/handoffs/DIRECTJUMP_PHASE_HANDOFF.md` §0 is the older entry point and
still correct about the architecture; everything about V1–V5 in it is history.

---

## 0. Where the work stands

**The jump itself WORKS on hardware.** V6.1-DIAG flashed 2026-09-27; audio switches in
DIRECT JUMP fashion, toast read **`A8 L8 R8 C0 T1 H0 G0`** (8 cues, each seen once while
idle, 8 arms, 8 landings; stock's countdown byte 0, transport running, no chain, no
arranger). The user's earlier "not engaging" report was the LED symptom below, not a
failure to jump.

**The one open defect: the pattern LEDs still behave as if the switch were merely CUED.**
With DJ ON, the switched-to pattern's LED turns *yellow* at the cue and only goes *red* when
the outgoing pattern reaches its end. It should go red at the landing. V6.2 tried to fix
this by posting stock's wrap-change UI message and **that did not work** (flashed; LEDs
unchanged).

Current build = **V6.2**, `tools/build_directjump_v6.py` (WIP tier, needs
`KYOTI_ALLOW_WIP=1`):

| artifact | sha256 (first 16) |
|---|---|
| `out/mainos_directjump_v6.bin` (+ `OCTATRACK_OS1.40C_DIRECTJUMP_V6.syx` / `.bin`) | `723df02401fe3452` |
| `out/mainos_directjump_v6diag.bin` (`140C_KDIAG`, `*_V6DIAG*`) | `c2692debeff10d0d` |

Emulator gates re-run on every V6.x and all pass: DJ-OFF identical to stock, DJ-ON-idle
identical to stock, and the 16↔7 NORMAL-mode oracle holds fire-time class `[0]` on every
track through five landings and two wraps.

---

## 1. What V6 is (so you do not re-derive it)

AR's DIRECT JUMP commit, run through the Octatrack's **own** landing path. Sessions 105's
decompilation of the AR engine established that AR waits for the next master step boundary
and then re-lands every track synchronously — and that OT already contains that landing as
stock code, behind the countdown byte `0x80006687` in phase D of the tick handler
(`consumer_a6c0_a33f8` @ `0x400a1eea`; the landing body is `0x400a1f72`–`0x400a222e`, and it
runs **before** the per-track scheduler at `0x400a2982`).

Two 6-byte detours, in `tools/patch_directjump_v6.s`:

- **`0x400a1f72` → `dj_land`** (replaces `move.b (0x80006687).l,%d0`). Arms by writing
  `0x80006687 = LEN_TBL[SCALE_IX] − TICK_CTR` (ticks to the next master boundary; stock's
  own decrement follows in the same tick). On the tick where that byte reads 1, `dl_commit`
  fills what stock's landing consumes: `PREV ← ACT`, `ACT ← PEND`,
  `0x80006638 = MASTER_STEP mod masterLen`, per track `0x80006516[t] = new_step mod len_t`
  and `0x80006536[t] = 0`, and clears the hold/resync masks. Stock then does the rest
  (reloads, `TICK_CTR = tps−1`, first-fire mask `0x80006624 = 0xffff`, `CNTDN = −1`, master
  step, scale caches, ARMED), and phases E/F/G of the same tick fire the landing step.
- **`0x400a221c` → `dj_nofa`** (replaces `tst.b (0x8000002a).l`): suppresses the MIDI START
  (`0xFA`) that stock's landing would send.

Plus the unchanged UI pieces: `dj_toggle` in the `[PTN]`-held keymap slot `0x400bf0c0`,
`dj_ptnrel` @ `0x40043418`, the OS toast, and DJ_MODE `0x800000d8` forced off at power-on.
**The pattern-boundary body, the rebuild loops, `0x80006628` and every per-track counter are
stock.** State lives in the cave, never in `0x80006a40+`.

---

## 2. The LED defect — what is measured, and what V6.2 got wrong

### 2.1 V6.2's attempt (failed)

Stock's wrap-change, right after its own `ACT ← PEND` swap at `0x400a44d0`, posts to the UI
queue: `0x400d8168 = ACT_BANK; FUN_40000c3c(0x460d17ae, 0x400d8167)` (`0x400a4548`–
`0x400a4566`). That message template is `{0x15, bank}` and it is the only image-wide post of
it. `dl_commit` now ends with those same three instructions. **Flashed: no change to the
LEDs.** So that message is not what clears the "cued" colour (plausibly its handler
early-outs because the *bank* did not change).

Leave the post in or take it out as you like — it is harmless and matches stock, but it is
not the fix.

### 2.2 The actual predicate (MEASURED, disassembly, Session 106)

The PTN-page pattern-grid LED painter is **`FUN_4007afe8`** (its LED-bit calls and the
`has_content` predicate at `0x4009a464` are already documented in
`tools/patch_pattern_led.s`; the chain-view twin is `FUN_400353d4`, and `FUN_400418e0` also
reads the same pair). At `0x4007b182`:

```
4007b182  mvs.b  (0x800065c0),%d5     ; d5 = PEND_PAT   (sequencer's cued pattern)
4007b188  mvz.b  (0x100b14d0),%d0     ; d0 = a UI/project-side pattern byte
4007b18e  cmp.l  %d5,%d0
4007b190  beq.s  0x4007b1e0           ; EQUAL -> skip the "cued" paint entirely
4007b192  mvs.b  (0x800065bf),%d1     ; d1 = PEND_BANK
4007b198  mvz.b  (0x80000002),%d0     ; d0 = current bank
4007b19e  cmp.l  %d1,%d0
4007b1a0  bne.s  0x4007b1e0           ; different bank -> skip
          ... paints the CUED (yellow) LED for pattern d5 via 0x400135b0 / 0x400131a0 ...
```

So **"cued" is painted when `PEND_PAT != [0x100b14d0]` and `PEND_BANK == [0x80000002]`.**
The comparison is *not* against `ACT_PAT`. V6's landing copies `PEND → ACT` and leaves
`PEND_PAT` equal to the new pattern, so whether the LED goes red depends entirely on what
`0x100b14d0` holds — and nothing in V6 updates it.

`0x100b14d0` is in the live project/part RAM region (neighbours: `0x100b14cc` current audio
track, `0x100b14cf` part index, `0x100b14d1` written by `FUN_400a013c` from `0x80006694`).
A naive 4-byte image scan for `0x100b14d0` returns ~484 false hits — **do not** use that;
find its writers with the Ghidra census instead (§4).

### 2.3 The next step, stated as an experiment (not a theory)

Do this before writing any hook — the repo's own rule (CLAUDE.md) is to measure when
hardware and reasoning disagree:

1. In the emulator, sample `PEND_PAT 0x800065c0`, `PEND_BANK 0x800065bf`, `ACT_PAT
   0x800065be`, `ACT_BANK 0x800065bd`, `0x100b14d0` and `0x80000002` every tick across
   **(a)** a stock DJ-off cued switch that commits at a natural wrap, and **(b)** a V6.2
   landing. Diff the two traces at and after the commit tick.
2. Whatever stock's wrap-change path makes true about `0x100b14d0` (directly, or via a
   message handler that runs in the UI task), make the landing make true as well.
   `tools/diag_tablearm_phase.py` is the nearest template for such a run (it boots a real
   project, cues patterns from a tick hook and watches addresses).
3. Candidates to check while you are in there, in order:
   - the **`{0x11, pattern}`** message (template `0x400d8164`, argument byte `0x400d8165`),
     which `FUN_400a0570`, `candidate_400a10d2` and the stop path post — i.e. stock's
     "pattern changed, here it is" announce, as opposed to V6.2's bank message;
   - a UI-task handler that copies `ACT_PAT → 0x100b14d0` on one of those messages (find it
     by censusing writers of `0x100b14d0`);
   - writing `0x100b14d0` from `dl_commit` directly — **last resort**: it is UI/project state
     written from the tick ISR, so it can race the UI task. Prefer the message route.
4. Whatever you choose, re-run the three gates in §3 and then have the user flash. The LED
   is a UI-visible change, so a DIAG variant is cheap insurance if the first attempt misses.

---

## 3. Gates — run all three before asking for a flash

```
cd ~/Documents/octatrack-kyoti-fw
KYOTI_ALLOW_WIP=1 python3 tools/build_directjump_v6.py            # mainline
DJ_DIAG=1 KYOTI_ALLOW_WIP=1 python3 tools/build_directjump_v6.py  # 140C_KDIAG twin

python3 tools/diff_stock_vs_patch.py --patched out/mainos_directjump_v6.bin \
        --tree-prefix out/_emu_off          # must print RESULT: IDENTICAL
python3 tools/diff_stock_vs_patch.py --patched out/mainos_directjump_v6.bin --dj-on \
        --tree-prefix out/_emu_on           # must print RESULT: IDENTICAL
python3 tools/diag_tablearm_phase.py --project ~/Desktop/DJTEST2 \
        --pattern 3 --to-pattern 4 --len 7 --image out/mainos_directjump_v6.bin
```

The third is the user's retraction case (both patterns forced NORMAL mode, 16 ↔ 7 steps,
1x). Expected, and what V6/V6.1/V6.2 all produce: `commits=[41, 78, 95, 149, 162, 203, 257]`
(five landings, each on a tick ≡ 5 mod 6 = a master boundary, plus two natural wraps of the
7-step pattern), and for every 1x track the scheduler writer `0x400a2e18` at class `[0]` in
every segment plus exactly one class-5 write per post-landing segment (that single write is
the landing's own immediate fire — it is expected, not a defect).

Each emulator run takes 30–40 minutes (the emulator is 120–145× slower than realtime; it is
slow, not hung). Run them in the background, in parallel, and do not poll — wait for the
completion notifications. `refs/octabam` is shared with other sessions: never rebuild its
Unicorn.

`python3 tools/build_bugbuilds.py --with-wip` also composes DIRECT JUMP with the three bug
fixes; it must report DISJOINT / ALL PRESERVED / NO STRAYS.

---

## 4. Tooling

- `tools/ghidra/GhidraSeqCensus.java` — every instruction touching a list of globals
  (data refs **and** bare scalar/cursor operands, so register-indirect loops are caught),
  then callers/callees of each touching function. Script args are `name=0xaddr …` and
  override the built-in table. **This is how to find `0x100b14d0`'s writers.**
- `tools/ghidra/GhidraDecompArgs.java` — decompile + raw listing for a list of entry
  addresses.
- Invocation: `export JAVA_HOME=/opt/homebrew/opt/openjdk@21` then
  `/opt/homebrew/Cellar/ghidra/12.1.2/libexec/support/analyzeHeadless ghidra_project octamax
  -process section_3_MAIN_OS.bin -noanalysis -scriptPath tools/ghidra -postScript X.java …`
  Scripts must be **Java** (no Jython/PyGhidra). Ghidra prints multi-line `println` output as
  one `INFO` line plus raw continuation lines — filter by stripping the prefix, never by
  grepping for the script name, or every decompiled body is silently dropped.
- The OT Ghidra project still has **no decode of `0x400a4568`–`0x400a4bdc`** (the
  wrap-change; Session 79's force-decode was never saved). V6 does not need it.
- Session 105's dumps are in `out/ghidra/*_session105.txt` (gitignored): `seq_decomp`
  (tick ISR + consumer), `seq_census`, `misc_census`, `transport_decomp`, `preroll_decomp`.

ColdFire assembly notes that cost time in Session 105: `cmpi` takes only a `Dn`
destination; there is no memory-to-memory or immediate-to-memory `move.b` (stage through a
`Dn`); displacements are 16-bit, so pattern-blob offsets like `0x8e53` need an index
register (`(%a2,%d7.l)`); `divu.l %dy,%dx` with one register is the 32-bit quotient (objdump
prints it `remul`); `bra.b`/`bne.b` overflow silently in a long hook — use `.w`.

---

## 5. Do not re-try these

- **Do not roll back to V6.** V6.1 added only a guard (`bgt` instead of `bne` on stock's
  countdown byte, so a *negative* stale byte cannot block arming). The hardware toast read
  `C0`, i.e. that byte was 0, so V6.1 ≡ V6 on every path the user exercised.
- **Do not re-enter the pattern-boundary body** (`0x400a4568`+) or write `0x80006628`. That
  is AR's *wrap-change* algorithm (ceil / remainder / hold / catch-up / deferred landing);
  AR never uses it for a jump, and every OT build from Session 79 to V5.11 — the Session 87
  image once called "gold" — was wrong because it did. Gold was **retracted on hardware**
  (fractional steps at 1x, NORMAL mode, 16↔7 patterns): do not gate anything against it, and
  do not treat `out/GOLD_S87_*` or `out/V5_3_*` as correctness references.
- **Do not reintroduce `dj_mrem`** or any sub-step remainder seed. The `(target step,
  remainder)` pair in AR is its pause / MIDI-Song-Position mechanism, not its jump
  (`reference/AR_DIRECT_JUMP.md` §10).
- **Do not keep state in `0x80006a40..0x80006abf`** — the unit overwrites it (Sessions
  94–98). The builder refuses any reference into that range.
- **Do not call UI primitives from the engine frame path** (`0x400522ca` / `FUN_40052200`) —
  that crashed a real MKI. The kernel post `FUN_40000c3c` **is** legal from the tick ISR:
  stock itself calls it there (`0x400a4566`, `0x400a3f8c`, `0x400a4dd8`).

---

## 6. After the LED: the test order, then the two known deviations

Once the LED lands correctly, the hardware sequence is:

1. The retraction case — 16-step and 7-step patterns, NORMAL mode, 1x, switches both ways,
   judged against the metronome, including the cadences that catch the AR.
2. `FLASHING.md` §4.3 steps 1–9: mixed lengths, PER-TRACK mode, track scales, MASTER LENGTH
   including `INF`, MIDI tracks, and confirm no MIDI START is emitted on a jump.
3. Master scales other than 1x — **expected to be imperfect**; note which direction lurches.

The user's standing instruction: **reach AR-exact behaviour first, then deviate on purpose,
one item at a time.** The record of AR behaviours to deviate from is
`reference/AR_DJ_QUIRKS.md` (canonical copy in the AR repo, `~/Documents/ar-kyoti-fw`), and
it currently holds three items:

1. **AR's own 16/7 half-step** — user hardware observation on the AR MKI: NORMAL mode, tracks
   of 16 and 7 steps, certain DIRECT JUMP cadences leave the 16-step track exactly half a
   step off. **Stock AR.** Mechanism not localised (the DJ commit zeroes every tick phase, so
   it arises later; hypotheses in the file). If the OT reproduces this, that *is* the
   AR-exact baseline, and item 1 becomes the first deliberate deviation.
2. **The landing duplicate** — the outgoing pattern's due event and the landing's immediate
   fire coincide on the boundary tick, split only by microtiming, so stock's equality-only
   dedupe lets both sound. Designed fix (~80 B, not built): purge the outgoing pattern's
   pending slots in `dl_commit` using stock's own purge idiom (`0x400a2530`+ /
   `0x400a4408`–`0x400a44e0`) — clear `0x80001904[t + slot·8]`, the MIDI table `0x46c76a26`,
   the record longs `0x46c7e998`/`0x46c769c0` and the slot-mask bits
   `0x46c7fe44`/`0x46c77be2`.
3. **Master-scale lurch** — the landing is quantised to the *outgoing* master's boundary,
   which is mid-step for the incoming scale when the two tick grids do not share it (e.g.
   2x → 1x on an odd 2x step). Designed fix (~120 B, not built): quantise the countdown in
   `dl_arm` to the **lcm** of the two tick grids (1x/2x → every 6 ticks, 1x/¾x → 24, 1x/1½x
   → 12), and when `tps_in ≠ tps_out` derive `new_step` in the incoming scale's tick domain
   instead of carrying the index. Separately, stock's own natural-wrap catch-up re-phases 1x
   tracks under a 2x master with DJ **off** too — that is stock behaviour, not a DJ bug.

Nothing from §6 is to be coded until the AR-exact baseline is confirmed on hardware.
