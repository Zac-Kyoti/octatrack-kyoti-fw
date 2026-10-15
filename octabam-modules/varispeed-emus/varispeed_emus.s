| SPDX-License-Identifier: MIT
| SPDX-FileCopyrightText: 2026 Zac-Kyoti
|
| VARISPEED_EMUS -- the ColdFire half (one link unit) -- and VARISPEED, the plain build.
|
| ONE SOURCE, TWO BUILDS (spec §7), chosen by the assembly switch VEM_EMUS below:
|   VEM_EMUS = 1  VARISPEED_EMUS (tools/build_varispeed_emus.py, this module's manifest):
|                 everything described here.
|   VEM_EMUS = 0  VARISPEED (tools/build_varispeed.py, octabam-modules/varispeed/): VARI with
|                 QUAN and nothing emulated -- no EMUS (TSNS stays TSNS, no second park pair),
|                 no engine tag or latch, no mask on stock tracks' increments, no load guard;
|                 the DSP is stock (SPRING REVERB stays). A VARI track's increment is the one
|                 VARISPEED_EMUS computes for EMUS = OT, bit for bit.
| A fix to the shared code lands in both. Everything that is VARISPEED_EMUS's alone sits
| inside `.if VEM_EMUS`.
|
| STATIC and FLEX get a fifth TSTR position, VARI (raw 4). A VARI track plays dry
| (no grains, no stretch) at the speed (project BPM x p) / (sample BPM x q), p/q the QUAN
| ratio picked with the PTCH knob, exact in integers; RATE still applies. Its TSNS knob
| becomes EMUS (OT / S950 / SP12, left to right), the engine the DSP kernel (rpk_dsp.asm)
| renders the track with, latched at each trig; four detents in one direction step it once.
| A DSP load guard (spec §6b) keeps each DSP core's estimated load, a property of the
| settings, under its budget: a change that would overload it is refused (EMUS, the FX
| type), TSTR / ATTR onto VARI steps THAT track's EMUS to OT (VEM7), and a change that
| cannot be refused (Part change, reload, load, machine, sample...) steps just enough
| tracks to OT;
| each raises the toast MAX DSP: EMU LIMIT from the UI task's message loop. Spec:
| reference/handoffs/REPITCH_REWRITE_SPEC.md; facts: REPITCH_REWRITE_SCOPE.md +
| REPITCH_REWRITE_SCOPE_EMUS.md (clean-room); this build: REPITCH_REWRITE_IMPL.md §12.
|
| Two parts:
|   PART 1, NEW CORE (written for VARISPEED_EMUS): the frame hook vem_frame, the TSTR
|     formatter, the audio-editor ATTR hooks, the EMUS widget / formatter / step and its
|     page-open reset, the DSP load guard, the hold wrappers of the bulk writers.
|   PART 2, RETAINED (REPITCH_REWRITE_RETAINED.s, extended): QUAN, the domain swap -- now
|     per machine, with a second pair (TSNS<->EMUS) -- the Part-DB gate, the Part-apply
|     bookkeeping and RELOAD PART.
|
| Every routine here is entered from a stock site the builder patches (tools/
| build_varispeed_emus.py: it asserts the stock bytes at each one) or from another
| routine here. Nothing here calls a kernel or UI primitive from the frame path.
|
| Calling convention: the stock C ABI (args on the stack, d0/d1/a0/a1 scratch) for
| routines stock calls; the private helpers say what they take and keep.

        .text
        .global vem_frame
        .global tstr_fmt
        .global attr_label
        .global attr_up
        .global attr_down
        .global attr_tail
        .global vh_srcpaste
        .global vh_trkpaste
        .global vh_partpaste
        .global vh_partclear
        .global rp_reload
        .global quant_widget
        .global quant_fmt
        .global quant_step
        .global qdial1
        .global qdial2
        .global qdial3
        .global qdial4
        .global rp_swap
        .global rp_swap_ui
        .global rp_ui_gate
        .global rp_gate_m
        .global rp_refresh
        .global rp_poll_all
        .global rp_forget
        .global rp_apply1
        .global rp_apply2
        .global rp_sync
        .global rp_pb
        .global rp_pp
        .global rp_prev
        .global vem_depth
        .global rk_ratios
        .global vem_end

| ---------------------------------------------------------------------------- the build
| The switch (see the head of this file). Its default lives HERE: octabam's defsyms are
| link-time (`ld --defsym`), too late for `.if`, so a plain assembly is VARISPEED_EMUS;
| VARISPEED sets it to 0 before the source is read (`as --defsym VEM_EMUS=0`, or the
| octabam wrapper octabam-modules/varispeed/varispeed.s).
        .ifndef VEM_EMUS
        .equ    VEM_EMUS, 1
        .endif

        .if VEM_EMUS
        .global emus_widget
        .global emus_fmt
        .global vg_fix
        .global vg_scan
        .global vg_room
        .global vg_fx_try
        .global vg_tick
        .global vh_fx1
        .global vh_fx2
        .global vg_eng
        .global vg_toast
        .global vg_pend
        .global vg_note
        .global vg_entered
        .global vg_sig
        .global vg_last
        .global vg_fxp
        .global vg_engp
        .global vg_budget
        .global vg_base
        .global str_emu_limit
        .global emus_p2step
        .global emus_open
        .global vb_fx1
        .global vb_fx2
        .global emus_stops
        .global em_tally
        .global em_ctx
        .endif

| ---------------------------------------------------------------------------- stock
        .equ    UI_TRACK, 0x80000000    | byte: the panel's track
        .equ    PART_B, 0x80000003      | byte: the current part
        .equ    PAGE_M, 0x460d5c30      | long: the machine whose SRC page is open (P2EDIT)
        .equ    DB_PTR, 0x46c82456      | -> the working bank blob
        .equ    PART_STRIDE, 0x18b2
        .equ    OFF_MACH, 0x8eda2       | + t: machine type (0 ST, 1 FL, 2 THRU, 3 NEIGHBOR, 4 PU)
        .equ    OFF_P1, 0x8edaa         | + 30t + 6m + slot: page-1 bytes
        .equ    OFF_P2, 0x8ef5a         | + 30t + 6m + slot2: page-2 bytes
        .equ    OFF_SLOT5, 0x8f04a      | + 5t + m: 0-based sample slot byte
        .equ    SHADOW_ADJ, 0x100a4ece-0x8ed80 | SRAM part copy, same DB-relative offsets
        .equ    LIVE_P1, 0x80000810     | live page-1 byte, + 72t + flat
        .equ    LIVE_P2, 0x80000830     | live page-2 byte, + 72t + slot2
        .equ    BASE_W, 0x80000a50      | page-1 base words, + 64t + 2 flat, ui<<8
        .equ    SET_STATIC, 0x100d5b30  | sample settings records, stride 0x448
        .equ    SET_FLEX, 0x100b14f0
        .equ    SET_STRIDE, 0x448
        .equ    VOICE, 0x800049d8       | per-track voice state, stride 168; +8 = settings
        .equ    TEMPO24, 0x8000181c     | project BPM x 24, copied per frame (0x4000ca9a)
        .equ    TRIGB, 0x46104d0c       | + t: bit 4 = a new sound starts this frame
        .equ    DIRTY_PARTS, 0x95048    | DB-relative byte bitmask, |= 1<<part
        .equ    DIRTY_SRAM, 0x100b145e  | byte bitmask, |= 1<<part
        .equ    DIRTY_DB2, 0x9b332      | DB-relative long, = 1
        .equ    DIRTY_GLOBAL, 0x100f8598
        .equ    REDRAW_L, 0x46c7d248    | page-1 slot 0's knob-redraw mark (long 0x14)
        .equ    KNOB, 0x400479b4        | stock dial widget (x, y, idx, value, flags, fmt, canvas)
        .equ    PTCH_FMT, 0x4003b4b0    | stock PTCH formatter (slot 0 of ST/FL/PU)
        .equ    STEP_PTCH, 0x40032d08   | stock slot-0 encoder step handler
        .equ    ENC_A_HELD, 0x46c7de2e  | encoder A's press state
        .equ    ACCUM, 0x4003249c       | P2EDIT's delta -> steps conversion
        .equ    ENC_SETUP, 0x400326d4   | a page's encoder set-up (SRC SETUP's open calls it)
        .equ    ENC_F_HELD, 0x46c7d8ee+24*(0x38+5) | encoder F's push held (P2EDIT's x7 test)
        .equ    SPRINTF, 0x40013a08
        .equ    STR_UNK, 0x400b442a     | "???"
        .equ    STR_ERROR, 0x400b94f6   | "ERROR"
        .equ    STR_OFF, 0x400b4e78
        .equ    STR_AUTO, 0x400b571e
        .equ    STR_NORM, 0x400b5728
        .equ    STR_BEAT, 0x400b572d
        .equ    ATTR_PRINT, 0x4006e878  | the ATTR value chain's common print
        .equ    ATTR_TAIL_UP, 0x4006eef0
        .equ    ATTR_TAIL_DN, 0x4006f026
        .equ    ATTR_REDRAW, 0x4006dbdc
        .equ    NAME0_ST, 0x400d3032    | STATIC slot-0 caption (E+0x4e)
        .equ    NAME0_FL, 0x400d31c4    | FLEX slot-0 caption
        .equ    NAME11_ST, 0x400d3074   | STATIC slot-11 (TSNS) caption
        .equ    NAME11_FL, 0x400d3206   | FLEX slot-11 caption
        .equ    RENDER_BACK, 0x40004108 | after the render's increment store
        .equ    NOTIFY, 0x4005a2b8      | FUN_4005a2b8(text, dur): the stock toast. UI TASK ONLY
                                        | (it posts to the kernel; CLAUDE.md, NOTES "Session 93"):
                                        | raised from vg_tick alone, never from the frame path
        .equ    TOAST_DUR, 0x48         | 1.2 s in 1/60 s units: 1.5 x stock's house 0x30 (dur > 0
                                        | only: dur <= 0 is the modal path that hung a unit)
        .equ    UI_TAIL_BACK, 0x40062d22 | the UI task's message loop, after its tail test
        .equ    UI_FLUSH, 0x46c7c72c    | the loop tail's own test (displaced)
        .equ    APPLIED_B, 0x80001828   | bank, part the live bytes were last applied from (all
        .equ    APPLIED_P, 0x80001829   |   three Part applies write these, and nothing else)
        .equ    BANK0_DB, 0x400e21e0    | bank b's blob = BANK0_DB + b * BANK_STRIDE
        .equ    BANK_STRIDE, 0x9b340
        .equ    OFF_FX1, 0x8ed80        | + t: the Part's FX1 type id; FX2 at + 8 + t
        .equ    PART_B_UI, 0x100b14cf   | PART_B's mirror (written with it)
        .equ    FX1_CURSOR, 0x460d5c94  | the FX1 chooser's cursor row
        .equ    FX2_CURSOR, 0x460d5ca8  | the FX2 chooser's cursor row
        .equ    FX1_LIST, 0x400d6060    | the choosers' rows (-> P, whose long is the id)
        .equ    FX2_LIST, 0x400d6090

| ---------------------------------------------------------------------------- ours
        .equ    VARI, 4                 | TSTR / TSMODE raw value
        .equ    TSTR_AUTO, 1
        .equ    BPM24_MIN, 720          | 30..300 BPM, the firmware's own range
        .equ    BPM24_MAX, 7200
        .equ    INC_MAX, 0x07fffff0     | 2.0 - 16 LSB, Q26
        .equ    RP_HOLD, 0xfe
        .equ    PARK1_ST, 18            | NEIGHBOR p1 slot 0: STATIC's PTCH park
        .equ    PARK1_FL, 23            | NEIGHBOR p1 slot 5: FLEX's PTCH park
        .equ    PARK2_ST, 23            | NEIGHBOR p2 slot 5: STATIC's TSNS park
        .equ    PARK2_FL, 21            | NEIGHBOR p2 slot 3: FLEX's TSNS park
        .equ    TSNS_SLOT2, 5
        .equ    TSTR_SLOT2, 4
        .equ    EM_DETENTS, 4           | EMUS: detents in one direction per stop (spec §6b item 6)

| ---------------------------------------------------------------------------- the DSP load guard
| Spec §6 item 1 (the cost model) and §6b (the guard). Every price and budget the guard
| uses is HERE and nowhere else (the tests read this block). Unit: MODELLED DSP cycles
| per output sample, the unit of the KYOTI load audit as the spec carries it (the audit
| itself is not read here: clean-room). Reports: REPITCH_REWRITE_IMPL.md §10, §12.
| The estimate of a core is a property of the SETTINGS (spec §6b item 1): base + the
| prices of its four tracks' FX1 / FX2 types + the engine of each of its tracks that is
| a VARI track with EMUS on S950 / SP12.
|
| Base: the four-track voice loop with every FX NONE, per DSP core -- spec §6 item 1
| (re-measured in ot_emu on stock 1.40C, 2026-10-14: 577 / 482).
        .equ    VG_BASE_C1, 574         | DSP core 1: tracks T1-T4
        .equ    VG_BASE_C0, 477         | DSP core 0: tracks T5-T8
        .equ    VG_SC, 0                | SIDECHAIN_COMPRESSOR adds 56 per core when it shares
                                        | the image (spec §6 item 1); not in this one
| Stock FX1 / FX2 prices, per effect instance -- spec §6 item 1 (measured on core 1, used for
| both). The ids are the stock FX type ids (the Part's bytes +0x8ed80 / +0x8ed88 + t, the
| page descriptors' id word, IMPL §10.1).
        .equ    VG_FX_NONE, 0
        .equ    VG_FX_FILTER, 267       | id 0x04
        .equ    VG_FX_SPATIALIZER, 77   | id 0x05
        .equ    VG_FX_DELAY, 0          | id 0x08 (ColdFire)
        .equ    VG_FX_EQ, 200           | id 0x0c
        .equ    VG_FX_DJEQ, 347         | id 0x0d
        .equ    VG_FX_PHASER, 223       | id 0x10
        .equ    VG_FX_FLANGER, 146      | id 0x11
        .equ    VG_FX_CHORUS, 312       | id 0x12
        .equ    VG_FX_COMB, 111         | id 0x13
        .equ    VG_FX_PLATE, 240        | id 0x14
        .equ    VG_FX_SPRING, 306       | id 0x15 -- stock's price; THIS image runs the empty
        .equ    VG_FX_SPRING_HERE, 0    |   stub for it (SPRING is the DSP kernel's donor)
        .equ    VG_FX_DARK, 267         | id 0x16
        .equ    VG_FX_COMPRESSOR, 89    | id 0x18
        .equ    VG_FX_LOFI, 313         | id 0x1c
| The emulation engines, per VARI track whose EMUS selects them (the DSP runs the engine on
| every pass whose increment carries it, sounding or not, IMPL §10.1): the worst case over the
| playback ratios 0.5-1.99x, both payloads, of tools/repitch_dsp_profile.py, its "~hw"
| column (a one-word instruction 2 cycles, a displaced access +2). VEM3's kernel: RPSP 269.8,
| RPS9 108.6 (its datasheet column, 146.5 / 57.3, cannot reproduce the user's brackets below,
| IMPL §10.3; this one does). The optimized kernels (VEM4, VARISPEED_EMUS_DSP_OPT.md),
| re-profiled 2026-10-15: RPSP 217.2, RPS9 99.0.
        .equ    VG_S950, 99
        .equ    VG_SP12, 218
| Budgets: the CLEAN points of the user's hardware brackets (4 SP12 voices, DARK on every
| FX2, DJ EQ added on FX1) -- spec §6 item 2. An estimate above them does not fit.
        .equ    VG_BUDGET_C1, 3930      | T1-T4 (crash ~4,310)
        .equ    VG_BUDGET_C0, 3350      | T5-T8, the core that fails first (crash ~3,740)

| ============================================================================
| PART 1 -- NEW CORE
| ============================================================================

| ---------------------------------------------------------------------------
| vem_frame: `jmp` from 0x40004100, the render's increment store, on the SECOND pass
| of a STATIC / FLEX / PICKUP track only (the first pass reuses 36(a3)). It replays
| the displaced `movclr.l acc0,d0 ; asr.l d6,d0 ; move.l d0,36(a3)` with d0 decided
| here, and returns to 0x40004108.
|   in:  acc0 = stock pitch x rate, d6 = its shift, a3 = render state (+36 = the
|        increment, reused by the next first pass), fp = this frame's lane record,
|        a5 -> this frame's machine byte, 52(sp) = track
|   out: d0 = the increment, 36(a3) = d0, acc0 = 0 (MACSR untouched)
|   free: d1-d5, d7, a0-a2, a4, a5 (written before read up to the epilogue)
| A track that is not a VARI candidate and whose rp_prev byte is 0 costs the test (and,
| in VARISPEED_EMUS, the mask). VARISPEED_EMUS: bits 2-3 of every increment carry the DSP
| engine: 0 everywhere but on a VARI track, where they are the engine latched at its last
| trig. VARISPEED: a VARI track's increment has bits 0-3 clear (VARISPEED_EMUS's on OT,
| bit for bit); every other increment is stock's, untouched.
vem_frame:
        .word   0xa1c0                  | movclr.l %acc0,%d0 (displaced)
        asr.l   %d6,%d0                 | displaced: d0 = stock's increment
        move.l  %d0,%d7                 | kept for the stock paths
        moveq   #0,%d3
        move.b  (%a5),%d3               | runtime machine: 0 ST, 1 FL, 2 PU
        moveq   #1,%d1
        cmp.l   %d1,%d3
        bhi     .vf_plain               | PICKUP: untouched
        move.l  52(%sp),%d2             | track
        moveq   #0,%d4                  | d4 = 1: a VARI candidate
        mvz.b   28(%fp),%d1             | lane TSTR (this frame's composed byte)
        moveq   #VARI,%d5
        cmp.l   %d5,%d1
        beq.s   .vf_cand
        moveq   #TSTR_AUTO,%d5
        cmp.l   %d5,%d1
        bne.s   .vf_nc
        bsr     voice_set               | AUTO: the voice's sample settings -> a1
        beq.s   .vf_nc
        moveq   #VARI,%d5
        cmp.l   0x110(%a1),%d5          | the sample's TSMODE
        bne.s   .vf_nc
.vf_cand:
        moveq   #1,%d4
        clr.b   28(%fp)                 | dry: the stream engine's resolve reads OFF
        bra.s   .vf_poll
.vf_nc:
        lea     rp_prev(%pc),%a0        | not a candidate: poll only while this
        move.l  %d2,%d1                 | machine's rp_prev byte is nonzero
        add.l   %d1,%d1
        add.l   %d3,%d1
        tst.b   (%a0,%d1.l)
        beq     .vf_plain
.vf_poll:
        move.l  %d2,%d1
        bsr     rp_swap                 | d0 = md<<8 | domain<<1 | swapped
        move.l  %d0,%d5
        btst    #1,%d5
        beq     .vf_plain               | the slot holds PTCH: stock pitch
        move.l  %d5,%d1
        lsr.l   #8,%d1
        cmp.l   %d3,%d1
        bne     .vf_plain               | the DB machine is not the one rendering
| Engaged only when the runtime gate agrees: a candidate (the lane's own TSTR, or AUTO
| through the sample this voice plays), its sample and the project tempo in 30..300
| BPM. Anything else -- out of range, or the Part gate and the voice disagreeing (a
| sample lock under AUTO) -- plays exactly as stock would (masked), dry if a candidate.
        tst.l   %d4
        beq     .vf_plain
        bsr     voice_set               | the sample this voice plays
        beq     .vf_plain
        move.l  0x114(%a1),%d4          | S = its BPM x 24
        cmpi.l  #BPM24_MIN,%d4
        blt     .vf_plain
        cmpi.l  #BPM24_MAX,%d4
        bgt     .vf_plain
        move.l  (TEMPO24).l,%d3         | T = the project's BPM x 24
        cmpi.l  #BPM24_MIN,%d3
        blt     .vf_plain
        cmpi.l  #BPM24_MAX,%d3
        bgt     .vf_plain
| The slot holds QUAN: PTCH is not pitch. The increment is RATE alone, exactly what
| stock computes with a neutral PTCH word (0x4000 -> 1.0, shift 1): the two EMAC
| products are exact multiples of 2^45, so the closed form is bit-identical.
        mvz.w   6(%fp),%d1              | lane RATE word
        mvz.b   27(%fp),%d0             | SETUP RATE mode: TSTR -> RATE not applied
        bne.s   .vf_unity
        cmpi.w  #0x7f00,%d1             | stock's own test (a signed word compare)
        bge.s   .vf_unity
        move.l  %d1,%d0
        andi.l  #0x3fff,%d0
        btst    #14,%d1
        bne.s   1f
        neg.l   %d0                     | below centre: (0x4000 - w) << 12, reverse
        addi.l  #0x4000,%d0
1:      moveq   #12,%d1
        lsl.l   %d1,%d0
        bra.s   .vf_rate
.vf_unity:
        move.l  #0x04000000,%d0
.vf_rate:
        move.l  %d0,%d7                 | d7 = the rate increment
| QUAN: the composed PTCH word's ui value, or the live byte on a swap frame (the lane
| was copied before the swap and still holds the old domain).
        btst    #0,%d5
        beq.s   1f
        movea.l %d2,%a0
        move.l  %d2,%d0
        lsl.l   #3,%d0                  | 72t = 64t + 8t
        lsl.l   #6,%d2
        add.l   %d0,%d2
        lea     (LIVE_P1).l,%a1
        moveq   #0,%d0
        move.b  (%a1,%d2.l),%d0
        move.l  %a0,%d2
        bra.s   2f
1:      mvz.w   (%fp),%d0
        lsr.l   #8,%d0
2:      bsr     rk_bucket               | d0 = idx 0..8
        add.l   %d0,%d0
        lea     rk_ratios(%pc),%a0
        moveq   #0,%d1
        move.b  (%a0,%d0.l),%d1         | p
        mulu.l  %d1,%d3                 | N = T * p
        move.b  1(%a0,%d0.l),%d1        | q
        mulu.l  %d1,%d4                 | D = S * q
        move.l  %d4,%d1
.vf_fold:
        add.l   %d1,%d1                 | 2D
        cmp.l   %d1,%d3
        bls.s   .vf_folded              | N <= 2D
        add.l   %d4,%d4                 | an exact octave
        move.l  %d4,%d1
        bra.s   .vf_fold
.vf_folded:
        move.l  %d7,%d0
        divu.l  %d4,%d0                 | q1 = inc / D
        remu.l  %d4,%d1:%d7             | r1 = inc % D
        mulu.l  %d3,%d0                 | q1 * N   (< 2^28 after the fold)
        mulu.l  %d3,%d1                 | r1 * N   (< D * N < 2^32)
        divu.l  %d4,%d1
        add.l   %d1,%d0                 | floor(inc * N / D)
        cmpi.l  #INC_MAX,%d0
        bls.s   1f
        move.l  #INC_MAX,%d0
1:
        .if VEM_EMUS
| The engine: latched when this track's new sound starts (the trig byte's bit 4 is
| still set during this second pass; the voice loop clears it at 0x4000d534), carried
| in 36(a3) bits 2-3 on every other frame. Nothing here steps an engine down (spec §6b
| item 1): the guard keeps the SETTINGS within the budget, and the latch takes them.
        lea     (TRIGB).l,%a0
        adda.l  %d2,%a0
        btst    #4,(%a0)
        beq.s   .vf_carry
        btst    #0,%d5
        beq.s   1f
        move.l  %d2,%d1                 | swap frame: the live EMUS byte
        lsl.l   #3,%d1
        move.l  %d2,%d4
        lsl.l   #6,%d4
        add.l   %d4,%d1
        lea     (LIVE_P2+TSNS_SLOT2).l,%a1
        move.l  %d0,%d4
        mvs.b   0(%a1,%d1.l),%d0
        bra.s   2f
1:      move.l  %d0,%d4
        mvs.b   29(%fp),%d0             | lane TSNS = the composed EMUS value
2:      bsr     emus_idx
        lea     emus_mode(%pc),%a0
        mvz.b   0(%a0,%d0.l),%d1        | DSP mode 0 OT / 1 S950 / 2 SP12
        move.l  %d4,%d0
        bra.s   .vf_tag
.vf_carry:
        move.l  36(%a3),%d1             | the latched engine, from the last frame
        lsr.l   #2,%d1
        moveq   #3,%d4
        and.l   %d4,%d1
.vf_tag:
        moveq   #-16,%d4
        and.l   %d4,%d0
        lsl.l   #2,%d1
        or.l    %d1,%d0
        bra.s   .vf_store
        .else
        moveq   #-16,%d4                | bits 0-3 clear: VARISPEED_EMUS's increment on OT
        and.l   %d4,%d0                 |   (engine 0), bit for bit
        bra.s   .vf_store
        .endif
.vf_plain:
        move.l  %d7,%d0
        .if VEM_EMUS
        andi.l  #0xfffffff3,%d0         | bits 2-3 are the DSP engine: never stock's
        .endif                          | (VARISPEED: stock's increment, untouched)
.vf_store:
        move.l  %d0,36(%a3)
        jmp     (RENDER_BACK).l
| d2 = track -> a1 = the sample settings record the voice plays (voice +8), Z set when
| there is none. Keeps everything but d1/a1 (d1 = the offset).
voice_set:
        move.l  #168,%d1
        mulu.l  %d2,%d1
        lea     (VOICE).l,%a1
        move.l  8(%a1,%d1.l),%d1
        movea.l %d1,%a1
        rts

        .if VEM_EMUS
| d0 = an EMUS value (signed byte) -> d0 = its stop index: 0 OT (..42 and any
| negative), 1 S950 (43..85), 2 SP12 (86..). Keeps everything else.
emus_idx:
        tst.l   %d0
        bmi.s   1f
        cmpi.l  #42,%d0
        ble.s   1f
        cmpi.l  #85,%d0
        ble.s   2f
        moveq   #2,%d0
        rts
1:      moveq   #0,%d0
        rts
2:      moveq   #1,%d0
        rts
        .endif

| ---------------------------------------------------------------------------
| tstr_fmt(buf, v): the STATIC / FLEX TSTR readout (descriptor formatter column; PICKUP
| keeps stock's). OFF AUTO NORM BEAT VARI, else "???". Stock's tail: sprintf(buf, s).
tstr_fmt:
        move.l  8(%sp),%d0
        moveq   #VARI,%d1
        cmp.l   %d1,%d0
        bhi.s   1f                      | unsigned: catches negatives too
        lsl.l   #2,%d0
        lea     tstr_tab(%pc),%a0
        move.l  (%a0,%d0.l),%d0
        move.l  %d0,8(%sp)
        jmp     (SPRINTF).l
1:      lea     (STR_UNK).l,%a0
        move.l  %a0,8(%sp)
        jmp     (SPRINTF).l

| ---------------------------------------------------------------------------
| The audio editor's ATTR page, TIMESTRETCH row (the sample's own TSMODE).
| attr_label: `jmp` from 0x4006e71c, the `else` of the label chain (stock: ERROR).
|   d0 = TSMODE; 4 -> "VARI", anything else stays "ERROR" (5/6 too, as stock).
attr_label:
        cmpi.l  #VARI,%d0
        bne.s   1f
        pea     str_vari(%pc)
        jmp     (ATTR_PRINT).l
1:      pea     (STR_ERROR).l
        jmp     (ATTR_PRINT).l

| attr_up: `jmp` from 0x4006ee48, the row-2 branch of the value-up handler, a0 =
| settings. OFF -> NORMAL -> BEAT -> VARI, stops there; then the handler's tail.
attr_up:
        move.l  0x110(%a0),%d0
        bne.s   1f
        moveq   #2,%d0
        bra.s   .au_st
1:      moveq   #2,%d1
        cmp.l   %d1,%d0
        bne.s   2f
        moveq   #3,%d0
        bra.s   .au_st
2:      moveq   #3,%d1
        cmp.l   %d1,%d0
        bne.s   .au_out                 | VARI and anything unknown: no change
        .if VEM_EMUS
        moveq   #7,%d1                  | BEAT -> VARI: tracks under AUTO on this sample enter
3:      bsr     vg_note                 |   VARI. Every track whose gate is off before the
        subq.l  #1,%d1                  |   edit is noted: vg_tick gives one the edit puts on
        bpl.s   3b                      |   VARI over budget EMUS = OT, its own (VEM7)
        .endif
        moveq   #VARI,%d0
.au_st: move.l  %d0,0x110(%a0)
.au_out:
        bsr     rp_refresh
        jmp     (ATTR_TAIL_UP).l

| attr_down: `jmp` from 0x4006ef7c. VARI -> BEAT -> NORMAL -> OFF; 5/6 stay (stock).
attr_down:
        move.l  0x110(%a0),%d0
        moveq   #VARI,%d1
        cmp.l   %d1,%d0
        bne.s   1f
        moveq   #3,%d0
        bra.s   .ad_st
1:      moveq   #3,%d1
        cmp.l   %d1,%d0
        bne.s   2f
        moveq   #2,%d0
        bra.s   .ad_st
2:      moveq   #2,%d1
        cmp.l   %d1,%d0
        bne.s   .ad_out
        moveq   #0,%d0
.ad_st: move.l  %d0,0x110(%a0)
.ad_out:
        bsr     rp_refresh
        jmp     (ATTR_TAIL_DN).l

| attr_tail: `jmp` from both handlers' common tail (0x4006eef0, 0x4006f026, each
| `movea.l (sp)+,a2 ; jmp 0x4006dbdc`): every ATTR edit polls the gates, so a TEMPO
| or TIMESTRETCH change that moves a track in or out of VARI swaps its domains now.
attr_tail:
        bsr     rp_poll_all
        movea.l (%sp)+,%a2
        jmp     (ATTR_REDRAW).l

        .if VEM_EMUS
| ---------------------------------------------------------------------------
| EMUS -- the TSNS slot (SRC SETUP slot 11) of a VARI track.
|
| emus_widget: STATIC / FLEX slot-11 widget column (stock 0 = the default dial). Args
| (x, y, index, value, flags, fmt, canvas). Off ST/FL or off VARI: the stock dial. On
| VARI: the dial snapped to the value's stop, read out by emus_fmt. The caption is
| drawn after the widget in the same pass (0x4003ce7a), so writing it here is enough.
emus_widget:
        move.l  %d2,-(%sp)              | (args now 8..32)
        moveq   #0,%d1
        move.b  (UI_TRACK).l,%d1
        bsr     db_mach
        moveq   #1,%d0
        cmp.l   %d0,%d2
        bls.s   1f
        move.l  (%sp)+,%d2
        jmp     (KNOB).l                | not ST/FL: stock, no poll
1:      bsr     rp_swap_ui
        andi.l  #1,%d0                  | the swap flag
        movea.l %d0,%a1
        bsr     rp_gate_m               | d1 = track, d2 = machine
        bsr     caption_m               | this descriptor's captions follow the gate
        tst.l   %d0
        bne.s   .ew_emus
        move.l  %a1,%d0
        bne.s   1f
        move.l  (%sp)+,%d2
        jmp     (KNOB).l                | TSNS, not swapped: stock, untouched
1:      bsr     live_tsns               | swapped on this draw: the restored TSNS
        movea.l 28(%sp),%a1             | with the caller's formatter
        bra.s   .ew_frame
.ew_emus:
        move.l  20(%sp),%d0             | the caller's value
        move.l  %a1,%d2
        beq.s   1f
        bsr     live_tsns               | swapped: the fresh EMUS value
1:      lea     emus_fmt(%pc),%a1
        tst.l   %d0
        bmi.s   .ew_frame               | an empty cell keeps the bare frame
        bsr     emus_idx                | the readout is the stored value: what plays
        lea     emus_stops(%pc),%a0
        mvz.b   0(%a0,%d0.l),%d0
.ew_frame:
        move.l  32(%sp),-(%sp)          | canvas
        move.l  %a1,-(%sp)              | formatter
        move.l  32(%sp),-(%sp)          | flags
        move.l  %d0,-(%sp)              | value
        move.l  32(%sp),-(%sp)          | index
        move.l  32(%sp),-(%sp)          | y
        move.l  32(%sp),-(%sp)          | x
        jsr     (KNOB).l
        lea     28(%sp),%sp
        move.l  (%sp)+,%d2
        rts

| d1 = track -> d0 = its live TSNS byte (signed). Keeps everything else.
live_tsns:
        move.l  %d1,-(%sp)
        move.l  %a0,-(%sp)
        move.l  %d1,%d0
        lsl.l   #3,%d0
        lsl.l   #6,%d1
        add.l   %d0,%d1
        lea     (LIVE_P2+TSNS_SLOT2).l,%a0
        mvs.b   0(%a0,%d1.l),%d0
        movea.l (%sp)+,%a0
        move.l  (%sp)+,%d1
        rts

| emus_fmt(buf, v): OT / S950 / SP12 by bucket; a negative value "???".
emus_fmt:
        move.l  8(%sp),%d0
        bmi.s   1f
        bsr     emus_idx
        lsl.l   #2,%d0
        lea     emus_tab(%pc),%a0
        move.l  (%a0,%d0.l),%d0
        move.l  %d0,8(%sp)
        jmp     (SPRINTF).l
1:      lea     (STR_UNK).l,%a0
        move.l  %a0,8(%sp)
        jmp     (SPRINTF).l

| emus_p2step(slot2, delta): `jsr` redirected from P2EDIT's only delta conversion
| (0x4003a566, stock `jsr 0x4003249c`), returning the steps P2EDIT adds to the
| stored byte. On an ST/FL VARI track's slot 5, EM_DETENTS detents in one direction
| move ONE stop; a detent the other way restarts the count, so jitter cannot flip it.
| Detents, not units: the panel's report is a signed detent count that P2EDIT has
| multiplied by 7 while the encoder is pushed, so a pushed report counts |units| / 7;
| a report of several detents (a fast turn) counts them all, never more. The count
| (em_tally) belongs to one track / machine / part (em_ctx) and restarts when that
| changes or SRC SETUP opens (emus_open). The return is (stop - old), so P2EDIT
| stores the stop itself (a non-stop value snaps to its bucket's stop on the first
| detent). The DSP load guard (spec §6b item 2): a move toward a dearer engine stops at
| the highest stop whose engine fits the track's DSP core (vg_cap), and flags the toast
| if it stopped short; a move toward a cheaper one is always allowed. TSTR (slot 4): the
| panel's track is noted when its gate is off (vg_note; vg_tick then gives it EMUS = OT if
| the edit put it on VARI over budget), then stock's conversion. Everything else: stock's.
| P2EDIT's own registers (d2 = old value, d3, d4, d5, a2-a5) are kept: C ABI, d0/d1/a0/a1
| only. This is P2EDIT, the SRC SETUP page's encoder handler (UI task).
emus_p2step:
        move.l  (PAGE_M).l,%d0
        moveq   #1,%d1
        cmp.l   %d1,%d0
        bhi.s   .ep_stock               | not ST / FL
        moveq   #TSNS_SLOT2,%d0
        cmp.l   4(%sp),%d0
        beq.s   1f
        moveq   #TSTR_SLOT2,%d0
        cmp.l   4(%sp),%d0
        bne.s   .ep_stock
        moveq   #0,%d1                  | TSTR: note the panel's track if it is off VARI now
        move.b  (UI_TRACK).l,%d1
        bsr     vg_note
.ep_stock:
        jmp     (ACCUM).l
1:      move.l  8(%sp),-(%sp)           | stock's accumulator first: it keeps its own
        move.l  8(%sp),-(%sp)           | state and its hold-off; for TSNS one unit is
        jsr     (ACCUM).l               | one step, so d0 = the units of this report
        addq.l  #8,%sp
        tst.l   %d0
        beq     .ep_out                 | nothing this time
        lea     -16(%sp),%sp
        movem.l %d2-%d5,(%sp)
        move.l  %d0,%d4                 | units, signed
        moveq   #0,%d1
        move.b  (UI_TRACK).l,%d1
        move.l  (PAGE_M).l,%d2
| the count's owner: track | machine << 8 | part << 16
        move.l  %d2,%d0
        lsl.l   #8,%d0
        or.l    %d1,%d0
        moveq   #0,%d3
        move.b  (PART_B).l,%d3
        swap    %d3
        or.l    %d3,%d0
        cmp.l   (em_ctx).l,%d0
        beq.s   2f
        move.l  %d0,(em_ctx).l
        clr.b   (em_tally).l            | another track / machine / part: start over
2:      bsr     rp_swap_ui              | settle the domain before deciding
        bsr     rp_gate_m
        tst.l   %d0
        bne.s   3f
        move.l  %d4,%d0                 | not VARI: stock's steps
        bra     .ep_ret
3:      move.l  %d4,%d5                 | d5 = detents = |units|, / 7 when pushed
        bpl.s   4f
        neg.l   %d5
4:      tst.l   (ENC_F_HELD).l
        beq.s   5f
        moveq   #7,%d0
        divu.l  %d0,%d5
        bne.s   5f
        moveq   #1,%d5
5:      mvs.b   (em_tally).l,%d3        | signed: the direction and the count so far
        tst.l   %d4
        bmi.s   .ep_down
        tst.l   %d3
        bpl.s   6f
        moveq   #0,%d3                  | turned back: restart
6:      add.l   %d5,%d3
        moveq   #0,%d5                  | d5 = stops to move
7:      moveq   #EM_DETENTS,%d0
        cmp.l   %d0,%d3
        blt.s   .ep_count
        sub.l   %d0,%d3
        addq.l  #1,%d5
        bra.s   7b
.ep_down:
        tst.l   %d3
        ble.s   6f
        moveq   #0,%d3                  | turned back: restart
6:      sub.l   %d5,%d3
        moveq   #0,%d5
7:      moveq   #-EM_DETENTS,%d0
        cmp.l   %d0,%d3
        bgt.s   .ep_count
        sub.l   %d0,%d3
        subq.l  #1,%d5
        bra.s   7b
.ep_count:
        move.b  %d3,(em_tally).l
        bsr     db_tsns                 | d0 = the stored byte now (d1 track, d2 m)
        bsr     emus_idx
        move.l  %d0,%d3                 | the stop it is on
        add.l   %d5,%d0
        bpl.s   8f
        moveq   #0,%d0
8:      moveq   #2,%d4
        cmp.l   %d4,%d0
        ble.s   9f
        move.l  %d4,%d0
9:      cmp.l   %d3,%d0
        ble.s   9f                      | the same stop, or a cheaper one: always allowed
        bsr     vg_cap                  | dearer: the highest stop up to it that fits
9:      lea     emus_stops(%pc),%a0
        mvz.b   0(%a0,%d0.l),%d0
        sub.l   (%sp),%d0               | - P2EDIT's old value (its d2): P2EDIT adds
                                        | this to its d2 and stores the stop itself,
                                        | even if a swap just moved the byte under it
.ep_ret:
        movem.l (%sp),%d2-%d5
        lea     16(%sp),%sp
.ep_out:
        rts

| emus_open: `jsr` redirected from SRC SETUP's open (0x400585f4, stock `jsr 0x400326d4`,
| the page's encoder set-up). It runs at every open of the page: entering it, and the
| re-open a track change makes. A half-turned EMUS count never carries over.
emus_open:
        clr.b   (em_tally).l
        jmp     (ENC_SETUP).l

| ---------------------------------------------------------------------------
| THE DSP LOAD GUARD (spec §6b and "6b, simplified"; constants: VG_* above; IMPL §12).
| The load of a DSP core is a property of the SETTINGS: base + the prices of its four
| tracks' FX1 / FX2 types (the current Part's bytes) + the engine of each of its tracks
| that is a VARI track whose EMUS is S950 / SP12 (vg_scan, vg_est). Nothing here looks at
| playback, and nothing steps a playing voice down: the engine latch at the trig is the
| frame hook's, unchanged. The guard keeps the settings within the budget instead:
|   * two refusals, at their UI handlers: EMUS turned toward an engine that does not fit
|     stops at the highest stop that fits (vg_cap, from P2EDIT); an FX type that does not
|     fit, when emulated engines are what tip the core over, does not land (vg_fx_try,
|     from the FX choosers' YES);
|   * TSTR / ATTR TIMESTRETCH onto VARI (spec "6b, answers", VEM7): the user acts on that
|     track, so when the edit puts its core over the budget THAT track's EMUS goes to OT
|     first (vg_note in the handler, vg_entered + vg_fix on those tracks alone in vg_tick);
|   * one safety net (vg_tick -> vg_fix): however a core got over its budget -- a Part
|     change or reload, a project or bank load (old projects included), a machine change,
|     a paste, a sample or tempo change that turns a gate on, and whatever the entering
|     track's own step leaves over --
|     just enough of its tracks get EMUS = OT, SP12 first, then S950, highest track number
|     first. It runs in the UI task's message loop, and only when a cheap signature of the
|     estimate's inputs (vg_sig) differs from the last one checked. RELOAD PART has no
|     special code: the net acts on a reload whose result is over budget;
|   * the toast MAX DSP: EMU LIMIT (1.2 s) is raised there too, the one NOTIFY: right after
|     the UI handler that caused it, or at the next UI message (a tick at 60 Hz) when the
|     cause was not the UI's (a sequencer Part switch). Never from the frame path.
| The frame hook gains nothing: no per-frame estimate, no step-down, no toast.

| vg_scan: vg_eng[t] = the DSP engine track t's settings run (0 OT / 1 S950 / 2 SP12), for
| the current Part: 0 unless its current machine is ST / FL, that machine's gate is on
| (rp_gate_m: VARI, or AUTO on a VARI sample, the sample's tempo in range) and the project
| tempo is in range; then the engine of its EMUS value -- in the TSNS slot, or in the park
| while the swap is still to come (rp_prev[2t+m] == 0: the gate came on since the last
| poll). Keeps every register.
vg_scan:
        lea     -24(%sp),%sp
        movem.l %d0-%d3/%a0-%a1,(%sp)
        bsr     rp_sync                 | rp_prev must describe this Part
        lea     vg_eng(%pc),%a1
        clr.l   (%a1)
        clr.l   4(%a1)
        move.l  (TEMPO24).l,%d0
        cmpi.l  #BPM24_MIN,%d0
        blt.s   .vs_out                 | the project tempo out of range: every VARI track
        cmpi.l  #BPM24_MAX,%d0          |   plays as OFF, no engine anywhere
        bgt.s   .vs_out
        moveq   #0,%d1
1:      bsr     db_mach                 | d2 = m
        moveq   #1,%d0
        cmp.l   %d0,%d2
        bhi.s   3f                      | not ST / FL
        bsr     rp_gate_m
        tst.l   %d0
        beq.s   3f
        lea     rp_prev(%pc),%a0
        move.l  %d1,%d0
        add.l   %d0,%d0
        add.l   %d2,%d0
        tst.b   0(%a0,%d0.l)
        bne.s   2f
        bsr     db_park2                | the swap still to come: EMUS is parked
        bra.s   4f
2:      bsr     db_tsns
4:      bsr     emus_idx
        move.b  %d0,0(%a1,%d1.l)
3:      addq.l  #1,%d1
        moveq   #8,%d0
        cmp.l   %d0,%d1
        blt.s   1b
.vs_out:
        movem.l (%sp),%d0-%d3/%a0-%a1
        lea     24(%sp),%sp
        rts

| vg_fxsum: d0 = g (0: T1-T4, DSP core 1 / 4: T5-T8, core 0) -> d0 = the prices of the
| current Part's FX1 and FX2 types on the core's four tracks. Keeps all but d0.
vg_fxsum:
        lea     -16(%sp),%sp
        movem.l %d1-%d2/%a0-%a1,(%sp)
        bsr     part_base
        adda.l  #OFF_FX1,%a0
        adda.l  %d0,%a0                 | -> FX1 of the core's first track (FX2 at + 8)
        lea     vg_fxp(%pc),%a1
        moveq   #0,%d0
        moveq   #3,%d2
1:      mvz.b   (%a0),%d1
        andi.l  #0x1f,%d1
        add.l   %d1,%d1
        mvz.w   0(%a1,%d1.l),%d1
        add.l   %d1,%d0
        mvz.b   8(%a0),%d1
        andi.l  #0x1f,%d1
        add.l   %d1,%d1
        mvz.w   0(%a1,%d1.l),%d1
        add.l   %d1,%d0
        addq.l  #1,%a0
        subq.l  #1,%d2
        bpl.s   1b
        movem.l (%sp),%d1-%d2/%a0-%a1
        lea     16(%sp),%sp
        rts

| vg_est: d0 = g -> d0 = the core's estimate: base + its FX + the engines vg_scan left in
| vg_eng for its four tracks. Keeps all but d0.
vg_est:
        lea     -20(%sp),%sp
        movem.l %d1-%d3/%a0-%a1,(%sp)
        move.l  %d0,%d3
        bsr     vg_fxsum
        lea     vg_base(%pc),%a0
        add.l   0(%a0,%d3.l),%d0
        lea     vg_eng(%pc),%a0
        adda.l  %d3,%a0
        lea     vg_engp(%pc),%a1
        moveq   #3,%d2
1:      mvz.b   (%a0)+,%d1
        lsl.l   #2,%d1
        add.l   0(%a1,%d1.l),%d0
        subq.l  #1,%d2
        bpl.s   1b
        movem.l (%sp),%d1-%d3/%a0-%a1
        lea     20(%sp),%sp
        rts

| vg_room: d1 = track -> d0 = the room its core has for its engine: the budget minus the
| estimate without that track's own engine. Interrupts masked across. Keeps all but d0.
vg_room:
        lea     -16(%sp),%sp
        movem.l %d1-%d3/%a0,(%sp)
        move.w  %sr,%d3
        move.w  #0x2700,%sr
        bsr     vg_scan
        move.l  %d1,%d2
        andi.l  #4,%d2                  | g
        move.l  %d2,%d0
        bsr     vg_est
        lea     vg_eng(%pc),%a0
        mvz.b   0(%a0,%d1.l),%d1
        lsl.l   #2,%d1
        lea     vg_engp(%pc),%a0
        sub.l   0(%a0,%d1.l),%d0        | the core without this track's engine
        lea     vg_budget(%pc),%a0
        move.l  0(%a0,%d2.l),%d1
        sub.l   %d0,%d1
        move.l  %d1,%d0
        move.w  %d3,%sr
        movem.l (%sp),%d1-%d3/%a0
        lea     16(%sp),%sp
        rts

| d0 = the project tempo's state: Z set when it is in 30..300 BPM. Keeps all but d0.
vg_tempo_ok:
        move.l  (TEMPO24).l,%d0
        cmpi.l  #BPM24_MIN,%d0
        blt.s   1f
        cmpi.l  #BPM24_MAX,%d0
        bgt.s   1f
        moveq   #0,%d0
        rts
1:      moveq   #1,%d0
        rts

| vg_cap (P2EDIT, the EMUS step, spec §6b item 2): d0 = the stop asked for, dearer than d3
| = the stop EMUS is on now, d1 = track -> d0 = the highest stop from d3 up to it whose
| engine fits the track's core (the room vg_room leaves). Stopped short: the toast is
| flagged. A project tempo out of range: the track is no VARI track (no engine), granted.
| Keeps all but d0.
vg_cap:
        lea     -20(%sp),%sp
        movem.l %d1-%d4/%a0,(%sp)
        move.l  %d0,%d2
        bsr     vg_tempo_ok
        bne.s   3f
        bsr     vg_room                 | d0 = room
        lea     vg_engp(%pc),%a0
1:      cmp.l   %d3,%d2
        ble.s   3f                      | back on the stop it is on: it stays there
        move.l  %d2,%d4
        lsl.l   #2,%d4
        cmp.l   0(%a0,%d4.l),%d0
        bge.s   3f                      | fits
        subq.l  #1,%d2
        moveq   #1,%d4
        move.b  %d4,(vg_toast).l        | refused (as far as it went): MAX DSP: EMU LIMIT
        bra.s   1b
3:      move.l  %d2,%d0
        movem.l (%sp),%d1-%d4/%a0
        lea     20(%sp),%sp
        rts

| vg_fix: d0 = the tracks it may step (bit t). The current Part: while a core's estimate
| is over its budget, the next track of that core -- SP12 first, then S950, highest track
| number first, within the mask -- gets EMUS = OT (vg_step_ot): just enough (spec §6b
| item 3). Stock FX alone over the budget: every emu track of the core steps, then
| nothing more. -> d0 = 1 when it stepped anything (the toast flagged), else 0.
| Interrupts masked inside (the frame hook's swaps and this never interleave); nothing
| while a bulk write holds the Part (vem_depth: the net runs after it). Data writes only.
| Keeps all but d0.
vg_fix:
        lea     -36(%sp),%sp
        movem.l %d1-%d7/%a0-%a1,(%sp)
        move.w  %sr,%d7
        move.w  #0x2700,%sr
        move.l  %d0,%d6                 | the mask
        moveq   #0,%d5                  | stepped?
        tst.b   (vem_depth).l
        bne.s   .vx_out
        bsr     vg_scan
        lea     vg_eng(%pc),%a0
        lea     vg_budget(%pc),%a1
        moveq   #0,%d4                  | g = 0 (core 1), then 4 (core 0)
.vx_core:
        move.l  %d4,%d0
        bsr     vg_est
        cmp.l   0(%a1,%d4.l),%d0
        ble.s   .vx_next                | fits
        moveq   #2,%d3                  | SP12 first, then S950
1:      moveq   #3,%d2                  | the core's highest track first
2:      move.l  %d4,%d1
        add.l   %d2,%d1
        btst    %d1,%d6
        beq.s   3f
        mvz.b   0(%a0,%d1.l),%d0
        cmp.l   %d3,%d0
        beq.s   4f
3:      subq.l  #1,%d2
        bpl.s   2b
        subq.l  #1,%d3
        bne.s   1b
        bra.s   .vx_next                | no emu track left to step
4:      bsr     vg_step_ot              | d1 = t
        clr.b   0(%a0,%d1.l)
        moveq   #1,%d5
        bra.s   .vx_core
.vx_next:
        addq.l  #4,%d4
        moveq   #8,%d0
        cmp.l   %d0,%d4
        blt.s   .vx_core
        tst.l   %d5
        beq.s   .vx_out
        move.b  %d5,(vg_toast).l
.vx_out:
        move.w  %d7,%sr
        move.l  %d5,%d0
        movem.l (%sp),%d1-%d7/%a0-%a1
        lea     36(%sp),%sp
        rts

| vg_step_ot: d1 = track: its EMUS becomes OT (stored 1) in the current Part, where it
| lives now: the TSNS slot of its current machine, or that machine's park while the swap
| into VARI is still to come (rp_prev 0). The working DB and its SRAM copy with the
| writer's dirty flags, as the swap writes them; the live byte too when the slot holds it
| and the live bytes are this Part's (APPLIED_B / APPLIED_P: during a sequencer Part switch
| the UI task moves PART_B a step before the frame applies the new Part). The swap's own
| rules then keep PTCH/QUAN and TSNS/EMUS consistent. Keeps every register.
vg_step_ot:
        lea     -28(%sp),%sp
        movem.l %d0-%d3/%a0-%a2,(%sp)
        bsr     db_mach                 | d2 = m
        bsr     part_base               | a0 = the Part's block
        moveq   #0,%d0
        move.b  (PART_B).l,%d0
        move.l  #PART_STRIDE,%d3
        mulu.l  %d3,%d0
        lea     (SHADOW_ADJ).l,%a1
        adda.l  %d0,%a1                 | a1 = its SRAM copy
        moveq   #30,%d3
        mulu.l  %d1,%d3
        addi.l  #OFF_P2,%d3             | d3 = the track's page-2 row
        lea     rp_prev(%pc),%a2
        move.l  %d1,%d0
        add.l   %d0,%d0
        add.l   %d2,%d0
        tst.b   0(%a2,%d0.l)
        bne.s   1f
        addi.l  #PARK2_ST,%d3           | the park
        tst.l   %d2
        beq.s   2f
        subq.l  #PARK2_ST-PARK2_FL,%d3
2:      moveq   #1,%d0
        move.b  %d0,0(%a0,%d3.l)
        move.b  %d0,0(%a1,%d3.l)
        bra.s   3f
1:      move.l  %d2,%d0                 | the slot
        add.l   %d0,%d0
        add.l   %d2,%d0
        add.l   %d0,%d0                 | 6m
        add.l   %d0,%d3
        addq.l  #TSNS_SLOT2,%d3
        moveq   #1,%d0
        move.b  %d0,0(%a0,%d3.l)
        move.b  %d0,0(%a1,%d3.l)
        moveq   #0,%d0                  | the live bytes' Part: APPLIED_B / APPLIED_P
        move.b  (APPLIED_B).l,%d0
        move.l  #BANK_STRIDE,%d2
        mulu.l  %d2,%d0
        addi.l  #BANK0_DB,%d0
        moveq   #0,%d2
        move.b  (APPLIED_P).l,%d2
        move.l  #PART_STRIDE,%d3
        mulu.l  %d3,%d2
        add.l   %d2,%d0
        cmpa.l  %d0,%a0
        bne.s   3f                      | another Part's live bytes: the apply brings ours
        move.l  %d1,%d0
        lsl.l   #3,%d0
        move.l  %d1,%d2
        lsl.l   #6,%d2
        add.l   %d2,%d0                 | 72t
        lea     (LIVE_P2+TSNS_SLOT2).l,%a2
        moveq   #1,%d2
        move.b  %d2,0(%a2,%d0.l)        | the live EMUS byte: the next trig latches OT
3:      move.b  (PART_B).l,%d0          | the writer's own dirty flags (as the swap's)
        movea.l (DB_PTR).l,%a1
        movea.l %a1,%a0
        adda.l  #DIRTY_PARTS,%a0
        bset    %d0,(%a0)
        lea     (DIRTY_SRAM).l,%a0
        bset    %d0,(%a0)
        moveq   #1,%d3
        movea.l %a1,%a0
        adda.l  #DIRTY_DB2,%a0
        move.l  %d3,(%a0)
        lea     (DIRTY_GLOBAL).l,%a0
        move.l  %d3,(%a0)
        movem.l (%sp),%d0-%d3/%a0-%a2
        lea     28(%sp),%sp
        rts

| vg_fx_try (the FX choosers' YES, spec §6b item 2): d0 = 0 FX1 / 8 FX2, a0 -> its cursor
| row, a1 -> its rows. -> d0 = 1 (refused, the toast flagged) when the type under the
| cursor would put the panel track's core over the budget AND emulated engines are what
| tip it (the core's base + FX with the new type alone fits); else 0 (stock applies it).
| The same type as now: 0 (stock does nothing). Keeps all but d0.
vg_fx_try:
        lea     -28(%sp),%sp
        movem.l %d1-%d5/%a0-%a1,(%sp)
        move.l  (%a0),%d1
        lsl.l   #2,%d1
        movea.l 0(%a1,%d1.l),%a1
        move.l  (%a1),%d1               | the new type id (stock reads it so)
        move.l  %d0,%d4
        moveq   #0,%d2
        move.b  (UI_TRACK).l,%d2
        bsr     part_base
        adda.l  #OFF_FX1,%a0
        adda.l  %d4,%a0
        mvs.b   0(%a0,%d2.l),%d3        | the type now (stock compares so)
        moveq   #0,%d0
        cmp.l   %d3,%d1
        beq.s   .ft_out                 | the same: stock returns at once
        move.w  %sr,%d5
        move.w  #0x2700,%sr
        bsr     vg_scan
        move.l  %d2,%d4
        andi.l  #4,%d4                  | g
        move.l  %d4,%d0
        bsr     vg_fxsum
        lea     vg_fxp(%pc),%a1
        andi.l  #0x1f,%d3
        add.l   %d3,%d3
        mvz.w   0(%a1,%d3.l),%d3
        sub.l   %d3,%d0
        andi.l  #0x1f,%d1
        add.l   %d1,%d1
        mvz.w   0(%a1,%d1.l),%d1
        add.l   %d1,%d0                 | the core's FX with the new type
        lea     vg_base(%pc),%a1
        add.l   0(%a1,%d4.l),%d0
        lea     vg_budget(%pc),%a1
        move.l  0(%a1,%d4.l),%d3
        cmp.l   %d3,%d0
        bgt.s   2f                      | stock FX alone over: nothing is refused
        lea     vg_eng(%pc),%a0
        adda.l  %d4,%a0
        lea     vg_engp(%pc),%a1
        moveq   #3,%d2
1:      mvz.b   (%a0)+,%d1
        lsl.l   #2,%d1
        add.l   0(%a1,%d1.l),%d0
        subq.l  #1,%d2
        bpl.s   1b
        cmp.l   %d3,%d0
        ble.s   2f                      | fits
        moveq   #1,%d0
        move.b  %d0,(vg_toast).l
        bra.s   3f
2:      moveq   #0,%d0
3:      move.w  %d5,%sr
.ft_out:
        movem.l (%sp),%d1-%d5/%a0-%a1
        lea     28(%sp),%sp
        rts

| The FX choosers' YES handlers (0x400526e4 FX1, 0x40052474 FX2; key handlers, UI task):
| the type is applied only when it fits (vg_fx_try). Refused: nothing changes, the chooser
| stays open on it, the toast shows from the loop tail.
vh_fx1:
        moveq   #0,%d0
        lea     (FX1_CURSOR).l,%a0
        lea     (FX1_LIST).l,%a1
        bsr     vg_fx_try
        tst.l   %d0
        beq.s   vb_fx1
        rts
vb_fx1:
        lea     -68(%sp),%sp            | displaced
        movem.l %d2-%d7/%a2-%fp,(%sp)   | displaced
        jmp     (0x400526ec).l
vh_fx2:
        moveq   #8,%d0
        lea     (FX2_CURSOR).l,%a0
        lea     (FX2_LIST).l,%a1
        bsr     vg_fx_try
        tst.l   %d0
        beq.s   vb_fx2
        rts
vb_fx2:
        lea     -68(%sp),%sp            | displaced
        movem.l %d2-%d7/%a2-%fp,(%sp)   | displaced
        jmp     (0x4005247c).l

| vg_note (UI task: P2EDIT's TSTR step, the ATTR value-up's BEAT -> VARI): d1 = track; when
| its gate (rp_ui_gate) is off now, it is noted in vg_pend: the edit about to land may put
| it on VARI. vg_tick (this handler's loop tail) then checks the noted tracks. Keeps every
| register.
vg_note:
        move.l  %d0,-(%sp)
        move.l  %a0,-(%sp)
        bsr     rp_ui_gate
        tst.l   %d0
        bne.s   1f
        lea     vg_pend(%pc),%a0
        bset    %d1,(%a0)
1:      movea.l (%sp)+,%a0
        move.l  (%sp)+,%d0
        rts

| vg_entered: d0 = tracks vg_note noted (bit t) -> d0 = those of them on VARI now (the edit
| put them there). Keeps all but d0.
vg_entered:
        lea     -12(%sp),%sp
        movem.l %d1-%d3,(%sp)
        move.l  %d0,%d2
        moveq   #0,%d3
        moveq   #7,%d1
1:      btst    %d1,%d2
        beq.s   2f
        bsr     rp_ui_gate
        tst.l   %d0
        beq.s   2f
        bset    %d1,%d3
2:      subq.l  #1,%d1
        bpl.s   1b
        move.l  %d3,%d0
        movem.l (%sp),%d1-%d3
        lea     12(%sp),%sp
        rts

| vg_tick: `jmp` from 0x40062d1c, the UI task's message-loop tail (C, stock: every message
| the UI task takes -- keys, encoders, and DTIM1's 60 Hz tick, type 5 -- ends here, at one
| stack depth, no handler in flight; stock's own message cases 27/29/31 raise NOTIFY at
| this level and branch here). The safety net: when the inputs' signature differs from
| the last one checked, vg_fix. Before that, the tracks a TSTR / ATTR edit just put on VARI
| (vg_pend, vg_entered) get the first step: vg_fix on them alone, so on an over-budget core
| THEIR EMUS goes to OT (VEM7). Then the toast when flagged (a refusal in the handler that
| just ran, the entering track's step, or the net): MAX DSP: EMU LIMIT, 1.2 s. The ONLY
| NOTIFY of this unit.
| d0/d1/a0/a1 are free at this point (the loop's next act is a call); the rest is kept.
vg_tick:
        tst.l   (DB_PTR).l
        beq.s   2f                      | no bank blob yet (early boot)
        tst.b   (vem_depth).l
        bne.s   2f                      | a bulk write holds the Part (not the UI task's)
        move.b  (vg_pend).l,%d0         | a TSTR / ATTR edit just ran
        beq.s   1f
        clr.b   (vg_pend).l
        bsr     vg_entered              | the tracks it put on VARI
        tst.l   %d0
        beq.s   1f
        bsr     vg_fix                  | over budget: THEIR EMUS to OT first
1:      bsr     vg_sig
        cmp.l   (vg_last).l,%d0
        beq.s   2f                      | nothing the estimate reads has changed
        move.l  %d0,(vg_last).l
        moveq   #-1,%d0
        bsr     vg_fix
        tst.l   %d0
        beq.s   2f
        bsr     vg_sig                  | it stepped: the signature of the fixed settings
        move.l  %d0,(vg_last).l
2:      tst.b   (vg_toast).l
        beq.s   3f
        clr.b   (vg_toast).l
        pea     (TOAST_DUR).w
        pea     str_emu_limit(%pc)
        jsr     (NOTIFY).l              | NOTIFY(text, 0x48): self-timing, closes itself
        addq.l  #8,%sp
3:      tst.l   (UI_FLUSH).l            | displaced: the loop's own test, its beq follows
        jmp     (UI_TAIL_BACK).l

| vg_sig -> d0: a cheap signature of everything vg_scan and vg_est read: the current Part
| (its block), its 16 FX type bytes, whether the project tempo is in range, and per track
| its machine and, on ST / FL, that machine's TSTR; when TSTR is AUTO or VARI (the only
| values that can open the gate) also its sample slot, that sample's TSMODE and tempo, the
| rp_prev byte, the TSNS slot and the park. h = 33 h + x over them (any one input changing
| changes it but for a collision). rp_sync first: rp_prev must describe this Part. About
| 15 instructions per track off AUTO / VARI, 50 on them. Uses d0, d1, a0, a1 (the tail's).
vg_sig:
        lea     -20(%sp),%sp
        movem.l %d2-%d5/%a2,(%sp)
        bsr     rp_sync
        bsr     part_base
        move.l  %a0,%d0                 | h
        movea.l %a0,%a2
        adda.l  #OFF_FX1,%a0
        moveq   #3,%d2
1:      move.l  %d0,%d1
        lsl.l   #5,%d0
        add.l   %d1,%d0
        add.l   (%a0)+,%d0              | the FX types, four bytes at a time
        subq.l  #1,%d2
        bpl.s   1b
        move.l  %d0,%d2
        bsr     vg_tempo_ok
        add.l   %d0,%d2
        moveq   #0,%d1                  | t
.sg_t:  move.l  %d2,%d0
        lsl.l   #5,%d2
        add.l   %d0,%d2
        movea.l %a2,%a0
        adda.l  #OFF_MACH,%a0
        mvz.b   0(%a0,%d1.l),%d3        | m
        add.l   %d3,%d2
        moveq   #1,%d0
        cmp.l   %d0,%d3
        bhi     .sg_n                   | not ST / FL
        moveq   #30,%d4
        mulu.l  %d1,%d4
        move.l  %d3,%d0
        add.l   %d0,%d0
        add.l   %d3,%d0
        add.l   %d0,%d0                 | 6m
        add.l   %d0,%d4
        movea.l %a2,%a0
        adda.l  %d4,%a0
        adda.l  #OFF_P2,%a0             | -> machine m's page-2 row
        mvz.b   TSTR_SLOT2(%a0),%d0
        add.l   %d0,%d2
        moveq   #VARI,%d5
        cmp.l   %d5,%d0
        beq.s   1f
        moveq   #TSTR_AUTO,%d5
        cmp.l   %d5,%d0
        bne     .sg_n                   | the gate cannot open
1:      mvz.b   TSNS_SLOT2(%a0),%d0
        lsl.l   #8,%d0
        add.l   %d0,%d2                 | the TSNS / EMUS slot
        move.l  %d1,%d0
        lsl.l   #2,%d0
        add.l   %d1,%d0
        add.l   %d3,%d0
        movea.l %a2,%a0
        adda.l  #OFF_SLOT5,%a0
        mvz.b   0(%a0,%d0.l),%d0        | the sample slot
        move.l  %d0,%d5
        swap    %d0
        add.l   %d0,%d2
        move.l  #SET_STRIDE,%d0
        mulu.l  %d0,%d5
        lea     (SET_STATIC).l,%a1
        tst.l   %d3
        beq.s   2f
        lea     (SET_FLEX).l,%a1
2:      adda.l  %d5,%a1
        move.l  0x110(%a1),%d0          | the sample's TSMODE
        lsl.l   #4,%d0
        add.l   %d0,%d2
        add.l   0x114(%a1),%d2          | its tempo
        lea     rp_prev(%pc),%a1
        move.l  %d1,%d0
        add.l   %d0,%d0
        add.l   %d3,%d0
        mvz.b   0(%a1,%d0.l),%d0
        swap    %d0
        lsl.l   #8,%d0
        add.l   %d0,%d2                 | rp_prev
        movea.l %a2,%a0
        moveq   #30,%d0
        mulu.l  %d1,%d0
        adda.l  %d0,%a0
        adda.l  #OFF_P2,%a0
        moveq   #PARK2_ST,%d0
        tst.l   %d3
        beq.s   3f
        moveq   #PARK2_FL,%d0
3:      mvz.b   0(%a0,%d0.l),%d0
        lsl.l   #3,%d0
        add.l   %d0,%d2                 | the park
.sg_n:  addq.l  #1,%d1
        moveq   #8,%d0
        cmp.l   %d0,%d1
        blt     .sg_t
        move.l  %d2,%d0
        movem.l (%sp),%d2-%d5/%a2
        lea     20(%sp),%sp
        rts

| d1 = track, d2 = machine -> d0 = the Part's TSNS byte for that machine (signed).
db_tsns:
        lea     -12(%sp),%sp
        movem.l %d1/%d3/%a0,(%sp)
        bsr     part_base               | a0 = this part's block
        moveq   #30,%d0
        mulu.l  %d1,%d0
        move.l  %d2,%d3
        add.l   %d3,%d3
        add.l   %d2,%d3
        add.l   %d3,%d3                 | 6m
        add.l   %d3,%d0
        addi.l  #OFF_P2+TSNS_SLOT2,%d0
        mvs.b   0(%a0,%d0.l),%d0
        movem.l (%sp),%d1/%d3/%a0
        lea     12(%sp),%sp
        rts

| d1 = track, d2 = machine (0 ST / 1 FL) -> d0 = machine m's parked TSNS-pair byte (signed):
| off VARI, its EMUS (0 = never written: enters as OT). Keeps everything else.
db_park2:
        move.l  %a0,-(%sp)
        bsr     part_base
        moveq   #30,%d0
        mulu.l  %d1,%d0
        adda.l  %d0,%a0
        adda.l  #OFF_P2+PARK2_ST,%a0
        tst.l   %d2
        beq.s   1f
        subq.l  #PARK2_ST-PARK2_FL,%a0
1:      mvs.b   (%a0),%d0
        movea.l (%sp)+,%a0
        rts
        .endif                          | VEM_EMUS: EMUS and the DSP load guard

| ---------------------------------------------------------------------------
| Bulk writers (the user's O2): SRC page paste, track paste and the PART menu (paste,
| undo, clear) rewrite TSTR together with values already in the right domain, and pass
| no Part apply before the ISR can see them (the PART paste core applies only at its
| end, and only for the current part). As
| rp_reload: every rp_prev byte on HOLD for the call, forgotten after it, so the next
| poll ADOPTS. Each `jmp`s from its function's 8-byte entry; the caller's (up to six)
| arguments are passed on again; d0 comes back untouched.
vh_srcpaste:
        bsr     vh_enter
        move.l  24(%sp),-(%sp)
        move.l  24(%sp),-(%sp)
        move.l  24(%sp),-(%sp)
        move.l  24(%sp),-(%sp)
        move.l  24(%sp),-(%sp)
        move.l  24(%sp),-(%sp)
        jsr     vb_srcpaste
        lea     24(%sp),%sp
        bra     vh_leave
vb_srcpaste:
        lea     -52(%sp),%sp            | displaced
        movem.l %d2-%d7/%a2-%fp,(%sp)   | displaced
        jmp     (0x40027e54).l

vh_trkpaste:
        bsr     vh_enter
        move.l  24(%sp),-(%sp)
        move.l  24(%sp),-(%sp)
        move.l  24(%sp),-(%sp)
        move.l  24(%sp),-(%sp)
        move.l  24(%sp),-(%sp)
        move.l  24(%sp),-(%sp)
        jsr     vb_trkpaste
        lea     24(%sp),%sp
        bra     vh_leave
vb_trkpaste:
        lea     -68(%sp),%sp            | displaced
        movem.l %d2-%d7/%a2-%fp,(%sp)   | displaced
        jmp     (0x4002b65c).l

vh_partpaste:                           | PART menu PASTE and UNDO: 0x40029a4c(clip, part)
        bsr     vh_enter
        move.l  24(%sp),-(%sp)
        move.l  24(%sp),-(%sp)
        move.l  24(%sp),-(%sp)
        move.l  24(%sp),-(%sp)
        move.l  24(%sp),-(%sp)
        move.l  24(%sp),-(%sp)
        jsr     vb_partpaste
        lea     24(%sp),%sp
        bra     vh_leave
vb_partpaste:
        lea     -20(%sp),%sp            | displaced
        movem.l %d2-%d5/%a2,(%sp)       | displaced
        jmp     (0x40029a54).l

vh_partclear:                           | PART menu CLEAR: 0x4004a9d0(part)
        bsr     vh_enter
        move.l  24(%sp),-(%sp)
        move.l  24(%sp),-(%sp)
        move.l  24(%sp),-(%sp)
        move.l  24(%sp),-(%sp)
        move.l  24(%sp),-(%sp)
        move.l  24(%sp),-(%sp)
        jsr     vb_partclear
        lea     24(%sp),%sp
        bra     vh_leave
vb_partclear:
        lea     -16(%sp),%sp            | displaced
        movem.l %d2-%d3/%a2-%a3,(%sp)   | displaced
        jmp     (0x4004a9d8).l

| RELOAD PART (stock 0x4004aab4(part)) copies the saved Part in and refreshes, through
| neither Part apply: the same hold/forget (patch_repitch_reload.s's design, 16 bytes).
rp_reload:
        bsr     vh_enter
        move.l  4(%sp),-(%sp)           | the part argument, again
        jsr     vb_reload
        addq.l  #4,%sp
        bra     vh_leave
vb_reload:
        lea     -32(%sp),%sp            | displaced
        movem.l %d2-%d5/%a2-%a3,(%sp)   | displaced
        jmp     (0x4004aabc).l

| HOLD every rp_prev byte; nested holds count, so an inner forget (a Part apply inside a
| PART menu operation) keeps the HOLD until the outermost one leaves. d1/a0 only.
vh_enter:
        lea     vem_depth(%pc),%a0
        move.b  (%a0),%d1
        addq.l  #1,%d1
        move.b  %d1,(%a0)
        lea     rp_prev(%pc),%a0
        move.l  #0xfefefefe,%d1
        move.l  %d1,(%a0)+
        move.l  %d1,(%a0)+
        move.l  %d1,(%a0)+
        move.l  %d1,(%a0)
        rts
vh_leave:
        lea     vem_depth(%pc),%a0
        move.b  (%a0),%d1
        subq.l  #1,%d1
        bpl.s   1f
        moveq   #0,%d1
1:      move.b  %d1,(%a0)
        bra     rp_forget               | rts to our caller, d0 kept

| ============================================================================
| PART 2 -- RETAINED (REPITCH_REWRITE_RETAINED.s), extended for VARISPEED_EMUS:
|   * per machine: rp_prev[2t + m], m = 0 ST / 1 FL, each with its own parks, its own
|     gate (rp_gate_m: VARI = raw 4 only, AUTO + TSMODE 4) and its own captions, so a
|     machine change never swaps anything (spec item 11);
|   * the second pair TSNS <-> EMUS swaps with PTCH <-> QUAN, in the same transition;
|   * the widgets and step handlers do nothing off ST/FL (item 11: no PICKUP poll);
|   * UI-side swaps run with interrupts masked against the frame hook's;
|   * RELOAD PART and the bulk writers HOLD (counted), the Part applies forget.
| ============================================================================

| d0 = ui value (the PTCH slot's 4..124 domain) -> d0 = QUAN index 0..8.
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

| -> a0 = this part's block in the working DB. Keeps everything else.
part_base:
        move.l  %d0,-(%sp)
        move.l  %d1,-(%sp)
        movea.l (DB_PTR).l,%a0
        moveq   #0,%d0
        move.b  (PART_B).l,%d0
        move.l  #PART_STRIDE,%d1
        mulu.l  %d1,%d0
        adda.l  %d0,%a0
        move.l  (%sp)+,%d1
        move.l  (%sp)+,%d0
        rts

| d1 = track -> d2 = its machine in the Part DB (boot-authoritative; the engine
| mirrors are stale until the transport first runs). Keeps everything else.
db_mach:
        move.l  %a0,-(%sp)
        bsr     part_base
        moveq   #0,%d2
        adda.l  %d1,%a0
        adda.l  #OFF_MACH,%a0
        move.b  (%a0),%d2
        movea.l (%sp)+,%a0
        rts

| d1 = track, d2 = machine (0 ST / 1 FL) -> d0 = 1 when that machine's own Part bytes
| put the track on VARI: TSTR 4, or AUTO with the bound sample's TSMODE 4, and that
| sample's BPM x 24 in 720..7200. Keeps everything but d0.
rp_gate_m:
        lea     -16(%sp),%sp
        movem.l %d1/%d3/%a0-%a1,(%sp)
        moveq   #7,%d0
        cmp.l   %d0,%d1
        bhi     .gm_no
        moveq   #1,%d0
        cmp.l   %d0,%d2
        bhi     .gm_no
        bsr     part_base
        move.l  %d1,%d3
        lsl.l   #2,%d3
        add.l   %d1,%d3                 | 5t
        add.l   %d2,%d3
        addi.l  #OFF_SLOT5,%d3
        moveq   #0,%d0
        move.b  (%a0,%d3.l),%d0         | the sample slot byte, raw (0-based)
        move.l  #SET_STRIDE,%d3
        mulu.l  %d0,%d3
        lea     (SET_STATIC).l,%a1
        tst.l   %d2
        beq.s   1f
        lea     (SET_FLEX).l,%a1
1:      adda.l  %d3,%a1
        moveq   #30,%d3
        mulu.l  %d1,%d3
        move.l  %d2,%d0
        add.l   %d0,%d0
        add.l   %d2,%d0
        add.l   %d0,%d0                 | 6m
        add.l   %d0,%d3
        addi.l  #OFF_P2+TSTR_SLOT2,%d3
        moveq   #0,%d0
        move.b  (%a0,%d3.l),%d0         | SETUP TSTR, the Part's own copy
        moveq   #VARI,%d3
        cmp.l   %d3,%d0
        beq.s   .gm_tempo
        moveq   #TSTR_AUTO,%d3
        cmp.l   %d3,%d0
        bne.s   .gm_no
        moveq   #VARI,%d3
        cmp.l   0x110(%a1),%d3          | the sample's own TSMODE
        bne.s   .gm_no
.gm_tempo:
        move.l  0x114(%a1),%d3          | the sample's BPM x 24
        cmpi.l  #BPM24_MIN,%d3
        blt.s   .gm_no
        cmpi.l  #BPM24_MAX,%d3
        bgt.s   .gm_no
        moveq   #1,%d0
        bra.s   .gm_out
.gm_no:
        moveq   #0,%d0
.gm_out:
        movem.l (%sp),%d1/%d3/%a0-%a1
        lea     16(%sp),%sp
        rts

| d1 = track -> d0 = rp_gate_m for its current DB machine (0 off ST/FL). Keeps all else.
rp_ui_gate:
        move.l  %d2,-(%sp)
        bsr     db_mach
        bsr     rp_gate_m               | 0 for a machine above 1
        move.l  (%sp)+,%d2
        rts

| d1 = track. The per-frame / per-draw poll of the track's CURRENT DB machine m:
| rp_swap_m(t, m) with the live bytes. Also adopts the other machine's byte while it
| is forgotten (no data moves on an adopt), so a forgotten pair does not keep this
| track off the hook's cheap path. Returns d0 = m<<8 | domain<<1 | swapped (domain:
| m's slots hold QUAN / EMUS); for a machine above FL, d0 = m<<8 and nothing is
| touched. Keeps everything else. Called from the frame hook (interrupt level) and,
| through rp_swap_ui, from the UI task.
rp_swap:
        lea     -12(%sp),%sp
        movem.l %d2-%d3/%a0,(%sp)
        bsr     db_mach                 | d2 = m
        moveq   #1,%d0
        cmp.l   %d0,%d2
        bls.s   1f
        move.l  %d2,%d0                 | THRU / NEIGHBOR / PICKUP: inert
        lsl.l   #8,%d0
        bra.s   .sp_out
1:      moveq   #1,%d3                  | live bytes: m is the current machine
        bsr     rp_swap_m
        move.l  %d0,%d3                 | keep the result
        moveq   #1,%d0
        eor.l   %d0,%d2                 | the other machine
        lea     rp_prev(%pc),%a0
        move.l  %d1,%d0
        add.l   %d0,%d0
        add.l   %d2,%d0
        adda.l  %d0,%a0
        moveq   #-1,%d0
        cmp.b   (%a0),%d0               | forgotten?
        bne.s   2f
        bsr     rp_gate_m
        move.b  %d0,(%a0)               | adopt
2:      moveq   #1,%d0
        eor.l   %d0,%d2                 | m again
        move.l  %d2,%d0
        lsl.l   #8,%d0
        or.l    %d3,%d0
.sp_out:
        movem.l (%sp),%d2-%d3/%a0
        lea     12(%sp),%sp
        rts

| rp_sync: rp_prev describes one Part (rp_pb / rp_pp: its bank blob and part). When the
| current Part is another, forget it, so the next poll ADOPTS the new Part as it is. A
| sequencer Part switch moves PART_B (UI message 20) a step BEFORE the frame applies the
| new Part, and a bank switch moves the bank pointer (message 21): until VEM5 the frame
| hook then polled the new Part's bytes against the old Part's rp_prev, read a gate
| difference as a TSTR change, and SWAPPED the new Part's PTCH/QUAN and TSNS/EMUS (C,
| ot_emu, IMPL §12). Called where it matters: by rp_swap_m on a gate difference (before
| it would swap; nothing per frame otherwise) and by the guard before it reads rp_prev
| (vg_scan, vg_sig). Keeps every register.
rp_sync:
        lea     -12(%sp),%sp
        movem.l %d1-%d2/%a0,(%sp)
        move.l  (DB_PTR).l,%d1
        cmp.l   (rp_pb).l,%d1
        bne.s   1f
        move.b  (PART_B).l,%d1
        cmp.b   (rp_pp).l,%d1
        beq.s   2f
1:      move.w  %sr,%d2                 | another Part: switch over in one piece (the UI
        move.w  #0x2700,%sr             | task's call and the frame hook's never interleave)
        move.l  (DB_PTR).l,%d1
        move.l  %d1,(rp_pb).l
        move.b  (PART_B).l,%d1
        move.b  %d1,(rp_pp).l
        bsr     rp_forget
        move.w  %d2,%sr
2:      movem.l (%sp),%d1-%d2/%a0
        lea     12(%sp),%sp
        rts

| rp_swap from the UI task: with interrupts masked, so the frame hook cannot swap the
| same pair in the middle of this one. Same contract as rp_swap.
rp_swap_ui:
        move.l  %d2,-(%sp)
        move.w  %sr,%d2
        move.w  #0x2700,%sr
        bsr     rp_swap
        move.w  %d2,%sr
        move.l  (%sp)+,%d2
        rts

| d1 = track, d2 = machine (0/1), d3 = 1: m is the track's current machine (write the
| live bytes + base word too). On a gate transition, swap BOTH pairs of machine m:
|   PTCH (p1 slot 0) <-> its park (ST: NEIGHBOR p1 s0, FL: NEIGHBOR p1 s5), an entering
|     value below 4 (a fresh park) becoming 64 = 1/1, either way;
|   TSNS (p2 slot 5) <-> its park (ST: NEIGHBOR p2 s5, FL: NEIGHBOR p2 s3), a fresh
|     park (0) entering EMUS as 1 = OT; TSNS comes back verbatim.
|     (VARISPEED_EMUS only. VARISPEED swaps PTCH <-> QUAN alone: TSNS stays TSNS.)
| in the working DB and the SRAM part copy, with the writer's own dirty flags. The
| NEIGHBOR bytes are '---' parameters stock saves with the Part and never applies.
| First sight (0xff or any non 0/1/HOLD value) adopts without swapping; HOLD (a RELOAD
| or bulk write in progress) touches nothing. Returns d0 = domain<<1 | swapped.
| Keeps everything else.
rp_swap_m:
        lea     -36(%sp),%sp
        movem.l %d1-%d7/%a0-%a1,(%sp)
        bsr     rp_gate_m               | d0 = g
        move.l  %d0,%d4
        lea     rp_prev(%pc),%a0
        move.l  %d1,%d0
        add.l   %d0,%d0
        add.l   %d2,%d0
        adda.l  %d0,%a0                 | a0 -> rp_prev[2t + m]
        mvs.b   (%a0),%d0               | signed: 0/1, -1 forgotten, -2 HOLD
        cmp.l   %d0,%d4
        beq     .sm_same
        bsr     rp_sync                 | a gate difference: but is rp_prev still about the
        mvs.b   (%a0),%d0               | current Part? (forgotten now if it was not: adopt)
        cmp.l   %d0,%d4
        beq     .sm_same
        moveq   #-2,%d5
        cmp.l   %d5,%d0
        beq     .sm_same                | HOLD: the Part is being written
        move.b  %d4,(%a0)
        moveq   #1,%d5
        cmp.l   %d5,%d0
        bhi     .sm_adopt               | not 0/1: first sight
| a transition: move the data
        bsr     part_base               | a0 = the part's block
        moveq   #0,%d0
        move.b  (PART_B).l,%d0
        move.l  #PART_STRIDE,%d5
        mulu.l  %d0,%d5
        lea     (SHADOW_ADJ).l,%a1
        adda.l  %d5,%a1                 | a1 = the SRAM copy's block
        moveq   #30,%d5
        mulu.l  %d1,%d5                 | 30t
        move.l  %d2,%d0
        add.l   %d0,%d0
        add.l   %d2,%d0
        add.l   %d0,%d0                 | 6m
        move.l  %d5,%d6
        add.l   %d0,%d6
        addi.l  #OFF_P1,%d6             | d6 = PTCH slot
        move.l  %d5,%d7
        addi.l  #OFF_P1+PARK1_ST,%d7    | d7 = its park
        tst.l   %d2
        beq.s   1f
        addq.l  #PARK1_FL-PARK1_ST,%d7
1:      moveq   #0,%d0
        move.b  (%a0,%d6.l),%d0         | leaving the slot
        moveq   #0,%d3
        move.b  (%a0,%d7.l),%d3         | entering it
        moveq   #4,%d5
        cmp.l   %d5,%d3
        bge.s   2f
        moveq   #64,%d3                 | fresh park: 1/1
2:      move.b  %d3,(%a0,%d6.l)
        move.b  %d0,(%a0,%d7.l)
        move.b  %d3,(%a1,%d6.l)
        move.b  %d0,(%a1,%d7.l)
        .if VEM_EMUS
        move.l  %d3,-(%sp)              | the new PTCH-slot value, for the live bytes
| TSNS <-> EMUS
        moveq   #30,%d5
        mulu.l  %d1,%d5
        move.l  %d2,%d0
        add.l   %d0,%d0
        add.l   %d2,%d0
        add.l   %d0,%d0
        move.l  %d5,%d6
        add.l   %d0,%d6
        addi.l  #OFF_P2+TSNS_SLOT2,%d6  | d6 = TSNS slot
        move.l  %d5,%d7
        addi.l  #OFF_P2+PARK2_ST,%d7    | d7 = its park
        tst.l   %d2
        beq.s   1f
        subq.l  #PARK2_ST-PARK2_FL,%d7
1:      moveq   #0,%d0
        move.b  (%a0,%d6.l),%d0         | leaving
        moveq   #0,%d3
        move.b  (%a0,%d7.l),%d3         | entering
        tst.l   %d4
        beq.s   2f                      | leaving VARI: TSNS verbatim
        tst.l   %d3
        bne.s   2f
        moveq   #1,%d3                  | entering EMUS from a fresh park: OT
2:      move.b  %d3,(%a0,%d6.l)
        move.b  %d0,(%a0,%d7.l)
        move.b  %d3,(%a1,%d6.l)
        move.b  %d0,(%a1,%d7.l)
        move.l  (%sp)+,%d5              | the new PTCH-slot value
        .else
        move.l  %d3,%d5                 | the new PTCH-slot value
        .endif
        tst.l   4*2(%sp)                | the caller's d3: live?
        beq.s   3f
        move.l  %d1,%d0
        lsl.l   #3,%d0
        move.l  %d1,%d6
        lsl.l   #6,%d6
        add.l   %d6,%d0                 | 72t
        lea     (LIVE_P1).l,%a1
        move.b  %d5,(%a1,%d0.l)         | live PTCH-slot byte
        .if VEM_EMUS
        lea     (LIVE_P2+TSNS_SLOT2).l,%a1
        move.b  %d3,(%a1,%d0.l)         | live TSNS byte (page 2 has no base word)
        .endif
        | The BASE word, not the lane: the lane is rebuilt from it every frame.
        lea     (BASE_W).l,%a1
        move.l  %d5,%d0
        lsl.l   #8,%d0
        move.w  %d0,(%a1,%d6.l)         | 64t: base word = ui<<8
3:
        | The writer's own dirty flags: BYTE bitmasks (bset), then the two longs.
        move.b  (PART_B).l,%d0
        movea.l (DB_PTR).l,%a1
        movea.l %a1,%a0
        adda.l  #DIRTY_PARTS,%a0
        bset    %d0,(%a0)
        lea     (DIRTY_SRAM).l,%a0
        bset    %d0,(%a0)
        moveq   #1,%d5
        movea.l %a1,%a0
        adda.l  #DIRTY_DB2,%a0
        move.l  %d5,(%a0)
        lea     (DIRTY_GLOBAL).l,%a0
        move.l  %d5,(%a0)
        moveq   #1,%d5                  | swapped
        bra.s   .sm_seen
.sm_adopt:
        moveq   #0,%d5
.sm_seen:
        | a change on the panel's track: its captions now (the page's text pass may
        | run before the widget's next poll)
        moveq   #0,%d0
        move.b  (UI_TRACK).l,%d0
        cmp.l   %d0,%d1
        bne.s   1f
        move.l  %d4,%d0
        bsr     caption_m
1:      move.l  %d4,%d0
        add.l   %d0,%d0
        or.l    %d5,%d0
        bra.s   .sm_out
.sm_same:
        move.l  %d4,%d0
        add.l   %d0,%d0
.sm_out:
        movem.l (%sp),%d1-%d7/%a0-%a1
        lea     36(%sp),%sp
        rts

| d0 = gate, d2 = machine (0/1): machine m's two captions, PTCH/QUAN and TSNS/EMUS
| (VARISPEED: PTCH/QUAN only; TSNS keeps stock's caption).
| The descriptor table is image SDRAM; bytes 4..5 of each name field stay 0. Keeps all.
caption_m:
        lea     -12(%sp),%sp
        movem.l %d0-%d1/%a0,(%sp)
        lea     cap_tab(%pc),%a0
        tst.l   %d0
        beq.s   1f
        .if VEM_EMUS
        addq.l  #8,%a0
1:      move.l  (%a0)+,%d0              | PTCH / QUAN
        move.l  (%a0),%d1               | TSNS / EMUS
        tst.l   %d2
        bne.s   2f
        move.l  %d0,(NAME0_ST).l
        move.l  %d1,(NAME11_ST).l
        bra.s   3f
2:      move.l  %d0,(NAME0_FL).l
        move.l  %d1,(NAME11_FL).l
        .else
        addq.l  #4,%a0
1:      move.l  (%a0),%d0               | PTCH / QUAN
        tst.l   %d2
        bne.s   2f
        move.l  %d0,(NAME0_ST).l
        bra.s   3f
2:      move.l  %d0,(NAME0_FL).l
        .endif
3:      movem.l (%sp),%d0-%d1/%a0
        lea     12(%sp),%sp
        rts

| Poll every track, both machines (UI task: the ATTR editor). A gate change of a
| machine that is not current (an ATTR edit of the sample the other machine plays)
| swaps that machine's Part bytes now, live bytes only for the current one. Keeps all.
rp_poll_all:
        lea     -20(%sp),%sp
        movem.l %d0-%d4,(%sp)
        move.w  %sr,%d4
        move.w  #0x2700,%sr
        moveq   #0,%d1
1:      bsr     db_mach
        move.l  %d2,%d0                 | the current machine
        moveq   #0,%d2
2:      moveq   #0,%d3
        cmp.l   %d0,%d2
        bne.s   3f
        moveq   #1,%d3                  | live bytes for the current machine
3:      move.l  %d0,-(%sp)
        bsr     rp_swap_m
        move.l  (%sp)+,%d0
        addq.l  #1,%d2
        moveq   #1,%d3
        cmp.l   %d3,%d2
        bls.s   2b
        addq.l  #1,%d1
        moveq   #7,%d3
        cmp.l   %d3,%d1
        bls.s   1b
        move.w  %d4,%sr
        movem.l (%sp),%d0-%d4
        lea     20(%sp),%sp
        rts

| Poll and refresh the PLAYBACK page's slot-0 dial: from the ATTR TIMESTRETCH editors,
| whose edits are otherwise invisible to that page until something forces a repaint
| (retained; unconditional on purpose: the frame hook may consume the transition
| first). Keeps every register.
rp_refresh:
        move.l  %d0,-(%sp)
        bsr     rp_poll_all
        moveq   #0x14,%d0
        move.l  %d0,(REDRAW_L).l
        move.l  (%sp)+,%d0
        rts

| P+0x12a slot 0, STATIC / FLEX: the per-slot ENCODER STEP handler the UI editor calls
| as handler(slot, delta, current) -> new value (then clamped and stored by stock).
| Off a VARI track: stock's. On one: one ratio per QS_FINE single detents (retained).
        .equ    QS_FINE, 3
quant_step:
        move.l  %d1,-(%sp)
        moveq   #0,%d1
        move.b  (UI_TRACK).l,%d1
        bsr     rp_ui_gate
        tst.l   %d0
        bne.s   .qs_quan
        move.l  (%sp)+,%d1
        jmp     (STEP_PTCH).l
.qs_quan:
        move.l  %d2,-(%sp)
        move.l  20(%sp),%d0             | current (arg 3, two pushes deep)
        bsr     rk_bucket               | -> zone 0..8
        move.l  16(%sp),%d1             | delta (arg 2)
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

| The four SETUP-page dial resolvers (MIDI NOTE / LFO / FX2 / FX1): re-create stock's
| resolve and use quant_widget when the record's formatter is playback slot 0's
| (retained, unchanged).
qdial1:                                 | 0x40036698, record in a4
        movea.l 48(%a4),%a0
        tst.l   %a0
        bne.s   1f
        lea     (KNOB).l,%a0
1:      move.l  (%a4),%d0
        cmpi.l  #PTCH_FMT,%d0
        bne.s   2f
        lea     quant_widget,%a0
2:      jmp     (0x400366a6).l
qdial2:                                 | 0x4003690c, record in a3
        movea.l 48(%a3),%a0
        tst.l   %a0
        bne.s   1f
        lea     (KNOB).l,%a0
1:      move.l  (%a3),%d0
        cmpi.l  #PTCH_FMT,%d0
        bne.s   2f
        lea     quant_widget,%a0
2:      jmp     (0x4003691a).l
qdial3:                                 | 0x4003786a, record in a3
        movea.l 48(%a3),%a0
        tst.l   %a0
        bne.s   1f
        lea     (KNOB).l,%a0
1:      move.l  (%a3),%d0
        cmpi.l  #PTCH_FMT,%d0
        bne.s   2f
        lea     quant_widget,%a0
2:      jmp     (0x40037878).l
qdial4:                                 | 0x40037c06, record in a3
        movea.l 48(%a3),%a0
        tst.l   %a0
        bne.s   1f
        lea     (KNOB).l,%a0
1:      move.l  (%a3),%d0
        cmpi.l  #PTCH_FMT,%d0
        bne.s   2f
        lea     quant_widget,%a0
2:      jmp     (0x40037c14).l

| PTCH's widget, STATIC / FLEX slot-0 widget column. Args (x, y, index, value, flags,
| fmt, canvas). Off ST/FL (item 11): the stock dial and no poll. Off VARI: the stock
| dial, rebuilt with the fresh live byte when this very draw swapped. On VARI: the
| dial snapped to the 9 QUAN stops (4 + 15*idx) read out by quant_fmt; the stored
| value stays the stock editor's, so locks are untouched.
quant_widget:
        move.l  %d2,-(%sp)              | (args now 8..32)
        moveq   #0,%d1
        move.b  (UI_TRACK).l,%d1
        bsr     db_mach
        moveq   #1,%d0
        cmp.l   %d0,%d2
        bls.s   1f
        move.l  (%sp)+,%d2
        jmp     (KNOB).l                | not ST/FL: stock, no poll
1:      bsr     rp_swap_ui
        andi.l  #1,%d0
        movea.l %d0,%a1                 | the swap flag
        moveq   #72,%d0
        mulu.l  %d1,%d0
        lea     (LIVE_P1).l,%a0
        adda.l  %d0,%a0                 | -> this track's live PTCH byte
        bsr     rp_gate_m
        bsr     caption_m
        tst.l   %d0
        bne.s   .qw_quant
        move.l  %a1,%d0
        bne.s   .qw_fresh
        move.l  (%sp)+,%d2
        jmp     (KNOB).l                | no swap: stock, untouched
.qw_fresh:
        moveq   #0,%d0
        move.b  (%a0),%d0               | the just-restored pitch
        movea.l 28(%sp),%a1             | with its own formatter
        bra.s   .qw_frame
.qw_quant:
        move.l  20(%sp),%d0             | the caller's value
        move.l  %a1,%d1
        beq.s   1f
        moveq   #0,%d0
        move.b  (%a0),%d0               | swapped: the fresh QUAN value
1:      lea     quant_fmt(%pc),%a1
        tst.l   %d0
        bmi.s   .qw_frame               | an empty cell keeps the bare frame
        bsr     rk_bucket
        moveq   #15,%d1
        mulu.l  %d0,%d1
        moveq   #4,%d0
        add.l   %d1,%d0
.qw_frame:
        move.l  32(%sp),-(%sp)          | canvas
        move.l  %a1,-(%sp)              | the path's formatter
        move.l  32(%sp),-(%sp)          | flags
        move.l  %d0,-(%sp)              | value
        move.l  32(%sp),-(%sp)          | index
        move.l  32(%sp),-(%sp)          | y
        move.l  32(%sp),-(%sp)          | x
        jsr     (KNOB).l
        lea     28(%sp),%sp
        move.l  (%sp)+,%d2
        rts

| fmt(buf, value): a ui value's ratio bucket.
quant_fmt:
        move.l  8(%sp),%d0
        bmi.s   .qf_unk
        bsr     rk_bucket
        lsl.l   #2,%d0
        lea     q_labels(%pc),%a0
        adda.l  %d0,%a0
        move.l  %a0,8(%sp)
        jmp     (SPRINTF).l
.qf_unk:
        lea     (STR_UNK).l,%a0
        move.l  %a0,8(%sp)
        jmp     (SPRINTF).l

| Any Part apply (heavy 0x40009094, light 0x40009e00) makes rp_prev meaningless: forget,
| so the next poll ADOPTS the applied state. Inside a held bulk write the bytes stay
| on HOLD until the outermost leaves. d1 and a0 only (rp_reload's verdict in d0 passes).
rp_forget:
        moveq   #-1,%d1
        tst.b   (vem_depth).l
        beq.s   1f
        move.l  #0xfefefefe,%d1
1:      lea     rp_prev(%pc),%a0
        move.l  %d1,(%a0)+
        move.l  %d1,(%a0)+
        move.l  %d1,(%a0)+
        move.l  %d1,(%a0)
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

| ---------------------------------------------------------------------------- data
        .balign 4
tstr_tab:
        .long   STR_OFF, STR_AUTO, STR_NORM, STR_BEAT, str_vari
        .if VEM_EMUS
emus_tab:
        .long   str_ot, str_s950, str_sp12
cap_tab:
        .ascii  "PTCHTSNS"              | off VARI
        .ascii  "QUANEMUS"              | on VARI
        .else
cap_tab:
        .ascii  "PTCH"                  | off VARI
        .ascii  "QUAN"                  | on VARI
        .endif
q_labels:
        .ascii  "1/2\0"
        .ascii  "2/3\0"
        .ascii  "3/4\0"
        .ascii  "4/5\0"
        .ascii  "1/1\0"
        .ascii  "5/4\0"
        .ascii  "4/3\0"
        .ascii  "3/2\0"
        .ascii  "2/1\0"
str_vari:
        .ascii  "VARI\0"
        .if VEM_EMUS
str_s950:
        .ascii  "S950\0"
str_ot:
        .ascii  "OT\0"
str_sp12:
        .ascii  "SP12\0"
str_emu_limit:                          | the guard's toast (spec §6b item 4); its width in
        .ascii  "MAX DSP: EMU LIMIT\0"  | the stock toast font is measured by the tests (IMPL §12)
        .endif
rk_ratios:                              | p, q per QUAN index
        .byte   1,2, 2,3, 3,4, 4,5, 1,1, 5,4, 4,3, 3,2, 2,1
        .if VEM_EMUS
emus_stops:                             | the stored value per stop: OT, S950, SP12
        .byte   1, 64, 127
emus_mode:                              | the DSP engine per stop (bits 2-3 of the increment)
        .byte   0, 1, 2
        .endif
        .balign 4
rp_prev:                                | [2t + m]: 0/1 gate, 0xff forgotten, 0xfe HOLD
        .byte   0xff,0xff,0xff,0xff,0xff,0xff,0xff,0xff
        .byte   0xff,0xff,0xff,0xff,0xff,0xff,0xff,0xff
vem_depth:                              | nested holds
        .byte   0
rk_acc:                                 | QUAN fine-detent tally, signed
        .byte   0
        .if VEM_EMUS
em_tally:                               | EMUS detent count, signed (sign = direction)
        .byte   0
        .balign 4
em_ctx:                                 | the count's owner: track | m << 8 | part << 16
        .long   0
| ---- the DSP load guard: its tables (VG_* constants) and state
vg_fxp:                                 | price per stock FX type id 0..31 (halfwords)
        .word   VG_FX_NONE, 0, 0, 0, VG_FX_FILTER, VG_FX_SPATIALIZER, 0, 0
        .word   VG_FX_DELAY, 0, 0, 0, VG_FX_EQ, VG_FX_DJEQ, 0, 0
        .word   VG_FX_PHASER, VG_FX_FLANGER, VG_FX_CHORUS, VG_FX_COMB
        .word   VG_FX_PLATE, VG_FX_SPRING_HERE, VG_FX_DARK, 0
        .word   VG_FX_COMPRESSOR, 0, 0, 0, VG_FX_LOFI, 0, 0, 0
vg_engp:                                | engine price by engine 0 OT / 1 S950 / 2 SP12 (x 4)
        .long   0, VG_S950, VG_SP12, VG_S950    | (3 is never stored; the kernel would run RPS9)
vg_base:                                | by g = 0 (T1-T4, core 1) / 4 (T5-T8, core 0)
        .long   VG_BASE_C1+VG_SC, VG_BASE_C0+VG_SC
vg_budget:
        .long   VG_BUDGET_C1, VG_BUDGET_C0
vg_last:                                | the signature the safety net last checked
        .long   0
        .else
        .balign 4
        .endif
rp_pb:                                  | the bank blob and part rp_prev describes (rp_sync)
        .long   0
rp_pp:
        .byte   0xff
        .balign 2
        .if VEM_EMUS
vg_eng:                                 | vg_scan: the engine each track's settings run
        .byte   0, 0, 0, 0, 0, 0, 0, 0
vg_toast:                               | MAX DSP: EMU LIMIT is due (vg_tick raises it)
        .byte   0
vg_pend:                                | tracks noted off VARI before a TSTR / ATTR edit (bit t)
        .byte   0
        .endif
        .balign 4
vem_end:
