| SPDX-License-Identifier: MIT
| SPDX-FileCopyrightText: 2026 Zac-Kyoti; ported from octabam modules/analog-bassdrum/machine.s
| (repeat98, MIT), which measured these seams (and Machinedrum's before it).
|
| OT-303 registration: machine row 5 in the track's machine chooser and in SRC SETUP, stored as FLEX
| plus the signature 'O','T',1 in unused NEIGHBOR page bytes (part + 0x2a + 18 + 30 t), on any track,
| one per DSP core. A new assignment seeds both Part copies with the OT-303 defaults (FLEX's values
| stashed beside the signature, put back when the track leaves OT-303); reselecting keeps the patch. Each stub is reached by a detour (tools/build_ot303.py) and replays the stock
| instructions it displaced. ANALOG BD's engine browser is not ported (no detours on the pool).
        .text
        .global ot_machine_name, ot_src_names, ot_main_commit, ot_src_commit, ot_src_commit2
        .global ot_name_a, ot_name_b, ot_setup_row, ot_chooser_row, ot_setup_open, ot_chooser_open
        .global ot_setup_edit6, ot_setup_draw6, ot_resolve_pb, ot_validate, ot_stock_validate
        .global ot_tick_hook, ot_glyph, ot_step_hook, ot_note_hook, ot_chooser_level, ot_setup_value_hook
        .global ot_slic_a, ot_slic_b, ot_slic_c, ot_pmtr_pb

        .equ    OT_ROW, 5
        .equ    FLEX, 1
        .equ    SRC_CURSOR, 0x460d5c30
        .equ    BANK_PTR, 0x46c82456
        .equ    PART_OFF, 0x8ed80
        .equ    SRAM_PART, 0x100a4ece
        .equ    SIG_OFF, 0x2a + 18
        .equ    PAGE2_GAP, 0x1da - 0x2a
        .equ    PB_TABLE, 0x400d5f38

| a0 = the Part, d0 = the track, d1 = 1 sign / 0 clear: control.c ot_assign (FLEX's values stashed
| while the track is an OT-303, put back when it leaves; both Part copies). Keeps every register.
ot_sig_write:
        lea     -16(%sp),%sp
        movem.l %d0-%d1/%a0-%a1,(%sp)
        move.l  %d1,-(%sp)
        move.l  %d0,-(%sp)
        move.l  %a0,-(%sp)
        jsr     ot_assign
        lea     12(%sp),%sp
        movem.l (%sp),%d0-%d1/%a0-%a1
        lea     16(%sp),%sp
        rts

| the chooser's row name: row 5 is ours, the rest stock (0x400334d8 displaced: move.l d2,-(sp);
| move.l 8(sp),d1)
ot_machine_name:
        move.l  4(%sp),%d0
        cmpi.l  #OT_ROW,%d0
        beq.s   1f
        move.l  %d2,-(%sp)
        move.l  8(%sp),%d1
        jmp     (0x400334de).l
1:      lea     ot_name(%pc),%a0
        move.l  %a0,%d0
        rts

| SRC SETUP's six machine names (the stock five, then ours): the operand of `lea abs.l,a5`
        .balign 4
ot_src_names:
        .long   0x400b3eac
        .long   0x400b3e98
        .long   0x400b7c67
        .long   0x400b5413
        .long   0x400b7a63
        .long   ot_name

ot_admit:
        lea     -20(%sp),%sp
        movem.l %d1/%a0-%a1,8(%sp)
        move.l  %a0,(%sp)
        move.l  %d0,4(%sp)
        jsr     ot_admit_track
        movem.l 8(%sp),%d1/%a0-%a1
        lea     20(%sp),%sp
        rts

| the main chooser's commit (0x4007981c: its three displaced words replayed below)
ot_main_commit:
        lea     -12(%sp),%sp
        movem.l %d0-%d1/%a0,(%sp)
        movea.l %a1,%a0
        adda.l  %d0,%a0
        adda.l  #PART_OFF,%a0
        move.l  %d1,%d0
        cmpi.l  #OT_ROW,%d4
        bne.s   .mc_other
        bsr     ot_admit
        tst.l   %d0
        beq.s   .mc_refuse
        move.l  %d1,%d0
        moveq   #1,%d1
        bsr     ot_sig_write
        moveq   #FLEX,%d4
        bra.s   .mc_store
.mc_other:
        moveq   #0,%d1
        bsr     ot_sig_write
.mc_store:
        movem.l (%sp),%d0-%d1/%a0
        lea     12(%sp),%sp
        .word   0x7710,0x1084,0xd081
        jmp     (0x40079822).l
.mc_refuse:
        movem.l (%sp),%d0-%d1/%a0
        lea     12(%sp),%sp
        pea     0x30.w
        pea     ot_reject_name(%pc)
        jsr     (0x4005a2b8).l
        addq.l  #8,%sp
        jmp     (0x4007989c).l

| SRC SETUP's two commit paths
ot_src_commit:
        pea     (0x4005a61c).l
        bra.s   ot_src_common
ot_src_commit2:
        pea     (0x4005a856).l
ot_src_common:
        move.l  (SRC_CURSOR).l,%d1
        lea     -12(%sp),%sp
        movem.l %d0/%d2/%a0,(%sp)
        movea.l %a1,%a0
        adda.l  %d0,%a0
        adda.l  #PART_OFF,%a0
        move.l  %d2,%d0
        cmpi.l  #OT_ROW,%d1
        bne.s   .sc_other
        bsr     ot_admit
        tst.l   %d0
        beq.s   .sc_refuse
        move.l  %d2,%d0
        moveq   #1,%d1
        bsr     ot_sig_write
        moveq   #FLEX,%d1
        bra.s   .sc_go
.sc_other:
        move.l  %d1,-(%sp)
        moveq   #0,%d1
        bsr     ot_sig_write
        move.l  (%sp)+,%d1
.sc_go:
        movem.l (%sp),%d0/%d2/%a0
        lea     12(%sp),%sp
        rts
.sc_refuse:
        movem.l (%sp),%d0/%d2/%a0
        lea     12(%sp),%sp
        moveq   #0,%d1
        move.b  (%a0),%d1
        move.l  %d1,(SRC_CURSOR).l
        pea     0x30.w
        pea     ot_reject_name(%pc)
        jsr     (0x4005a2b8).l
        addq.l  #8,%sp
        rts

ot_setup_open:
        move.b  (%a0),%d3
        move.l  %d0,-(%sp)
        mvs.b   %d3,%d0
        bsr     ot_row_type
        move.l  %d0,%d3
        move.l  (%sp)+,%d0
        mvs.b   %d3,%d4
        pea     (0x400bb704).l
        jmp     (0x400585e6).l

| SETUP's editor and drawer use the track's FLEX slot for row 5 (d2/d6 = the row; replays d * 6)
ot_setup_edit6:
        cmpi.l  #FLEX,%d2               | FLEX's row on an OT-303 track shows FLEX's stash: not editable
        bne.s   2f                      | here (its bytes are the OT-303's SETUP knobs)
        lea     -16(%sp),%sp
        movem.l %d0-%d1/%a0-%a1,(%sp)
        move.l  %d4,-(%sp)
        jsr     ot_track_is
        addq.l  #4,%sp
        tst.l   %d0
        movem.l (%sp),%d0-%d1/%a0-%a1
        lea     16(%sp),%sp
        beq.s   2f
        jmp     (0x4003a624).l
2:      cmpi.l  #OT_ROW,%d2
        bne.s   1f
        moveq   #FLEX,%d2
1:      move.l  %d2,%d0
        lsl.l   #3,%d0
        add.l   %d2,%d2
        sub.l   %d2,%d0
        jmp     (0x4003a536).l
ot_setup_draw6:
        clr.l   (ot_preview_flex).l
        cmpi.l  #FLEX,%d6
        bne.s   2f
        moveq   #1,%d7
        move.l  %d7,(ot_preview_flex).l
2:      cmpi.l  #OT_ROW,%d6
        bne.s   1f
        moveq   #FLEX,%d6
1:      move.l  %d6,%d7
        lsl.l   #3,%d7
        add.l   %d6,%d6
        sub.l   %d6,%d7
        jmp     (0x4003cda0).l

ot_chooser_open:
        mvs.b   (%a0),%d0
        bsr     ot_row_type
        move.l  %d0,-(%sp)
        pea     (0x460e7386).l
        jmp     (0x40078890).l

| the machine window's focus (0x400788c4, a0 = the track's type byte): stock opens STATIC and FLEX
| (type < 2) on the sample list, any other machine on the machine list. An OT-303 (stored as FLEX)
| reads as its row (5): a track double-tap shows the machine list, as for THRU / NEIGHBOR / PICKUP.
ot_chooser_level:
        mvz.b   (%a0),%d0
        bsr     ot_row_type
        moveq   #1,%d2
        cmp.l   %d0,%d2
        jmp     (0x400788ca).l

ot_name_a:
        bsr.s   ot_name_pick
        jmp     (0x4003d722).l
ot_name_b:
        bsr.s   ot_name_pick
        jmp     (0x4004c374).l
ot_name_pick:
        bsr     ot_row_type
        lea     ot_src_names(%pc),%a0
        move.l  (%a0,%d0.l*4),%d1
        rts

ot_setup_row:
        mvs.b   (%a0),%d0
        lea     24(%sp),%sp
        bsr.s   ot_row_type
        jmp     (0x4003c986).l
ot_chooser_row:
        mvs.b   (%a0),%d0
        bsr.s   ot_row_type
        cmp.l   %d0,%d2
        bne.s   1f
        jmp     (0x400786ce).l
1:      jmp     (0x400786fc).l
| d0 = the stored type, a0 -> it in the Part: 5 for an OT-303 track
ot_row_type:
        lea     -20(%sp),%sp
        movem.l %d1/%a0-%a1,8(%sp)
        move.l  %d0,(%sp)
        move.l  %a0,4(%sp)
        jsr     ot_type
        movem.l 8(%sp),%d1/%a0-%a1
        lea     20(%sp),%sp
        rts

ot_resolve_pb:
        mvs.b   %d5,%d0
        bsr     ot_row_type
        cmpi.l  #OT_ROW,%d0
        bne.s   1f
        move.l  %a0,-(%sp)
        jsr     ot_track_page
        addq.l  #4,%sp
        jmp     (0x40031ed6).l
1:      lea     (PB_TABLE).l,%a0
        jmp     (0x40031ece).l

| MT13: the LFO page's PMTR formatter (0x4003bf64) names a machine destination from PB_TABLE by the
| track's stored type (a0 -> the Part type byte; d1 = the track): an OT-303 (stored as FLEX) reads row 5,
| our page, so it lists PTCH CUT RES ENV DEC ACC
ot_pmtr_pb:
        mvs.b   (%a0),%d0
        bsr     ot_row_type
        lea     (PB_TABLE).l,%a0
        jmp     (0x4003c054).l          | a2 = PB_TABLE[d0]

ot_validate:
        jmp     ot_validate_part
ot_stock_validate:
        lea     -96(%sp),%sp
        movem.l %d2-%d7/%a2-%fp,(%sp)
        jmp     (0x40002320).l

| publishes our page in the page table's row 5 (memory writes only: no UI or kernel call here)
ot_tick_hook:
        jsr     0x4005213c
        jsr     0x4007e940
        jsr     ot_ui_tick
        jmp     0x40052228

| the side columns' machine letter: the stock drawer (0x40040088, track d4, its type in a4) pushes the
| glyph from a table at fp - 24 indexed by type, or the M glyph (0x400bb3a6) for a MASTER T8; an
| OT-303 track gets a 3 (control.c ot_glyph3; the user's choice). Replays the 16 displaced bytes
| (0x4004012c: pea 1(a2); move.l d3,-(sp); pea 0x400bf10a; the glyph) and goes on at the draw call.
| d0/d1/a0/a1 are free here (the draw call clobbers them).
ot_glyph:
        move.l  %d4,-(%sp)
        jsr     ot_track_is
        addq.l  #4,%sp
        pea     1(%a2)
        move.l  %d3,-(%sp)
        pea     (0x400bf10a).l
        tst.l   %d0
        bne.s   1f
        move.l  -24(%fp,%a4.l*4),-(%sp)
        jmp     (0x4004013c).l
1:      pea     ot_glyph3
        jmp     (0x4004013c).l

ot_name:                                | MT17: the machine's display name (BlackPyramid_303; 9 characters fit
        .asciz  "BLKPYRAMD"             | the chooser, SRC SETUP, the track box and PLAYBACK>name, ot_emu)
ot_reject_name:
        .asciz  "ONE 303 PER CORE!"
        .balign 2

| the sequencer's step handler 0x4009d1e8 (track, bank, pattern, step, ...; about 3 frames before the
| step): control.c ot_step reads an OT-303 note step's gate and slide first. Replays the 8 displaced
| bytes (lea -104(sp),sp; movem.l d2-d7/a2-a6,(sp)) and goes on after them. d0/d1/a0/a1 are free at
| the entry (the handler loads them before it reads them).
ot_step_hook:
        move.l  16(%sp),-(%sp)
        move.l  16(%sp),-(%sp)
        move.l  16(%sp),-(%sp)
        move.l  16(%sp),-(%sp)
        jsr     ot_step
        lea     (16-104,%sp),%sp
        movem.l %d2-%d7/%a2-%fp,(%sp)
        jmp     0x4009d1f0

| the step handler queues a note (0x4009d422: the trig's condition passed, code 29 goes in for track
| d7): control.c ot_note queues its gate and slide. Replays the 12 displaced bytes (lea 0x46c7a810,a0;
| moveq #29,d2; move.l d2,(a0,d7.l*4)). d0/d1/a0/a1 are reloaded before they are read after it.
ot_note_hook:
        move.l  %d7,-(%sp)
        jsr     ot_note
        addq.l  #4,%sp
        lea     (0x46c7a810).l,%a0
        moveq   #29,%d2
        move.l  %d2,(%a0,%d7.l*4)
        jmp     (0x4009d42e).l

| SRC SETUP's value read (0x4003ce02: d6 = the byte at Part + 0x1da + fp + d7 + d3, fp = part 0x18b2 +
| track 30, d7 = row 6, d3 = the knob): control.c ot_setup_value (FLEX's stash for FLEX's row on an
| OT-303 track). Replaces the 20 bytes up to 0x4003ce16; a1 is live after them, d0/d1/a0 are not.
ot_setup_value_hook:
        move.l  %a1,-(%sp)
        move.l  %d7,-(%sp)
        move.l  %d3,-(%sp)
        move.l  %fp,-(%sp)
        jsr     ot_setup_value
        lea     12(%sp),%sp
        move.l  (%sp)+,%a1
        move.b  %d0,%d6
        jmp     (0x4003ce16).l

| Three stock reads of the current machine's SLIC byte (address = the register + 585563): control.c
| ot_setup_byte gives an OT-303 track FLEX's own value. Each saves d0/d1/a0/a1 and puts the result
| where stock would: ot_slic_a (0x4003b33c, LEN's label: d0's low byte, a1 the address),
| ot_slic_b (0x40044dbe: tst.b, the CCR kept to its beq), ot_slic_c (0x4004fee2: d6's low byte).
ot_slic_a:
        adda.l  #585563,%a1
        lea     -16(%sp),%sp
        movem.l %d0-%d1/%a0-%a1,(%sp)
        move.l  %a1,-(%sp)
        jsr     ot_setup_byte
        addq.l  #4,%sp
        move.b  %d0,3(%sp)
        movem.l (%sp),%d0-%d1/%a0-%a1
        lea     16(%sp),%sp
        jmp     (0x4003b344).l
ot_slic_b:
        adda.l  #585563,%a0
        lea     -16(%sp),%sp
        movem.l %d0-%d1/%a0-%a1,(%sp)
        move.l  %a0,-(%sp)
        jsr     ot_setup_byte
        addq.l  #4,%sp
        tst.b   %d0
        movem.l (%sp),%d0-%d1/%a0-%a1
        lea     16(%sp),%sp
        jmp     (0x40044dc6).l
ot_slic_c:
        adda.l  #585563,%a0
        lea     -16(%sp),%sp
        movem.l %d0-%d1/%a0-%a1,(%sp)
        move.l  %a0,-(%sp)
        jsr     ot_setup_byte
        addq.l  #4,%sp
        move.b  %d0,%d6
        movem.l (%sp),%d0-%d1/%a0-%a1
        lea     16(%sp),%sp
        jmp     (0x4004feea).l
