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
|     stop  4   19   34   49   64   79   94  109  124
|     ratio 1/2  2/3  3/4  4/5  1/1  5/4  4/3  3/2  2/1
| Nine values, pitch-symmetric about 1/1 (every interval has its mirror:
| 4/5 is 5/4 inverted), so 1/1 lands on stop 64 -- the dial's exact centre
| and stock's own neutral PTCH value.
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
| Adapted in part from Jannik Assfalg's (repeat98) Repitch module for
| octabam, refs/octabam/modules/repitch/repitch.s (MIT, Copyright (c) 2026
| Sam Banks, octabam's licence) -- rp_source, rate_gate and all seven hook
| sites (the three builder hooks, the TSTR resolver, the three ATTR hooks)
| and tstr_fmt's approach. Every borrowed site byte-verified against our
| image, Session 106. See CREDITS.md.

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
        .global rp_forget
        .global rp_prev
        .global rp_caption
        .global quant_step
        .global rp_refresh
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
        .equ    BASE_W, 0x80000a50      | per-track base words, 64 B/track, ui<<8:
                                        | the lane's first 24 B are copied from
                                        | here every frame (0x4000cb2a), and the
                                        | editor's slew (0x4000d63c) moves them
                                        | toward the live bytes only while its
                                        | counter (0x80000db4 + 32t) runs
        .equ    DIRTY_PARTS, 0x95048    | DB-relative: |= 1<<part
        .equ    DIRTY_SRAM, 0x100b145e  | |= 1<<part
        .equ    DIRTY_DB2, 0x9b332      | DB-relative: = 1
        .equ    DIRTY_GLOBAL, 0x100f8598
        .equ    TSTR_SLOT2, 4           | page 2: LOOP SLIC LEN RATE TSTR TSNS
        .equ    RP_HOLD, 0xfe           | rp_prev value: a Part RELOAD is in progress
                                        | (rp_reload writes it; rp_swap tests -2)
        .equ    PARKED, 18              | NEIGHBOR's slot-0 byte: page-1 '---'
        .equ    REDRAW_L, 0x46c7d248    | slot 0's knob-redraw mark: a LONG 0x14 at
                                        | 0x46c7d244 + slot*20 + 4, measured at the
                                        | UI editor's own tail (0x4005543c)
        .equ    STEP_PTCH, 0x40032d08   | stock slot-0 encoder-step handler
        .equ    QS_FINE, 3              | single detents per ratio (feel knob)
        .equ    ENC_A_HELD, 0x46c7de2e  | key state of encoder A's press (code 0x38):
                                        | 0x46c7d8ee + 24*code -- stock's generic step
                                        | handler (0x4003240c) turns 7x while it is set
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
        addq.l  #3,%d0                  | nearest of the 9 stops at 4 + 15*idx
        moveq   #15,%d1
        divu.l  %d1,%d0
        moveq   #8,%d1
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
        bsr     rp_source               | (reads only the lane and the voice: rp_swap
        move.l  %d0,%d3                 | writes neither) bpm | modeoff<<16, 0 = not repitch
        bne.s   1f
        | Not a repitch voice now, and its gate was off last time: rp_swap could
        | only find a gate turning on that this voice does not play yet -- the
        | swap waits for the frame it does, or for the dial draw's poll (rp_swap
        | runs there too). This is the early exit for every stock-TSTR voice
        | (KYOTI load audit: ~200 instructions per voice per frame without it).
        lea     rp_prev(%pc),%a0
        tst.b   (%a0,%d1.l)
        beq.s   2f
1:      bsr     rp_swap                 | domain bookkeeping (also polled at draw)
2:      movem.l (%sp),%d0-%d1/%a0
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
        | Bits 2-3 are the DSP mode channel (see .rh_tag), so they are cleared
        | on EVERY increment this builder emits, tagged or not. Otherwise a
        | stock track -- PTCH +1 st is 1.0594631..., low bits arbitrary --
        | would read as RPS9/RPSP on the DSP by chance. The four other
        | increment writers (0x40004028/0x40004448/0x4000468c/0x40004804) all
        | store the literal 0x04000000, so with this every increment reaching
        | the DSP has bits 2-3 == 0 unless a repitch track tagged it.
        | Cost to stock tracks: <= 12*2^-26 of the increment, inaudible.
        andi.l  #0xfffffff3,%d0
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
        cmpi.l  #INC_MAX-16,%d0         | -16: the tag below can never push the
        bls.s   .rh_tag                 | result past stock's own 2.0 ceiling
        move.l  #INC_MAX-16,%d0
.rh_tag:
        | The mode rides Q26 BITS 2-3 (Session 108). The DSP rebuilds the
        | increment as a net >>2 (P:0x3bd/0x3bf: asr #16 then asr #10 over a
        | right-justified hi16:lo16 pair), so bits 0-1 are DISCARDED -- the
        | old tag position was unreadable there. Bits 2-3 land in the Q24
        | fraction LSBs, stored at the fixed address y:$40 (l:$40 = this
        | voice's increment), where the DSP cave reads them. Cost: at most
        | 2*2^-24 of the increment -- far below anything audible, and the
        | DSP phase re-seeds every call.
        move.l  %d3,%d5
        swap    %d5
        andi.l  #3,%d5                  | modeoff
        lsl.l   #2,%d5                  | -> bits 2-3
        moveq   #-16,%d4                | clear bits 0-3
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
.ifdef RPK_DIAG
        move.b  %d3,(rk_dvals+1).l
.endif
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
.ifdef RPK_DIAG
        move.b  %d0,(rk_dvals+2).l
.endif
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
.ifdef RPK_DIAG
        move.b  %d0,(rk_dvals+3).l
.endif
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
.ifdef RPK_DIAG
        move.b  %d0,(rk_dvals).l
.endif
        movem.l (%sp),%d1-%d3/%a0-%a1
        lea     20(%sp),%sp
        rts

| d1 = track. On a gate transition the PTCH slot's stored value trades
| places with the PARKED byte -- NEIGHBOR's page-1 slot 0, a '---' param
| stock saves with the project but never applies -- in the working DB AND
| the SRAM part copy, and the live byte + base word follow, with the writer's own
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
        .word   0x7330,0x2800           | mvs.b (%a0,%d2.l),%d1 -- SIGNED: 0/1 are
                                        | gate values, -1 (0xff) first sight,
                                        | -2 (RP_HOLD) a Part RELOAD in progress
        cmp.l   %d1,%d0
        beq     .sw_none
        addq.l  #2,%d1                  | RP_HOLD: rp_reload is copying the Part
        beq     .sw_none                | in -- touch nothing until it forgets
        move.b  %d0,(%a0,%d2.l)
        subq.l  #1,%d1                  | 0xff (d1 is dead after this test)
        beq     .sw_adopt               | first sight: adopt what is stored
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
        | The BASE word, not the lane: the lane is rebuilt from it every
        | frame, so a lane write lasted one frame and the old domain's value
        | came back -- leaving RPCH* then played the QUAN value as PTCH until
        | a knob turn re-armed the editor's slew (rev 16; entering only
        | worked when a recent turn's slew was still running).
        move.l  %d2,%d0
        lsl.l   #6,%d0
        lea     (BASE_W).l,%a1
        move.l  %d5,%d1
        lsl.l   #8,%d1
        move.w  %d1,(%a1,%d0.l)         | base word = ui<<8
        | The writer's own dirty flags. DIRTY_PARTS and DIRTY_SRAM are BYTE
        | bitmasks (stock: move.b at 0x4004ab52/0x4004ab5c, 0x4000b062, ...).
        | Until Session 119 they were written with or.l, a LONG: the 1<<part
        | landed in the byte 3 past each flag -- saved Part 1's T2 FX1 type
        | (DB+0x9504b: FILTER 4 -> SPATIALIZER 5 on Part 1) and Part 3's
        | "has been saved" flag (0x100b1461, the SRAM copy of DB+0x9b312..).
        | bset Dn,<mem> is a byte op and takes the bit number mod 8.
        move.b  (PART_B).l,%d0
        movea.l (DB_PTR).l,%a1          | one DB load, reused: CF lea takes only
        movea.l %a1,%a0                 | a 16-bit displacement, so the big
        adda.l  #DIRTY_PARTS,%a0        | DB-relative offsets need adda.l
        bset    %d0,(%a0)
        bset    %d0,(DIRTY_SRAM).l
        moveq   #1,%d1
        movea.l %a1,%a0
        adda.l  #DIRTY_DB2,%a0
        move.l  %d1,(%a0)
        lea     (DIRTY_GLOBAL).l,%a0
        move.l  %d1,(%a0)
        moveq   #1,%d0                  | -> a swap happened this call
        bra.s   .sw_seen
.sw_adopt:
        moveq   #0,%d0                  | adopted, so no value substitution --
        bra.s   .sw_seen                | but the caption still has to refresh
                                        | (a project load or part apply lands
                                        | here, and its display must be right)
.sw_none:
        moveq   #0,%d0
.sw_out:
        movem.l (%sp),%d1-%d5/%a0-%a1
        lea     28(%sp),%sp
        rts

| A gate change on the track the panel is showing: set the caption and the
| dial's redraw mark HERE, not at draw time. A draw-time caption write is one
| repaint late by construction -- the page's text pass reads the name table
| before the widget pass runs -- which is why an ATTR edit needed a page
| press. rp_swap runs per frame from rate_gate and directly from the ATTR
| editors, so both are already right when the next repaint happens.
.sw_seen:
        move.l  %d0,-(%sp)
        moveq   #0,%d1
        move.b  (UI_TRACK).l,%d1
        cmp.l   %d1,%d2                 | was this the panel's track?
        bne.s   .sw_seen_out
        move.l  %d2,%d1
        bsr     rp_ui_gate
        move.l  #0x50544348,%d1         | 'PTCH'
        tst.l   %d0
        beq.s   1f
        move.l  #0x5155414e,%d1         | 'QUAN'
1:      move.l  %d1,%d0
        bsr     rp_caption
        | NO redraw mark here. 0x14 at 0x46c7d244+slot*20+4 is what the UI
        | editor writes to SHOW a parameter's value under the knob with its
        | fade -- correct when the user turned it, wrong for a mode switch,
        | where it popped a value nobody dialled and sat there (flash 8).
        | The caption alone is enough: leaving page 2 for page 1 repaints.
.sw_seen_out:
        move.l  (%sp)+,%d0
        bra.s   .sw_out

| d0 = a 4-char caption -> the descriptor name fields the page's text pass
| reads (STATIC and FLEX slot 0). The image is SDRAM; octabam's mode-rename
| cave writes this table the same way.
rp_caption:
        move.l  %d0,(NAME_ST).l         | 4 chars; bytes 4..5 of the field are
        move.l  %d0,(NAME_FX).l         | already 0 in stock ('PTCH\0\0') and
        rts                             | nothing here ever writes them

| Poll the panel track's gate and refresh the caption + dial mark. Called
| from the ATTR editors, whose edits are otherwise invisible to the PLAYBACK
| page until something else forces a repaint. Preserves every register.
rp_refresh:
        move.l  %d0,-(%sp)
        move.l  %d1,-(%sp)
        moveq   #0,%d1
        move.b  (UI_TRACK).l,%d1
        bsr     rp_swap
        | The ATTR path, and ONLY it, marks slot 0 changed -- exactly what
        | every stock editor does after a store (0x40039510, 0x4005543c, ...).
        | Returning from the audio editor is not a full page redraw; without
        | this the knob keeps its old caption until a page press (flash 10,
        | a regression of rev 7's blanket removal). Unconditional on purpose:
        | the per-frame rate_gate poll can consume the gate transition before
        | this runs, and an ATTR TIMESTRETCH edit is a rare deliberate act, so
        | one ordinary value pop-and-fade on return is the right trade. The
        | page-2 TSTR path stays mark-free -- that is where it stuck (flash 8).
        moveq   #0x14,%d0
        move.l  %d0,(REDRAW_L).l
        move.l  (%sp)+,%d1
        move.l  (%sp)+,%d0
        rts

| P+0x12a slot 0 -- the per-slot ENCODER STEP handler the UI editor calls as
| handler(slot, delta, current) -> new value, which it then clamps with the
| descriptor's own min/count and stores (0x40055352..0x4005538a). Off a QUAN
| track this tail-jumps to stock's. On one, ONE DETENT IS ONE RATIO: the
| value walks the 8 zone centres (19 + 15*idx), so the whole set is 7 detents
| wide instead of ~105, and stock still clamps, stores to Part/shadow/live
| and does its own redraw bookkeeping.
quant_step:
.ifdef RPK_DIAG
        move.l  %d0,-(%sp)              | latch WHO called us: the low word of
        move.l  %a0,-(%sp)              | the return address, two pushes deep
        move.l  8(%sp),%d0
        lea     rk_dret(%pc),%a0
        move.w  %d0,(%a0)
        move.l  (%sp)+,%a0
        move.l  (%sp)+,%d0
.endif
        move.l  %d1,-(%sp)
        moveq   #0,%d1
        move.b  (UI_TRACK).l,%d1
        bsr     rp_ui_gate
        tst.l   %d0
        bne.s   .qs_quan
        move.l  (%sp)+,%d1
        jmp     (STEP_PTCH).l
.qs_quan:
.ifdef RPK_DIAG
        move.l  %d0,-(%sp)              | quant_step reached the QUAN path
        move.l  %a0,-(%sp)              | (CF has no addq.b to memory)
        lea     rk_dvals(%pc),%a0
        move.b  4(%a0),%d0
        addq.l  #1,%d0
        move.b  %d0,4(%a0)
        move.l  (%sp)+,%a0
        move.l  (%sp)+,%d0
.endif
        move.l  %d2,-(%sp)
        move.l  20(%sp),%d0             | current (arg 3, two pushes deep)
        bsr     rk_bucket               | -> zone 0..7
        move.l  16(%sp),%d1             | delta (arg 2)
        | A single detent (|delta| = 1) is a FINE move: accumulate and advance
        | one ratio every QS_FINE of them, so the 8 ratios are ~21 detents
        | wide rather than 7. Anything bigger is the accelerated turn and
        | passes straight through. QS_FINE is the one number to change for feel.
        | PRESSED + turn: the press is not in the delta -- stock reads the key
        | state itself -- so a held knob's detent counts double: a ratio every
        | 2 detents instead of QS_FINE's 3 (the OT's convention: faster).
        | Rev 15's one ratio per detent was too fast (user, rev 16).
        move.l  %d1,%d2
        bpl.s   .qs_absok
        neg.l   %d2
.qs_absok:
        subq.l  #1,%d2
        bne.s   .qs_coarse
        move.b  (rk_acc).l,%d2
        extb.l  %d2
        add.l   %d1,%d2                 | signed detent accumulator
        tst.l   (ENC_A_HELD).l
        beq.s   1f
        add.l   %d1,%d2                 | pressed: the detent counts twice
1:
        move.l  %d2,%d1
        bpl.s   .qs_accok
        neg.l   %d1
.qs_accok:
        cmpi.l  #QS_FINE,%d1
        blt.s   .qs_hold
        tst.l   %d2
        bmi.s   .qs_down
        addq.l  #1,%d0
        bra.s   .qs_zeroacc
.qs_down:
        subq.l  #1,%d0
.qs_zeroacc:
        moveq   #0,%d2
.qs_hold:
        move.b  %d2,(rk_acc).l
        bra.s   .qs_clamp
.qs_coarse:
        add.l   %d1,%d0
        moveq   #0,%d1
        move.b  %d1,(rk_acc).l          | a coarse move voids the fine tally
.qs_clamp:
        tst.l   %d0
        bpl.s   1f
        moveq   #0,%d0
1:      moveq   #8,%d1
        cmp.l   %d1,%d0
        ble.s   2f
        move.l  %d1,%d0
2:      moveq   #15,%d1                 | 4 + 15*idx
        mulu.l  %d0,%d1
        moveq   #4,%d0
        add.l   %d1,%d0
        move.l  (%sp)+,%d2
        move.l  (%sp)+,%d1
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
        bsr     rp_caption
        move.l  %a1,%d0
        bne.s   .qw_fresh
        jmp     (KNOB).l                | no swap: stock, untouched
.qw_fresh:
        moveq   #0,%d0
        move.b  (%a0),%d0               | the just-restored pitch
        movea.l 24(%sp),%a1             | with its own formatter
        bra.s   .qw_frame
.qw_quant:
        move.l  #0x5155414e,%d0         | 'QUAN'
        bsr     rp_caption
        move.l  16(%sp),%d0             | the caller's value
        move.l  %a1,%d1
        beq.s   1f
        moveq   #0,%d0
        move.b  (%a0),%d0               | swapped: the fresh QUAN value
1:      lea     (quant_fmt).l,%a1       | the ratio readout
        tst.l   %d0
        bmi.s   .qw_frame               | an empty cell keeps the bare frame
        bsr     rk_bucket
        | snap to this idx's stop -- ONE scale for display and storage now
        | (4 + 15*idx), so 1/2 sits hard left, 2/1 hard right and 1/1 dead
        | centre at 64, which is also stock's neutral PTCH value
        moveq   #15,%d1
        mulu.l  %d0,%d1
        moveq   #4,%d0
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
.ifdef RPK_DIAG
        bsr     rp_diagstr              | diagnostic build: four nibbles
        lea     rk_dbuf(%pc),%a0
        move.l  %a0,8(%sp)
        jmp     (SPRINTF).l
.endif
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
        .ascii  "4/5\0"
        .ascii  "1/1\0"
        .ascii  "5/4\0"
        .ascii  "4/3\0"
        .ascii  "3/2\0"
        .ascii  "2/1\0"
rp_prev:
        .byte   0xff,0xff,0xff,0xff,0xff,0xff,0xff,0xff
        .balign 2
rk_acc:
        .byte   0                       | fine-detent tally, signed
        .balign 2
.ifdef RPK_DIAG
| Diagnostic build only. The PTCH/QUAN cell's readout becomes four hex
| nibbles: [gate][SETUP TSTR][sample TSMODE][quant_step calls & 0xf], read
| for the panel's track at the moment the gate last ran. Nothing else
| changes; the increment path is untouched.
rk_dvals:
        .byte   0,0,0,0,0
        .balign 2
rk_dret:
        .word   0
rk_dbuf:
        .byte   0,0,0,0,0
        .balign 2
| DIAG readout: the four hex digits of quant_step's caller -- the low word of
| the return address it was last entered with. Session 108-cont-5: the gate,
| the machine and the SETUP byte are all settled (1/0/4 on hardware), and the
| step counter advances, so the open question is WHICH call site reaches the
| P+0x12a handler. 0x536a would be the UI editor's own (0x4005536a, the
| instruction after its jsr); anything else names a different consumer.
| '----' until quant_step has run once.
rp_diagstr:
        lea     -16(%sp),%sp
        movem.l %d0-%d2/%a0,(%sp)
        lea     rk_dret(%pc),%a0
        moveq   #0,%d0
        move.w  (%a0),%d0
        lea     rk_dbuf(%pc),%a0
        moveq   #0,%d1
        move.b  %d1,4(%a0)              | NUL
        tst.l   %d0
        bne.s   .ds_hex
        moveq   #0x2d,%d1               | '----': quant_step never entered
        move.b  %d1,(%a0)
        move.b  %d1,1(%a0)
        move.b  %d1,2(%a0)
        move.b  %d1,3(%a0)
        bra.s   .ds_out
.ds_hex:
        moveq   #3,%d2                  | four digits, least significant last
.ds_loop:
        move.l  %d0,%d1
        andi.l  #0xf,%d1
        cmpi.l  #9,%d1
        ble.s   1f
        addq.l  #7,%d1                  | 'A'..'F'
1:      addi.l  #0x30,%d1
        move.b  %d1,(%a0,%d2.l)
        lsr.l   #4,%d0
        subq.l  #1,%d2
        bpl.s   .ds_loop
.ds_out:
        movem.l (%sp),%d0-%d2/%a0
        lea     16(%sp),%sp
        rts
.endif

| Any part apply (heavy 0x40009094 -- the audio-engine-restarting one; light
| 0x40009e00 -- seq_goto_pattern's) makes rp_prev meaningless: reset it so
| the next poll ADOPTS the freshly applied state. Part changes and project
| loads are therefore never treated as transitions -- only live in-part
| edits (SETUP TSTR, ATTR under AUTO) swap the domains.
| d1 and a0 only: rp_reload returns straight through here with stock RELOAD
| PART's verdict still in d0 (RELOAD_FROM_PROJECT tests it).
rp_forget:
        lea     rp_prev(%pc),%a0
        moveq   #-1,%d1
        move.l  %d1,(%a0)
        move.l  %d1,4(%a0)
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
        .byte   1,2, 2,3, 3,4, 4,5, 1,1, 5,4, 4,3, 3,2, 2,1
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
        bsr     rp_refresh              | the PLAYBACK dial follows at once
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
        bsr     rp_refresh
        jmp     (0x4006f026).l
