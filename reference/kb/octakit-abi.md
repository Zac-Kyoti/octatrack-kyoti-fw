# Octakit ABI — stock-firmware address map from a shipping Kit mod

Curated distillate of **emuyia/ems-octakit** ("Octakit"), which replaces the
Octatrack's 4-Parts-per-Bank model with 256 Kits per Project. The repo was
**closed-source until 2026-09** (README + issue templates only); commit
[`ca3b527`](https://github.com/emuyia/ems-octakit/commit/ca3b527304565e3bcb0d81f4e667b3cfc9b2f088)
("add octakit source and build tools") published the full toolchain:

- `runtime/abi.inc` — **~500 `.equ` symbols**: named stock-firmware addresses
  (`GK_STOCK_*`) plus struct-offset / enum constants (`GK_*`) for the Part / Kit /
  Bank / Project / scene / LFO-designer / sequencer / MIDI-CC subsystems.
- `runtime/firmware.json` — the build recipe: **598 guarded patch sites** (each a
  file offset + `length` + SHA-256 guard over the stock bytes + the replacement
  `writes`) and **411 `m68k-relocate` / `stock-copy` operations** that rebuild the
  appended runtime region from the user's own OS.
- `runtime/*.S` — 62 ColdFire (`-mcfv4e`) assembly modules; `build.py` +
  `patcher/` (Rust → native & WASM).

> source: `refs/ems-octakit/runtime/{abi.inc,firmware.json}` + `build.py` + `runtime/loader.S`
> @ `ca3b527` · fetched 2026-09-06 · **licence: no `LICENSE` file** (same posture as
> octamax — GitHub ToS, educational use only; we store facts + small excerpts, no
> wholesale source). Full symbol list lives in the gitignored `refs/` cache after
> `python3 tools/refs/sync.py ems-octakit`.
>
> confidence: **C** for the addresses themselves — they are load-bearing in a
> firmware mod that flashes and runs on real hardware (`build.filename =
> ot-26905-*-dev.syx`). **L** for the subsystem groupings and any "= our
> `FUN_…`" identification, which is ours.

Base: OS image `0x40000400`–`0x4010fdf0` (`GK_STOCK_OS_IMAGE_START/END`); a
`firmware.json` patch `offset` is a byte offset into that image, so
`addr = 0x40000400 + offset`. Bank/blob offsets (the `0x000xxxxx` ones below) are
offsets **within the bank file / in-RAM bank blob**, not absolute addresses.

---

## Confirms our existing RE

| Octakit symbol | Value | Our prior name / note |
|---|---|---|
| `GK_STOCK_BANK_POINTER` | `0x46c82456` | `_DAT_46c82456` per-track pattern-data base (`memory-map.md` "Storage") |
| `GK_STOCK_BANK_DESERIALIZE` | `0x4008ded0` | `FUN_4008ded0` bank deserialiser (`file-format.md` — "runs the real `FUN_4008ded0`") |
| `GK_STOCK_ENGINE_PART_LOAD` | `0x40009094` | `FUN_40009094` "applies a Part by event" (`memory-map.md` "Parts / Bank apply") |
| `GK_STOCK_PATTERN_STRIDE` | `0x00008ed8` | pattern tempo/settings stride `pat*0x8ed8` (`FUN_4009c550`) |
| `GK_PART_PAYLOAD_SIZE` | `0x18b2` | trig/param stride `pat*0x18b2` (`_DAT_46c82456`); OctaLib PART stride `0x18BB` = this + `9` header |
| `GK_STOCK_BANK_SIZE` | `0x0009b4d1` (636 113) | **exactly** the factory OT DEMO `bank01.work` size (`file-format.md`) |
| `GK_STOCK_PART_PAYLOAD_INITIALIZE` | `0x40005638` | `FUN_40005638` FX-default initialiser (`memory-map.md` "UI / menu") |
| `GK_STOCK_MACHINE_SELECT_FX1_TABLE` / `_FX2_TABLE` | `0x400d6060` / `0x400d6090` | extend past the descriptor table `0x400d2fe4`–`0x400d5e04` (octa-bt-pt) |

No conflicts found. One to watch: Octakit's `GK_STOCK_PATTERN_PART_OFFSET =
0x00008e57` (pattern-block → Part-index byte) vs OctaLib's `OFFSET_PATTERN_PART_NUM
= +0x8EE7` — different framing (payload-relative vs block-relative?); reconcile
before trusting either for a write.

---

## Bank / Project / Part file & blob model  → feeds `file-format.md`, NOTES Session 13

| Symbol | Value | What |
|---|---|---|
| `GK_STOCK_BANK_WORKING_OFFSET` | `0x0008ed80` | start of the working-copy region inside a bank blob |
| `GK_STOCK_BANK_STRIDE` | `0x0009b340` | per-bank stride in the resident-banks array |
| `GK_STOCK_BANK_NAMES_OFFSET` | `0x0009b316` | bank-name string |
| `GK_STOCK_BANK_DIRTY_OFFSET` | `0x0009b332` | bank dirty flag |
| `GK_STOCK_BANK_STATUS_OFFSET` | `0x0009b336` | bank status |
| `GK_STOCK_BANK_EDITED_OFFSET` | `0x00095048` | "edited since load" |
| `GK_STOCK_PATTERN_PART_OFFSET` | `0x00008e57` | pattern → Part-index byte (see caveat above) |
| `GK_PART_MACHINE_SELECTOR_OFFSET` / `GK_STOCK_PLAYBACK_MACHINE_OFFSET` | `0x22` | 8 machine-type bytes at part+`0x22` |
| `GK_STOCK_SEQUENCER_PART_STEP_OFFSET` | `0x1832` | per-step data within the part payload |
| `GK_STOCK_SEQUENCER_PART_CONDITION_OFFSET` | `0x1822` | per-step **trig-condition** data within the part payload |
| `GK_STOCK_SLICE_LOCK_SLOT_OFFSET` | `0x000002ca` | slice-lock slot in the per-track parameter block |

**Per-track parameter-page payload offsets** (offset into the part payload for
each SETUP page's parameter block — directly relevant to turning the
`file-format.md` p-lock `record[step][p]` byte offsets into a parameter map):

| Page | editor fn | payload offset | UI cache |
|---|---|---|---|
| PLAYBACK (SRC) | `0x4003a474` | `0x01da` | `0x80000830` |
| AMP | `0x4003adec` | `0x02f8` | `0x8000083c` |
| FX1 setup | `0x4003abe4` | `0x02fe` | `0x80000842` |
| FX2 setup | `0x4003a9dc` | `0x0304` | `0x80000848` |
| track "twelve-byte" editor | `0x4002ef28` | `0x0602` | `0x80000c94` |

`GK_TRACK_SETUP_*` enum: PLAYBACK 0, EFFECT2 1, EFFECT1 2, AMP 3.

### .work ↔ .strd store / restore (the load/save choke points)

| Symbol | Value |
|---|---|
| `GK_STOCK_BANKS_STORE_WORK_TO_STRD` | `0x4008eda4` |
| `GK_STOCK_BANKS_RESTORE_STRD_TO_WORK` | `0x4008f0b0` |
| `GK_STOCK_PROJECT_STORE_WORK_TO_STRD` | `0x4008ee74` |
| `GK_STOCK_PROJECT_RESTORE_STRD_TO_WORK` | `0x4008f180` |
| `GK_STOCK_BANKS_SAVE_WORK` | `0x400917c8` |
| `GK_STOCK_BANKS_LOAD_WORK` | `0x400905d4` |
| `GK_STOCK_CURRENT_PROJECT_CARD_SYNC` | `0x400919e4` |
| `GK_STOCK_RESIDENT_BANK_BASE` / `_INITIALIZE_ALL` | `0x400e21e0` / `0x4000fd34` |
| `GK_STOCK_PATTERN_ASSIGNMENT_TABLE` | `0x400eb036` |
| `GK_STOCK_PATTERN_HAS_CONTENT` | `0x4009a464` (predicate — "is this pattern non-empty") |
| `GK_STOCK_PATTERN_CLEAR_CURRENT` | `0x4003a244` |

`GK_STOCK_BUFFERED_FILE_{OPEN,READ,WRITE,SEEK,CLOSE}` = `0x40016864` / `0x40016564`
/ `0x400166b8` / `0x4001660c` / `0x4001677c` (the CF file API the loaders call).

---

## Current bank/part/pattern selection state (work RAM)

| Symbol | Value | What |
|---|---|---|
| `GK_STOCK_ENGINE_UI_TRACK` / `_SECONDARY` | `0x80000000` / `0x80000001` | selected track (+ twin) |
| `GK_STOCK_CURRENT_BANK_MIRROR` | `0x80000002` | current bank byte |
| `GK_STOCK_CURRENT_PART_MIRROR` | `0x80000003` | current part byte |
| `GK_STOCK_CURRENT_PATTERN` | `0x80000004` | current pattern byte |
| `GK_STOCK_CURRENT_{TRACK,BANK,PART,PATTERN}_PRIMARY` | `0x100b14cc`..`0x100b14d0` | the primary (non-mirror) copies |
| `GK_STOCK_ENGINE_BANK` / `_PART` | `0x80001828` / `0x80001829` | engine-side bank/part |
| `GK_STOCK_ENGINE_SCENE_TABLE` | `0x800010e4` | |
| `GK_STOCK_AUDIO_SCENE_FLAGS` / `_A_VALUE` / `_B_VALUE` | `0x80006904` / `…06906` / `…06907` | active scene A/B |
| `GK_STOCK_SEQUENCER_TRACK_STATE_BASE` | `0x80006500` | base of the `0x80006500`-region seq state (our `_DAT_800065xx` step/queue bytes live here) |
| `GK_STOCK_SEQUENCER_CURRENT_BANK` / `_PATTERN` | `0x800065bd` / `0x800065be` | (matches `memory-map.md` DIRECT-JUMP COMMIT) |
| `GK_STOCK_QUEUED_BANK` / `_PATTERN` | `0x800065bf` / `0x800065c0` | pending stash (matches ours) |
| `GK_STOCK_SELECTED_PART` | `0x460d10c8` | |

---

## Subsystem entry points (selection)

FX / machine chooser: `GK_STOCK_MACHINE_CHOOSER 0x40079424`, FX1/FX2 definition &
selection tables `0x400d5f58` / `0x400d5fdc` (defs), `0x460d5c94` / `0x460d5ca8`
(selection), `0x400d6060` / `0x400d6090` (id→pos tables), `GK_STOCK_MACHINE_SETUP
0x40096c54`, `GK_STOCK_PART_MACHINE_TRANSITION 0x400972fc`.

Sequencer tick: `GK_STOCK_SEQUENCER_TICK_*` cluster around `0x400a17xx–0x400a1exx`
(`_EPILOGUE 0x400a1e02`), `GK_STOCK_SEQUENCER_ADVANCE_CONTINUE 0x40099ef4`,
`GK_STOCK_SEQUENCER_CONDITION_CONTINUE 0x40099ddc`, track state `0x46c79e9a`.

Scene A/B input: encoders `GK_STOCK_SCENE_A_ENCODER 0x40053498` /
`_B_ENCODER 0x40052e98`; buttons `0x4005435c` / `0x40053a68`; parameter writer
`0x40052ae8`; undo buffer `0x460bf218`, undo tag `0x460c80f0`.

LFO designer: renderer `0x400572e8`, editor `0x40038e04`, registry `0x46c7dede`,
mode `0x460d1a32`, paste buffer `0x460c8122`.

MIDI CC commit paths (relevant to Bug 2): `GK_STOCK_MIDI_CTRL1_{SINGLE,DIRECT,COMMIT}`
= `0x4003fc44` / `0x4003fd34` / `0x4003fe14`; CTRL2 = `0x4003f71c` / `0x4003f80c` /
`0x4003f8e8`; MIDI-learn callback `0x400c0c34`, refresh op `0x4009ec70`.

Part edit / dispatch: `GK_STOCK_MKI_PART_DISPATCH 0x40058a64` (the MKI PART-button
path — FUNC+MIDI / FUNC+BANK in Octakit), `part-edit-dispatch 0x40058a70`,
`GK_STOCK_PART_EDIT_OPEN_CURRENT 0x4002dc9c`, `GK_STOCK_PART_MODAL_ACTIVE 0x4002dc3c`.

Recording Setup menu / LOAD KIT (added `1760ac0`/`d1a9ef0`, 2026-09-12 —
Octakit's own "stale ownership at a Kit/Pattern handoff" bugfix pair, not stock
bugs, but adjacent territory to Session 49's Part-carryover family):
`GK_STOCK_RECORDING_SETUP_CALLBACK 0x400b9e16`, `_CLOSE 0x4002ee88`, `_OBJECT
0x460d10cc` (the live popup-object pointer), `GK_STOCK_RECORDING_EDIT_MENU_OPEN
0x4003105c`, `GK_STOCK_MKI_RECORDING_SETUP_INPUT_MAP 0x400b9e36`,
`GK_STOCK_PATTERN_KEY_REQUEST_RETURN 0x40056b6e`. Not consumed by
`patch_partreapply` (that fix restores the recorder-cache *data* directly, not
menu-ownership state) — keep on hand if a future report describes the Recording
Setup *menu* itself staying attributed to the wrong track after a Part change.

Menu / popup / text: `GK_STOCK_POPUP_CREATE 0x4005829c`, popup objects
`0x46c7d34c` (stride `0x38`, 5 slots, active-bit 5), `GK_STOCK_SCROLLING_CALLBACK_MENU_OPEN
0x4006d94c`, callback-menu state block at `0x460e5e28`, text editor open
`0x4007e664` (max-len word `0x400d0730`), `GK_STOCK_NOTIFICATION_SHOW 0x4005a2b8`,
`GK_STOCK_STRING_FORMAT 0x40013a08`, `GK_STOCK_MEMORY_COPY 0x40020898`.

Boot / container (→ `container-format.md`): from `runtime/loader.S` —
`GK_STOCK_BOOT_CONTINUE 0x40001e50`, **`GK_STOCK_APLIB_DEPACK 0x400e0aca`** (the
aPLib depack routine), `GK_STOCK_EVENT_POINTER_PUSH 0x40000c3c`.

---

## Build recipe facts (→ `techniques.md`, `container-format.md`)

- Toolchain: **`m68k-elf-gcc` 16.1.0**, `-mcfv4e -Os -ffreestanding -nostdlib
  -Wstack-usage=576 -Werror`; Rust `1.97.1` for the patcher.
- Provenance model `authenticated-stock-local-reconstruction-v1` +
  `sparse-public-write-v3`: the repo embeds **no guard byte-arrays and no
  stock-derived blobs** — `replacement_encoding = "changed-bytes-only"`, and the
  appended 73 111-byte runtime region is rebuilt from the user's OS via 411
  `m68k-relocate`/`stock-copy` ops. Same "bring your own OS, ship no binary"
  stance as this repo; a stricter *encoding* of it than our `build_*.py`
  (we assert-and-splice; they classify every output byte by origin).
- Append region loads at `0x45d0dde0` (cached/uncached alias delta `0x08000000`);
  a 160-byte loader is spliced at OS offset 0 of the appended area, OS image tail
  at `0x4010fdf0`.
- `firmware.json` patch sites are individually SHA-256-guarded against the stock
  bytes — an independent 598-point confirmation of the 1.40C image whose OS
  SHA-256 is `164f3122…` (the one we RE, MKI == MKII).

---

## The append-a-runtime architecture — escaping the code-cave limit

> source: `refs/ems-octakit/runtime/{link.ld,loader.S}` + `firmware.json` patch
> list + `README.md` @ `ec70dda` (2026-09-09). confidence: **C** — this is the
> mechanism of a firmware mod that boots and runs on real MKI/MKII hardware;
> **L** for our interpretation of the audio-page allocator constants.

Octakit does **not** squeeze into `0x400d2000–0x400d8000` code caves. It reclaims
a multi-megabyte contiguous slice of the **flex sample pool**, appends an
aPLib-packed "runtime" blob to the OS image, and hooks boot to unpack it there.
This is the load-bearing technique for anyone who needs more than a few KB of new
ColdFire code.

### 1. Carve the region — 4 two-byte constant patches in the audio-page allocator

The flex/sample RAM is managed as fixed-size **"audio pages"** with a free list,
built around `0x40096f80–0x40097130`. Octakit changes four count immediates:

| patch | addr | new operand | role |
|---|---|---|---|
| `reserve-audio-page-free-list-tail` | `0x40096f82` | `0x36fa` @ `+2` | free-list length cap |
| `shorten-audio-page-free-list-initializer` | `0x40096fac` | `0x36fb` @ `+2` | init loop bound |
| `shorten-audio-page-arena-clear` | `0x40097008` | `0x2788` @ `+1` | arena zero-fill bound |
| `cap-recorder-page-allocation` | `0x40097126` | `0x36fa` @ `+2` | recorder-buffer ceiling |

That's the *entire* cost side. `README` (`ec70dda`): the carve is **18.4 s of
16-bit / 12.3 s of 24-bit sample time = 3.6 % of the pool**, i.e. ≈ **3.1 MB**
(`RUNTIME_END − RUNTIME_START = 0x46025de0 − 0x45d0dde0 = 0x318000`). Scales
down — take 128–256 KB and the sample-time hit is well under a second.

### 2. The reclaimed region (`link.ld`)

| symbol | value | note |
|---|---|---|
| `RUNTIME_START` | `0x45d0dde0` | base, in the (now smaller) flex pool |
| `RUNTIME_END` | `0x46025de0` | +`0x318000` |
| cached↔uncached alias | `+0x08000000` | runtime is written via the uncached alias `0x4dd0dde0` |
| `RUNTIME_CODE_BUDGET` | `0x25000` (≈148 KB; asserted ≤128 KB "allowance") | **ColdFire code** lives in the low part |
| after code | `KIT_COUNT*0x18b2 = 0x18b200` canonical + `0x0c5900` spill + metadata/UI/IO… | Octakit's Kit *data* fills the rest |
| `STAGE_ADDRESS` | `0x47fc7410` | transient unpack scratch near top of SDRAM (`< 0x47fe0000`, "128 KiB below SP") |

### 3. The boot chain (`loader.S` + `firmware.json`)

Container = **stock OS + appended `.early` loader (~160 B at `0x4010fdf0`, the OS
tail) + appended `.stage` (a small anchor + the aPLib-packed runtime)**. ~73 KB
appended total. ~10 guarded splices wire it in:

| patch | addr | what |
|---|---|---|
| `stage-before-bank-init` | `0x4000050c` | earliest boot redirect (3 B) |
| `install-early-stage-and-repair-wrapper` | `0x40020870` | `jsr 0x4010fdf0` (the appended loader) → `jsr 0x4000f97c` (auth) → `jsr` into runtime `0x45d1dc1c` |
| `install-runtime-authentication-gate` | `0x4000f97c` | hash-verify the unpacked runtime |
| `install-runtime-hash-helper` / `-repair-helper` | `0x40014418` / `0x400148d4` | hash + repair; both `lea 0x4dd0dde0` (uncached runtime) |
| `install-post-clear-relocation-wrapper` / `relocate-after-alias-clear` | `0x40013304` / `0x40009822` | **re-unpack the runtime after the stock SDRAM-alias clear wipes it** — refs `0x4ffc7414` (stage), `0x400e0aca` (aPLib depack), `0x40014424` |
| `install-instruction-cache-sync` | `0x4001f3e0` | I-cache flush after writing code |

`loader.S`: `jsr GK_STOCK_BOOT_CONTINUE (0x40001e50)` → byte-copy stage to
`STAGE_UNCACHED` → hash-check → `GK_STOCK_APLIB_DEPACK (0x400e0aca)` unpacks the
runtime into `0x4dd0dde0` → hash-check → byte-copy a backup to `RUNTIME_END −
size`. Magic words: stage sig `0x474b5832` ("GKX2"), runtime header `0x474b4133`
("GKA3").

### 4. What it gives you — and what it does NOT

| | |
|---|---|
| ✅ **ColdFire code** | ~128 KB, linked as one blob with a real linker script — no hand-placed caves, no overlap asserts |
| ✅ **ColdFire data / work RAM** | the rest of the 3.1 MB (or whatever you carve) — big buffers, tables, state |
| ❌ **DSP program (P) memory** | untouched. The DSP FX budget (~2,724 words/payload) is a separate address space the DSP uploads; this region is ColdFire SDRAM the DSP never sees |
| ❌ **DSP X/Y scratch** | likewise — the keybus / SVF-state / cross-core-ring problems are DSP-internal and unaffected |
| cost | a slice of flex sample time (Octakit: 18.4 s; a KYOTI-sized carve: sub-second) + ~10 boot splices + the loader + an aPLib pack step + **its own hardware boot validation** |

**For KYOTI:** this is the way out of the `0x400d7000` cave crunch for anything
ColdFire — DIRECT JUMP, RELOAD FROM PROJECT (already scaled down for space), the
MUTE-MODE menu surgery, the SIDE-CHAIN *menu* side. It does **nothing** for the
DSP half of the side-chain compressor (program words, shared-Y keybus, cross-core
race). Adopting it is a build-system change on the scale of "ship a bootloader
extension," not a patch tweak — but Octakit's `link.ld` + `loader.S` +
`patcher/` are a working reference to adapt.

## Kit-format constants (Octakit's own invention — informational)

`GK_KIT_COUNT 256`, `GK_KIT_NAME_SIZE 8` (7 visible), `GK_PATTERN_ASSIGNMENT_COUNT
256`, `GK_PHYSICAL_COUNT 64` (migration target: old Parts → first 64 Kit slots).
The `GK_V3_*` / `GK_FORMAT_*` constants describe Octakit's on-card Kit persistence
file, not a stock structure — skip unless mirroring their storage approach.
