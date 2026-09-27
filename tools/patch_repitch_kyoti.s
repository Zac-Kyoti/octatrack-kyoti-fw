| SPDX-License-Identifier: MIT
| SPDX-FileCopyrightText: 2026 Zac-Kyoti
|
| repitch-kyoti, gate 1 (ColdFire only) -- scope: reference/handoffs/REPITCH_KYOTI_SCOPE.md
|
| TSTR grows three tempo-following varispeed values on STATIC and FLEX:
|     4 RPCH   stock 2-tap linear (the DSP's own dry path)
|     5 RPS9   linear + 12-bit truncate      -- DSP side NOT built yet (gate 3)
|     6 RPSP   ZOH + 12-bit + ~26 kHz hold   -- DSP side NOT built yet (gate 4)
| In gate 1 all three PLAY IDENTICALLY (linear): the voice renderer resolves
| any of them to OFF and plays dry; only the increment carries the tempo.
| The sample's own TIMESTRETCH attribute gains REPITCH/RPS9/RPSP (raw 4/5/6)
| after BEAT; under SETUP AUTO each sample's own setting applies, mode
| included (Session 107 revision, matching the manual's AUTO contract;
| supersedes Session 106's AUTO-always-RPCH).
|
| QUANT -- the reclaimed PTCH slot: on a repitch track the PTCH dial draws as
| an 8-way ratio selector and the PTCH word (record +0, ui<<8, 64=neutral)
| becomes its storage. The composed word is captured in pitch_gate, so
| p-locks and scenes move QUANT. Buckets of 15 ui units, neutral centred:
|     ui 4..26  27..41 42..56 57..71 72..86 87..101 102..116 117..124
|     1/2       2/3    3/4    1/1    5/4    4/3     3/2      2/1
| The ratio multiplies the tempo scale EXACTLY (integer p/q), and the
| product octave-folds in the integer domain (D doubles while N > 2D), so
| the increment never exceeds 2x AND never leaves the rational grid -- the
| polyrhythm closes instead of drifting. PTCH itself is never applied on a
| repitch track (neutral 0x4000), so leaving RPCH* restores plain PTCH
| behaviour with whatever the knob last held.
|
| The finished increment's low 2 bits carry modeoff (0 RPCH / 1 RPS9 /
| 2 RPSP): gate-2 pre-staging for the DSP dispatch. Repitch tracks only;
| worth 3/2^26 of a sample per sample, inaudible. The gate-2 open question
| (a stock track's increment can end in 01/10 by chance) is in the scope §4.
|
| Ported in part from refs/octabam/modules/repitch/repitch.s (MIT, Sam
| Banks) -- rp_source's shape, the three builder hooks, the ATTR hooks.
| Every borrowed site byte-verified against our image, Session 106.

        .text
        .global rate_gate
        .global pitch_gate
        .global rate_hook
        .global tstr_resolve
        .global tstr_fmt
        .global quant_widget
        .global qdial1
        .global qdial2
        .global qdial3
        .global qdial4
        .global attr_label
        .global attr_up
        .global attr_down

        .equ    LANES, 0x80000510       | per-track ColdFire records, 48 B
        .equ    VOICES, 0x800049d8      | per-track voices, 168 B; settings ptr +8, machine +20
        .equ    PICKUP_M, 4             | voice +20: a pickup keeps stock's grains
        .equ    STATES, 0x80004898      | per-track 40 B builder states
        .equ    CUR_STATE, 0x800062a4   | -> the state the builder is on
        .equ    UI_TRACK, 0x80000000
        .equ    PROJECT_BPM24, 0x8000181c
        .equ    TSTR_AUTO, 1
        .equ    RPCH, 4
        .equ    RPSP, 6
        .equ    BPM24_MIN, 720          | the firmware's own tempo range, 30..300 BPM
        .equ    BPM24_MAX, 7200
        .equ    INC_MAX, 0x08000000     | 2x in the Q26 increment
        .equ    SPRINTF, 0x40013a08
        .equ    KNOB, 0x400479b4        | the stock PTCH dial; value -1 draws its frame alone
        .equ    PTCH_FMT, 0x4003b4b0    | A[0] of STATIC/FLEX/PICKUP -- only playback slot 0 uses it
        .equ    NAME_ST, 0x400d3032     | STATIC slot-0 caption 'PTCH', 6 B (E+0x4e)
        .equ    NAME_FX, 0x400d31c4     | FLEX   slot-0 caption -- the image is SDRAM, writable
        .equ    TXT_MEASURE, 0x40012f30 | (font, -1, str) -> px width
        .equ    TXT_DRAW, 0x40012bd8    | (font, canvas, x, y, -1, str)
        .equ    FONT, 0x400ba876
        .equ    STR_UNK, 0x400b442a     | stock "???"
        .equ    STR_ERROR, 0x400b94f6   | stock "ERROR"

| ---------------------------------------------------------------------------
| d1 = track  ->  d0 = bpm24 | modeoff<<16 when a repitch mode is in force
| (SETUP 4/5/6, or AUTO with the sample's TSMODE = 4 -> modeoff 0), the track
| is not a PICKUP and the sample's tempo is in range; 0 otherwise.
| Every other register preserved.
rp_source:
        lea     -12(%sp),%sp
        movem.l %d1-%d2/%a0,(%sp)
        moveq   #0,%d0
        moveq   #7,%d2
        cmp.l   %d2,%d1
        bhi     .rs_out
        moveq   #48,%d2
        mulu.l  %d1,%d2
        lea     (LANES).l,%a0
        moveq   #0,%d0
        move.b  28(%a0,%d2.l),%d0       | SETUP TSTR, zero-extended
        move.l  %d0,%d2
        move.l  #168,%d0
        mulu.l  %d0,%d1
        lea     (VOICES).l,%a0
        moveq   #PICKUP_M,%d0
        cmp.b   20(%a0,%d1.l),%d0
        bne.s   .rs_bound
        moveq   #0,%d0
        bra     .rs_out
.rs_bound:
        movea.l 8(%a0,%d1.l),%a0        | the bound sample's settings
        moveq   #0,%d0
        move.l  %a0,%d1
        beq     .rs_out
        moveq   #RPCH,%d1
        cmp.l   %d1,%d2
        blt.s   .rs_auto
        moveq   #RPSP,%d1
        cmp.l   %d1,%d2
        bgt     .rs_out
        subi.l  #RPCH,%d2               | modeoff 0..2 from SETUP
        bra.s   .rs_on
.rs_auto:
        moveq   #TSTR_AUTO,%d1
        cmp.l   %d1,%d2
        bne     .rs_out
        move.l  0x110(%a0),%d2          | AUTO: the sample's own TSMODE
        moveq   #RPCH,%d1               | carries the mode (manual: each
        cmp.l   %d1,%d2                 | sample its own setting)
        blt     .rs_out
        moveq   #RPSP,%d1
        cmp.l   %d1,%d2
        bgt     .rs_out
        subi.l  #RPCH,%d2               | modeoff from the sample
.rs_on:
        move.l  0x114(%a0),%d1          | the sample's BPMx24
        cmpi.l  #BPM24_MIN,%d1
        blt.s   .rs_out
        cmpi.l  #BPM24_MAX,%d1
        bgt.s   .rs_out
        swap    %d2                     | modeoff<<16
        move.l  %d1,%d0
        or.l    %d2,%d0
.rs_out:
        movem.l (%sp),%d1-%d2/%a0
        lea     12(%sp),%sp
        rts

| d0 = ui value (the PTCH slot's 4..124 domain)  ->  d0 = QUANT index 0..7.
| 15-unit buckets from ui 12; neutral 64 sits mid-bucket in 1/1.
rk_bucket:
        move.l  %d1,-(%sp)
        moveq   #12,%d1
        sub.l   %d1,%d0
        bpl.s   1f
        moveq   #0,%d0
1:      moveq   #15,%d1
        divu.l  %d1,%d0
        moveq   #7,%d1
        cmp.l   %d1,%d0
        bls.s   2f
        move.l  %d1,%d0
2:      move.l  (%sp)+,%d1
        rts

| ---------------------------------------------------------------------------
| 0x4000406a, the playback-increment builder: d3 is free from entry to
| 0x40004176 (octabam, hardware-proven on this image) and carries this
| track's packed word to the two hooks below. Then the displaced
| `btst #4,67(sp); bne` (the per-frame recompute flag).
rate_gate:
        lea     -8(%sp),%sp
        movem.l %d0-%d1,(%sp)
        move.l  (CUR_STATE).l,%d1
        subi.l  #STATES,%d1
        moveq   #40,%d3
        divu.l  %d3,%d1                 | the track
        bsr     rp_source
        move.l  %d0,%d3                 | bpm | modeoff<<16 (0 = not repitch)
        movem.l (%sp),%d0-%d1
        lea     8(%sp),%sp
        btst    #4,67(%sp)              | displaced
        bne.s   .rg_compute
        jmp     (0x40004072).l
.rg_compute:
        jmp     (0x4000407a).l

| 0x4000409e: on a repitch track the composed PTCH word (p-locks and scenes
| included) becomes QUANT -- its bucket joins d3 at bits 24..26 -- and the
| word the table path sees is neutral 0x4000. Stock path untouched.
pitch_gate:
        tst.l   %d3
        bne.s   .pg_rp
        .word   0x71d6                  | displaced: mvz.w (%a6),%d0
        bra.s   .pg_cmp
.pg_rp:
        .word   0x71d6                  | the composed word, for QUANT
        lsr.l   #8,%d0                  | ui 4..124
        bsr     rk_bucket
        swap    %d0                     | idx<<16
        lsl.l   #8,%d0                  | idx<<24
        or.l    %d0,%d3
        move.l  #0x4000,%d0             | PTCH is not applied
.pg_cmp:
        .word   0xa346                  | displaced: mov3q #1,%d6
        .word   0x0c40,0x4000           | displaced: cmpi.w #0x4000,%d0
        jmp     (0x400040a6).l

| 0x40004100: finish the stock rate (RATE applied), then scale by
| (project * p) / (sample * q), exactly: N and D are 16-bit-range integer
| products; D doubles while N > 2D (the octave fold, exact); then
| inc = (inc0 div D)*N + ((inc0 mod D)*N) div D. All intermediates bounded
| (N <= 36000, post-fold N <= 2D, q^*N <= 2*inc0 <= INC_MAX). Low 2 bits
| then carry modeoff for the future DSP dispatch.
rate_hook:
        .word   0xa1c0                  | displaced: movclr.l %acc0,%d0 (V4e)
        asr.l   %d6,%d0                 | displaced
        tst.l   %d3
        beq     .rh_store
        lea     -20(%sp),%sp
        movem.l %d1-%d2/%d4-%d5/%a0,(%sp)
        move.l  (PROJECT_BPM24).l,%d2
        cmpi.l  #BPM24_MIN,%d2
        blt     .rh_restore
        cmpi.l  #BPM24_MAX,%d2
        bgt     .rh_restore
        move.l  %d3,%d4
        moveq   #24,%d5
        lsr.l   %d5,%d4                 | QUANT index
        add.l   %d4,%d4
        lea     .rk_ratios(%pc),%a0
        moveq   #0,%d1
        move.b  (%a0,%d4.l),%d1         | p
        mulu.l  %d1,%d2                 | N = project * p
        moveq   #0,%d1
        move.b  1(%a0,%d4.l),%d1        | q
        move.l  %d3,%d4
        andi.l  #0xffff,%d4             | sample bpm24
        mulu.l  %d4,%d1                 | D = sample * q
.rh_fold:
        move.l  %d1,%d5
        add.l   %d5,%d5
        cmp.l   %d5,%d2
        bls.s   .rh_folded
        move.l  %d5,%d1                 | D <<= 1: an octave down, still exact
        bra.s   .rh_fold
.rh_folded:
        move.l  %d0,%d5
        divu.l  %d1,%d5                 | q^
        move.l  %d5,%d4
        mulu.l  %d1,%d4
        sub.l   %d4,%d0                 | r
        mulu.l  %d2,%d5                 | q^ * N
        mulu.l  %d2,%d0                 | r * N
        divu.l  %d1,%d0
        add.l   %d5,%d0
        cmpi.l  #INC_MAX-4,%d0          | -4: the mode tag below must never
        bls.s   .rh_tag                 | push the result past stock's own
        move.l  #INC_MAX-4,%d0          | 2.0 ceiling (worth 2^-24, inaudible)
.rh_tag:
        move.l  %d3,%d5
        swap    %d5
        andi.l  #3,%d5                  | modeoff
        moveq   #-4,%d4
        and.l   %d4,%d0
        or.l    %d5,%d0
.rh_restore:
        movem.l (%sp),%d1-%d2/%d4-%d5/%a0
        lea     20(%sp),%sp
.rh_store:
        move.l  %d0,36(%a3)             | displaced; CPU and DSP both use it
        jmp     (0x40004108).l

| 0x40007d96, in the voice renderer: d1 is the resolved TSTR. All three
| repitch values resolve to OFF -- every renderer reader takes the dry path,
| forwards and back. Stock's next line still turns a PICKUP's 0 into 2.
tstr_resolve:
        moveq   #RPCH,%d2
        cmp.l   %d2,%d1
        blt.s   .tr_stock
        moveq   #RPSP,%d2
        cmp.l   %d2,%d1
        bgt.s   .tr_stock
        moveq   #0,%d1
.tr_stock:
        .word   0x712a,0x0014           | displaced: mvs.b 20(%a2),%d0
        moveq   #4,%d2                  | displaced
        jmp     (0x40007d9c).l

| ---------------------------------------------------------------------------
| void fmt(char *buf, int raw): sprintf's buf is already at 4(sp); replacing
| raw at 8(sp) with the label makes the stock sprintf tail print it.
tstr_fmt:
        move.l  8(%sp),%d0
        moveq   #RPSP,%d1
        cmp.l   %d1,%d0
        bhi.s   .tf_unknown
        lea     .tf_tab(%pc),%a0
        move.w  (%a0,%d0.l*2),%d1
        andi.l  #0xffff,%d1
        adda.l  %d1,%a0
        move.l  %a0,8(%sp)
        jmp     (SPRINTF).l
.tf_unknown:
        lea     (STR_UNK).l,%a0
        move.l  %a0,8(%sp)
        jmp     (SPRINTF).l
.tf_tab:
        .word   .t0-.tf_tab,.t1-.tf_tab,.t2-.tf_tab,.t3-.tf_tab
        .word   .t4-.tf_tab,.t5-.tf_tab,.t6-.tf_tab
.t0:    .asciz  "OFF"
.t1:    .asciz  "AUTO"
.t2:    .asciz  "NORM"
.t3:    .asciz  "BEAT"
.t4:    .asciz  "RPCH"
.t5:    .asciz  "RPS9"
.t6:    .asciz  "RPSP"
        .balign 2

| -> d0 = 1 when the PTCH cell should draw as QUANT for the UI track.
| DISPLAY truth, distinct from rp_source's ENGAGEMENT truth: the lane's
| SETUP byte decides (4..6), because the voice's sample binding is not
| trustworthy from the UI thread while the track is idle. A bound sample
| whose tempo is out of range vetoes (that track plays stock); an unbound
| voice is optimistic. AUTO still needs the binding (conservative: the
| stock dial until the sample's TSMODE is reachable). PICKUP never QUANTs.
rp_ui_gate:
        lea     -12(%sp),%sp
        movem.l %d1-%d2/%a0,(%sp)
        moveq   #0,%d0
        move.b  (UI_TRACK).l,%d0
        moveq   #7,%d1
        cmp.l   %d1,%d0
        bhi     .ug_no
        move.l  %d0,%d2                 | track
        moveq   #48,%d1
        mulu.l  %d2,%d1
        lea     (LANES).l,%a0
        moveq   #0,%d0
        move.b  28(%a0,%d1.l),%d0       | SETUP TSTR
        move.l  #168,%d1
        mulu.l  %d2,%d1
        lea     (VOICES).l,%a0
        adda.l  %d1,%a0                 | the track's voice
        moveq   #PICKUP_M,%d1
        cmp.b   20(%a0),%d1
        beq     .ug_no
        moveq   #RPCH,%d1
        cmp.l   %d1,%d0
        blt.s   .ug_auto
        moveq   #RPSP,%d1
        cmp.l   %d1,%d0
        bgt.s   .ug_no
        movea.l 8(%a0),%a0              | bound settings, or 0
        move.l  %a0,%d1
        beq.s   .ug_yes
        move.l  0x114(%a0),%d1
        cmpi.l  #BPM24_MIN,%d1
        blt.s   .ug_no
        cmpi.l  #BPM24_MAX,%d1
        bgt.s   .ug_no
.ug_yes:
        moveq   #1,%d0
        bra.s   .ug_out
.ug_auto:
        moveq   #TSTR_AUTO,%d1
        cmp.l   %d1,%d0
        bne.s   .ug_no
        movea.l 8(%a0),%a0
        move.l  %a0,%d1
        beq.s   .ug_no
        move.l  0x110(%a0),%d0
        moveq   #RPCH,%d1
        cmp.l   %d1,%d0
        blt.s   .ug_no
        moveq   #RPSP,%d1
        cmp.l   %d1,%d0
        bgt.s   .ug_no
        move.l  0x114(%a0),%d1
        cmpi.l  #BPM24_MIN,%d1
        blt.s   .ug_no
        cmpi.l  #BPM24_MAX,%d1
        bgt.s   .ug_no
        moveq   #1,%d0
        bra.s   .ug_out
.ug_no:
        moveq   #0,%d0
.ug_out:
        movem.l (%sp),%d1-%d2/%a0
        lea     12(%sp),%sp
        rts

| The page-1 dial renderers do NOT read the descriptor widget column: each
| resolves a per-slot record's widget pointer (+48) and falls back to a
| HARDCODED knob when it is null (found Session 107 after the first flash
| drew the stock dial). Four sites, one shape; the shim re-creates the
| resolve and overrides the result with quant_widget exactly when the
| record's formatter (+0) is playback slot 0's -- page-agnostic, and
| quant_widget itself falls back to the knob off a repitch track.
qdial1:                                 | 0x40036698, record in a4
        movea.l 48(%a4),%a0
        tst.l   %a0
        bne.s   1f
        lea     (KNOB).l,%a0
1:      move.l  (%a4),%d0            | d0 dead at every site: reloaded after the call
        cmpi.l  #PTCH_FMT,%d0
        bne.s   2f
        lea     quant_widget,%a0
2:      jmp     (0x400366a6).l
qdial2:                                 | 0x4003690c, record in a3
        movea.l 48(%a3),%a0
        tst.l   %a0
        bne.s   1f
        lea     (KNOB).l,%a0
1:      move.l  (%a3),%d0            | d0 dead at every site: reloaded after the call
        cmpi.l  #PTCH_FMT,%d0
        bne.s   2f
        lea     quant_widget,%a0
2:      jmp     (0x4003691a).l
qdial3:                                 | 0x4003786a, record in a3
        movea.l 48(%a3),%a0
        tst.l   %a0
        bne.s   1f
        lea     (KNOB).l,%a0
1:      move.l  (%a3),%d0            | d0 dead at every site: reloaded after the call
        cmpi.l  #PTCH_FMT,%d0
        bne.s   2f
        lea     quant_widget,%a0
2:      jmp     (0x40037878).l
qdial4:                                 | 0x40037c06, record in a3
        movea.l 48(%a3),%a0
        tst.l   %a0
        bne.s   1f
        lea     (KNOB).l,%a0
1:      move.l  (%a3),%d0            | d0 dead at every site: reloaded after the call
        cmpi.l  #PTCH_FMT,%d0
        bne.s   2f
        lea     quant_widget,%a0
2:      jmp     (0x40037c14).l

| PTCH's widget, args (x, y, index, value, flags, fmt, canvas). Off a
| repitch track (rp_ui_gate): the stock dial untouched. On one: the dial's
| frame (value -1 draws chrome alone) with the QUANT ratio centred in it.
| A negative value (an empty cell, sign-extended by the dial renderers)
| keeps the bare frame.
quant_widget:
        bsr     rp_ui_gate
        tst.l   %d0
        bne.s   .qw_quant
        move.l  #0x50544348,%d0         | 'PTCH': restore the caption
        bsr.s   .qw_name
        jmp     (KNOB).l
| the caption lives in the descriptor name table, which the page's text pass
| reads on every redraw; writing it at widget-draw time renames the dial
| (one redraw of lag at worst on a mode change)
.qw_name:
        move.l  %d0,(NAME_ST).l
        move.l  %d0,(NAME_FX).l
        clr.w   (NAME_ST+4).l
        clr.w   (NAME_FX+4).l
        rts
.qw_quant:
        move.l  #0x5155414e,%d0         | 'QUAN'
        bsr.s   .qw_name
        move.l  28(%sp),-(%sp)          | canvas
        move.l  28(%sp),-(%sp)          | fmt
        move.l  28(%sp),-(%sp)          | flags
        moveq   #-1,%d0
        move.l  %d0,-(%sp)              | value -1: frame alone
        move.l  28(%sp),-(%sp)          | index
        move.l  28(%sp),-(%sp)          | y
        move.l  28(%sp),-(%sp)          | x
        jsr     (KNOB).l
        lea     28(%sp),%sp
        lea     -16(%sp),%sp
        movem.l %d2-%d4/%a2,(%sp)
        move.l  20(%sp),%d2             | x
        move.l  24(%sp),%d3             | y
        move.l  44(%sp),%d4             | canvas
        move.l  32(%sp),%d0             | ui value
        bmi.s   .qw_done                | empty cell: the bare frame only
        bsr     rk_bucket
        lsl.l   #2,%d0
        lea     .q_labels(%pc),%a2
        adda.l  %d0,%a2                 | the 4-byte label
        move.l  %a2,-(%sp)
        moveq   #-1,%d0
        move.l  %d0,-(%sp)
        pea     (FONT).l
        jsr     (TXT_MEASURE).l         | -> d0 = px width
        lea     12(%sp),%sp
        lsr.l   #1,%d0
        addq.l  #8,%d2
        addq.l  #1,%d2                  | cell centre x+9
        sub.l   %d0,%d2
        move.l  %a2,-(%sp)
        moveq   #-1,%d0
        move.l  %d0,-(%sp)
        addq.l  #1,%d3
        move.l  %d3,-(%sp)              | y+1
        move.l  %d2,-(%sp)
        move.l  %d4,-(%sp)
        pea     (FONT).l
        jsr     (TXT_DRAW).l
        lea     24(%sp),%sp
.qw_done:
        movem.l (%sp),%d2-%d4/%a2
        lea     16(%sp),%sp
        rts
.q_labels:
        .ascii  "1/2\0"
        .ascii  "2/3\0"
        .ascii  "3/4\0"
        .ascii  "1/1\0"
        .ascii  "5/4\0"
        .ascii  "4/3\0"
        .ascii  "3/2\0"
        .ascii  "2/1\0"
.rk_ratios:
        .byte   1,2, 2,3, 3,4, 1,1, 5,4, 4,3, 3,2, 2,1
        .balign 2

| ---------------------------------------------------------------------------
| Audio editor ATTR, TIMESTRETCH row (the sample's own TSMODE: only REPITCH=4
| is offered -- AUTO resolves it to RPCH). 0x4006e71c: d0 not 0/2/3.
attr_label:
        moveq   #RPCH,%d1
        cmp.l   %d1,%d0
        beq.s   .al_rpch
        moveq   #5,%d1
        cmp.l   %d1,%d0
        beq.s   .al_rps9
        moveq   #RPSP,%d1
        cmp.l   %d1,%d0
        beq.s   .al_rpsp
        pea     (STR_ERROR).l
        jmp     (0x4006e878).l
.al_rpch:
        pea     .repitch(%pc)
        jmp     (0x4006e878).l
.al_rps9:
        pea     .rps9(%pc)
        jmp     (0x4006e878).l
.al_rpsp:
        pea     .rpsp(%pc)
        jmp     (0x4006e878).l
.repitch:
        .asciz  "REPITCH"
.rps9:
        .asciz  "RPS9"
.rpsp:
        .asciz  "RPSP"
        .balign 2

| 0x4006ee56, value up: stock steps 2 -> 3 and stops; 3 -> REPITCH is the top.
attr_up:
        moveq   #2,%d1
        cmp.l   %d1,%d0
        blt.s   .au_done
        moveq   #5,%d1
        cmp.l   %d1,%d0
        bgt.s   .au_done
        addq.l  #1,%d0
        move.l  %d0,272(%a0)
.au_done:
        jmp     (0x4006eef0).l

| 0x4006ef7c, value down: stock steps 3 -> 2 -> 0; REPITCH -> 3 first.
attr_down:
        move.l  272(%a0),%d0            | displaced
        moveq   #2,%d1
        cmp.l   %d0,%d1
        bne.s   .ad_upper
        clr.l   272(%a0)
        bra.s   .ad_done
.ad_upper:
        moveq   #3,%d1
        cmp.l   %d1,%d0
        blt.s   .ad_done
        moveq   #RPSP,%d1
        cmp.l   %d1,%d0
        bgt.s   .ad_done
        subq.l  #1,%d0
        move.l  %d0,272(%a0)
.ad_done:
        jmp     (0x4006f026).l
