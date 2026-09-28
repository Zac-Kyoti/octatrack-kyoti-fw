# DIRECT JUMP V6 — handoff (Session 106 → next session)

> **Superseded as the entry point (Session 108).** V6.4 is hardware-confirmed and FROZEN as the
> **OT↔AR parity build**. Current work is V7 (clock-locked jumps): start at
> `reference/handoffs/DIRECTJUMP_V7_DESIGN.md` and NOTES Session 108. Everything below is
> still correct about V6's machinery, which V7 reuses unchanged.

Written 2026-09-27 at the end of Session 106, for a fresh session picking this up.
Read this file, then `NOTES.md` Sessions 105–106, then `reference/AR_SEQUENCER_ENGINE.md`
§3 and §6. `reference/handoffs/DIRECTJUMP_PHASE_HANDOFF.md` §0 is the older entry point and
still correct about the architecture; everything about V1–V5 in it is history.

---

## 0. Where the work stands

**The jump itself WORKS on hardware.** V6.1-DIAG flashed 2026-09-27; toast read
**`A8 L8 R8 C0 T1 H0 G0`** (8 cues, 8 arms, 8 landings).

**The LED defect is SOLVED in V6.3 (Session 107) — root-caused, reproduced in the emulator,
fixed, and the fix confirmed in the emulator. AWAITING HARDWARE.** Full account in §2 and
NOTES Session 107 (continued). One line: V6.2 posted the `{0x15, bank}` message, whose
handler has no code path to the byte the LED painter reads; the message that does is
`{0x11, pattern}`, and stock's wrap-change posts it from a *second* template `0x400d816b`
that the Session 106 scan never saw.

**V6.3 hardware 2026-09-27: LED fix CONFIRMED; 16↔7 NORMAL 1x CORRECT** (the one-step
shift reproduces and is the recorded cross-machine characteristic — see
`reference/AR_DJ_QUIRKS.md` item 1, refined with the user's DJ-OFF/PER-TRACK matrix). One
new defect surfaced and was fixed the same session: **DJ ON was not persistent** — a cue
arriving on a master boundary tick computed `LAND_CNTDN = 1`, the ARMED wait could never
serve it (stock's same-tick decrement ran the zero-landing with the stale transport-start
snapshot), Hook N never consumed, and `dj_state` wedged at ARMED — every later cue fell
back to stock wrap cueing. Reproduced and cured in-emulator with `tools/diag_dj_wedge.py`
(cues by master-tick phase; V6.3 = 2/4 landings, wedged; V6.4 = 4/4, clean). **V6.4** =
one change in `dl_arm`: countdown == 1 → `bsr dl_commit` (a boundary-tick request lands
that tick, AR's own rule). NOTES Session 107 continued (3).

Current build = **V6.4**, `tools/build_directjump_v6.py` (WIP tier, needs `KYOTI_ALLOW_WIP=1`):

| artifact | sha256 (first 16) |
|---|---|
| `out/mainos_directjump_v6.bin` (+ `OCTATRACK_OS1.40C_DIRECTJUMP_V6.syx` / `.bin`) | `4a6c1b5e3fb8562c` |
| `out/mainos_directjump_v6diag.bin` (`140C_KDIAG`, `*_V6DIAG*`) | `1ba196a674c74d0a` |

Cave 848 B; 792 B vs stock; 0 bytes outside caves + declared sites. AWAITING HARDWARE
(persistence re-test: many switches, rapid/rhythmic cadences included).

**All four gates pass** (§3): DJ-OFF identical, DJ-ON-idle identical, the 16↔7 NORMAL-mode
oracle byte-for-byte the V6/V6.1/V6.2 result, and the new LED trace showing `0x100b14d0`
updating at the landing. `build_bugbuilds.py --with-wip` composes DISJOINT / ALL PRESERVED /
NO STRAYS.

**What the user should do next:** flash V6.3, DJ on via `[PTN]`+`[YES]`, and check the
switched-to pattern's LED turns **red at the landing** rather than at the outgoing pattern's
end. Then §6's order. Note the author's Session 107 restatement of AR quirk 1: the 16-vs-7
symptom is a **whole one-step shift against the master pulse**, not fractional timing, and it
is the **stretch goal** — if the OT reproduces it, that is the AR-exact baseline, not a
regression.

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

## 2. The LED defect — SOLVED (Session 107), mechanism measured end to end

**Status: root-caused, fixed in V6.3, emulator-confirmed, awaiting hardware.**

### 2.1 The predicate (unchanged from Session 106, re-verified)

`FUN_4007afe8` @ `0x4007b182` paints "cued" (yellow) while
`PEND_PAT (0x800065c0) != [0x100b14d0]` and `PEND_BANK == [0x80000002]`.

### 2.2 What `0x100b14d0` actually is

`0x100b14d0` is the **project-RAM twin of `0x80000004`, the UI's "current pattern"**
(`0x80000002` twins `0x100b14ce`, the current bank). An opcode-filtered image scan — match
only absolute-long *destination* encodings, not the 484 bare 4-byte occurrences — gives it
exactly **four** writers, and the two that matter write the pair together.

The UI task's message dispatcher is **`FUN_40061a94`** (4618 B, **no callers** = a task
entry point, callees spanning every UI subsystem). It switches on **`msg[0] − 1`**:

| case | message | what it does to the pair |
|---|---|---|
| `'\x10'` | **`0x11`** | `0x100b14d0 = 0x80000004 = msg[1]`; refresh part index `0x100b14cf`; full repaint battery incl. `FUN_400418e0` (`0x400620ec`–`0x4006211a`). **If `msg[2] == 0` it ALSO calls `FUN_4009c550()`.** |
| `'\x14'` | **`0x15`** | writes **only** the bank pair (`0x80000002` / `0x100b14ce`), and early-outs when the bank is unchanged; falls through to a repaint. **Cannot reach `0x100b14d0` on any path.** |

**That is why V6.2 failed**: it posted `{0x15, bank}`, whose handler has no path to the
pattern byte. Not (as guessed in Session 106) because the handler early-outed on an
unchanged bank.

### 2.3 The experiment (handoff §2.3 as written, run — `tools/diag_led_pend.py`)

Per-tick sampling of `PEND_PAT / PEND_BANK / ACT_PAT / ACT_BANK / 0x100b14d0 / 0x80000002`,
plus a write hook over the whole neighbourhood (so base-register writes cannot hide) and a
hook on the kernel post `FUN_40000c3c` logging every message body. DJTEST2, pattern 3↔4.

**Stock, DJ off, cue at t40, commits at its natural wrap t90:**

```
t90  W ACT_PAT  <- 4                    pc=0x400a44d0     the wrap swap
t90  POST 0x400d8167  body=15 00 14     ret=0x400a4568    {0x15, bank}
t90  POST 0x400d816b  body=11 04 01     ret=0x400a4b9a    {0x11, pattern}
t90  W 0x100b14d0 <- 4                  pc=0x4006210e     handler case 0x10  -> LED goes red
t90  W 0x100b14cf <- 0                  pc=0x40062148     part-index refresh
```

**V6.2, DJ on, landings at t41 and t143:** the `{0x15}` post **only**; `0x100b14d0` stays `3`
for the entire run. The reported hardware defect, reproduced in the emulator.

**Why no static scan had found it:** stock's wrap-change posts `{0x11}` from a **second
template, `0x400d816b`** — not the `0x400d8164` that §2.3 named. A scan for references to
`0x400d8164` therefore finds the UI/arranger/reset posters and misses the wrap-change
entirely, which is exactly what made the wrap-change look like the one `ACT_PAT` writer that
does not announce itself. Both templates live in the little table at `0x400d8160`.

### 2.4 The fix (V6.3)

`dl_commit` now ends with **stock's wrap-change pair of posts, in stock's order**:

```
move.b ACT_BANK,%d0 ; move.b %d0,0x400d8168 ; pea 0x400d8167 ; pea UI_QUEUE ; jsr KPOST
move.b ACT_PAT ,%d0 ; move.b %d0,0x400d816c ; pea 0x400d816b ; pea UI_QUEUE ; jsr KPOST
```

Order is load-bearing: case `0x10`'s part-index refresh indexes the bank base pointer
`0x46c82456`, which is what case `0x14` rewrites when the bank changes — so a bank-changing
jump must land `{0x15}` before `{0x11}`.

**Template choice is load-bearing too.** There are two `{0x11}` templates, differing in the
byte the handler branches on:

| template | bytes | arg byte | posted by | side effect |
|---|---|---|---|---|
| `0x400d8164` | `{0x11, arg, 0x00}` | `0x400d8165` | `FUN_400a0570`, `candidate_400a10d2`, the ISR reset path `0x400a40fc` | **also calls `FUN_4009c550()`** |
| `0x400d816b` | `{0x11, arg, 0x01}` | `0x400d816c` | **stock's wrap-change `0x400a4b9a`** | none |

`FUN_4009c550` re-applies the **tempo** (`0x80001814`/`0x80001818`, from the pattern's own
`+0x8e58` field when per-pattern tempo is enabled). A jump is a wrap-change analogue, not a
UI pattern-set, so V6.3 uses `0x400d816b` and leaves the tempo alone. The first V6.3 build
used `0x400d8164` and would have re-applied tempo on every landing — an unasked-for
deviation from stock; caught by reading the trace's message bytes, not the address alone.

The kernel post from the tick ISR remains stock-legal (§5) — this is the same call, the same
queue and the same two messages stock itself posts from this ISR.

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
