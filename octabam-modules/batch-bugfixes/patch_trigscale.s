| SPDX-License-Identifier: MIT
| SPDX-FileCopyrightText: 2026 Zac-Kyoti
| patch_trigscale -- fix the MIDI manual-trig stall (Plays Free + Direct + Per-Track scale)
|
| Root cause (NOTES.md "Session 5 part 3"): FUN_4009b5c8's SCALE_MODE("Per Track")-gated
| per-track scale-index seed reads with the AUDIO track stride (0x91a) and offset (+0x51)
| for every track index, including MIDI tracks 8..15. For a MIDI track that expression
| overshoots into the track's trig data -> DAT_8000663e[track] (== DAT_80006646[track-8])
| gets a garbage byte (0xff in the repro bank) instead of a 0..12 scale index. FUN_400a1eea
| then indexes DAT_400aba50[13] (the step-length table) with 255 -> huge garbage step
| length -> the MIDI step-advance gate is always false -> the track never leaves step 1.
|
| The corrupting code, raw asm 0x4009b6f2..0x4009b703 (18 bytes), fall-through of the
| `beq 0x4009b704` at 0x4009b6f0 (i.e. only when pattern SCALE_MODE +0x8e55 != 0):
|
|     4009b6f2  move.l  #0x91a,D0
|     4009b6f8  muls.l  D3,D0
|     4009b6fc  add.l   D2,D0            ; D2 = pattern*0x8ed8
|     4009b6fe  movea.l D1,A0            ; D1 = 0x400e21e0 + bank*0x9b340
|     4009b700  lea     (0x51,A0,D0*1),A0
|     4009b704  move.b  (A0),(0,A1,D3*1) ; A1 = 0x8000663e ; D3 = track (0..15)
|
| No room in place (18 bytes, D3 live as the store index at 0x4009b704), so detour to a
| code cave: keep the audio math for tracks 0..7, use the MIDI stride/offset for 8..15:
|     MIDI:  A0 = D1 + D2 + (D3-8)*0x8b0 + 0x48f9      (== what FUN_400a1eea's MIDI loop reads)
|
| Detour (18 bytes @ 0x4009b6f2):  jmp 0x400d7b00 ; then 6x nop
| Cave   (@ 0x400d7b00):           the type-split address math, then jmp back to 0x4009b704
|
| Assemble like build.py's stubs:  m68k-elf-as -mcpu=5407 ; ld -Ttext=<at> ; objcopy -O binary

    .equ  MIDI_STRIDE, 0x8b0
    .equ  MIDI_SCALE_OFF, 0x48f9
    .equ  AUDIO_STRIDE, 0x91a
    .equ  AUDIO_SCALE_OFF, 0x51
    .equ  BACK, 0x4009b704

    .text
    .global cave
cave:
    moveq   #7,%d0
    cmp.l   %d3,%d0
    blt.b   .Lmidi                  | 7 < track  ->  MIDI track (8..15)

    | ---- audio track (0..7): unchanged behaviour ----
    move.l  #AUDIO_STRIDE,%d0
    muls.l  %d3,%d0
    add.l   %d2,%d0
    movea.l %d1,%a0
    lea     (AUDIO_SCALE_OFF,%a0,%d0.l),%a0
    jmp     BACK

.Lmidi:
    | ---- MIDI track (8..15): A0 = D1 + D2 + (D3-8)*0x8b0 + 0x48f9 ----
    | D6 (pattern index) is dead past 0x4009b6d6, reuse it as the multiplier scratch.
    move.l  %d3,%d0
    subq.l  #8,%d0
    move.l  #MIDI_STRIDE,%d6
    muls.l  %d6,%d0
    add.l   %d2,%d0
    add.l   #MIDI_SCALE_OFF,%d0
    movea.l %d1,%a0
    adda.l  %d0,%a0
    jmp     BACK
