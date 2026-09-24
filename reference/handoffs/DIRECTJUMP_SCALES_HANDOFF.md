# DIRECT JUMP — handoff: non-1x TRACK and MASTER scales

Written at the end of Session 87. Read this before touching DIRECT JUMP again.

---

## 1. What is already working — DO NOT REGRESS THIS

Flashed and **hardware-confirmed on the MKI**, image `0657157f...`, commit `16df386`:

- Tracks and patterns **stay in master time** through DIRECT JUMP switches.
- Patterns **land on the correct step** between switches.
- **Different track LENGTHS work well together** (7, 12, 16 in one pattern).
- **MASTER LENGTH is respected**, including **`INF`**.
- No doubled trigs, no crash, no drift.

**Every one of those results was obtained with 1x track scales and a 1x master scale.**

This baseline cost seven sessions and four hardware flashes, two of which were regressions
(a full lockup in Session 86, doubled trigs in Session 87). Treat it as load-bearing. Any
change for non-1x must keep the 1x path byte-identical in behaviour, and the cheapest way to
prove that is to re-run the 1x fixtures below before proposing a flash.

## 2. The problem to solve

Setting **any track scale, or the master scale, to anything other than 1x** produces
unexpected results. The user has not yet characterised the symptom in detail beyond that —
**ask for a precise description before building anything** (which scale, which tracks, what
it sounds like, whether it is wrong immediately or drifts).

## 3. Current architecture — what each hook does

| hook | site | what it does |
|---|---|---|
| `dj_toggle` | `[PTN]`+`[YES]` keymap slot `0x400bf0c0` | flips `DJ_MODE` (`0x800000d8`). No persistence — power-on default is OFF, guaranteed by stock's boot re-image, asserted at build time |
| Hook A `dj_a` | `0x400a4006` | every clock tick. Arms only (`G_ARMED`); never forces the grid. Clears `G_ARMED` and `G_JUST_COMMITTED` on its disarm path |
| Hook B `dj_b` | `0x400a42fa` | when armed, bypasses the CHAIN-AFTER gate and sets `D6 = 1` |
| Hook D `dj_scaleix_fix` | `0x400a4220` | ungated; recomputes master `SCALE_IX` from live `ACT_PAT`/`ACT_BANK`, branching on `SCALE_MODE` |
| Hook C `dj_c` | `0x400a4840` | armed only: corrects master `SCALE_IX`, refreshes **`TRK_SCALE_IX[0..15]`** (`0x8000663e`) from the incoming pattern, sets `G_JUST_COMMITTED` |
| Hook H `dj_d7` | `0x400a47f6` | armed only: `0x80006628 = 0x800065b2 mod newMasterLen` — AR's `new_step` (AR `0x40099274`) |
| Hook P `dj_pertrack` | `0x400a4d36` | gated on `DJ_MODE` **and** `G_JUST_COMMITTED`: writes **`STEP_ARR[i] = new_step mod trackLen_i`** for all 16, **and nothing else** (AR `0x400992be`) |

## 4. The standing hypothesis for why non-1x breaks

OT's stock rebuild loop computes per-track position in the **TICK domain**:

```
0x400a4912   q     = ceil(D7 / tps_t)        D7 = LEN_TBL[masterScale] * 0x80006628
0x400a4976   pos_t = q mod len_t
```

Hook P overrides the result with AR's **step domain** `new_step mod trackLen_t`.

**At 1x everywhere the two agree exactly.** That is almost certainly why 1x works and nothing
else does — it is the one case where the port's disagreement with stock is invisible.

When any scale is non-1x they diverge, and **Hook P only overrides `STEP_ARR`**. Everything
else stock derived from its own tick-domain answer is left in place and is now inconsistent
with the position it sits next to:

- **`CNTDN_TBL[t]`** (`0x800065c3`) — written by stock's rebuild at `0x400a49c6`
- **`NEXT_STEP[t]`** (`0x800065e4`) — the quotient array, also the source stock's tail uses to
  seed `STEP_ARR` at `0x400a4be6` (which Hook P then overwrites)

That inconsistency is the prime suspect.

## 5. Why AR does not have this problem — and what to go read

**AR's commit rebuilds the per-track RATE state, not just the position.** The OT port
currently rebuilds the position (Hook P) and the resolution cache (`dj_c`) but **not** the
countdown reload.

Go back to the real AR code. Source of truth, already extracted in this repo's sibling:

- **`~/Documents/ar-kyoti-fw/out/fun4009905c_listing.txt`** — the full commit function
- `~/Documents/ar-kyoti-fw/MECHANISM.md` and `reference/AR_DIRECT_JUMP.md` (§2 inventory,
  §4 mapping, §7c the arithmetic spec, §8 methodology hazards)

The regions that matter for scales specifically:

| AR address range | what it does |
|---|---|
| `0x400991de`–`0x40099202` | **loop 1** — per-track countdown reloads: `*(0x405667c7 + t) = ticksPerStep[*(track + 0x2c7)] - 1`. **This is the per-track RATE state.** |
| `0x40099222`–`0x40099248` | the non-per-track branch: `0x405666e6 = ticksPerStep[patternRes] - 1`, then fills `0x405667c7[]` with that value for every track |
| `0x40099204`–`0x4009921a` | master: `0x405666e6 = ticksPerStep[pattern-wide res] - 1` |
| `0x400992e2`–`0x40099314` | resolution-cache loop: `0x40566774` = master resolution index, then `0x40566775[t]` per track from `*(track + 0x2c7)` |
| `0x4009927c`–`0x400992d2` | **loop 2** — position: `pos_t = new_step mod trackLen_t`. Note it divides by LENGTH only; resolution never enters the position |

**The question to answer from that code:** AR separates *position* (loop 2, step domain, no
resolution) from *rate* (loop 1 + the resolution cache). OT's port currently ports the
position and the resolution cache. **What is OT's true analogue of AR's `0x405667c7[t]`
countdown reload, and does the commit need to write it?**

### The single most load-bearing unverified claim in this thread

Session 85 deliberately did **not** write OT's `CNTDN_TBL` (`0x800065c3[t]`), on the strength
of a **Session 79** measurement describing it as a *one-shot trig arm*
(`0xff` idle → `1` at commit → `0` → fires → `0xff`) rather than a per-step reload. §4's
mapping table nevertheless pairs it with AR's `0x405667c7[t]`.

**Both cannot be right.** If `CNTDN_TBL` really is OT's per-track rate reload, then not
writing it is very likely exactly why non-1x breaks. **Re-derive this first**, before writing
any code. It is cheap to check statically: find every writer and reader of `0x800065c3`, and
watch its values per tick for a track at 2x versus 1x.

And note the hard-won rule from Session 87, which this thread violated twice:

> **Before copying any AR per-track write onto its OT counterpart, measure OT's own writers
> and readers of that array first.** Role-equivalence in the mapping table is not semantic
> equivalence. `PREV_ARR` and `CNTDN_TBL` both looked portable and were not.

## 6. Also still open, and probably entangled with this

**Per-track sub-step phase at a mid-cycle commit** (open since Session 82). Stock's tail
zeroes ticks-within-step `0x800064f0[i]` for all 16 at `0x400a4bf0`. At a natural pattern
boundary that is correct. At a DIRECT JUMP commit mid-cycle, a track whose ticks-per-step
differs from the master's may be mid-step — a 1/2x track (tps 12) under master tps 6 is at
tick 6 of 12 on every other master step — and zeroing it restarts that track's step early.

**This only bites when a track's tps differs from the master's, i.e. exactly the non-1x
case.** It may well be the same bug. AR's loop 2 writes `clr.b (A4)+` (its
`0x4056672d[t] = 0`), so AR does zero its equivalent — which is another reason to establish
what OT's arrays actually mean rather than reasoning from the mapping.

## 7. Fixtures and tools

Real hardware-exported project `~/Desktop/DJTEST2`, bank 0:

| pattern (index) | shape | use |
|---|---|---|
| 0, 1 | uniform `SCALE_MODE=0`, all tracks len 16; **p0 = 1x, p1 = 2x** | the master-scale pair |
| 6, 7 (A07/A08) | `SCALE_MODE=1`, len `[16,16,12,7,16,16,16,16]`, scale idx `[2,0,2,2,4,2,2,2]`; A07 master 1x, A08 master 2x | per-track scales **and** master scale |

Note A07 and A08 have **identical per-track scales**, so they cannot expose a stale
per-track scale cache — that is what let the Session 84 bug hide. **Still missing: a fixture
with two patterns of differing MASTER LENGTH.** Ask the user to export one.

| tool | what it proves |
|---|---|
| `diff_stock_vs_patch.py` | DJ-OFF inertness vs stock. **Poisons `0x80006a40..0x80006a60` with `0xAA` by default** — Unicorn zero-fills, so without this an uninitialised-global bug is invisible. `--dj-on` = feature on, no switch, must still be inert |
| `diag_resume_pos.py` | per-track landing positions vs AR's rule, computed independently in Python |
| `diag_grid_lock.py` | timing: whole-step gaps, one rate change at the commit, playhead `+1` per boundary |
| `diag_trigfire.py` | every call to the trig-fire routine with track, call site, tick. `--dj-on-tick N` flips `DJ_MODE` mid-playback |
| `diag_trkscale.py` | is the live per-track scale cache stale after a commit |
| `diag_playhead.py` | is `0x800065b2` a bounded playhead |
| `diag_tick_domain.py` | tick-vs-step domain of the sequencer body |
| `scan_dj_project_lengths.py` | per-track LEN/SCALE of every pattern in a project |

## 8. Methodology rules this thread paid for

1. **Never snapshot at a detour site.** A Unicorn code hook at address X fires *before* X
   executes, so hooking your own hook's `jsr` measures the state before it ran. Snapshot at
   the return address. (Cost: a false 15/16 FAIL in S85, and a false PASS in cont.29.)
2. **Poison uninitialised scratch before any inertness gate.** Unicorn zero-fills; hardware
   does not. Globals at `0x80006a40+` are outside stock's boot re-image (`0x3e88` bytes from
   `0x401086f4`) and its zero-fill (to `0x80004000`), so they are garbage at power-on. Gate
   on something inside the re-image (`DJ_MODE`), or clear it every tick, or recompute.
   (Cost: a full hardware lockup that the gate called IDENTICAL.)
3. **A gate that cannot fail proves nothing.** Build the failing control. Every claim in
   Sessions 82–87 that survived did so because a control reproduced the bug first.
4. **Name the uncovered case *and build the fixture*.** S83 wrote "per-track scale
   differences: NOT covered" and moved on; hardware found it in one test.
5. **AR↔OT array mapping is by role, not semantics.** See §5.
