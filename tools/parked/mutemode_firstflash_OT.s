| SPDX-License-Identifier: MIT
| SPDX-FileCopyrightText: 2026 Zac-Kyoti
| PARKED 2026-09-25 -- NOT part of any build.  Was tools/patch_firstflash.s; renamed and moved
| here when the user rolled MUTEMODE_DT back to the flashed/confirmed 2026-09-21 build.  It was
| built and emulator-verified, never flashed.  To revive it (and for what it does and does not
| prove): tools/parked/README.md.  The symbol name `first_flash` and the label below are what the
| parked build-tool diff refers to -- do not rename them without updating that diff.
|
| patch_firstflash -- a freshly flashed MUTE MODE build always comes up in "OT".
|
| WHY THIS EXISTS.  MUTE MODE (GATE, 0x800000dc) persists in the battery-backed 'ANDY' block
| (shadow 0x100fff6c) and the boot restore copies it straight back.  That is what we want
| once the user has chosen a mode -- but it also means a unit that ran an EARLIER build keeps
| whatever GATE that build left behind (OTFX-T, DT-T, ...) and the new build boots straight
| into it.  "Defaults verified" in addendum 14 only covered a unit with NO battery data (the
| defaults path zero-fills the block); it never covered a unit with a stale, VALID block, which
| is exactly what a re-flash of a test unit is.  The checksum is valid, so stock takes no
| reset path at all.
|
| WHAT IT DOES.  One extra battery-backed longword -- the FIRST-FLASH TAG at 0x100fff70 --
| says "this block has been through a build carrying this patch".  At boot, immediately
| before the block is restored into RAM:
|
|     tag == TAG_MAGIC  ->  nothing (a normal boot: one load, one compare, one branch)
|     tag != TAG_MAGIC  ->  shadow GATE = 0 ("OT"), tag = TAG_MAGIC, re-seal the checksum
|
| so the very next instruction (the stock memcpy) restores GATE = 0.  From then on the tag is
| set and the user's own choice persists as before.  A unit with NO battery data takes the same
| branch harmlessly (its GATE is already 0).  Nothing else in the block is touched.
|
| WHERE.  The real boot function is the one whose restore site is 0x4001fb24 (verified by
| watching the three restore sites in a boot: the validate function 0x4001f340 is NOT on the
| power-up path; it belongs to a later settings reload).  We detour the two instructions just
| before that restore -- `pea 1 / jsr 0x4000fd34` at 0x4001fb1a, 10 bytes, a branch TARGET only
| at its first byte (0x4001faf0 `bnes 0x4001fb1a`) -- replay them exactly, and jump back to
| 0x4001fb24.  The existing `pea 0x64 -> pea 0x70` restore-length patch there is untouched.
|
| WHY 0x100fff70.  Stock references the ANDY block by absolute address only up to 0x100fff60
| (whole-image scan, 2026-09-25); 0x100fff70 is outside the 0x70-byte restore window, so the tag
| is never copied into RAM and has no runtime alias at all.  It is inside the checksummed 252
| bytes, which is why the checksum is re-sealed -- with the OS's OWN routine, 0x4001f23c, the
| one the PERSONALIZE key handler calls after every setter.  A wrong seal would make the NEXT
| boot see a bad checksum and take the wipe-everything defaults path, so this is the one place
| an error here would be expensive; the routine is self-contained (clobbers only d0/d1/a0).
|
| REGISTERS.  Entered by `jmp` from the middle of the boot function.  d3 (the "defaults ran"
| flag tested at 0x4001fb62) and a2 are live across this point and are NOT touched.  d0/d1/a0
| are scratch here: the very next thing that runs is the replayed `jsr`, and stock reloads
| every register it needs afterwards.
|
| TO FORCE ANOTHER RESET in a later build (e.g. if the mode numbering ever changes), change
| TAG_MAGIC.  Do not reuse a value from an earlier build.

    .equ SH_GATE,    0x100fff6c      | battery-SRAM shadow of MUTE MODE (0x800000dc)
    .equ SH_TAG,     0x100fff70      | first-flash tag -- outside the restore window
    .equ TAG_MAGIC,  0x4d4d4454      | "MMDT"
    .equ ANDY_SEAL,  0x4001f23c      | recompute + store the 'ANDY' checksum (stock, no args)
    .equ BOOT_FN,    0x4000fd34      | the displaced `jsr` target
    .equ BOOT_BACK,  0x4001fb24      | the stock restore memcpy setup, right after the detour

    .text
    .global first_flash
first_flash:
    move.l  SH_TAG,%d0
    cmpi.l  #TAG_MAGIC,%d0
    beq.b   ff_done                  | already tagged: a normal boot, nothing to do
    clr.l   SH_GATE                  | stale/absent mode -> "OT"
    move.l  #TAG_MAGIC,%d0           | ColdFire has no move #imm -> abs.l; go through a register
    move.l  %d0,SH_TAG
    jsr     ANDY_SEAL                | the checksum covers both words
ff_done:
    pea     1                        | displaced 0x4001fb1a (4 B)
    jsr     BOOT_FN                  | displaced 0x4001fb1e (6 B)
    jmp     BOOT_BACK
