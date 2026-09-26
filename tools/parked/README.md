# `tools/parked/` — our own work, deliberately shelved

Unlike [`../attic/`](../attic/README.md) (inherited octamax sources, kept as RE
cross-reference), everything here is **this project's own code, built and tested, then
parked by decision** — not abandoned because it failed. Each item records what it did, how
far it was verified, why it was parked, and the exact steps to bring it back.

**Nothing here is part of any build.** No `build_*.py` references this directory; the files
are renamed so they cannot be picked up by a builder that globs `tools/patch_*.s`.

---

## `mutemode_firstflash_OT.*` — "a first flash of MUTE MODE comes up in OT"

Parked **2026-09-25**, same day it was written, at the user's request: *"roll back to the
previous build version… I want to return to the previous, flashed/confirmed finalized
build."* MUTEMODE_DT is hardware-confirmed and final (2026-09-21), and this would have put
new code in its **boot path** for a convenience behaviour. Parked rather than deleted.

| file | was | what it is |
|---|---|---|
| `mutemode_firstflash_OT.s` | `tools/patch_firstflash.s` | the cave: 54 B, one 10 B detour |
| `mutemode_firstflash_OT_test.py` | `tools/emu_firstflash.py` | the emulator test (31 checks) |
| `mutemode_firstflash_OT_buildtool.diff` | — | the exact `build_mutemode_dt.py` diff that wired it in |

### The problem it solved (still real, still unfixed)

MUTE MODE persists in the battery-backed `'ANDY'` block (shadow `0x100fff6c`), and the boot
restore copies it back into `0x800000dc`. So **a unit that ran an earlier MUTE MODE build
boots the next one straight into that build's stored mode** (OTFX-T / DT-T / OTFX), not OT.

⚠️ Addendum 14's "defaults verified" does **not** cover this. It booted with *no* battery
data: the checksum fails, stock takes the defaults path (`0x4001f298`, zero-fills), GATE = 0.
A unit coming from an earlier build has a **valid** block, so stock takes no reset path at
all. Measured, not assumed: the test below fails 23 checks against the pre-patch image,
including *"GATE 1 → runtime `0x800000dc` restored as 0"* (it is restored as 1).

So: **the shipping, confirmed build does not come up in OT on a re-flash.** If that matters
later, this is the fix, and it was verified.

### How it worked

A tag longword at shadow `0x100fff70` means "this block has been through a build carrying
this patch". `0x100fff70` is outside the 0x70-byte restore window (no runtime alias) and
outside everything stock addresses absolutely (whole-image scan: stock never names
`0x100fff64+`). Detour at `0x4001fb1a`, immediately before the boot restore memcpy:

    tag == TAG_MAGIC  ->  fall through (a normal boot: one load, one compare, one branch)
    tag != TAG_MAGIC  ->  shadow GATE = 0, set tag, jsr 0x4001f23c (re-seal the checksum)

then replay the displaced `pea 1 / jsr 0x4000fd34` and `jmp 0x4001fb24`, so the stock
restore copies GATE = 0 into RAM.

**Semantics:** the reset fires **once per unit per `TAG_MAGIC`** — on the first boot of a
build carrying the patch. After that the user's choice persists as before, across power
cycles *and* re-flashes of the same build. If a reset on *every* new flash is wanted
instead, derive the tag from a build stamp (never implemented — it changes the
"your setting is sticky" contract, so ask first).

### Two boot-path facts worth keeping even if this stays parked

1. **The power-up restore is `0x4001fb24`, not `0x4001f340`.** Watched through a real boot:
   `0x4001f298` (defaults) → `0x4001f322` → `0x4001fb24` fire; the "validate" function
   `0x4001f340` does **not** — its callers (`0x4004abf0`, `0x4006233a`) are a later settings
   reload. A patch aimed at `0x4001f340` would never run at power-up.
2. **A checksum mismatch at boot is expensive**: that path clears
   `0x10000000..0x100fff00` and runs defaults, i.e. it resets *all* PERSONALIZE. Anything
   that edits the block must re-seal with the OS's own routine `0x4001f23c` (no args,
   clobbers only d0/d1/a0 — the one the PERSONALIZE key handler runs after every setter).
   Do not roll your own.

### Verification it reached (emulator only — **never flashed**)

- **62 bytes** changed vs the confirmed MUTEMODE_DT image: the 10 B detour + the 54 B cave.
  `patch_softmute` (the whole audio path), the menu, the arrays and the restore-length
  patches were byte-identical to the confirmed build. Same 62 bytes in the Bugbuild.
- `mutemode_firstflash_OT_test.py` — **all checks passed** on the standalone and Bugbuild
  images. It runs the *real* patched boot tail (detour, cave, stock `0x4001f23c`, stock
  memcpy `0x40020898`, CFV4E CPU model) over seeded blocks whose validity is judged by the
  **ROM's own validator** `0x4001f268` (self-checked: it rejects a 1-byte flip). Cases:
  stale GATE 1/2/3 untagged → shadow *and* runtime 0, tag set, checksum valid, every other
  block byte untouched, `d3` preserved, exactly one re-seal; tagged blocks GATE 0..3 →
  byte-identical, no re-seal; five non-matching tag values → reset; blank block → stays 0;
  and reset → pick OTFX → three further boots → OTFX persists.
- Whole-image boot under `ot_emu`: reaches the RTOS handoff, M6a gate PASS, watches show
  detour → cave → re-seal on the real power-up path, and the dumped block afterwards has
  the tag, shadow GATE 0, a valid checksum and runtime `0x800000dc` = 0.
- Bugbuild interlock proof passed; the other four features' artifacts hashed identically.

**Not verified:** the unit test starts at `0x4001fb1a` with hand-set registers, and `ot_emu`
can only boot a *blank* battery block (no way to pre-seed SRAM there) — so the
stale-valid-block case is proven on the real code path but **not through a real power-up**.
Per CLAUDE.md: emulator green is evidence about the logic, never about the machine.

### To bring it back

1. `cp tools/parked/mutemode_firstflash_OT.s tools/patch_firstflash.s`
   `cp tools/parked/mutemode_firstflash_OT_test.py tools/emu_firstflash.py`
   (the builder resolves sources as `tools/{name}.s`, so it must sit in `tools/` under the
   name used in the `PATCHES` entry — or change that entry's path handling.)
2. `git apply tools/parked/mutemode_firstflash_OT_buildtool.diff` — or re-add by hand:
   - the `PATCHES` entry
     `("patch_firstflash", 0x400d7a00, None, [(0x4001fb1a, "first_flash", "487800014eb94000fd34", 10)])`
   - the two allowlist regions `(0x400d7a00, 0x400d7a40)` and `(0x4001fb1a, 0x4001fb24)`
     in the "vs build_mutemode.py" check, or it will refuse the build.
   - ⚠️ the diff also adds a **general safety guard** (see below) — keep that part even if
     you drop the patch.
3. `python3 tools/build_mutemode_dt.py && python3 tools/emu_firstflash.py`
   then `python3 tools/build_bugbuilds.py --no-rebuild`.
4. Check the cave still fits: at park time `0x400d7a00`–`0x400d7a35` sat in the gap between
   the PERSONALIZE arrays (ending `0x400d79e4`) and `patch_trigscale` (`0x400d7b00`). Any
   later growth of `patch_mutemode` or the arrays eats into it — the build asserts the cave
   region is zero first, so it will refuse rather than collide, but re-place it if it does.

### Worth reviving on its own merits: the detour guard

The build-tool diff also adds a guard to `build_mutemode_dt.py` that refuses **any** detour
displacing more than 6 bytes if a relative branch (reusing `build_bugbuilds.assert_no_branch_into`)
or an absolute address anywhere in the image lands *inside* the displaced bytes. That is
independent of this feature and applies to the existing 8-byte detours (`mt_rebind`,
`fresh_bind`). It was reverted here only because it arrived in the same change. Consider
lifting it into the builders on its own.

### Gotcha for whoever revives this

ColdFire has no `move #imm,abs.l` — `move.l #TAG_MAGIC,SH_TAG` does not assemble
("operands mismatch"). Go through a register. This bit on the first assemble.

Full narrative: `NOTES.md` "Session 58 continued yet again, part 19".
