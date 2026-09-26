# MERGE.md — combining every final-scoped mod into one firmware

**Status: READY TO BUILD, in two stages (re-scanned 2026-09-23, Session 86; both WIP
mods' state and measured sizes refreshed 2026-09-24 at commit `91f2f15`, Session 88).**
There is still deliberately no combined build on disk — `tools/build_merged.py` and
`tools/emu_merged.py` remain withdrawn (recoverable from `068fbb5^`). This document is
the authoritative allocation map they will be reconstructed from: cave addresses, the
full detour inventory, the shared-state table, and the two blockers that are left.

Keep it current: update it whenever a cave address, a detour site, or a shared global
changes, even though nothing builds from it today.

**The headline of the 2026-09-23 re-scan:** the merge got *substantially simpler* than
the version of this document written at S48/S83, and *only* because DIRECT JUMP and
RELOAD both moved off the sites that used to collide.

- **The `[YES]` handler collision at `0x4005e4c8` is gone.** DIRECT JUMP **v4** reaches
  its toggle through the `[PTN]`-held keymap overlay (`0x400bf0c0`), not a detour, and
  **RELOAD3** deleted the picker entirely in favour of direct chords. Neither touches
  `0x4005e4c8` any more. **The `[YES]` trampoline, the `MERGE=1` chaining mechanism and
  `patch_reload2.s`'s `.ifdef MERGE` block are all obsolete — do not carry them forward.**
- **Every one of the 27 detour sites across all nine mods is distinct, with zero byte
  overlap** (verified numerically against stock; closest non-sibling pair is 27 B apart).
- **The seven finished mods have no real conflict at all** — only mechanical repacking.
  Both remaining blockers are DIRECT-JUMP-vs-someone-else, and both are *builder
  assertion* conflicts rather than byte conflicts.

---

## Stage the merge: `KYOTI_V1.0` now, `KYOTI_V1.1` when DJ and RELOAD land

The user's own framing — "everything is complete except direct jump and reload" — is
also the right build boundary, because it is exactly the cut that removes both blockers.

| | contents | conflicts to resolve | headroom |
|---|---|---|---|
| **`KYOTI_V1.0`** | the **seven finished, hardware-confirmed mods** | **none** — mechanical repack only | 3196 B (53 %) |
| **`KYOTI_V1.1`** | + DIRECT JUMP v4 + RELOAD3 | blockers **B1** and **B2** below | **≈ 64 B (1 %)** — derived, see the update below |

Build V1.0 first and flash it. It is a genuinely conflict-free composition of work that
is already signed off on hardware, it is the thing that can ship, and it de-risks V1.1 by
proving the repacked builder before the two hard cases are added.

---

## The seven finished mods (the `KYOTI_V1.0` set)

Only the *scoped* build of each — not the intermediates. Sizes below are **measured**, by
running each builder on 2026-09-23; several are far larger than the numbers this document
used to carry (`patch_softmute` 368 B → **970 B**, `patch_qlrec` 194 B → **358 B**, since cut to **176 B**).

| Mod | Standalone build | Sources | cave | HW |
|---|---|---|---|---|
| Bug-1 MIDI manual-trig fix | `build_trigscale_only.py` | `patch_trigscale.s` | 62 B | confirmed |
| Bug-2 pattern-LED "only p-locks → empty" | `build_pattern_led.py` | `patch_pattern_led.s` | 142 B | confirmed |
| MUTE MODE — `OT` / `OTFX` / `OTFX-T` / `DT-T` | `build_mutemode_dt.py` | `patch_softmute.s` + `patch_mutemode.s` (`DT_MODE=1`) | 970 + 208 + 204 B | confirmed |
| SIDE-CHAIN compressor (cross-core) | `build_sidechain3.py` | `patch_sidechain.s` + `patch_sc_dsp3.asm` + `sc_tables.py` | 134 B (+ DSP) | confirmed |
| QUANTIZE LIVE REC — `[REC]` + `[PLAY]`, toast-gated | `build_qlrec.py` | `patch_qlrec.s` | **176 B** | confirmed working 2026-09-25 |
| TRIGLESS-LOCK AUTO-REMOVE | `build_triglock.py` | `patch_triglock.s` | 296 B | confirmed |
| Part-change carryover (PARTREAPPLY) | `build_partreapply.py` | `patch_partreapply.s` | 402 B | confirmed |

Two of these were finished *after* the merge tooling was withdrawn and have never been in
any combined build: **TRIGLESS-LOCK AUTO-REMOVE** and **PARTREAPPLY**. The withdrawn
`build_merged.py` composed seven mods, but not the same seven — it carried DIRECT JUMP
and RELOAD2 and lacked these two. **Do not resurrect its mod table.**

### Audit of the finished set against the 2026-09-24 KB ingest

*Asked and answered 2026-09-24: does the new external research change the approach to any
finished build, and does anything need revisiting? **Verdict: no mod needs to be rebuilt or
reflashed.** Two get a sharper root-cause statement, two were positively validated by
independent evidence, and one merge blocker is unchanged. Every check below was run against
our own image or by assembling the shipping build — not inferred from an upstream's label.*

| Mod | New evidence bearing on it | Verdict |
|---|---|---|
| Bug-1 MIDI manual-trig | none | **no change** |
| Bug-2 pattern-LED | stock's predicate `FUN_4009a464` skips exactly `+0x10..0x17`, the trigless-lock mask | **no change; root cause sharpens** — see below |
| MUTE MODE | its hooks sit inside the frame ISR (level 5); PIT0 is level 1 | **validated** — the MACSR race it feared is impossible; see below |
| SIDE-CHAIN | `fx1_disallowed_effects` = DELAY, PLATE, SPRING, DARK (HW-confirmed upstream) | **no change**, but note it below |
| QUANTIZE LIVE REC | `0x4009b5c0` is `bank_reload_gate_read` and the gate is **wider than a byte** | **no change** — we only replay the `jsr`; see below |
| TRIGLESS-LOCK AUTO-REMOVE | p-lock store `0x4004f5f8`, step-record parameter map | **no change** |
| PARTREAPPLY | the part-apply family: `0x40009094` is the only variant that restarts the audio engine | **validated — our design was right for reasons we did not have at the time** |

**PARTREAPPLY — validated, and the reasoning is now evidenced.** The patch calls
`FUN_40009094(bank, part)` **only when the transport is stopped** (`0x800065b8 == 0`), and
documents its convention as "2 long stack args, bank closest to jsr". Both are now
independently confirmed: our own disassembly of all three part-apply siblings gives
`(bank, part)` (and shows octemu's `apply_part(part, pattern)` label is wrong), and octalab
measured `0x40029a4c(src,part) → 0x40009094(bank,part)` on a MKI. More importantly, the new
finding explains *why* the transport gate matters: `0x40009094` is the **only** variant that
republishes tempo (`0x80001814/18/1c`, `0x80001824` — the recorder doc's own tempo chain),
**re-arms the audio eDMA TCD0/TCD1 chain**, re-unmasks INTC0, and posts a kernel queue
message. Calling that mid-playback would re-arm the audio DMA under a running sequencer. The
patch's own comment called this "avoid racing whatever jump-avoidance property its timing
has" — a hunch that is now a mechanism. **Keep the gate.**
⚠️ One documentation-only correction: the patch's header comment attributes the playing-case
catch-up to "`FUN_4000c8a4`", which **is not a function boundary** (it points inside the frame
ISR, at an operand). The *premise* is right — the frame ISR does re-stage machine params and
scene data per frame (`0x4000cae8` copier, `scene_morph_frame 0x4000c202`,
`scene_level_morph 0x4000cc60`) — only the label is wrong. No code change.

**MUTE MODE — the MACSR hazard it was built around cannot happen.** `kb/memory-map.md` long
carried an unresolved worry that adding cycles to the level chain could let a PIT0 tick
preempt a `MACSR=0x60` window and corrupt EMAC results. Settled 2026-09-24: every level-chain
site is inside the DSP frame ISR (`0x4000aad0..0x4000d9b0`), which runs at **interrupt level
5** (`ICR1 = 5` at `0x4001fc30`) and masks its own source at entry; **PIT0 runs at level 1**
(`ICR43 = 1` at `0x400005e2`). Level 1 cannot preempt level 5. octemu independently places
`patch_softmute`'s own `0x4000d49e` site "inside frame_isr". **The only things that can
interrupt it are the two level-6 sources** (MIDI IN `0x400106ec`, serial link `0x400109bc`) —
so if the hardware silence regression ever returns, *that* is the surface to examine, not the
scheduler. No change to the build; a real reduction in its risk surface.

**Bug-2 pattern-LED — fix unchanged, root cause sharpened.** Verified the stock predicate by
disassembly: per audio track it ORs `+0x00,+0x04,+0x08,+0x0c` then `+0x18,+0x1c,+0x20,+0x24,
+0x28,+0x2c,+0x30,+0x34`, and MIDI `MTRA-8,-4,+0,+4`. It therefore **skips precisely
`+0x10..0x17`** — the 64-bit mask octabam reads as the *trigless-lock* mask
(`tools/hw/ot_bank.py`, "exactly the locked steps without a trig"). So stock does not merely
"ignore p-locks": it omits the one mask that records the content in question.
A **cheaper fix exists** — OR in `+0x10`/`+0x14` instead of scanning 16 × 0x800 B of lock
array. **Deliberately not adopted:** (a) nordseele lowered that mask's label to 🟡 on
22 Sep 2026 while octabam holds ✅, and our fix reads the lock arrays themselves, so it is
correct *whichever way that dispute lands*; (b) the reported bug was MIDI-track p-locks and
the MIDI side's scan covers only 16 bytes — whether MIDI has an equivalent mask is unmapped;
(c) the current fix is hardware-confirmed. Record the alternative, keep the ground truth.

**QUANTIZE LIVE REC — no bug, and the detour site is corroborated.** octemu warns that
`bank_reload_gate` (`0x46c77bf6`) is wider than a byte and must be tested as a full word.
`patch_qlrec` never interprets it: it treats `jsr 0x4009b5c0` purely as the **displaced
instruction** to replay before `jmp 0x4006177e`, where stock's own `tst.l %d0` reads the full
32-bit return. octemu independently confirms `0x4009b5c0` is the gate accessor that
`play_button` (`0x40061778`) calls first — exactly the patch's own reading of its detour site.

**SIDE-CHAIN — no change, one thing to know.** It pulls SPRING REVERB to donate DSP space.
Upstream now records `fx1_disallowed_effects` = **DELAY, PLATE, SPRING, DARK**, "confirmed on
real hardware" — i.e. SPRING was never selectable as FX1 anyway, which is mild independent
support for it being the cheapest donor. No action.

**`0x800000d4` — checked, and it does not affect any shipped mod.** Assembled
`patch_softmute` exactly as `build_mutemode_dt.py` does (`DT_MODE=1`): **970 B with no
reference to `0x800000d4` or `0xd5`**; only the diagnostic `OTFX_PROBE=1` build (986 B)
contains them. The `0x800000d4` mentions in `patch_mutemode.s` are **comments** about the
restore-span widening; its state word is `0x800000dc`. The B1 merge blocker below
(`DJ_MODE` at `0x800000d8` riding the widened restore) is **unchanged and still open** — it
was never about `0xd4`.

**Cave collisions with other projects — for combined images only.** Our `KYOTI_V1.0`
allocation (`0x400d64dc`–`0x400d7c3a`) lies entirely inside the "classic cave", which is
good (it is the only region with a hardware record) and also means we overlap **octalab's
`LAB_MENU`** (`0x400d64e0..0x400d6671`, inside our `patch_sidechain` + `patch_softmute`),
**octabam's list cave** (`0x400d6b00`, inside our `patch_partreapply`), and **standalone
1.40MIDISC** (`0x400d6500..0x400d7c48`, nearly all of ours). **No action for our own builds** —
this only rules out naively merging an image with those projects. → `kb/caves.md` §2.

### The two WIP mods (the `KYOTI_V1.1` delta)

| Mod | Build | cave | state |
|---|---|---|---|
| DIRECT JUMP — `[PTN]`+`[YES]` | `build_directjump_v4.py` (**v4**, not v3) | **1026 B** | **HW-confirmed at 1x** (Session 87). Non-1x root-caused and fixed Session 88, bit-identical to the confirmed build at 1x, **unflashed**. One unexplained report still open (visited steps vs trigs present; LEDs vs audio) |
| RELOAD FROM PROJECT — direct chords | `build_reload3.py` (**v3**, not v2) | **2104 B** | **FINAL — HW-confirmed 2026-09-25.** Grew from 1870 B: two-line block toasts, the live self-verify, the playing-bank fix, and the request bytes moved into the cave |

**`build_directjump_v3.py` is superseded.** This document used to say "DIRECT JUMP: use
v3". That is wrong now: v1–v3 were dead on hardware and v4 is the line. v4 is not a
retoast of v3 — it has **7** ColdFire detours (v3 had 3), reaches its toggle by keymap
slot instead of by detouring `0x4005e4c8`, and leaves the ANDY restore stock.

Likewise **`build_reload2.py` / `patch_reload2.s` are superseded by RELOAD3**, which
deletes the modal picker. The old "RELOAD `reload` vs `reload2`" open decision is closed
by that redesign; so is the `MERGE`/`rly_stock` port it implied.

---

## ColdFire cave allocation — the proposed packing

Free zone **`0x400d64da … 0x400d7c3c` = 5986 B**, verified as one contiguous zero run in
`out/raw/section_3_MAIN_OS.bin` (2026-09-23). Packed ascending from `0x400d64dc` on a
4-byte alignment, with `patch_trigscale` **pinned at `0x400d7bfc`** (the top of the zone,
where `build_reload3.py` already puts it) so it lands at the *same address in both V1.0
and V1.1* and the free span stays contiguous below it.

### `KYOTI_V1.0`

| Cave | Addr | Size |
|---|---|---|
| `patch_sidechain` | `0x400d64dc` | 134 B |
| `patch_softmute` (`DT_MODE=1`) | `0x400d6564` | 970 B |
| `patch_mutemode` (`DT_MODE=1`) | `0x400d6930` | 208 B |
| PERSONALIZE array — labels (17×4) | `0x400d6a00` | 68 B |
| PERSONALIZE array — getters (17×4) | `0x400d6a44` | 68 B |
| PERSONALIZE array — setters (17×4) | `0x400d6a88` | 68 B |
| `patch_partreapply` | `0x400d6acc` | 402 B |
| `patch_pattern_led` | `0x400d6c60` | 142 B |
| `patch_qlrec` | `0x400d6cf0` | **176 B** (was 358 B before the Sessions 94-96 rewrite; the freed 182 B is not reflected in the rows below) |
| `patch_triglock` | `0x400d6e58` | 296 B |
| — free — | `0x400d6f80` | **3196 B** |
| `patch_trigscale` | `0x400d7bfc` | 62 B **pinned** |
| — tail — | `0x400d7c3a` | 2 B |

### `KYOTI_V1.1` — identical up to `patch_triglock`, then

| Cave | Addr | Size |
|---|---|---|
| `patch_directjump` (`DJ_V3=1,DJ_KEYMAP=1`) | `0x400d6f80` | 1026 B |
| `patch_reload3` | `0x400d7384` | **2104 B** (final; was 1870 B) |
| — free — | `0x400d7bbc` | **64 B** (derived) |
| `patch_trigscale` | `0x400d7bfc` | 62 B **pinned** |

**Update 2026-09-25 — RELOAD3 is final at 2104 B (+234 B vs the 1870 B above), so V1.1's free run is ≈ 64 B (298 − 234). This is derived arithmetic, not a builder run: the merged builder is withdrawn. RELOAD3 alone into V1.0 fits with ≈ 1092 B to spare (3196 − 2104), also derived.** ⚠️ **5 % headroom, and shrinking fast.** Both WIP mods move every session, and the
trend is the wrong way: at `18824ad` this table read 1020 + 1500 = 676 B free; five
commits later, at `91f2f15`, it reads 1026 + 1870 = **298 B**. RELOAD3 alone took 370 B
in one session (the titled message card, Session 88). At this rate V1.1 overflows the
zone before both features are finished, so **treat the second zone as likely, not
contingent**, and re-measure before every pack — these are the numbers a builder run
printed at **commit `91f2f15`**, not estimates. They are the *committed* sizes: an
in-progress working tree can differ, so measure the tree you intend to pack from.
If V1.1 overflows, the next-largest stock zero runs are **`0x400d24d0` (2064 B)** and
`0x400d2ee6` (314 B) — usable, but a second zone means the builder must pack multiple
spans, so treat it as a real change, not a one-line bump.

This table is a **record of one packing, not a specification.** The revived builder must
re-pack from scratch every run and assert the result (disjoint, inside the zone, every
displaced-byte guard). Do not hand-copy these addresses into another tool.

### Outside the free zone (SIDE-CHAIN only)

| Region | What |
|---|---|
| `0x400d5ac8–0x400d5ba3` | COMPRESSOR descriptor slots 8–11 (`KEY` / `KFLT` / `KGAIN` / `MON`) + enable bitmap `0x400d5c0c` |
| `0x400d607e–0x400d61c3` | **FX2** chooser list + its id→position table (SPRING REVERB pulled, 15→14 entries) |
| DSP payload A `P:0x01252`, B `P:0x01012` | 388-word cave in the SPRING REVERB donor + `sctap`/`scdet`/`moncommit` hooks + `X:0x215[0x15]` null-stub. **Separate address space — zero ColdFire interaction.** |

**Correction to the old text:** it said SPATIALIZER is pulled and that *both* FX1 and FX2
id→position tables must be rebuilt. Neither is true of `build_sidechain3.py` as it stands
— SPATIALIZER is back as a normal selectable effect, **SPRING REVERB** is what gets
pulled, and the builder prints `FX1_LIST/FX1_ID2POS untouched`. Only FX2's copy is edited.

**Descriptor pointers track the cave base.** Three of the COMPRESSOR descriptor's
formatter pointers point *into* `patch_sidechain`'s cave (slot 8 A = base, slot 8 B =
base+0x72, slot 9 A = base+0x36); the rest point at stock code. Relocating the cave
changes those three values, so they differ from `build_sidechain3.py`'s output by design —
assert them against `sc_syms`, and exempt them from the stray-byte check.

---

## Detour-site inventory — 27 sites, all distinct, zero overlap

Verified numerically on 2026-09-23 against stock. Sorted by address.

| Site | Mod | Sym | Kind | Notes |
|---|---|---|---|---|
| `0x40004c72` | MUTE MODE | `trigflag` | jmp (6) | |
| `0x40004dc6` | MUTE MODE | `pre` | jmp (6) | |
| `0x40006820` | MUTE MODE | `fresh_bind` | jmp (8) | |
| `0x40006844` | MUTE MODE | `mt_trig` | jmp (6) | |
| `0x4000d498` | MUTE MODE | `dt_trig` | jmp (6) | |
| `0x4000f4dc` | MUTE MODE | `mt_rebind` | jmp (8) | |
| `0x40023c62` | RELOAD3 | `rl_done` | jmp (6) | |
| `0x40038a5c` | TRIGLESS-LOCK | `cave` | jsr (6) | fires only when the erased param was really locked |
| `0x40040250` | RELOAD3 | `rl3_bank_trk` | jmp (6) | |
| `0x40043418` | DIRECT JUMP | `dj_ptnrel` | jmp (6) | `[PTN]` release |
| `0x4004883a` | QLREC | `qlr_recrel` | jmp (6) | `[REC]` release |
| `0x40061778` | QLREC | `qlr_play` | jmp (6) | `[PLAY]` press |
| `0x400621da` | PARTREAPPLY | head | jsr (6) | dirty-flag snapshot |
| `0x40062216` | PARTREAPPLY | tail | jsr (6) | 54 B after the head; same function, same owner |
| `0x4007af42` | RELOAD3 | `rl3_bank_show` | jmp (6) | |
| `0x4007b3e0` | RELOAD3 | `rl3_bank_rel` | jmp (8) | |
| `0x40083dc4` | RELOAD3 | `rl3_ptn_trk` | jmp (6) | the `[PTN]`-overlay TRACK handler — detoured, *not* slot-poked |
| `0x40085864` | RELOAD3 | `rl_job` | jmp (8) | |
| `0x4009a464` | Bug-2 | `cave` | jmp (6) | |
| `0x4009b6f2` | Bug-1 | `cave` | jmp+6nop (18) | byte-identical in every build; the shared base |
| `0x400a4006` | DIRECT JUMP | `dj_a` | jsr (6) | |
| `0x400a4220` | DIRECT JUMP | `dj_scaleix_fix` | jsr (6) | v4 only |
| `0x400a42fa` | DIRECT JUMP | `dj_b` | jsr (6) | |
| `0x400a47f6` | DIRECT JUMP | `dj_d7` | jsr (6) | v4 only |
| `0x400a4840` | DIRECT JUMP | `dj_c` | jsr (8) | |
| `0x400a4d36` | DIRECT JUMP | `dj_pertrack` | jsr (6) | v4 only |

**Removed since the last revision of this document:** MUTE MODE's `pre_v` @ `0x40005178`;
RELOAD2's five sites (`0x4005a044`, `0x4005e25c`, `0x4005e4c8`, `0x4004b970`, `0x400491a0`)
— RELOAD3 keeps only `0x40085864`; DIRECT JUMP's `0x4005e4c8` toggle detour.

### Non-detour edits

| Edit | Owner | Notes |
|---|---|---|
| PERSONALIZE menu ref repoints `0x40068efe`, `0x40068f0a`, `0x40069022`, `0x4006903e`, `0x40069056` | MUTE MODE | to the three relocated arrays |
| PERSONALIZE count `0x40068fb2` (`moveq #15` → `#16`) | MUTE MODE | MUTE MODE spliced at row index 2 |
| Restore length `pea 0x64` → `0x70` at `0x4001f322`, `0x4001f3be`, `0x4001fb24` | **MUTE MODE only** | ⚠️ **blocker B1** — DIRECT JUMP v4 now *requires these stay stock* |
| `[PTN]`-overlay keymap YES record `0x400bf0c0` (press NULL → `dj_toggle`) | DIRECT JUMP v4 | ⚠️ **blocker B2** — RELOAD3 asserts the overlay is byte-for-byte stock |
| COMPRESSOR descriptor + FX2 chooser + DSP payloads | SIDE-CHAIN | see the table above |

Only MUTE MODE does menu surgery. Only SIDE-CHAIN touches the FX chooser or the DSP.
QLREC flips the stock PERSONALIZE word `0x800000ac` but calls its getter/setter by
address (`0x40068ce0` / `0x40068ca0`) and never indexes the arrays — and it is row 0,
ahead of MUTE MODE's splice point, so the insertion cannot shift it.

---

## The two blockers — both DIRECT JUMP vs. someone else, both V1.1-only

### B1 — DIRECT JUMP's power-on default vs MUTE MODE's restore widening

The user's requirement: **DIRECT JUMP is a performance feature and must come up OFF on
every power-on.** It is never saved, per project or otherwise.

`build_directjump_v4.py` guarantees that structurally, and *asserts* it: it checks all
three restore sites are still `pea 0x64` and exits if not
(`"the ANDY restore must stay stock so it never reaches DJ_MODE"`), then verifies the boot
ROM seed at `0x401087cc` is `00000000` so `FUN_4000f938`'s re-image zeroes `DJ_MODE`
(`0x800000d8`) every boot. Both facts re-verified against true stock on 2026-09-23.

`build_mutemode_dt.py` widens all three to `pea 0x70`, because its own `GATE` word is
`0x800000dc` (offset `0x6c`) and that is how MUTE MODE persists.

Stock restore covers `0x80000070..0x800000d3`; widened it covers `..0x800000df`, which
now includes `DJ_MODE` at `0x800000d8` (offset `0x68`). A merged build would restore
`DJ_MODE` from battery SRAM `0x100fff68` — a word nothing maintains, which pre-Session-83
builds may have left a stale `1` in. **DIRECT JUMP could come up ON.** The two builders'
assertions are directly contradictory, so this fails loudly rather than silently — good.

**Resolution — move `DJ_MODE` out of `0x80000070..0x800000df` entirely** (option 1 of the
two the old text listed; the alternative needs a boot-only hook site, and all three
restore sites are shared with save/validate paths that recompute the checksum, so hooking
one would also fire on an ordinary settings write). Requirements for the new home: inside
the `0x3e88`-byte boot re-image span, ROM seed zero, and unused by stock.

A scan of true stock offers **`0x800000f8`** as the leading candidate — zero ROM seed, and
no absolute-long reference anywhere in the image. ⚠️ **Not yet proven free.** An
absolute-long scan cannot see base-register-plus-displacement access, and `0x800000f0`
and `0x800000f4` *are* referenced (3× and 7×), so `0xf8` may well be a field of a struct
based just below it. Confirm with an emulator read/write watchpoint over a stock boot and
a few minutes of ordinary operation before adopting it. `0x80000114`–`0x80000138` and
`0x80000144`–`0x80000184` are further candidates from the same scan, under the same caveat
(and `0x80000110` is referenced 93× — almost certainly a struct base, so treat its
neighbourhood as occupied until proven otherwise).

Do **not** simply re-add the SRAM shadow: that reintroduces persistence, which is the
thing the user does not want.

*Note:* `patch_softmute`'s `PROBE_LO`/`PROBE_HI` (`0x800000d4`/`d5`) are also inside the
widened span, and `0x800000d4` **is** referenced once in stock. They are gated behind
`OTFX_PROBE`, which the shipping `build_mutemode_dt.py` does not define, so this is not a
merge problem — but do not let that defsym into a merged build.

### B2 — DIRECT JUMP's keymap slot vs RELOAD3's overlay assertion

Both features now live on the `[PTN]`-held keymap overlay, and they arrived there by
opposite routes:

- **DIRECT JUMP v4 writes** the overlay's YES record (`0x400bf0c0`, all-NULL in stock) so
  `[PTN]`+`[YES]` reaches `dj_toggle`.
- **RELOAD3 deliberately stopped writing overlay records.** `build_reload3.py`'s own
  comment says earlier builds poked the `[PTN]` overlay and *"that mechanism caused the
  DIRECT JUMP slot collision"*; it now detours ordinary key handlers instead and
  **asserts every overlay record is untouched**, plus that all 8 `[PTN]`-overlay TRACK
  slots still point at `0x40083dc4`.

So RELOAD3's assertion will fire against any image carrying DJ v4's slot poke. This is an
**assertion conflict, not a byte conflict** — they want different records, and RELOAD3
only actually depends on the 8 TRACK slots.

**Resolution:** make the merged builder the single owner of the overlay table. Narrow
RELOAD3's assertion from "every record is stock" to "every record I depend on is stock,
and every record written was written by exactly one mod", and have the merged builder
assert one-owner-per-record across the whole table. Keep the strict form in the
standalone `build_reload3.py`.

**Gesture split to confirm on hardware:** `[PTN]`+`[YES]` = DIRECT JUMP toggle;
`[PTN]`+`[TRACK n]` = RELOAD track n; `[BANK]`+`[TRACK n]` = reload + Part. All three are
`[PTN]`/`[BANK]`-held chords sharing one modifier protocol.

---

## Shared / adjacent state — all compatible, two to re-test

| Concern | MUTE MODE | SIDE-CHAIN | QLREC | TRIGLOCK | PARTREAPPLY | DIRECT JUMP | RELOAD3 | Verdict |
|---|---|---|---|---|---|---|---|---|
| PERSONALIZE word | `0x800000dc` | — | `0x800000ac` (stock) | — | — | `0x800000d8` | — | ⚠️ **B1** |
| SRAM shadow | `0x100fff6c` | — | `0x100fff3c` (stock) | — | — | **none** | — | disjoint |
| `pea 0x64→0x70` ×3 | **yes** | no | no (`0xac` already in span) | no | no | **must stay stock** | no | ⚠️ **B1** |
| private scratch | `0x80006c66` | — | **none** — own handle-gated since Sessions 94-96 | — | — | `0x80006a40–0x80006a4a` | **none** — own cave since Session 98 | **disjoint** |
| keymap overlay | — | — | — | — | — | writes YES `0x400bf0c0` | asserts stock | ⚠️ **B2** |
| menu surgery | owns it | — | — | — | — | — | — | single owner |
| FX chooser / DSP | — | owns it | — | — | — | — | — | single owner |
| `PTN_USED 0x460d173e` | — | — | — | — | — | sets | sets | same flag, same meaning — re-test combined |
| `ACT_PAT 0x800065be` | — | — | — | — | — | **writes** | reads | ⚠️ re-test: RELOAD during a DJ-pending change |
| `RUNNING/TRANSPORT 0x800065b8` | — | — | — | — | reads | reads | reads | read-only, fine |
| `CUR_BANK 0x80000002` | — | — | — | — | reads | — | reads | read-only, fine |
| `ARR_ACT 0x460d1aec` | — | — | — | — | — | reads | reads | arranger guard, fine |

**The scratch block: QLREC and RELOAD3 have both LEFT it.** DJ `0x6a40–4a` is the only
user left; `0x6a50–55` (RELOAD3) and `0x6a5c–73` (QLREC) are released.

Both gave theirs up for the same reason, found the same way — a diagnostic build that
reported the value on screen, after static analysis and the emulator had both said fine:

* **QLREC, Sessions 94-96.** `0x80006a60` read back as *not* the value just written, on the
  very next key press, while persisting indefinitely in the emulator.
* **RELOAD3, Session 98.** The request bytes at `0x80006a54-55` were overwritten between the
  key chord and the storage job that read them, so the reload hit the wrong (MIDI) track and
  its own verify passed on that slice.

**Neither feature keeps any state in this block now**, and the rule earned twice is that a
static "no references" scan cannot tell you whether RAM is written at runtime — and neither
can route A, while it does not run the DSP/audio path.

⚠️ **Two problems with this block, not one.**
1. It is **beyond the boot zero-fill** (`FUN_4000f938` zeroes only to `0x80004000`), so
   every word is garbage at power-on — the DIRECT JUMP lockup of Session 87.
2. **It is not reliably ours at runtime.** It sits in the DSP shared-RAM window, and
   under live audio a word there was clobbered between two key presses. A static scan
   finds **0 references** into `0x80006a00..0x80006ac0` — and that scan was clean while
   the RAM was being overwritten. See `kb/caves.md`.

**DJ and RELOAD3 still keep state here and are untested against (2).** DIRECT JUMP
re-arms its flag every gesture and clears it every tick, so a clobber would be invisible
rather than absent. Not claimed broken — flagged. The safe pattern, proven on hardware by
QLREC, is **keep no private state: read what the OS already maintains.** **Any new mod
must claim scratch from a fresh region, not by guessing a gap here.**

**Two adjacency notes, neither a conflict:**

- `patch_softmute`'s `REL_STATE` (`0x8000184a`) and `patch_partreapply`'s `KILLBIT`
  (`0x8000184c`) are two bytes apart in the same stock voice-state region. Both are
  accessed strictly as **bytes** (`move.b`) by both mods — verified — so there is no
  overlap. But soft-mute force-mutes voices and PARTREAPPLY kills/re-triggers them, so
  *"change Part while a track is soft-muted in OTFX/DT mode"* is a runtime case to test on
  the combined image.
- QLREC's `qlr_tick` (`0x400522ca`) sits inside `FUN_40052200` — the per-control-frame
  handler that also decrements the **soft-mute release counter**. No byte conflict (MUTE
  MODE detours none of that function), but MUTE MODE and QLREC now share a frame handler.
  ✅ **RESOLVED, Session 93: QLREC no longer touches that frame handler at all.** Its
  `0x400522ca` detour was deleted after it crashed hardware — the hook reaches the kernel
  post `FUN_40000c3c` (task wake + ready-list poke) from the engine frame context. MUTE
  MODE now has `FUN_40052200` to itself, and there is no QLREC/MUTE-MODE adjacency case
  left to test. ⚠️ **General rule from that crash: `0x400522ca` is not a safe site for any
  UI- or kernel-facing call.** Current DIRECT JUMP (v4/v5) does not splice it; only the
  dead v2 does.

---

## Version string — `KYOTI_V1.0`

The combined image is the shipping build, so it carries its own branding, **not** the
`140C_KYOTI` the per-feature test images use. Boot splash and **SYSTEM STATUS → OS
VERSION** must both read **`KYOTI_V1.0`** — exactly 10 chars, which is the ELEK version
field cap, so the builder must **error rather than truncate** if it overflows.

Note the finished builders are not uniform today: `build_pattern_led.py`,
`build_triglock.py` and `build_partreapply.py` hardcode `VERSTR = "1.40C"` (deliberately
stock-transparent, since each is a pure bug fix); the other four default to
`140C_KYOTI`. The merged builder overrides all of them. Keep the per-feature builds as
they are, so a flash log makes it obvious which image is on the unit.

---

## What a revived builder must do

Recover `tools/build_merged.py` (456 lines) and `tools/emu_merged.py` from `068fbb5^` as a
**skeleton only** — the mod table, the cave packing and the `[YES]` trampoline are all
wrong now.

The builder must assert, as the withdrawn one did: cave layout disjoint and inside the
zone; every displaced-byte guard; no two detours at one site; Bug-1 bytes identical to
`build_trigscale_only.py` (modulo relocation); every change is one a standalone feature
also makes, barring relocated caves, detours and the three SIDE-CHAIN descriptor pointers
that track `patch_sidechain`'s address; round-trip + checksum through Elektron's tool;
SIDE-CHAIN DSP bytes byte-identical to `build_sidechain3.py`. Plus, new:

1. **Run every detour through `assert_no_branch_into`.** `build_triglock.py` is currently
   the *only* builder that has it — it refuses a detour whose displaced bytes contain a
   branch target, which is exactly the mistake that sank triglock's first attempt
   (`0x40038af8`, whose neighbour is branched to from two places). Promote it to a shared
   helper and run all 27 sites through it.
2. **Emit a symbol map** (`out/merged_syms.json`: every cave symbol → address) so the
   emulator harnesses can find relocated entry points instead of hardcoding them.
3. **Assert one-owner-per-keymap-record** across the overlay table (B2).
4. **Assert the restore-width / `DJ_MODE` invariant** explicitly rather than letting two
   builders disagree (B1).

### Emulator re-validation — the largest single chunk of work

The per-feature `emu_*.py` mostly cannot be pointed at a merged image today. Two classes:

- **Full-firmware harnesses** (boot a real image, drive real dispatch) — the majority,
  including `emu_dt.py`, `emu_solo.py`, `emu_triglock.py`, `emu_reload.py`, the five
  `emu_artl_*.py` and the thirteen `emu_mute_dynamic*.py`. These hardcode a
  `mainos_<feature>.bin` path. **Retrofit is a one-line `--image` passthrough** — their
  attach path already takes a path, and because they drive real dispatch, cave relocation
  does not matter to them. `emu_pattern_led.py` and `emu_partswitch.py` already do this
  and are the pattern to copy.
- **Cave-unit harnesses** with a hardcoded load address — `emu_qlrec.py`,
  `emu_directjump{,_v2,_v3}.py` (`LOAD = 0x400d7400`) and `emu_mutemode.py`
  (`AT = 0x400d7700`, already stale vs the current `0x400d7800`). These need the symbol
  map from (2), not just a path.
- `emu_sc_dsp3.py`'s `CAVE_ORG = 0x1012` is a **DSP** address and is unaffected by
  ColdFire repacking.

`emu_merged.py`'s old job — driving the six `[YES]` ownership cases — no longer exists.
Its replacement should cover the merge-specific risks that *do*: the `[PTN]`/`[BANK]`
chord split, `PTN_USED` handover between DJ and RELOAD3, RELOAD during a DJ-pending
pattern change, Part change during a soft-mute tail, and QLREC's tick sharing
`FUN_40052200` with soft-mute.

---

## Order of operations (when the MKI is free)

1. **Build and flash `KYOTI_V1.0`** — the seven finished mods. Re-run each feature's HW
   checklist on the combined image (they are all individually signed off, so this is a
   regression pass, not a discovery pass), plus the two adjacency cases above:
   and a Part change during a soft-mute tail.
   ✅ **QLREC is no longer a blocker** — hardware-confirmed working 2026-09-25 after the
   rewrite (cave 176 B, two key-handler detours, zero scratch). ⚠️ But **do not ship the
   pre-Session-93 QLREC**: the `0x400522ca` tick hook crash was latent in the Session 51
   build this document once treated as finished. Any composite must be rebuilt from the
   current `build_qlrec.py`. The QLREC/MUTE-MODE frame-handler adjacency case is gone
   (above) — QLREC no longer touches `FUN_40052200` at all.
2. Finish DIRECT JUMP (**flash the Session 88 non-1x fix** — the 1x behaviour is already
   HW-confirmed and is the baseline not to regress; one report is still unexplained) and
   flash it **standalone** first — `build_directjump_v4.py`, not v3. RELOAD3 is finished
   (final, hardware-confirmed 2026-09-25) and no longer gates the merge.
   Note `reference/handoffs/DIRECTJUMP_SCALES_HANDOFF.md` is now **stale**: its section 5
   `CNTDN_TBL` question was answered in Session 88 (`max(1, tps_master + 1 - tps_t)`), and
   its section 4 pairing with AR's `0x405667c7` is wrong.
3. Resolve **B1** (relocate `DJ_MODE`, with the watchpoint proof) and **B2** (scope
   RELOAD3's overlay assertion; merged builder owns the table).
4. **Build and flash `KYOTI_V1.1`**, and test the gesture split: `[PTN]`+`[YES]` vs
   `[PTN]`+`[TRACK n]` vs `[BANK]`+`[TRACK n]`; a DIRECT JUMP toggle immediately after a
   RELOAD; MUTE MODE changes while a reload is in flight.

## Open decisions

- **Whether the merge ships at all** vs staying a per-feature menu of builds — the
  combined image is the harder thing to support (one HW regression sinks all seven).
  Staging V1.0/V1.1 reduces but does not remove this.
- **Whether V1.1 should carry both features or just RELOAD3.** DIRECT JUMP owns both
  blockers; RELOAD3 is now finished and flashed and would merge into V1.0 with no
  conflict at all (≈ 1092 B to spare, derived). If DIRECT JUMP stays unfinished, ship
  RELOAD3 as V1.1 and hold DIRECT JUMP for V1.2.
- **Retiring the superseded builders.** `build_directjump{,_v2,_v3}.py`,
  `build_reload{,2}.py`, `build_mutemode{,_new}.py`, `build_sidechain{,2}.py` and
  `build_softmute.py` are all superseded by a later scoped build. Keeping them is
  cheap, but the merged builder must never be pointed at one — the mod table above is
  the authority on which build of each mod is the merge's.
