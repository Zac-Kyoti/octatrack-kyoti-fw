| SPDX-License-Identifier: MIT
| SPDX-FileCopyrightText: 2026 Zac Kyoti
| patch_triglock_bp -- ERASE_EMPTY_TRIGLESS_LOCKS beside BLACKPYRAMIDS_303 (KYOTI V1.8BC only).
|
| On a BLKPYRAMD track a trigless lock straight after a note is a TIE (tools/ot303/cf/control.c, the
| step hook's gate: "a whole step for each trigless lock or trigless trig straight after"), and an
| EMPTY one ties just as well: it is how a tie is placed. ERASE removes a trigless lock whose last
| p-lock was erased live, which on that track would cut the note short. So on a BLKPYRAMD track this
| entry replays the stock store and returns, and ERASE's cave never runs; on any other track it
| jumps to the cave's AUDIO entry `cave` (its first byte; octabam-modules/erase-empty-trigless-locks/
| patch_triglock.s). The MIDI detour at 0x400387b8 (FUN_40038668, 2026-11-20) goes straight to the
| cave's `cave_midi`, never through here: BLKPYRAMD is a machine on an audio track.
|
| The detour at 0x40038a5c (FUN_40038874's erase store) is `jsr` here instead of `jsr cave`. At the
| site: d7 = track (0..7: this is the AUDIO worker), d1 = 0xff, d2 = the param, a0 = the step's TRAC
| row + step*32, d4 = step*32; the displaced `move.b %d1,%a0@(0x59,%d2:l) ; add.l %d4,%d0`.
|
| "BLKPYRAMD track" is the machine's own test, signed_track() in control.c, on the same Part: the
| bank blob (0x46c82456) + 0x8ed80 + (Part index 0x100b14cf & 3) * 0x18b2; machine byte +0x22+t = 1
| (FLEX) and the signature 'O','T',1 at +60 + 30*t.
|
| Assembled only by build_erase_empty_trigless_locks.py when build_kyoti.py places it (triglock_bp
| = its address, --defsym CAVE = the cave's), so ERASE's own unit and image are unchanged.

    .equ  BANK,        0x46c82456
    .equ  PART_IDX,    0x100b14cf
    .equ  PART_OFF,    0x8ed80
    .equ  PART_STRIDE, 0x18b2
    .equ  SIG,         60
    .equ  PLOCK_OFF,   0x59

    .text
    .global tl_bp
tl_bp:
    lea     %sp@(-8),%sp
    movem.l %d0/%a1,%sp@
    moveq   #8,%d0
    cmp.l   %d0,%d7
    bcc.s   .Lstock                   | not an audio track: ERASE as always
    movea.l BANK,%a1
    adda.l  #PART_OFF,%a1
    mvz.b   PART_IDX,%d0
    and.l   #3,%d0
    mulu.w  #PART_STRIDE,%d0
    adda.l  %d0,%a1                   | a1 = the Part
    mvz.b   %a1@(0x22,%d7:l),%d0
    subq.l  #1,%d0
    bne.s   .Lstock                   | not FLEX: not BLKPYRAMD
    move.l  %d7,%d0
    mulu.w  #30,%d0
    adda.l  %d0,%a1
    mvz.b   %a1@(SIG),%d0
    cmpi.l  #0x4f,%d0                 | 'O'
    bne.s   .Lstock
    mvz.b   %a1@(SIG+1),%d0
    cmpi.l  #0x54,%d0                 | 'T'
    bne.s   .Lstock
    mvz.b   %a1@(SIG+2),%d0
    subq.l  #1,%d0
    bne.s   .Lstock
    movem.l %sp@,%d0/%a1              | a BLKPYRAMD track: the stock store only, the tie stays
    lea     %sp@(8),%sp
    move.b  %d1,%a0@(PLOCK_OFF,%d2:l)
    add.l   %d4,%d0
    rts
.Lstock:
    movem.l %sp@,%d0/%a1
    lea     %sp@(8),%sp
    jmp     CAVE
