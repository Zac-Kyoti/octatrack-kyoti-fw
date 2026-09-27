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
        .global quant_fmt
        .global rp_swap
        .global rp_apply1
        .global rp_apply2
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
        .equ    SET_STATIC, 0x100d5b30  | STATIC sample settings, stride 0x448 (STORAGE.md)
        .equ    SET_FLEX, 0x100b14f0    | FLEX settings array (recorders above slot 128)
        .equ    SET_STRIDE, 0x448
| the Part DB -- boot-authoritative, unlike the engine mirrors (0x80000eb4 /
| 0x8000082f), which are stale until the transport first runs (flash 3)
        .equ    DB_PTR, 0x46c82456      | -> the working bank blob
        .equ    PART_B, 0x80000003      | current part (byte; MIDI.md's editors)
        .equ    PART_STRIDE, 0x18b2
        .equ    OFF_MACH, 0x8eda2       | + t: machine type (0 ST, 1 FL, 4 PU)
        .equ    OFF_P1, 0x8edaa         | + t*30 + m*6 + slot: page-1 bytes
        .equ    OFF_P2, 0x8ef5a         | + t*30 + m*6 + slot2: page-2 bytes
        .equ    OFF_SLOT5, 0x8f04a      | + t*5 + m: 0-based sample slot byte
        .equ    SHADOW_ADJ, 0x100a4ece-0x8ed80 | SRAM part copy, addressed with
                                        | the same DB-relative offsets
        .equ    LIVE_B, 0x80000810      | live param byte per [t*72 + flat]
        .equ    DIRTY_PARTS, 0x95048    | DB-relative: |= 1<<part
        .equ    DIRTY_SRAM, 0x100b145e  | |= 1<<part
        .equ    DIRTY_DB2, 0x9b332      | DB-relative: = 1
        .equ    DIRTY_GLOBAL, 0x100f8598
        .equ    TSTR_SLOT2, 4           | page 2: LOOP SLIC LEN RATE TSTR TSNS
        .equ    PARKED, 18              | NEIGHBOR's slot-0 byte: page-1 '---'
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
        lea     -12(%sp),%sp
        movem.l %d0-%d1/%a0,(%sp)
        move.l  (CUR_STATE).l,%d1
        subi.l  #STATES,%d1
        moveq   #40,%d3
        divu.l  %d3,%d1                 | the track
        bsr     rp_swap                 | domain bookkeeping (also polled at draw)
        bsr     rp_source
        move.l  %d0,%d3                 | bpm | modeoff<<16 (0 = not repitch)
        movem.l (%sp),%d0-%d1/%a0
        lea     12(%sp),%sp
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
        .word   0x71d6                  | the composed word -- base value,
        lsr.l   #8,%d0                  | p-locks and scenes included: QUAN
        bsr     rk_bucket               | is a real page-1 parameter again
        swap    %d0
        lsl.l   #8,%d0
        or.l    %d0,%d3                 | idx -> bits 24..26
        move.l  #0x4000,%d0             | PTCH itself is not applied
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

| d1 = track -> d0 = 1 when QUAN is in force. BOOT-AUTHORITATIVE: resolved
| from the Part DB (the engine mirrors 0x80000eb4 / 0x8000082f proved stale
| until the transport first runs -- flash 3's caption-on-STOP). Chain, all
| measured upstream (PARAM_PAGES.md / file-format.md / STORAGE.md):
| DB = [DB_PTR], part = byte PART_B; machine = DB[part*0x18b2+0x8eda2+t];
| SETUP TSTR = DB[..+0x8ef5a+t*30+m*6+4]; the sample slot byte (0-based,
| +1 indexes the settings arrays) = DB[..+0x8f04a+t*5+m]; TSMODE/BPM at
| settings +0x110/+0x114. QUAN shows exactly when repitch would engage.
| Preserves everything but d0. Also the deciding truth for rp_swap.
rp_ui_gate:
        lea     -20(%sp),%sp
        movem.l %d1-%d3/%a0-%a1,(%sp)
        move.l  %d1,%d2                 | track
        moveq   #0,%d0
        moveq   #7,%d1
        cmp.l   %d1,%d2
        bhi     .ug_out
        movea.l (DB_PTR).l,%a0
        moveq   #0,%d1
        move.b  (PART_B).l,%d1
        move.l  #PART_STRIDE,%d0
        mulu.l  %d1,%d0
        adda.l  %d0,%a0                 | this part's block in the DB
        move.l  %d2,%d1
        addi.l  #OFF_MACH,%d1
        moveq   #0,%d3
        move.b  (%a0,%d1.l),%d3         | machine
        moveq   #1,%d1
        cmp.l   %d1,%d3
        bhi     .ug_no                  | STATIC/FLEX only
        lea     (SET_STATIC).l,%a1
        tst.l   %d3
        beq.s   1f
        lea     (SET_FLEX).l,%a1
1:      move.l  %d2,%d1
        lsl.l   #2,%d1
        add.l   %d2,%d1                 | t*5
        add.l   %d3,%d1
        addi.l  #OFF_SLOT5,%d1
        moveq   #0,%d0
        move.b  (%a0,%d1.l),%d0         | the sample slot byte, used RAW:
        move.l  #SET_STRIDE,%d1         | the arrays are 0-based (slot byte
        mulu.l  %d0,%d1                 | 128 = recorder R1 = FLEX record
        adda.l  %d1,%a1                 | 128; flash-4 falsified the +1)
        moveq   #30,%d1
        mulu.l  %d2,%d1
        move.l  %d3,%d0
        lsl.l   #2,%d0
        add.l   %d3,%d0
        add.l   %d3,%d0                 | machine*6
        add.l   %d0,%d1
        addi.l  #OFF_P2+TSTR_SLOT2,%d1
        moveq   #0,%d0
        move.b  (%a0,%d1.l),%d0         | SETUP TSTR, the Part's own copy
        moveq   #RPCH,%d1
        cmp.l   %d1,%d0
        blt.s   .ug_auto
        moveq   #RPSP,%d1
        cmp.l   %d1,%d0
        bgt.s   .ug_no
        bra.s   .ug_tempo
.ug_auto:
        moveq   #TSTR_AUTO,%d1
        cmp.l   %d1,%d0
        bne.s   .ug_no
        move.l  0x110(%a1),%d0          | the sample's own TSMODE
        moveq   #RPCH,%d1
        cmp.l   %d1,%d0
        blt.s   .ug_no
        moveq   #RPSP,%d1
        cmp.l   %d1,%d0
        bgt.s   .ug_no
.ug_tempo:
        move.l  0x114(%a1),%d1          | the sample's BPMx24
        cmpi.l  #BPM24_MIN,%d1
        blt.s   .ug_no
        cmpi.l  #BPM24_MAX,%d1
        bgt.s   .ug_no
        moveq   #1,%d0
        bra.s   .ug_out
.ug_no:
        moveq   #0,%d0
.ug_out:
        movem.l (%sp),%d1-%d3/%a0-%a1
        lea     20(%sp),%sp
        rts

| d1 = track. On a gate transition the PTCH slot's stored value trades
| places with the PARKED byte -- NEIGHBOR's page-1 slot 0, a '---' param
| stock saves with the project but never applies -- in the working DB AND
| the SRAM part copy, and the live/lane bytes follow, with the writer's own
| dirty flags so a project save carries both domains. First sight adopts
| without swapping (a project saved in a repitch mode already holds QUAN in
| the slot; TSTR is saved alongside, so the domains stay matched). A parked
| value below the ui minimum (4: a fresh project) enters as 64 = 1/1.
| Called per frame from rate_gate and at every dial draw. Preserves all.
rp_swap:
        lea     -28(%sp),%sp
        movem.l %d1-%d5/%a0-%a1,(%sp)
        move.l  %d1,%d2                 | track
        bsr     rp_ui_gate
        lea     rp_prev(%pc),%a0
        moveq   #0,%d1
        move.b  (%a0,%d2.l),%d1
        cmp.l   %d1,%d0
        beq     .sw_none
        move.b  %d0,(%a0,%d2.l)
        cmpi.l  #0xff,%d1
        beq     .sw_none                | first sight: adopt what is stored
        movea.l (DB_PTR).l,%a0
        moveq   #0,%d1
        move.b  (PART_B).l,%d1
        move.l  #PART_STRIDE,%d0
        mulu.l  %d1,%d0
        move.l  %d0,%d4                 | part*stride
        adda.l  %d0,%a0                 | the part's block
        move.l  %d2,%d1
        addi.l  #OFF_MACH,%d1
        moveq   #0,%d3
        move.b  (%a0,%d1.l),%d3
        moveq   #1,%d1
        cmp.l   %d1,%d3
        bhi     .sw_none                | machine changed mid-flight: skip
        moveq   #30,%d1
        mulu.l  %d2,%d1
        addi.l  #OFF_P1,%d1
        move.l  %d1,%d5
        addi.l  #PARKED,%d5             | d5 = parked offset (DB-relative)
        move.l  %d3,%d0
        lsl.l   #2,%d0
        add.l   %d3,%d0
        add.l   %d3,%d0
        add.l   %d0,%d1                 | d1 = active offset (machine*6)
        move.l  %d5,%d3                 | machine no longer needed
        moveq   #0,%d0
        move.b  (%a0,%d1.l),%d0         | the value leaving the slot
        moveq   #0,%d5
        move.b  (%a0,%d3.l),%d5         | the value entering it
        cmpi.l  #4,%d5
        bge.s   1f
        moveq   #64,%d5                 | fresh park: 1/1
1:      move.b  %d5,(%a0,%d1.l)
        move.b  %d0,(%a0,%d3.l)
        lea     (SHADOW_ADJ).l,%a1      | the SRAM part copy, same offsets
        adda.l  %d4,%a1
        move.b  %d5,(%a1,%d1.l)
        move.b  %d0,(%a1,%d3.l)
        moveq   #72,%d0
        mulu.l  %d2,%d0
        lea     (LIVE_B).l,%a1
        move.b  %d5,(%a1,%d0.l)         | live byte, flat 0
        moveq   #48,%d0
        mulu.l  %d2,%d0
        lea     (LANES).l,%a1
        move.l  %d5,%d1
        lsl.l   #8,%d1
        move.w  %d1,(%a1,%d0.l)         | lane word = ui<<8
        moveq   #0,%d0                  | the writer's own dirty flags
        move.b  (PART_B).l,%d0
        moveq   #1,%d1
        lsl.l   %d0,%d1
        movea.l (DB_PTR).l,%a0
        adda.l  #DIRTY_PARTS,%a0
        or.l    %d1,(%a0)
        lea     (DIRTY_SRAM).l,%a0
        or.l    %d1,(%a0)
        movea.l (DB_PTR).l,%a0
        adda.l  #DIRTY_DB2,%a0
        moveq   #1,%d1
        move.l  %d1,(%a0)
        lea     (DIRTY_GLOBAL).l,%a0
        move.l  %d1,(%a0)
        moveq   #1,%d0                  | -> a swap happened this call
        bra.s   .sw_out
.sw_none:
        moveq   #0,%d0
.sw_out:
        movem.l (%sp),%d1-%d5/%a0-%a1
        lea     28(%sp),%sp
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
| repitch track: the stock dial -- rebuilt with the fresh live byte when
| this very draw performed the swap (the caller fetched its value before
| the poll ran). On a repitch track: the dial SNAPPED to the 8 QUAN
| positions (19 + 15*idx; 1/1 = 64, dead centre) with quant_fmt as the
| readout -- display only, the stored value stays the stock editor's, so
| p-locks and scene locks are untouched.
quant_widget:
        moveq   #0,%d1
        move.b  (UI_TRACK).l,%d1
        bsr     rp_swap                 | d0 = swapped on this draw?
        movea.l %d0,%a1                 | the flag
        moveq   #72,%d0
        mulu.l  %d1,%d0
        lea     (LIVE_B).l,%a0
        adda.l  %d0,%a0                 | -> this track's live PTCH byte
        bsr     rp_ui_gate              | a0/a1/d1 preserved
        tst.l   %d0
        bne.s   .qw_quant
        move.l  #0x50544348,%d0         | 'PTCH': restore the caption
        bsr.s   .qw_name
        move.l  %a1,%d0
        bne.s   .qw_fresh
        jmp     (KNOB).l                | no swap: stock, untouched
.qw_fresh:
        moveq   #0,%d0
        move.b  (%a0),%d0               | the just-restored pitch
        movea.l 24(%sp),%a1             | with its own formatter
        bra.s   .qw_frame
| the caption lives in the descriptor name table, which the page's text pass
| reads on every redraw; writing it at widget-draw time renames the dial
.qw_name:
        move.l  %d0,(NAME_ST).l
        move.l  %d0,(NAME_FX).l
        clr.w   (NAME_ST+4).l
        clr.w   (NAME_FX+4).l
        rts
.qw_quant:
        move.l  #0x5155414e,%d0         | 'QUAN'
        bsr.s   .qw_name
        move.l  16(%sp),%d0             | the caller's value
        move.l  %a1,%d1
        beq.s   1f
        moveq   #0,%d0
        move.b  (%a0),%d0               | swapped: the fresh QUAN value
1:      lea     (quant_fmt).l,%a1       | the ratio readout
        tst.l   %d0
        bmi.s   .qw_frame               | an empty cell keeps the bare frame
        bsr     rk_bucket
        move.l  %d0,%d1                 | snap = 19 + 15*idx
        lsl.l   #4,%d1
        sub.l   %d0,%d1
        moveq   #19,%d0
        add.l   %d1,%d0
.qw_frame:
        move.l  28(%sp),-(%sp)          | canvas
        move.l  %a1,-(%sp)              | the path's formatter
        move.l  28(%sp),-(%sp)          | flags
        move.l  %d0,-(%sp)              | value
        move.l  28(%sp),-(%sp)          | index
        move.l  28(%sp),-(%sp)          | y
        move.l  28(%sp),-(%sp)          | x
        jsr     (KNOB).l
        lea     28(%sp),%sp
        rts

| fmt(buf, value): a ui value's ratio bucket.
quant_fmt:
        move.l  8(%sp),%d0
        bmi.s   .qf_unk
        bsr     rk_bucket
        lsl.l   #2,%d0
        lea     .q_labels(%pc),%a0
        adda.l  %d0,%a0
        move.l  %a0,8(%sp)
        jmp     (SPRINTF).l
.qf_unk:
        lea     (STR_UNK).l,%a0
        move.l  %a0,8(%sp)
        jmp     (SPRINTF).l

.q_labels:
        .ascii  "1/2\0"
        .ascii  "2/3\0"
        .ascii  "3/4\0"
        .ascii  "1/1\0"
        .ascii  "5/4\0"
        .ascii  "4/3\0"
        .ascii  "3/2\0"
        .ascii  "2/1\0"
rp_prev:
        .byte   0xff,0xff,0xff,0xff,0xff,0xff,0xff,0xff
        .balign 2

| Any part apply (heavy 0x40009094 -- the audio-engine-restarting one; light
| 0x40009e00 -- seq_goto_pattern's) makes rp_prev meaningless: reset it so
| the next poll ADOPTS the freshly applied state. Part changes and project
| loads are therefore never treated as transitions -- only live in-part
| edits (SETUP TSTR, ATTR under AUTO) swap the domains.
rp_forget:
        lea     rp_prev(%pc),%a0
        moveq   #-1,%d0
        move.l  %d0,(%a0)
        move.l  %d0,4(%a0)
        rts
rp_apply1:
        bsr.s   rp_forget
        lea     -104(%sp),%sp           | displaced
        movem.l %d2-%d7/%a2-%fp,(%sp)   | displaced
        jmp     (0x4000909c).l
rp_apply2:
        bsr.s   rp_forget
        lea     -76(%sp),%sp            | displaced
        movem.l %d2-%d7/%a2-%fp,(%sp)   | displaced
        jmp     (0x40009e08).l
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
