# MERGE.md — combining every final-scoped mod into one firmware

**Status: DEFERRED (2026-09-21). There is deliberately no combined build.**
`tools/build_merged.py` and `tools/emu_merged.py` have been **withdrawn** — a
single combined image must not be buildable while DIRECT JUMP, RELOAD FROM PROJECT
and the part-change carryover fix are still unfinished, because the obvious way to
produce "the Kyoti firmware" would quietly ship them.

**This document is the reason the tooling could be withdrawn safely.** It is the
authoritative allocation map — cave addresses, the full detour inventory, the shared
`[YES]` handler and its trampoline, the shared-state table — and it is what the
combined build will be reconstructed from when every feature is shippable. Keep it
current: update it whenever a cave address, a detour site, or a shared global
changes, even though nothing builds from it today.

The withdrawn scripts are recoverable from git history (`tools/build_merged.py`,
`tools/emu_merged.py`, last present at the commit that removed them).

---

## When this is revived — the deltas since the tooling was withdrawn

The withdrawn `build_merged.py` composed **seven** mods, and that set is now wrong in
three ways. Do not resurrect it unchanged:

1. **Add trigless-lock auto-remove.** Finished and hardware-confirmed after the merge
   tooling was written, so it was never in it. One 6-byte detour at `0x40038a5c`
   (`moveb %d1,%a0@(0x59,%d2:l) ; addl %d4,%d0`), one cave, 296 B standalone at
   `0x400d7200`. It touches `FUN_40038874` — the LIVE erase worker — which no other
   mod goes near, and shares no global with any of them. Its builder also carries
   `assert_no_branch_into`, which every future detour in this project should be run
   through: it refuses a detour whose displaced bytes contain a branch target.
2. **Drop DIRECT JUMP and RELOAD FROM PROJECT** unless they are finished by then.
   Both are still WIP with real open bugs (DJ resets the playhead to step 1 on a
   manual pattern change; RELOAD2 has fixes that were never reflashed).
3. **The `[YES]` trampoline exists only because those two collide.** If either is
   dropped, `0x4005e4c8` has a single owner and the whole `MERGE=1` chaining
   mechanism — and `patch_reload2.s`'s `.ifdef MERGE` path, and `dj_toggle` being
   reached by chain rather than by its own detour — becomes unnecessary. Do not carry
   that complexity forward without the collision that justifies it.

Also note the cave map below was packed for the seven-mod set. Adding trigless-lock
and removing two large caves (DIRECT JUMP 490 B, RELOAD2 1512 B) changes every address
after the first removal, so re-pack from scratch rather than editing the table by hand.

---

## The seven final-scoped mods (the withdrawn tooling's set — see the deltas above)

Only the *scoped* build of each — not the intermediates (`RELOAD2` not `RELOAD`,
`SIDECHAIN3` not `SIDECHAIN`/`2`, DIRECT JUMP **v3** — see "DIRECT JUMP: use v3").

| Mod | Standalone build | Sources |
|---|---|---|
| Bug-1 MIDI manual-trig fix | `build_trigscale_only.py` | `patch_trigscale.s` |
| Bug-2 pattern-LED "only p-locks → empty" fix | `build_pattern_led.py` | `patch_pattern_led.s` |
| MUTE MODE — now `OT` / `OTFX` / `OTFX-T` / `DT-T` (four values since addendum 14) | `build_mutemode_dt.py` | `patch_softmute.s` + `patch_mutemode.s` (`DT_MODE=1`) |
| DIRECT JUMP — `[PTN]`+`[YES]` | `build_directjump_v3.py` (**v3**) | `patch_directjump.s` (`DJ_V3=1`) |
| SIDE-CHAIN compressor | `build_sidechain3.py` | `patch_sidechain.s` + `patch_sc_dsp3.asm` + `sc_tables.py` |
| RELOAD FROM PROJECT — hold `[PTN]` | `build_reload2.py` | `patch_reload2.s` |
| QUANTIZE LIVE REC — `[REC]` + `[PLAY]`×2 | `build_qlrec.py` | `patch_qlrec.s` |

QUANTIZE LIVE REC is a front-panel shortcut for the PERSONALIZE **QUANTIZE LIVE REC**
row (`0x800000ac`) — no menu surgery, no defsym, two `jmp` detours (`0x40061778`
[PLAY] press, `0x4004883a` [REC] release) and one cave, none of it shared with the
other six. Added to the merge in S48 (needed `FREE_START` lowered).

Combined build: **withdrawn** — see the status note at the top. The per-feature builds
in `BUILD_KYOTI.md` are the only supported way to flash today, one feature at a time.

---

## Verdict

**One real code collision, one mechanical cave clash, everything else composes.**

1. **`[YES]` handler @ `0x4005e4c8`** — DIRECT JUMP *and* RELOAD2 both detour the same
   8 bytes. Resolved by a trampoline (below). *Needs integration + retest.*
2. **Cave base `0x400d7400`** — MUTE MODE, DIRECT JUMP, RELOAD2 each link there.
   Resolved by auto-packing (below). *Mechanical.*
3. Space: **`FREE_START` was lowered to `0x400d6500`** in S48 (Bug-2 then QLREC filled
   the old `0x400d7000` zone). The whole `0x400d64da–0x400d7c3c` span is zero in stock;
   the seven ColdFire caves now occupy `0x400d6500–0x400d70aa` (**~2.6 KB headroom**
   below the pinned `patch_trigscale`).
4. Consequence of (3): `patch_sidechain`'s cave no longer lands at `0x400d7000`, so the
   COMPRESSOR descriptor's per-slot formatter pointers (`E+0x102+4*slot`) differ from
   `build_sidechain3.py`. Their **values** are still asserted against `sc_syms` in
   section 2; the stray-byte check (section 8) exempts those four-byte pointer slots.
5. SIDE-CHAIN is otherwise orthogonal — DSP address space + a descriptor region nothing
   else touches.
6. Bug-2 (`patch_pattern_led`) and QLREC (`patch_qlrec`) each detour only sites nothing
   else touches (`0x4009a464`; `0x40061778` / `0x4004883a`) and share no global with the
   other five.
7. `patch_trigscale` is byte-identical in every build; it is the shared base.

---

## ColdFire cave allocation (as the withdrawn `build_merged.py` packed it)

Free zone `0x400d6500 … 0x400d7c3c` (~5.8 KB). Packed from the bottom;
`patch_trigscale` pinned at `0x400d7b00` so its bytes match `build_trigscale_only.py`,
and the relocated PERSONALIZE menu arrays go after it.

| Cave | Addr | Size | Notes |
|---|---|---|---|
| `patch_sidechain` (CF: `key_fmt` / `kfilt_fmt`) | `0x400d6500` | 140 B | + descriptor & chooser edits outside the zone; descriptor pointers track this addr |
| `patch_softmute` (`DT_MODE=1`) | `0x400d658c` | 368 B | |
| `patch_mutemode` (`DT_MODE=1`) | `0x400d66fc` | 136 B | |
| `patch_directjump` (`DJ_V3=1`) | `0x400d6784` | 490 B | `dj_toggle` reached via chain, not a detour |
| `patch_reload2` (`MERGE=1`) | `0x400d6970` | 1512 B | TRK SEQ / PTN SEQ / PART + PTN SEQ (S47) |
| `patch_pattern_led` | `0x400d6f58` | 142 B | Bug-2 |
| `patch_qlrec` | `0x400d6fe8` | 194 B | QUANTIZE LIVE REC |
| — free — | `0x400d70aa` | ~2.6 KB | to the pin |
| `patch_trigscale` | `0x400d7b00` | 62 B | **pinned** |
| PERSONALIZE menu arrays ×3 (17 entries) | `0x400d7b40` | 204 B | relocated from `0x400b2a34/74/c0`; **placed after trigscale** (S47 -- RELOAD2 grew) |
| — free — | `0x400d7c0c` | 48 B | |

Addresses shift if any cave's size changes — the merged builder re-packed and
re-asserted every run (disjoint, inside the zone, every displaced-byte guard). This
table is therefore a **record of one packing**, not a specification: when the combined
build is rebuilt, re-pack from scratch and let the tool assert the result. Do not
hand-copy these addresses into another tool.

### Outside the free zone (SIDE-CHAIN only, no other mod touches these)

| Region | What |
|---|---|
| `0x400d5ac8–0x400d5ba3` | COMPRESSOR descriptor slots 8–11 (`KEY` / `KFLT` / `KGAIN` / `MON`) |
| `0x400d607e–0x400d61c3` | FX1/FX2 chooser lists + id->position tables (SPATIALIZER pulled). **Two separate id->position tables live here, not one**: `0x400d60d0` is FX1's OWN copy, `0x400d6150` (called `ID2POS` in the build scripts) is FX2's — identical stock values made this easy to miss (Session 55 fixed FX2's copy only; Session 56 found and fixed FX1's). Any future edit to these lists must rebuild BOTH. |
| DSP payload A `0x400e2324+`, B `0x400f59ef+` | SPATIALIZER donor cave + `sctap`/`scdet`/`sctail` hooks + `X:0x215[5]` null-stub. **Separate address space — zero ColdFire interaction.** |

---

## Detour-site inventory

| Site | Mod | Sym | Kind | Displaced (stock) |
|---|---|---|---|---|
| `0x4009b6f2` | Bug-1 | `cave` | jmp+6nop (18) | `move.l #0x91a,d0` … |
| `0x4009a464` | Bug-2 | `cave` | jmp (6) | `move.l d2,-(sp) ; move.l 8(sp),d0` (cave replays both, then either returns 1 or `jmp 0x4009a46a` into the stock body) |
| `0x40061778` | QLREC | `qlr_play` | jmp (6) | `jsr 0x4009b5c0` ([PLAY] press; cave replays it on the stock path, resumes `0x4006177e`) |
| `0x4004883a` | QLREC | `qlr_recrel` | jmp (6) | `clr.l 0x460d1726` ([REC] release; cave replays it, then clears its own counter) |
| `0x40038a5c` | TRIGLESS-LOCK AUTO-REMOVE | `cave` | jsr (6) | `moveb %d1,%a0@(0x59,%d2:l) ; addl %d4,%d0` (cave replays both; fires only when the erased param was really locked and every other param in the row is already `0xFF`) |
| `0x40004dc6` | MUTE MODE | `pre` | jmp (6) | `move.l 0x80000008,d5` |
| `0x40005178` | MUTE MODE | `pre_v` | jmp (8) | `lea -0xc(sp),sp` … |
| `0x400a4006` | DIRECT JUMP | `dj_a` | jsr (6) | `tst.b (0x8000667e).l` |
| `0x400a42fa` | DIRECT JUMP | `dj_b` | jsr (6) | `move.l #0x8e56,d0` |
| `0x400a4840` | DIRECT JUMP | `dj_c` | jsr (8) | `clr.b d0 ; move.b d0,(0x800065b6).l` |
| `0x4005a044` | RELOAD2 | `rl_ptn` | jmp (6) | `move.l 8(sp),d0 ; moveq #1,d1` |
| `0x4005e25c` | RELOAD2 | `rl_no` | jmp (6) | `move.l 8(sp),d0 ; beq.s …` |
| **`0x4005e4c8`** | **RELOAD2** | **`rl_yes`** | **jmp (8)** | `move.l 4(sp),d1 ; move.l 8(sp),d0` |
| `0x4004b970` | RELOAD2 | `rl_arr_a` | jmp (8) | `lea -12(sp),sp ; movem.l d2-d3/a2,(sp)` |
| `0x400491a0` | RELOAD2 | `rl_arr_b` | jmp (6) | `move.l d2,-(sp) ; movea.l 8(sp),a0` |
| `0x40085864` | RELOAD2 | `rl_job` | jmp (8) | `move.l a2,-650(fp) ; move.l 4(a2),-(sp)` |

Non-detour edits: menu ref repoints `0x40068efe/f0a`, `0x40069022/3e/56`; count
`0x40068fb2` (`moveq #15`→`#16`); restore-length `pea 0x64`→`0x70` at `0x4001f322`,
`0x4001f3be`, `0x4001fb24` (MUTE MODE **and** DIRECT JUMP — identical, idempotent).

**Standalone, DIRECT JUMP also detours `0x4005e4c8` (`dj_toggle`).** In the merge it
does **not** — RELOAD2 owns that site and chains.

---

## The `[YES]` trampoline (`0x4005e4c8`)

DIRECT JUMP wants it for the `[PTN]`+`[YES]` toggle; RELOAD2 wants it to answer its
picker. One `jmp` fits. Both source files already anticipate the merge.

**Resolution — RELOAD2 is the outer hook, DIRECT JUMP is chained:**

```
0x4005e4c8  jmp rl_yes
                │
  rl_yes: ──────┤  event==press && G_MENU==1 && !POPUP ?
                │        yes → close picker, run the highlighted item, swallow
                │        no  → jmp dj_toggle            ◄── MERGE=1 only
                │
  dj_toggle: ───┤  event==press && [PTN] held && !arranger && !POPUP ?
                │        yes → toggle DIRECT JUMP, toast, swallow
                │        no  → replay `move.l 4(sp),d1 ; move.l 8(sp),d0`
                │              jmp 0x4005e4d0  (stock YES handler)
```

Implementation: `patch_reload2.s` gained an `.ifdef MERGE` block. Standalone,
`rly_stock` replays the prologue and `jmp`s `YES_RESUME`; under
`--defsym MERGE=1 --defsym MERGE_DJ_TOGGLE=<addr>` it is a single `jmp DJ_TOGGLE`.
`build_merged.py` assembles `patch_directjump` first, reads `dj_toggle`, feeds it in.
`dj_toggle` needs no change for the chain — it behaves identically whether entered from
a detour or from `rl_yes`, because the stack is untouched on that path (`0(sp)`=ret,
`4`=keycode, `8`=event). (`patch_directjump.s`'s only merge-relevant edit is the
separate `DJ_V3` overlay switch.)

`emu_merged.py` drives all six cases on the real merged bytes:

| picker | `[PTN]` | key | → owner |
|---|---|---|---|
| open | — | press | RELOAD2 |
| open | held | press | RELOAD2 (picker wins) |
| closed | held | press | DIRECT JUMP |
| closed | none | press | stock |
| closed | held | release | stock |
| closed | held + popup | press | stock (DJ guard) |

---

## Shared / adjacent state — all compatible

| Concern | MUTE MODE | DIRECT JUMP | RELOAD2 | QLREC | Verdict |
|---|---|---|---|---|---|
| runtime setting word | `0x800000dc` | `0x800000d8` | — | `0x800000ac` (stock — QLREC only flips it) | distinct; `0xac` is in the stock `0x64` restore span already |
| SRAM shadow | `0x100fff6c` | **none (Session 83)** | — | `0x100fff3c` (stock) | DIRECT JUMP no longer persists |
| `pea 0x64→0x70` ×3 | yes | **no (Session 83)** | no | no (`0xac` < `0xd3`, in the stock span) | ⚠️ **see the hazard below** |
| scratch RAM globals | `0x80006c66` | `0x80006a40–44` | `0x80006a50–55` | `0x80006a5c` / `0x80006a60` | disjoint |
| `[PTN]` flags | — | reads `0x460d1742` | detours PTN handler, replays prologue on non-hold | — | stock still sets `0x460d1742`; both set `PTN_USED 0x460d173e` |
| menu surgery | owns it | none | none | none | only MUTE MODE |
| `[REC] held` `0x460d1726` | — | — | — | detours the release path, replays `clr.l` | stock still sets it on press |

### ⚠️ MERGE HAZARD — DIRECT JUMP's power-on default (Session 83)

The user's requirement: **DIRECT JUMP is a performance feature and must come up OFF on every
power-on.** It is never saved, per project or otherwise.

Standalone this is free. `kb/memory-map.md`: `FUN_4000f938` re-images the DSP shared-RAM
window from ROM (`0x401086f4` → `0x80000000`, `0x3e88` B) at every boot, and the ROM seed for
`DJ_MODE` at `0x401087cc` is `00000000` — asserted by `build_directjump_v4.py`. Stock's ANDY
restore is `memcpy(0x80000070, 0x100fff00, 0x64)`, covering `0x80000070..0x800000d3`, so it
does **not** reach `DJ_MODE` at `0x800000d8`. The shadow write and the `0x64→0x70` widening
are both removed, and the stale `1` left in battery SRAM by pre-Session-83 builds is inert.

**But MUTE MODE still needs that widening** — its own word is `0x800000dc`, offset `0x6c`.
A merged build that widens the restore to `0x70` for MUTE MODE will also restore offset
`0x68`, and DIRECT JUMP would start persisting again from a shadow nothing maintains —
i.e. it could come up **ON**, which is exactly what the user does not want.

Before merging the two, do one of:

1. **Move `DJ_MODE` outside `0x80000070..0x800000df`** to another word inside the boot
   re-image span whose ROM seed is zero (verify the seed, the way the build already does).
   Cleanest — keeps the "OFF at power-on" guarantee structural. Note every free word in
   `0x70..0xdf` is inside the widened span, so it must move out of that range entirely.
2. Have the merged build **zero `DJ_MODE` after the restore**, which needs a boot-only hook
   site; all three restore sites are shared with save/validate paths (they recompute the
   checksum then copy), so hooking one would also fire on an ordinary settings write.

Option 1 is preferred. Do not simply re-add the shadow: that reintroduces persistence.

**Gesture split:** quick `[PTN]`+`[YES]` = DIRECT JUMP toggle; `[PTN]` **hold** =
RELOAD picker. Confirm the hold feel on hardware (HW unknown, `FLASHING.md` §4.7).

---

## DIRECT JUMP: use v3

Three overlay builds exist. The pattern-jump behaviour is identical in all three;
only the confirmation toast differs.

| | overlay | hooks | window |
|---|---|---|---|
| v1 | `FUN_40059f8c` — SELECT-BANK/PTN window: text **+ 4 countdown boxes** | 3 (dj_a/b/c) + toggle | borrows the SELECT handle `0x460d1e5c` < 1 s |
| v2 | `FUN_4005a0e0` — dead-code bare text box, **no timeout** | **4** (+ `dj_tick2` @ `0x400522ca`) | own handle `0x460d1e64` — **shared with RELOAD's picker** |
| **v3** | **`FUN_4005a2b8(text, dur)`** — the OS's own self-timing notification ("PART n RELOADED"; ems-octakit `GK_STOCK_NOTIFICATION_SHOW`) | **3** (dj_a/b/c) + toggle | none — self-contained |

The countdown boxes in v1 were never a design choice — they are what `FUN_40059f8c`
paints, and v1 reused that routine as the cheapest timed-text primitive known at the
time. `FUN_4005a2b8` (the right primitive) was only identified during the RELOAD work.
Mnemonically the boxes signal "contemplate and commit" (bank/pattern select) — wrong
for a mode toggle you have already decided on.

**v3 removes every DIRECT JUMP merge friction:** no `0x400522ca` splice (v2's, next to
soft-mute), no borrowed SELECT-window handle (v1's), no `FUN_4005a0e0` / `0x460d1e64`
collision with RELOAD2's picker (v2's). `patch_reload2`'s `rl_yes` uses the identical
call. `DJ_TOAST_DUR` defaults to `0x44` (the dwell RELOAD2 uses), `--defsym`-tunable.

`build_directjump.py` (v1) and `build_directjump_v2.py` are kept for the standalone
line until v3 has a hardware pass; `build_merged.py` takes v3.

---

## Version string — the merged build is `KYOTI_V1.0`

The combined image is the shipping build, so it carries its own branding, **not** the
`140C_KYOTI` used by the per-feature test images. Boot splash and **SYSTEM STATUS → OS
VERSION** must both read **`KYOTI_V1.0`** — exactly 10 chars, which is the ELEK version
field cap, so a revived builder must *error* rather than truncate if it overflows.
Bump on a real release (`KYOTI_V1.1`, …); keep the per-feature builds on
`140C_KYOTI` so a flash log makes it obvious which image is on the unit.

## Build & verify — *what the withdrawn tooling did, and what a revived build must do*

There is no combined build today (see the status note at the top), so nothing here is
runnable. It is recorded because these are the checks the combined image needs, and
re-deriving them from scratch would be expensive.

The builder asserted: cave layout disjoint + inside the zone; every displaced-byte
guard; no two detours at one site; Bug-1 bytes identical to `build_trigscale_only.py`;
every change is one a standalone feature also makes (bar relocated caves / detours /
the four SIDE-CHAIN descriptor pointer slots, which track `patch_sidechain`'s address);
round-trip + checksum through Elektron's tool. The SIDE-CHAIN DSP bytes are
byte-identical to `build_sidechain3.py`.

The emulator pass also asserted the Bug-2 detour (`0x4009a464` → `patch_pattern_led:cave`,
cave ends `jmp 0x4009a46a`) and the two QLREC detours (`0x40061778` / `0x4004883a` →
`patch_qlrec:qlr_play` / `qlr_recrel`). `tools/emu_pattern_led.py --image out/mainos_merged.bin`
re-runs the full Bug-2 case set against the relocated cave in the combined image
(ALL GOOD, S48); QLREC's cave logic is covered by `emu_qlrec.py` on the standalone
(same bytes, re-linked).

The per-feature `emu_*.py` still run against their **standalone** images (they assert
`0x400d7400`-era cave addresses); `emu_merged.py` covers the merge-specific risk only.
The v3 overlay has its own `emu_directjump_v3.py` (toggle → `FUN_4005a2b8`; dj_a/b/c
asserted byte-identical to v1).

---

## Order of operations (when the MKI is back)

1. Flash & sign off each feature standalone, in the `FLASHING.md` / `START_HERE.md`
   order: **DT → SIDECHAIN2 → SIDECHAIN3 → DIRECTJUMP** (+ Bug-2 confirm, QLREC confirm,
   p-lock Phase-0). DIRECT JUMP: flash **v3** (`build_directjump_v3.py`) — that is what
   the merge carries; check the toast reads cleanly and `DJ_TOAST_DUR` feels right.
2. Only then flash `OCTATRACK_KYOTI_ALL.bin` and re-run each feature's HW checklist on
   the combined image, plus: the `[PTN]` gesture split (tap vs hold), MUTE MODE while
   the RELOAD picker is open, a DIRECT JUMP toggle immediately after a RELOAD.

## Open decisions

- **RELOAD `reload` vs `reload2`** (the Session 43/44 open item) — `build_merged.py`
  takes `reload2` (2-item). Swap to `patch_reload.s` if the 3-item picker wins; the
  `MERGE` block must be ported to `patch_reload.s` too (same `rly_stock` edit).
- **Whether the merge ships at all** vs staying a per-feature menu of builds — the
  combined image is the harder thing to support (one HW regression sinks all six).
- **DIRECT JUMP v3 as the standalone default too** — v3 is strictly better than v1/v2
  (right primitive, no extra hook, no shared handle). Once it has a HW pass, consider
  making `build_directjump_v3.py` the DIRECT JUMP line and retiring v1/v2.
