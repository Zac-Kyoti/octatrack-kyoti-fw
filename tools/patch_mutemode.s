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

| part 18 addendum 14: ONE persisted word, and the menu index is DERIVED from it.
|
| The modes are listed OT / OTFX / OTFX-T / DT-T (increasing "stickiness"), which is not the
| order of the GATE values patch_softmute reads.  Renumbering GATE to match is not an option:
| hook 1 tests the modes as a CHAIN, so a mode's position in that chain is its instruction
| count, and moving OTFX-T from first-tested to second-tested would silently cost it two
| instructions per frame -- enough to break its bit-identity (one is enough; measured).
|
| Addendum 12 solved that with a SECOND word holding the menu index.  That was a mistake: two
| independently-persisted words can disagree, and on the user's first flash they did -- a unit
| coming from an older build had a GATE value stored but no menu index, so the menu could show
| one mode while the firmware ran another.  There is now ONE persisted word (GATE) and the
| menu index is computed from it every time it is needed:
|
|   GATE 0 "OT"  <-> UI 0        GATE 2 "DT-T"   <-> UI 3
|   GATE 1 "OTFX-T" <-> UI 2     GATE 3 "OTFX"   <-> UI 1
|
| ui_to_gate[] and gate_to_ui[] are inverses of each other; both are 4 bytes and both are read
| only by the getter/setter, i.e. once per key press.  The audio path pays nothing.
|
| DEFAULTS.  A unit with no valid battery data boots with 0x800000dc = 0 = "OT" -- verified in
| the emulator by booting with no poke at all and dumping the word and its shadow (both zero).
| That is also what an OS UPGRADE leaves behind, since it resets PERSONALIZE.
|
| PERSISTENCE.  The 0x800000xx words are VOLATILE -- boot re-images 0x80000000.. from ROM, so
| a raw `move.l %d0,GATE` is lost on the next power cycle.  The durable store is the
| checksummed 'ANDY' block in battery SRAM at 0x100fff00: boot restores runtime 0x80000070 <-
| shadow 0x100fff00 with memcpy length 0x64 (ending 0x800000d3, one byte short of GATE), and
| this build patches that length 0x64 -> 0x70 at all three restore sites so 0x800000d4..df
| ride along.  set_mutemode writes its shadow at 0x100fff6c (= 0x100fff00 + (GATE -
| 0x80000070)) and the PERSONALIZE key handler re-checksums the block for free
| (jmp 0x4001f23c @ 0x40069074).
    .equ GATE,         0x800000dc    | the ONE persisted word -- what patch_softmute reads
    .equ SH_GATE,      0x100fff6c    | battery-SRAM shadow = 0x100fff00 + (GATE - 0x80000070)

    .ifdef DT_MODE
    .equ N_MODES,   4                | menu order: OT / OTFX / OTFX-T / DT-T
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
gate_to_ui:                          | the exact inverse of ui_to_gate
    .byte 0                          | GATE 0 -> UI 0 "OT"
    .byte 2                          | GATE 1 -> UI 2 "OTFX-T"
    .byte 3                          | GATE 2 -> UI 3 "DT-T"
    .byte 1                          | GATE 3 -> UI 1 "OTFX"
    .align 2
    .endif

| ---- getter: GATE -> menu index -> its string ----
    .global get_mutemode
get_mutemode:
    move.l  GATE,%d0
    bpl.b   gm_hi
    moveq   #0,%d0                     | negative (impossible via the setter) -> OT
gm_hi:
    cmpi.l  #NMAX,%d0
    ble.b   gm_ok
    moveq   #0,%d0                     | out of range -> OT, never a silently wrong label
gm_ok:
    .ifdef DT_MODE
    lea     gate_to_ui,%a0             | GATE is not the menu order; translate
    moveq   #0,%d1
    move.b  (%a0,%d0.l),%d1
    move.l  %d1,%d0
    .endif
    lsl.l   #2,%d0
    lea     val_tbl,%a0
    move.l  (%a0,%d0.l),%d0
    rts

| ---- setter: (delta @ 4(sp), wrap @ 8(sp)) -- steps the MENU index, stores the GATE ----
    .global set_mutemode
set_mutemode:
    move.l  GATE,%d0
    bpl.b   sm_rng
    moveq   #0,%d0
sm_rng:
    cmpi.l  #NMAX,%d0
    ble.b   sm_cur
    moveq   #0,%d0                     | corrupt value -> treat as OT before stepping
sm_cur:
    .ifdef DT_MODE
    lea     gate_to_ui,%a0             | current GATE -> current menu index
    moveq   #0,%d1
    move.b  (%a0,%d0.l),%d1
    move.l  %d1,%d0
    .endif
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
    .ifdef DT_MODE
    lea     ui_to_gate,%a0             | menu index -> the value patch_softmute reads
    moveq   #0,%d1
    move.b  (%a0,%d0.l),%d1
    move.l  %d1,%d0
    .endif
    move.l  %d0,GATE                   | volatile runtime word
    move.l  %d0,SH_GATE                | battery-SRAM shadow -- the key handler re-checksums
    rts
