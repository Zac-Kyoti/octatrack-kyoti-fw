# Code caves in OS 1.40C — the ecosystem ledger, and the test a region must pass

*Distilled 2026-09-24. Every address is in OS 1.40C, MAIN OS
`section_3_MAIN_OS.bin` sha256 `164f3122…`, 1,112,560 B, load base `0x40000400`
(VA = file offset + base) — the same image octabam, octalab, midisc, octemu and
ems-octakit all cite, verified locally this session with `shasum -a 256`.*

This file exists because cave choice is the one decision in this project that
can **brick a unit into a MIDI-only recovery**, and because five other projects
are now cutting code into the same few kilobytes of the same image. Read it
before picking an address for a new hook.

---

## 0. ⛔ The parameter-page descriptor table is live data — zeros included (2026-10-06)

**Never place code or data in `0x400d2e52..0x400d5f00`** unless the entry it lands in is
proven unreachable in that image.

**The table.** One table describes every parameter page: 31 entries × 402 (`0x192`) bytes,
`0x400d2e52..0x400d5f00`.
- Pages are reached as `P = entry + 0x38`, through:
  - the getter `0x40031da4` / `0x40031ee0`;
  - the machine table `0x400d5f38[mtype]`;
  - FX1 `0x400d5f58[id]`, FX2 `0x400d5fdc[id]`.
- From `P`, stock reads arrays indexed by slot:
  - min `P+0x6a`, count `P+0x9a`;
  - formatters `P+0xca`, widgets `P+0xfa`;
  - per-encoder step handlers `P+0x12a`;
  - `P+0x15a`;
  - the enable nibbles `P+0x18a`/`P+0x18e`.
- **A zero entry means "the default"**:
  - a zero widget draws a plain dial;
  - a zero step handler falls back to `0x4003240c`;
  - zero nibbles mean the slot is off.

So the table's zero runs are not free space.
source: `refs/octabam` → octabam `docs/firmware/PARAM_PAGES.md` §1–3b, `docs/contributing/PLACEMENT.md`
("`0x400d2ee6..0x400d3020` refused at placement by the build, 25 Sep 2026: a live descriptor")
@ `36a056c5` · fetched 2026-10-06 (read from `~/Documents/octabam`; `refs/octabam` not advanced, see
`UPSTREAM_INBOX.md`) · confidence **C**: confirmed on our image by disassembly, an emulator read census
(`tools/load_audit/ot_emu_load_audit.patch`, `OT_RW`) and two reproduced crashes.

**Readers measured on our image (S125):**
- the page renderer `0x4004e4c6..`;
- the FX1/FX2 encoder handlers `0x4003ac50` / `0x4003aa48`. They `jsr` the step handler at
  `P+0x12a+4·(enc+6)` unconditionally.
- Eight routines read the enable words: `0x40032712`, `0x4003780e`, `0x400378a4`,
  `0x40037baa`, `0x40037c40`, `0x4004e56c`, `0x4004e5a4`, `0x40055032`, plus `0x4003c074` /
  `0x4003cdda` / `0x4003ce68`.

**All five midisc pads lie inside this table**, so the earlier "trimmed pads" entry in §2b
is ❌ retracted:

| pad | entry (`P`) | page | what happens when something is placed there |
|---|---|---|---|
| CAVE2 `0x400d2ee6..` | `0x400d2e8a` | MASTER track PLAYBACK / LFO (T8, `0x80000034` set) | KYOTI V1.0: draw → `jsr 0xd6000000` (**crash**, emulator) |
| SEAM `0x400d46e2..` | `0x400d4618` | the FX **NONE** page (every unused FX id) | KYOTI V1.0: encoder A → `jsr 0x460d1726` (**crash**); **midisc 2.0: → `jsr 0x13c1400d` (crash)**, emulator |
| RELOAD_CAVE `0x400d359c..` | `0x400d34d2` | NEIGHBOR PLAYBACK | KYOTI V1.0 set the enable nibbles, so rows read code as descriptors (latent); midisc 2.0 left them zero (not read) |
| SCENE_PASTE `0x400d3da2..` | `0x400d3cac` | a page used with the sample-slot arena (probably the audio editor's ATTRIBUTES) | widget/step tables overlaid; untested |
| FILT_PERSIST_LOAD `0x400d347e..` | `0x400d3340` | THRU PLAYBACK | step slots 6–11 and `+0x15a`, plus the first 5 bytes of the enable words; not read in exercised paths |

**What is safe.**
- octabam: no ROM module in the table (its free list is `0x400c45b0`, `0x400d24d0`,
  `0x400d64da..`); overflow goes to DRAM. Its `midi-scenes` port links every midisc unit into
  DRAM and is "immune (measured)".
- Our standalone images, Bugbuilds and OBKYOTI6–12: stock bytes in all five pads.
- **KYOTI V1.0, which used them, was withdrawn on 2026-10-06** (`reference/handoffs/KYOTI_LOAD_AUDIT.md` §8/8b).

**One exception, with its condition.** The SPRING reclaim (`0x400d575e..0x400d58f0`, placed
from `0x400d5760`) is SPRING's own record. It is safe only while that image leaves SPRING unreachable (no
`0x400d5fdc`/`0x400d5f58` entry and no `id2e` pointing at it); `build_kyoti.py` asserts that.

**A record is the 0x192 bytes from `P`, not from `E`.** `P = E + 0x38` is what `id2e` holds and
what every reader indexes from, so a record's encoder-handler pointers (`P+0x15a`) and enable
nibbles (`P+0x18a`/`P+0x18e`) lie *past* `E + 0x192`, in the bytes that look like the next
entry's head. KYOTI V1.0 and V1.2 reclaimed SPRING as `0x400d5728..0x400d58b8` (from `E`) and
so overwrote PLATE REV's last 0x38 bytes. On hardware (V1.2, 2026-10-10), the PLATE page showed only TIME,
LP and an unnamed 0/1 slot 10, exactly what the clobbered nibbles decode to, and its knobs did
nothing. V1.1 placed nothing there and was clean. Fixed in V1.3: bounds from `id2e[0x15]`
(asserted), and every changed table byte outside the reclaimed record must be one a standalone
build changes (the pointer scan cannot see indexed readers).

---

## 1. The free-space scan — and why it is only half a test

> source: `refs/octalab/docs/CAVES.md` @ `e0dc56d` · fetched 2026-09-24.
> confidence: **C** for the ranges and ref counts (static scan of the image),
> **C** for the two hardware verdicts.

Runs of zero in the loaded image, with a count of every 32-bit value anywhere in
the image that points into them:

| range | size | static refs | verdict |
|---|---:|---:|---|
| `0x401087e4 .. 0x4010c315` | 15,153 B | **0** | ⛔ **NOT USABLE — live at runtime.** Hardware-proven. |
| `0x4010cdd1 .. 0x4010fdf0` | 12,319 B | **0** | ⛔ **NOT USABLE** — same region class, same verdict until a canary says otherwise. |
| `0x400d64da .. 0x400d7c3c` | 5,986 B | 2 | ⚠️ the "classic cave" — **contested and effectively full**; see §2. **This is where our builds live — from `0x400d6500` only** (§2b). |
| `0x400d24d0 .. 0x400d2ce0` | 2,064 B | 1 | ⚠️ contested — octabam's `modules/menushortcut` pins 300 B here; our KB calls it `SAFE_CAVE` (midisc's). |
| `0x4010c350 .. 0x4010c57e` | 558 B | 2 | ❓ **unclaimed** — but it sits between the two proven-live tail runs, so treat it as live until a canary clears it. |

**⛔ The tail of the image is not free space.** This is the single most expensive
lesson available here, and octalab paid it on hardware so we do not have to:

> A build put a 405-byte menu table at `0x401087e4` and repointed a descriptor
> at it. On the unit, opening that menu raised **`VEC:03` (address error) at
> `0x40064abc`** — a `jsr (a0)` where `a0` is read from the table at record
> `+0x0C`. Every record written there had `0` in that field, and a null is
> explicitly skipped two instructions earlier — *so the value read back was not
> the value written.* The region is live at runtime.
>
> The cost was not the failed feature: the patched menu was the screen that
> contains **OS UPGRADE**, so the unit could only be recovered over MIDI —
> about an hour of SysEx.

**The inference rule, stated exactly:** *no static references* means nothing is
**known** to point at a region — **not** that nothing writes to it. A pointer
computed at runtime leaves no immediate in the image. Only a canary run settles
it.

This also retires a tempting idea: `0x4010fdf0` is **the end of the image**, and
that is where ems-octakit's `BOOTSTRAP_LOAD` (`runtime/link.ld`) puts its
appended runtime. Leaving the tail unclaimed keeps the append-a-runtime route
open instead of forcing a migration later — see
[`octakit-abi.md`](octakit-abi.md) and §5 below.

## 2. Who owns the classic cave — and the fact that it is full

> source: `refs/octalab/docs/CAVES.md` @ `e0dc56d` · fetched 2026-09-24. confidence: **C**.

`0x400d64da .. 0x400d7c3c` (5,986 B) is the only region in the image with a
**hardware record** — octamax has shipped from it for months. It is therefore
also the most contested:

| claimant | range |
|---|---|
| octamax | all of its features |
| octabam | `0x400d6b00` (its list cave) |
| standalone 1.40MIDISC | `0x400d6500 .. 0x400d7c48` |
| octalab `LAB_MENU` | `0x400d64e0 .. 0x400d6671` (402 B, pure data, HW-confirmed 7 Sep 2026) |
| octalab build v22 | `0x400d64e0 .. 0x400d7bf5` — **69 B left** |
| **this project** | `CODE2 0x400D6500..0x6600`, `STUB 0x400D7600..0x7C48`, `FREE_START` lowered to `0x400d6500` (S48) |

**Two consequences for us, stated plainly:**

1. **An image combining octamax and octabam is already impossible** — their
   claims overlap. Ours overlap both. Any "combine with another project" plan
   must start from this table, not from a fresh scan.
2. **Our V1.1 headroom (~5 %) is headroom inside the most contested region in
   the ecosystem.** When it runs out, the answer is the append-a-runtime route
   (§5), not a new cave in the tail (§1).

octalab's own reasoning for staying in the contested cave is worth adopting:
*"Contested and proven beats spacious and untested."*

**Regions known unsafe for CODE specifically** (they hold data tables, not zero
pads — a stock pointer table or a runtime path reaches into them):

| addr | why |
|---|---|
| `0x400C4302` (`CLEAR_CAVE`) | a stock pointer table at `0x400ba8fa` refs into it. midisc puts only filter-UI **data** there, never logic. |
| `0x400C1153` (`SPARSE_CKPT_CAVE`) | inside a data table, not a real zero pad; an earlier midisc revision put code there and **bricked on Part Reload**. |
| `0x400C14D5` | **new 2026-09-24** — midisc 8.2's `memory_map.py` adds this to the same "never ba8 pads" warning alongside `C1153`. |
| `0x400EC8BC`, `0x400E6E5B` | **new 2026-09-24** — midisc 8.2: "table zero-gaps", not pads. Never place code. |
| above `0x400d8000` | the OS `.bss` tail is not free — the cave ceiling (octabam `FAILURE_MODES.md`, already in [`techniques.md`](techniques.md)). |

> source for the three new rows: `refs/midisc/tools/midisc/memory_map.py` @
> `63ca127` ("Persist trampolines — D-region pads only (VOICE/RELOAD class).
> Never ba8 pads (C1153/C14D5) or table zero-gaps (EC8BC/E6E5B)") · fetched
> 2026-09-24. confidence: **C** (midisc ships from these; the exclusions are its
> own hardware experience).

**Newly-published safe D-region pads** (midisc 8.2 uses these for its persist
trampolines — "D-region pads only, VOICE/RELOAD class"):

| range | size |
|---|---:|
| `0x400D347E .. 0x400D34CF` | 81 B |
| `0x400D352D .. 0x400D356F` | 66 B |

These are *outside* the contested classic cave — worth knowing when a patch
needs a small, independent landing pad rather than more of `0x400d6xxx`.

## 2b. Measured on our own image, 2026-09-29 (the KYOTI V1.0 build) — confidence **C**

**The first 38 B of the classic cave are a runtime table, not free space.** `0x400d64ca` is
the base of an array of 24-byte records: `0x4000176c` walks it (`tst.l (a0); lea 24(a0)`)
for the first record whose first long is 0, and `0x40001732`/`0x4000174e` write fields
`+0x10`/`+0x14` of record `d2` (`0x400d64da` + 24·d2). Stock's first record is already
empty, so records are appended at runtime, and the long at `0x400d64e2` is the terminator
while there is one. An emulator boot + project load + 1500 sequencer frames wrote nothing
there, so the writer is on some other path — but every flashed build (and midisc's `CODE2`)
starts at **`0x400d6500`**, which is where ours start. ⚠️ `build_bugbuilds.py` used to prefer
`0x400d64dc` for PARTREAPPLY (fixed the same day; those composites were never flashed).

**❌ RETRACTED 2026-10-06, see §0: these pads are live descriptor-table data, not free.**
The original text is kept below for provenance. **midisc's shipping pads, trimmed**
(ranges that stock references at the END — the pad ends where the referenced word starts): CAVE2 `0x400d2ee6..0x400d301c` (not `..3020`),
RELOAD_CAVE `0x400d359c..0x400d3664` (not `..3668`), SEAM_CAVE `0x400d46e2..0x400d47aa` (not
`..47ad`). They are zero tails of 402-byte parameter-page records at `0x400d301c + k·0x192`.
FILT_PERSIST_SAVE (`0x400d352d..`) is read by stock (`0x4000578e` reads `0x400d3530`) — not
used. The byte-aligned reference scan found these; a 2-aligned scan does not.

**Reclaim — stock data made unreachable by our own edits.** In an image that removes SPRING
REVERB (SIDE-CHAIN, REPITCH) its CF descriptor record `0x400d575e..0x400d58f0` (`P..P+0x192`; see §0) has no reference
left; in an image with MUTE MODE the three stock PERSONALIZE arrays (`0x400b2a34`,
`0x400b2a74`, `0x400b2ac0`, 16 longs each) have none either. `build_kyoti.py` uses both and
asserts the no-reference property on every build. This is only as good as a static scan
plus the emulator's read watches (none seen) — the first flash is the canary.

## 3. The canary test — the gate before anything ships in a new region

> source: `refs/octalab/docs/CAVES.md` @ `e0dc56d` · fetched 2026-09-24. confidence: **C** (this is the protocol that produced the §1 verdict).

A region is accepted only after this, **on hardware**:

1. Fill the candidate range with a recognisable pattern — `0xA5` bytes, or a
   32-bit counter so a *partial* overwrite is visible.
2. Flash, then **use the unit normally for a full session**: load a project,
   record, change patterns, save, power cycle, load again.
3. Dump the range back and compare byte for byte.

*Survives untouched* → the region is real; record the run with the date and what
was exercised. *Comes back modified* → it is live data; note what changed and
drop the claim.

octamax paid for this lesson twice: an early home for the dual-256 SET-B tables
sat in the heap tail and was overwritten at runtime, and its probe counters were
silently clobbered by a region the sidecar restored on every load.

**For us:** our pre-flash gate is an emulator diff (`emu_check.py` lineage), which
proves the patch does what we meant — it does **not** prove the bytes we chose
stay ours across a real session. Those are different questions. See the workflow
note added to [`techniques.md`](techniques.md) §"Cave placement".

## 4. Overlap enforcement — the ledger as a build step

octalab has every module declare its sub-range in its own `manifest`, and **the
build refuses to place two modules that overlap**. The idea is lifted from
octabam's `tools/remix/ledger.py`.

The reason to copy this rather than eyeball it: silently overlapping machine
code is *the* one class of bug that produces **a unit that boots and then
misbehaves** — no crash, no obvious symptom, and nothing an image diff flags.

Our `build_merged.py` composes 7 mods into `KYOTI_V1.0` and already tracks
`FREE_START`; an explicit per-mod range declaration + overlap assertion is the
cheap version of the same guarantee. See `reference/MERGE.md`.

## 5. When the cave runs out — the append-a-runtime route, now MKI-proven

> source: `refs/octalab/docs/FINDINGS.md` "octabam's DRAM loader boots on a MKI"
> @ `e0dc56d` · fetched 2026-09-24. confidence: **C** (hardware, MKI, 11 Sep 2026).

An image built by octabam's remixer (origin `9a49f21`) — loader appended at
`0x4010fdf0`, reached from the boot site `0x4000050c`, depacking a ColdFire DRAM
unit into the platform reserve at the bottom of the audio-page arena
(`0x40a955e0`, 10 MiB) — **ran on an Octatrack MKI** on 11 Sep 2026.

This matters specifically to us: octabam's own notes list their ColdFire pipeline
as unflashed and every test as MKII. **This is the MKI data point**, and we are an
MKI-only project. The route past the 6 KB cave ceiling is therefore not
theoretical for our hardware.

⚠️ **Known cost on that image:** the audio pool's Flex list reads **FREE MEM
71.4 MB** — the 10 MiB reserve is gone from the pool — but the **MEMORY page
still shows an 85.5 MB total** (visible when changing RESERVE LENGTH): its total
does not follow the rewritten arena geometry. The page count 14,602
(`0x0000390a`) appears as a word at 18 places in stock and most stay untouched;
which one the page reads is **not yet pinned**. A cosmetic-but-visible artefact
any adoption of this route inherits.

**Update 2026-10-06: it is now octabam's standard placement class, and ours on hardware.**
- octabam `docs/contributing/PLACEMENT.md` @ `36a056c5` has two classes:
  - ROM cave (`CavePatch`): ~8.4 KB total, shared;
  - **DRAM unit** (`Linked(..., dram=True)`): every DRAM unit in a remix is linked as one
    image, packed, appended after the OS behind the loader, and depacked at boot into the
    reserve. 10 MiB, taken from the sample/recorder pool.
- The third class (Octakit's appended runtime) went with Octakit on 6 Oct 2026.
- octabam's ROM free list now: `0x400c45b0..0x400c4702`, `0x400d24d0..0x400d2ce0`,
  `0x400d64da..0x400d7c3c` (the FX2 chooser's NONE row sits at `0x400d6b00`; clones from
  `0x400d6b20`). CAVE2 is refused, and nothing inside the descriptor table is listed (§0).
- **Ours, confidence C:** OBKYOTI6–12 put RELOAD_FROM_PROJECT, DIRECT_JUMP_KYOTI and
  REPITCH's ColdFire half in DRAM. They are hardware-tested on the author's MKI (NOTES S120).
  The emulator measures DRAM-resident code at the same per-frame cost as ROM code
  (`reference/handoffs/KYOTI_LOAD_AUDIT.md`).

## 5b. The OTHER way past the ceiling — a payload on the CF card

> source: `refs/octemu/custom/usb-audio.py` (+ `custom/coldfire/usb-audio*.s`) @ `6a9ff68`
> (markandrus, MIT) · fetched 2026-09-24. confidence: **C** for the architecture as
> described and for the ☠ addresses, which the file marks hardware-measured.

octemu's USB-Audio feature needed **far more** than the image had free (four grown UAC2
descriptors + iso servicing + a 36 KB audio ring, against ~408 B of remaining slack). Its
answer is a second route past the ceiling, and it is more incremental than
append-a-runtime:

1. **The payload lives on the CF card** as `/USBAUDIO.BIN`, not in the image, and is
   **position-independent via a relocation table**.
2. **A small trampoline goes in the image slack** (408 B) and hooks `fs_card_detect_poll`;
   once the card is mounted it loads the payload, **invalidates the I-cache**, and `jsr`s a
   stage-2 installer.
3. **Stage 2 installs the runtime hooks** — into image code, but *only after the card blob
   is confirmed loaded*.
4. The payload lands in **flex-heap pages stage 2 takes out of the firmware's own free
   list** (`--heap-reserve`), "where nothing else will ever be placed".
5. Small helper blobs (page allocator, status reporter, hook guard) each sit in their own
   measured free zone.
6. **In-image writes are few and all `expect()`-guarded** — the same posture as our own
   guarded splices.

**Why this is attractive for us specifically:** the failure mode is benign. *"An image
without the card file is exactly the stock usb-midi composite."* Recovery is **hold `NO` at
boot** (skips loading) or **delete the file from the card** — no reflash, no SysEx. Compare
append-a-runtime, which costs sample memory permanently and changes the arena geometry
(§5's FREE MEM artefact). For a large optional feature, card-payload has a far better
risk profile than either more cave or a reclaimed pool.

**☠ Hardware-measured SDRAM scratch warnings — do not re-derive these the expensive way.**
The file carries these as a skull-marked comment, explicitly "HARDWARE-MEASURED, not
canary-derived":

| addr | verdict |
|---|---|
| `0x48001000` | **WRONG.** On a real unit, **writes past ~`0x48003000` destroy image code.** |
| `0x48010000` | **so badly occupied that the corruption takes out the exception screen's own display** — i.e. it breaks the very screen you would debug it with |
| `0x49000000` | **write-verified clean for 256 KB on hardware** (`cf/memtest-probe.s`) — the address it ships |

⚠️ "Re-measure before moving this again" is their note, and it applies to us too: these are
measurements of *one* unit's SDRAM population, not a datasheet guarantee.

## 5c. Where the resident bank blobs end — three sources agree

> sources: `refs/octemu/re/coldfire.syms` @ `6a9ff68` (arithmetic proof);
> `refs/octalab/docs/FINDINGS.md` @ `e0dc56d` (MKI hardware); our own KB.
> confidence: **C**.

`sample_heap_base = 0x40a955e0` — the base of the RAM sample-PCM heap, a paged allocator
with **6144-byte pages** (`FLEX PCM address = 0x40a955e0 + page*6144 + frame*bytesPerFrame`;
the literal is added at `0x40094a3c` / `0x40094a9c`).

**The arithmetic proof it is exactly the end of the resident bank blobs:**
`0x400e21e0` (bank blob base) `+ 16 × 0x9b340` = **`0x40a955e0`** exactly. The STATIC/FLEX
slot-usage scan walks banks to this sentinel (`0x400254f2`/`0x400254f8`).

And it is the same address octalab reports octabam's MKI-proven DRAM loader depacking into —
"the platform reserve at the bottom of the audio page arena (`0x40a955e0`, 10 MiB)". So the
append-a-runtime route (§5) and this number are the same fact seen from two sides.

⚠️ **`0x400e21e0` has two identities, and confusing them would be expensive.** octemu labels
it `dsp_bootstrap_a` — "core A's first-stage scatter loader blob" — *and*, in the same file,
as the bank blob base. Both are right, **disjoint in time**: in the **image file** those
bytes are DSP bootstrap data (memcpy'd to the staging buffer at boot,
`pd_memcpy dst=0x40a955e0 src=dsp_bootstrap_a len=0x96` at `0x4000045c`); at **runtime** the
region is the 16 resident bank blobs. The same is true of `0x40a955e0` itself: DSP payload
staging buffer at boot, sample heap afterwards.
**So: patching the IMAGE at `0x400e21e0` corrupts the DSP loader; reading it at RUNTIME gives
the bank blob.** Our `patch_pattern_led` reads it at runtime (correct, and it is what stock
itself does at `0x4009a486`).

## 6. The menu descriptor — corroborated twice, and the gate that catches its bugs

> source: `refs/octalab/docs/CAVES.md` "The menu model, corroborated independently"
> @ `e0dc56d` · fetched 2026-09-24. confidence: **C** (two independent readings).

```
CONTROL_DESC = 0x400cbd54    CONTROL_ROWS = 0x400cc5a8    ROW_LEN = 24    STOCK_N = 6
count = u32(img, CONTROL_DESC)        rows = u32(img, CONTROL_DESC + 0x18)
```

Count at `+0x00`, rows pointer at `+0x18`, 24-byte records — octabam's
`tools/verify_menushortcut.py` and octalab's own survey (AUDIO · INPUT ·
SEQUENCER · MIDI SEQUENCER) agree exactly. Our own 24-byte row struct
(`kb/techniques.md` "Adding a whole menu SCREEN") is the third reading.

**The technique worth copying:** that script *boots the patched image and walks
the menu out of RAM using the firmware's own layout*. octalab's verdict on its
own brick: **"MENUPROBE's crash was the cave and nothing else — the record
layout it wrote was right."** A RAM-side menu walk is exactly the gate that
separates those two failure modes before a flash.

---

## Cross-references

- Cave ceiling, `.bss` tail, sentinel-address cross-cave calls, the existing
  cave coordinate list → [`techniques.md`](techniques.md) "Cave placement" and
  "midisc".
- The append-a-runtime architecture in detail → [`octakit-abi.md`](octakit-abi.md).
- Free *scratch words* (single words of work RAM for feature state, a different
  problem from code caves) → [`memory-map.md`](memory-map.md) "Free scratch words".


## Scratch RAM: `0x80006a40+` is not safe under live audio (C, ours, Sessions 94-96)

The cave discussion above is about **code** space. The same "a static scan is necessary
and not sufficient" rule applies to the **data** scratch every mod keeps at
`0x80006a40+`, and it has now been caught failing on hardware.

QLREC kept a single 32-bit magic at **`0x80006a60`** to mark "the toast on screen is
ours". On a real MKI, a diagnostic build reported the word as **already not the magic on
the very next key press** after writing it. In route A it persisted indefinitely — the
emulator does not run the DSP/audio path, and the unit was live-recording. The block is
inside the **DSP shared-RAM window** (`FUN_4000f938` re-images `0x80000000..0x80003e88`
from ROM and zero-fills only to `0x80004000`; kernel globals live at
`0x800068d8..0x80006903`, immediately below).

- **0 static references** into `0x80006a00..0x80006ac0` anywhere in the image, and no
  literal for those addresses. The scan was clean and the RAM was still not ours.
- **The fix that worked: keep no private state.** Read what the OS already maintains —
  for a notification, the handle `0x460d1e70` (set by `FUN_4005a2b8`, cleared by
  `FUN_40056bec` via `FUN_40055db4`). QLREC's cave went from 5 scratch words to none.
- **Second hardware proof (Session 98):** RELOAD3's request bytes `0x80006a54-55` were
  overwritten on the unit between a key chord and the storage job that read them
  (diagnostic toast: chord `0000`, worker `005B`; later `0045`, `004F`, `003F` — the values
  vary, so what writes there is still unknown). RELOAD3 moved them into its own cave data;
  the build now rejects any reference into `0x80006a40..0x80006abf`. **Cave data words do
  survive**: in the same toast the chord-time capture, stored in cave data, was intact at
  job completion while the copy in the scratch block was not.
- **DIRECT JUMP no longer keeps state there.** V6 and V7 keep every state byte in their
  own cave and `build_directjump_v{6,7}.py` reject the same range; only the retired V1–V5
  line used `0x80006a40-4a`.
- **Only a diagnostic build on the unit settles this.** Nothing static, and nothing in
  route A, can.
