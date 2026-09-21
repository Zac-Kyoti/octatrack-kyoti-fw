| SPDX-License-Identifier: MIT
| SPDX-FileCopyrightText: 2026 Zac-Kyoti
| patch_mutemode -- the "MUTE MODE" PERSONALIZE entry (a multi-value text option, not a
| checkbox).  Modeled on the stock LED BRIGHTNESS item (FUN_40068c80 getter / FUN_4006907c
| setter): a getter returns a char* shown in the right-hand column, a setter takes
| (delta, wrap) on the stack and clamps/wraps the value word.
|
|   MUTE MODE   0x800000dc   0 = "OT"     -> stock instant post-FX cut
|                            1 = "OTFX-T" -> patch_softmute: dry cuts, FX inserts ring tails,
|                                            and new trigs are suppressed (the -T suffix).
|                                            Was called "OT+FX" through addendum 11.
|                            2 = "DT-T"   -> patch_softmute: pure sequencer mute (Digitakt
|                                            style) -- the sounding voice rides its own amp
|                                            envelope, only new trigs are suppressed.
|                                            Was called "DT" through addendum 11.
|                            3 = "OTFX"   -> patch_softmute: hard cut + FX tails with the
|                                            SEQUENCER LEFT ALONE -- trigs keep firing and
|                                            voices keep restarting underneath, so unmuting
|                                            picks up exactly where the pattern would have
|                                            been.  The dry is cut every frame by hook 16.
|                                            2 and 3 are built only with --defsym DT_MODE=1.
|
| 0x800000dc is the same free PERSONALIZE word patch_softmute already reads as GATE, so
| 0 = a freshly-flashed unit behaves exactly like stock.
|
| PERSISTENCE.  The 0x800000xx words are VOLATILE -- boot re-images 0x80000000.. from ROM,
| so a raw `move.l %d0,MUTE_MODE` setting is lost on the next power cycle.  The durable
| store is the checksummed 'ANDY' block in battery SRAM at 0x100fff00; boot restores
| runtime 0x80000070 <- shadow 0x100fff00, memcpy length 0x64 (ends 0x800000d3 -- one byte
| short of MUTE MODE).  build_mutemode.py patches that length 0x64 -> 0x70 at all three
| restore sites (boot / validate / defaults), so 0x800000d4..df ride along; set_mutemode
| writes its shadow at 0x100fff6c (= 0x100fff00 + 0x800000dc - 0x80000070) and the
| PERSONALIZE key handler re-checksums the block for free (jmp 0x4001f23c @ 0x40069074).
| Mechanism lifted from octamax c78ff70 (hardware-confirmed there; not yet on our MKI).
|
| The renderer (FUN_40068e00) calls the getter with jsr and pushes D0 as the column text;
| D0/D1/A0/A1 are scratch.  The input handler (FUN_40068fd0) calls the setter as
| (*setter)(delta, wrap) -- delta at 4(sp), wrap at 8(sp) -- same ABI as set_notimer.
|   [YES]   -> (+1, wrap=1)   cycle with wraparound
|   [RIGHT] -> (+1, wrap=0)   clamp
|   [LEFT]  -> (-1, wrap=0)   clamp

| part 18 addendum 12: the menu's ORDER is decoupled from the value the hooks read.
|
| The user wants the modes listed OT / OTFX / OTFX-T / DT-T (increasing "stickiness").
| Renumbering GATE to match would be expensive in a way that is easy to miss: patch_softmute's
| hook 1 tests the modes as a CHAIN, so a mode's position in that chain is its instruction
| count, and moving OTFX-T from first-tested to second-tested would silently cost it two
| instructions per frame -- which is more than enough to break its bit-identity (measured:
| ONE is enough).  So GATE keeps the numbering every measurement in addendum 12 was taken
| with, and the menu gets its own word:
|
|   MUTE_UI  0x800000d8  the MENU index, 0..3, what the getter/setter cycle through
|   GATE     0x800000dc  what patch_softmute reads -- UI_TO_GATE[MUTE_UI]
|
|   UI 0 "OT"      -> GATE 0      UI 2 "OTFX-T" -> GATE 1
|   UI 1 "OTFX"    -> GATE 3      UI 3 "DT-T"   -> GATE 2
|
| The translation happens in the SETTER, i.e. once per key press, so it costs the audio path
| nothing at all.  Both words live in the 0x800000d4..df span the build's own battery-SRAM
| restore already covers (pea 0x64 -> 0x70), and the setter writes both shadows, so both
| persist across a power cycle.  A freshly flashed unit has both at 0 = OT, as before.
|
| ⚠ ONE-TIME NOTE AFTER FLASHING: a unit coming from an older build has a GATE value stored
| but no MUTE_UI, so the menu may show the wrong entry until MUTE MODE is set once.  Setting
| it once writes both words and they stay in step from then on.
    .equ MUTE_MODE,    0x800000d8    | the MENU index (0..3)
    .equ SH_MUTE_MODE, 0x100fff68    | battery-SRAM shadow = 0x100fff00 + (MUTE_MODE - 0x80000070)
    .equ GATE,         0x800000dc    | what patch_softmute reads
    .equ SH_GATE,      0x100fff6c    | its shadow
    .ifdef DT_MODE
    .equ N_MODES,   4                | OT / OTFX-T / DT-T / OTFX   (--defsym DT_MODE=1)
    .else
    .equ N_MODES,   2                | OT / OT+FX
    .endif
    .equ NMAX,      N_MODES - 1

    .text

| ---- label ----
    .global lbl_mutemode
lbl_mutemode:
    .asciz "MUTE MODE"
    .align 2

| ---- value strings + table ----
vm_0:
    .asciz "OT"
    .align 2
vm_1:
    .ifdef DT_MODE
    .asciz "OTFX"                    | hard cut + FX tails, sequencer untouched -- unmuting
    .else                            | picks up where the pattern would have been
    .asciz "OT+FX"
    .endif
    .align 2
    .ifdef DT_MODE
vm_2:
    .asciz "OTFX-T"                  | renamed from "OT+FX": the -T suffix marks the modes
    .align 2                         | that also stop the TRIGS
vm_3:
    .asciz "DT-T"                    | renamed from "DT", same reason
    .align 2
    .endif
val_tbl:
    .long vm_0
    .long vm_1
    .ifdef DT_MODE
    .long vm_2
    .long vm_3
    .endif

| ---- menu index -> the value patch_softmute reads ----
    .ifdef DT_MODE
ui_to_gate:
    .byte 0                          | UI 0 "OT"     -> GATE 0
    .byte 3                          | UI 1 "OTFX"   -> GATE 3
    .byte 1                          | UI 2 "OTFX-T" -> GATE 1
    .byte 2                          | UI 3 "DT-T"   -> GATE 2
    .align 2
    .endif

| ---- getter: return &val_tbl[clamp(MUTE_MODE, 0, NMAX)] ----
    .global get_mutemode
get_mutemode:
    move.l  MUTE_MODE,%d0
    bpl.b   gm_hi
    moveq   #0,%d0
gm_hi:
    cmpi.l  #NMAX,%d0
    ble.b   gm_ok
    moveq   #NMAX,%d0
gm_ok:
    lsl.l   #2,%d0
    lea     val_tbl,%a0
    move.l  (%a0,%d0.l),%d0
    rts

| ---- setter: (delta @ 4(sp), wrap @ 8(sp)) ----
    .global set_mutemode
set_mutemode:
    move.l  MUTE_MODE,%d0
    add.l   4(%sp),%d0
    tst.l   8(%sp)                     | wrap flag  (clobbers N/Z -> re-test d0 below)
    bne.b   sm_wrap
| ---- clamp to [0, NMAX] ----
    tst.l   %d0
    bpl.b   sm_clhi
    moveq   #0,%d0
    bra.b   sm_store
sm_clhi:
    cmpi.l  #NMAX,%d0
    ble.b   sm_store
    moveq   #NMAX,%d0
    bra.b   sm_store
| ---- wrap around [0, NMAX] ----
sm_wrap:
    cmpi.l  #NMAX,%d0
    ble.b   sm_wlo
    moveq   #0,%d0
    bra.b   sm_store
sm_wlo:
    tst.l   %d0
    bpl.b   sm_store
    moveq   #NMAX,%d0
sm_store:
    move.l  %d0,MUTE_MODE       | volatile runtime word (the MENU index, read by the getter)
    move.l  %d0,SH_MUTE_MODE    | battery-SRAM shadow -- the key handler re-checksums on return
    .ifdef DT_MODE
| ---- translate the menu index into the value patch_softmute reads, and persist that too ----
    lea     ui_to_gate,%a0
    moveq   #0,%d1
    move.b  (%a0,%d0.l),%d1
    move.l  %d1,GATE
    move.l  %d1,SH_GATE
    .else
    move.l  %d0,GATE            | 2-mode build: the menu index IS the gate
    move.l  %d0,SH_GATE
    .endif
    rts
