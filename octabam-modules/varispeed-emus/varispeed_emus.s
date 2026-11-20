| SPDX-License-Identifier: MIT
| SPDX-FileCopyrightText: 2026 Zac Kyoti
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
| becomes EMUS (OT / S950 / SP12, left to right), the engine the DSP kernel (vem_dsp.asm)
| renders the track with, latched at each trig; four detents in one direction step it once.
| A DSP load guard (spec §6b) keeps each DSP core's estimated load, a property of the
| settings, under its budget: a change that would overload it is refused (EMUS, the FX
| type), TSTR / ATTR onto VARI steps THAT track's EMUS to OT (VEM7), and a change that
| cannot be refused (Part change, reload, load, machine, sample...) steps just enough
| tracks to OT;
| each raises the toast MAX DSP: EMU LIMIT from the UI task's message loop. Spec:
| reference/handoffs/VARISPEED_SPEC.md; facts: VARISPEED_SCOPE.md +
| VARISPEED_SCOPE_EMUS.md (clean-room); this build: VARISPEED_IMPL.md §12.
| VEM11 (2026-11-18, the author's "full fix, plus pitch-jump fix"; NOTES 2026-11-18): a Part
| switch is priced as the transition it plays (vgx_tick), the frame hook clamps a carried
| engine on the real switch frame when the transition needs it (vem_frame, vgx_cl), caps the
| incoming Part's engines there (vgx_ovr; committed to the Part at the switch), and keeps a
| carried VARI voice on its engine and speed until its own next trig (vf_win, vf_eng).
|
| Two parts:
|   PART 1, NEW CORE (written for VARISPEED_EMUS): the frame hook vem_frame, the TSTR
|     formatter, the audio-editor ATTR hooks, the EMUS widget / formatter / step and its
|     page-open reset, the DSP load guard, the hold wrappers of the bulk writers.
|   PART 2, RETAINED (VARISPEED_RETAINED.s, extended): QUAN, the domain swap -- now
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
        .global vh_enter                | for VARISPEED's STORE client (octabam: varispeed_store.s)
        .global vh_leave
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
        .global rp_migrate
        .global rp_bpt
        .ifdef  VEM_BP
        .global vh_bptake               | KYOTI V1.8BC: BLACKPYRAMIDS_303's ot_assign calls them
        .global vh_bpback
        .endif
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
        .global vg_new
        .global vg_tkey
        .global vg_gon
        .global vg_bulk
        .global vg_key
        .global vg_pick
        .global vg_pick_src
        .global vg_pick_ae
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
        .equ    UI_TRACK_M, 0x100b14cc  | byte: the track the machine / slot choosers act on
        .equ    SRC_SLOT_SEL, 0x4003d014 | the SRC menu's slot column: selects its slot (C)
        .equ    AE_PICK_M, 0x460e738e   | long: the audio editor chooser's machine (C)
        .equ    DB_PTR, 0x46c82456      | -> the working bank blob
        .equ    PART_STRIDE, 0x18b2
        .equ    OFF_MACH, 0x8eda2       | + t: machine type (0 ST, 1 FL, 2 THRU, 3 NEIGHBOR, 4 PU)
        .equ    OFF_P1, 0x8edaa         | + 30t + 6m + slot: page-1 bytes
        .equ    OFF_P2, 0x8ef5a         | + 30t + 6m + slot2: page-2 bytes
        .equ    OFF_SLOT5, 0x8f04a      | + 5t + m: 0-based sample slot byte
        .equ    SHADOW_ADJ, 0x100a4ece-0x8ed80 | SRAM part copy, same DB-relative offsets
        .equ    LIVE_P1, 0x80000810     | live page-1 byte, + 72t + flat
        .equ    LIVE_P2, 0x80000830     | live page-2 byte, + 72t + slot2
        .equ    LIVE_SLOT, 0x8000082f   | live sample-slot byte, + 72t (C: 0x40079604 writes it)
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
        .equ    SEQ_RUN, 0x800065b8     | long: 1 while the transport runs (C: 0x400a05aa, the cue)
        .equ    PLAY_B, 0x800065bd      | the playing pattern's bank, pattern (the commit at the
        .equ    PLAY_P, 0x800065be      |   boundary copies PEND here, C: 0x400a44d0)
        .equ    PEND_B, 0x800065bf      | the cued pattern's bank, pattern (C: 0x400a06d6; -1 none)
        .equ    PEND_P, 0x800065c0
        .equ    PAT_STRIDE, 0x8ed8      | pattern p of a bank blob at + p * PAT_STRIDE
        .equ    PAT_PART, 0x8e57        |   + PAT_PART: its Part (C: 0x400a4568, the hand-off)
        .equ    RENDER, 0x80004898      | per-track render state, + RENDER_STRIDE * t; +36 = the
        .equ    RENDER_STRIDE, 40       |   increment (C: the voice loop 0x4000d386 / 0x4000d536)
        .equ    LIVE_FX1, 0x80000ec4    | the live FX1 type ids, + t (FX2 at + 8; IMPL §10.1)
        .equ    LIVE_PB, 0x8000182a     | + t: the bank its live bytes came from, + 8 + t: the part --
                                        |   stock's own pair per track, written at its trigs
                                        |   (C: 0x4000bf62 / 0x4000bf6a) and by the heavy apply
                                        |   (0x40009396): a track carried across a sequencer switch
                                        |   keeps the old Part's pair until its own first trig
        .equ    TRAC_STRIDE, 0x91a      | a pattern's track t at + t * TRAC_STRIDE: its step masks
        .equ    TRIG_WORD, 0x89a        |   (+0 note, +8/+0x10/+0x18 trig types, +0x38 swing; step 1 =
                                        |   bit 0 of byte 7) and its trig words (+0x89a + 2s: count,
                                        |   micro-timing, condition; C: the step handler 0x4009d33e)

| ---------------------------------------------------------------------------- ours
        .equ    VARI, 4                 | TSTR / TSMODE raw value
        .equ    TSTR_AUTO, 1
        .equ    BPM24_MIN, 720          | 30..300 BPM, the firmware's own range
        .equ    BPM24_MAX, 7200
        .equ    INC_MAX, 0x07fffff0     | 2.0 - 16 LSB, Q26
        .equ    RP_HOLD, 0xfe
| What VARISPEED keeps per track (VRG3, 2026-11-19; NOTES): four bytes of the track's Part record that
| stock never edits or shows -- no page, encoder, chooser, MIDI CC or p-lock reaches them (ot_emu, every
| machine's pages and the SRC SETUP chooser), its Part validator keeps 0..127, and a track playing THRU /
| NEIGHBOR sounds the same whatever they hold (ot_emu audio, bit for bit). Their one stock writer, the SRC
| page paste of a THRU / NEIGHBOR page, is undone around it (vh_pgsave / vh_pgrest). Until VRG2 this lived
| in NEIGHBOR's page bytes, which BLACKPYRAMIDS_303 owns (and NEIGHBOR's SETUP bytes are editable from the
| SRC SETUP chooser): rp_migrate moves an older build's park in.
        .equ    VP_ST, 14               | + OFF_P1 + 30t: THRU page 1 slot 2 ('---'): STATIC's PTCH park
        .equ    VP_FL, 17               | THRU page 1 slot 5 ('---'): FLEX's PTCH park
        .equ    VM_ST, 2                | + OFF_SLOT5 + 5t: THRU's slot byte: STATIC's side byte
        .equ    VM_FL, 3                | NEIGHBOR's slot byte: FLEX's side byte
        .equ    VM_QUAN, 0x0f           | VM off VARI: the remembered QUAN + 1 (0: none)
        .equ    VM_EMUS, 0x30           |   the remembered EMUS stop + 1 (VARISPEED_EMUS; 0: none = OT)
        .equ    VM_BPV, 6               |   bit 6 (FLEX): BLACKPYRAMIDS_303 took the track while on VARI
| the older builds' NEIGHBOR park (rp_migrate only)
        .equ    OLD_P1, 18              | + OFF_P1 + 30t: NEIGHBOR page 1, byte 0
        .equ    OLD_P2_AT, 0x1b0        | NEIGHBOR page 2, from page 1's (OFF_P2 - OFF_P1)
        .equ    OLD_PK1_ST, 0           | page 1 byte 0: STATIC's PTCH park
        .equ    OLD_PK1_FL, 5           | page 1 byte 5: FLEX's PTCH park
        .equ    OLD_PK2_ST, 5           | page 2 byte 5: STATIC's TSNS park (VARISPEED_EMUS)
        .equ    OLD_PK2_FL, 3           | page 2 byte 3: FLEX's TSNS park (VARISPEED_EMUS)
        .equ    TSNS_SLOT2, 5
        .equ    TSTR_SLOT2, 4
        .equ    EM_DETENTS, 4           | EMUS: detents in one direction per stop (spec §6b item 6)

| ---------------------------------------------------------------------------- the DSP load guard
| Spec §6 item 1 (the cost model) and §6b (the guard). Every price and budget the guard
| uses is HERE and nowhere else (the tests read this block). Unit: MODELLED DSP cycles
| per output sample, the unit of the KYOTI load audit as the spec carries it (the audit
| itself is not read here: clean-room). Reports: VARISPEED_IMPL.md §10, §12.
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
| playback ratios 0.5-1.99x, both payloads, of tools/varispeed_emus_dsp_profile.py, its "~hw"
| column (a one-word instruction 2 cycles, a displaced access +2). VEM3's kernel: SP12 269.8,
| S950 108.6 (its datasheet column, 146.5 / 57.3, cannot reproduce the user's brackets below,
| IMPL §10.3; this one does). The optimized kernels (VEM4, VARISPEED_EMUS_DSP_OPT.md),
| re-profiled 2026-10-15: SP12 217.2, S950 99.0. SP12 in full stereo (VEM9,
| VARISPEED_EMUS_SP12_STEREO.md), 2026-10-15: SP12 186.4 (S950 unchanged).
        .equ    VG_S950, 99
        .equ    VG_SP12, 187
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
        bsr     vf_win                  | this track's live bytes another Part's than the DB's
        bne     .vf_frz                 |   current one (a Part switch): no poll (VEM11, fix 3;
                                        |   VARISPEED too since VARIG1)
        move.l  %d2,%d1
        bsr     rp_swap                 | d0 = md<<8 | domain<<1 | swapped
        move.l  %d0,%d5
        lea     vf_eng(%pc),%a0
        clr.b   0(%a0,%d2.l)
        btst    #1,%d5
        beq     .vf_plain               | the slot holds PTCH: stock pitch
        move.l  %d5,%d1
        lsr.l   #8,%d1
        cmp.l   %d3,%d1
        bne     .vf_plain               | the DB machine is not the one rendering
        moveq   #1,%d1
        move.b  %d1,0(%a0,%d2.l)        | vf_eng: this poll's verdict, kept for the window
.vf_go:
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
        lea     vgx_ovr(%pc),%a0        | VEM11: the guard's cap on the incoming Part's engine
        mvz.b   0(%a0,%d2.l),%d4        |   for this track (0: none, else 1 + the engine), for a
        bne.s   .vf_cap                 |   trig of THAT Part (its EMUS is committed at the switch)
        bra.s   .vf_tag
.vf_carry:
        move.l  36(%a3),%d1             | the latched engine, from the last frame
        lsr.l   #2,%d1
        moveq   #3,%d4
        and.l   %d4,%d1
        lea     vgx_cl(%pc),%a0         | VEM11: a clamp the guard asks for this carried note
        tst.b   0(%a0,%d2.l)            |   (0: none, else 1 + the engine)
        bne.s   .vf_clamp
.vf_tag:
        moveq   #-16,%d4
        and.l   %d4,%d0
        lsl.l   #2,%d1
        or.l    %d1,%d0
        bra.s   .vf_store
| VEM11: the guard's decisions for a Part switch (vgx_tick, made before it; nothing reaches
| the Part until the switch). vgx_tgt = the incoming Part (bank << 8 | part), -1 none.
| .vf_cap: a trig whose live bytes are vgx_tgt's (LIVE_PB) latches min(its EMUS, the cap):
|   the incoming Part's step-down, its boundary trigs included. d4 = 1 + the cap.
| .vf_clamp: a carried note gets min(its engine, the clamp) on its first carried frame under
|   vgx_tgt (APPLIED_B / APPLIED_P: the real switch frame), once; a temporary step-down that
|   ends at its own next trig. a0 -> vgx_cl. Both: d0 = the increment, d1 = the engine.
.vf_cap:
        subq.l  #1,%d4
        cmp.l   %d4,%d1
        bls.s   .vf_tag                 | within the cap
        lea     (LIVE_PB).l,%a1
        mvz.b   0(%a1,%d2.l),%d5        | this trig's Part: bank << 8 | part
        lsl.l   #8,%d5
        move.b  8(%a1,%d2.l),%d5
        cmp.w   vgx_tgt(%pc),%d5
        bne.s   .vf_tag                 | not the incoming Part's trig
        move.l  %d4,%d1
        bra.s   .vf_tag
.vf_clamp:
        move.w  (APPLIED_B).l,%d4
        cmp.w   vgx_tgt(%pc),%d4
        bne.s   .vf_tag                 | the switch is still to come
        mvz.b   0(%a0,%d2.l),%d4
        clr.b   0(%a0,%d2.l)            | once
        subq.l  #1,%d4
        cmp.l   %d4,%d1
        bls.s   .vf_tag
        move.l  %d4,%d1
        bra.s   .vf_tag
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
| VEM11, fix 3 (both builds since VARIG1): a track whose live bytes -- the lane -- are not the DB's current Part's: from a
| sequencer switch's PART_B / bank move to the apply (every track), and after the apply until the
| track's own first trig in the new Part (stock copies its live bytes then, per track). The poll
| would read the NEXT Part's bytes: a playing VARI voice would leave VARI early (its engine and
| speed: a pitch jump; FINAL: 7 ticks before the switch), and one held into a Part where that
| track is not VARI would change speed on the downbeat. Keep its last poll's verdict instead, so
| it changes at its own next trig, as stock changes everything else. A track that is no VARI
| candidate plays stock's increment, unpolled (a held non-VARI note into a VARI Part: at its trig).
.vf_frz:
        tst.l   %d4
        beq     .vf_plain               | not a candidate: stock (nothing polled)
        lea     vf_eng(%pc),%a0
        tst.b   0(%a0,%d2.l)
        beq     .vf_plain
        moveq   #-126,%d5               | ..82: QUAN, not a swap frame
        bra     .vf_go
| vf_win: d2 = track -> Z set when its live bytes are the current Part's: its live-bytes pair
| (LIVE_PB, stock's) is the DB's bank and PART_B. Uses d0 / d1 / a0.
vf_win:
        lea     (LIVE_PB).l,%a0
        moveq   #0,%d0
        move.b  8(%a0,%d2.l),%d0
        cmp.b   (PART_B).l,%d0
        bne.s   1f
        move.b  0(%a0,%d2.l),%d0
        move.l  #BANK_STRIDE,%d1
        mulu.l  %d1,%d0
        addi.l  #BANK0_DB,%d0
        cmp.l   (DB_PTR).l,%d0
1:      rts
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

        .ifdef  VEM_UI_SECTION          | VRG3: UI-task code, in the UI section (see THE UI SECTION)
        .section .vemui,"ax"
        .balign 2
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
        lea     (tstr_tab).l,%a0
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
        pea     (str_vari).l
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
3:      jsr     (vg_note).l             |   VARI. Every track whose gate is off before the
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
        .ifdef  VEM_UI_SECTION
        .text
        .endif

        .if VEM_EMUS
| ---------------------------------------------------------------------------
| EMUS -- the TSNS slot (SRC SETUP slot 11) of a VARI track.
|
| emus_widget: STATIC / FLEX slot-11 widget column (stock 0 = the default dial). Args
| (x, y, index, value, flags, fmt, canvas). Off ST/FL or off VARI: the stock dial. On
| VARI: a 3-position rotary switch (tools/ui_switch.s sw3_draw: stock SPRING TYPE's,
| 9:00 / 12:00 / 3:00) on the value's stop, read out by emus_fmt. The caption is
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
        bmi.s   .ew_frame               | an empty cell keeps the bare frame (the dial's)
        move.l  %d0,%d1                 | the readout is the stored value: what plays
        bsr     emus_idx                | d0 = its stop 0..2
        move.l  (%sp)+,%d2
        bra     sw3_draw
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
| while the swap is still to come (rp_pend: rp_prev[2t+m] == 0, the gate came on since the
| last poll; or forgotten over a PTCH park that the next poll's first sight enters from,
| VARIG2). Keeps every register.
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
        jsr     (rp_pend).l             | d0 = 1: the swap into VARI is still to come
        tst.l   %d0
        beq.s   2f
        bsr     db_park2                | EMUS is parked
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
| lives now: the TSNS slot of its current machine, or the EMUS that machine's VM remembers
| while the swap into VARI is still to come (rp_pend). The working DB and its SRAM copy with the
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
        jsr     (rp_pend).l             | the swap into VARI still to come: the remembered EMUS
        tst.l   %d0
        beq.s   1f
        move.l  %d1,%d3
        lsl.l   #2,%d3
        add.l   %d1,%d3
        add.l   %d2,%d3
        addi.l  #OFF_SLOT5+VM_ST,%d3    | VM_m
        moveq   #0,%d0
        move.b  0(%a0,%d3.l),%d0
        andi.l  #0xff-VM_EMUS,%d0
        ori.l   #0x10,%d0               | stop 0 + 1: OT
        move.b  %d0,0(%a0,%d3.l)
        move.b  %d0,0(%a1,%d3.l)
        bra.s   3f
1:      moveq   #30,%d3
        mulu.l  %d1,%d3
        addi.l  #OFF_P2,%d3             | d3 = the track's page-2 row
        move.l  %d2,%d0                 | the slot
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

| vg_new (vg_tick, when the signature changed; spec "6b, option B", VEM8): d0 = the tracks
| that became VARI tracks INDIRECTLY since the last check, so that each can be named as the
| one the change was made to: its gate (its current machine's, rp_ui_gate, with the project
| tempo in range) is on now and was off then, its machine and that machine's TSTR are what
| they were (TSTR untouched), and nothing since has rewritten Parts wholesale. What that
| leaves is a change of what its slot plays -- the sample's ATTR TEMPO or TIMESTRETCH, a
| sample loaded into the slot -- or of which slot it plays: the slot byte, but only when the
| live slot byte already agrees with it (a UI assign writes both, C: 0x40079424 at
| 0x400795c0 / 0x40079610; a bank read during a project load rewrites the Part alone and
| the Part apply comes after it, C: ot_emu, IMPL §15). Not named, so the net's order applies:
| a Part apply, a bulk write (paste, PART menu, RELOAD PART) or another current Part since the
| last check (rp_forget sets vg_bulk; rp_sync forgets on another Part), a machine change, a
| TSTR change (P2EDIT's TSTR is VEM7's: vg_note / vg_entered). Keeps the snapshot (vg_gon,
| vg_key) for the next check. Keeps all but d0.
| VEM10 (spec "6b, option B extended"): a machine change made by a SLOT PICK -- a slot of the
| other machine picked from a slot list (vg_pick, set by the two choosers' slot columns for
| their track, cleared at every loop tail) -- names that track when its gate is on now (its
| new machine's setting puts it on VARI; on or off under the old machine) and no bulk change
| came between. No live-slot test here: the pick that finds the other machine's slot byte
| already on its slot changes the machine alone and writes no live slot byte (C: ot_emu,
| IMPL §17), and vg_pick already says the change came from this message's UI handler. A
| machine change from the machine column, or any other, sets no vg_pick bit: the net's order.
vg_new:
        lea     -36(%sp),%sp
        movem.l %d1-%d7/%a0-%a1,(%sp)
        move.w  %sr,%d7
        move.w  #0x2700,%sr             | the flag is set from the frame path too
        mvz.b   (vg_bulk).l,%d6
        clr.b   (vg_bulk).l
        move.w  %d7,%sr
        mvz.b   (vg_pick).l,%d7         | VEM10: the track a slot pick just ran on (bit t)
        tst.l   %d6
        beq.s   1f
        moveq   #0,%d7                  | (a bulk change since: no pick counts either)
        moveq   #-1,%d6                 | a bulk change since: as if every gate had been on
        bra.s   2f
1:      mvz.b   (vg_gon).l,%d6          | the gates at the last check
2:      bsr     vg_tempo_ok
        move.l  %d0,%d5                 | 0: the project tempo in range
        moveq   #0,%d3                  | named
        moveq   #0,%d4                  | the gates now
        lea     vg_key(%pc),%a1
        moveq   #0,%d1                  | t
.vn_t:  jsr     (vg_tkey).l             | d0 = its key now
        move.l  (%a1),%d2
        move.l  %d0,(%a1)+
        eor.l   %d0,%d2                 | what changed in it
        tst.l   %d5
        bne.s   .vn_n                   | the project tempo out of range: no gate
        bsr     rp_ui_gate
        tst.l   %d0
        beq.s   .vn_n
        bset    %d1,%d4                 | on now
        btst    %d1,%d7
        beq.s   4f                      | no slot pick on this track
        move.l  %d2,%d0
        andi.l  #0xff0000,%d0
        bne.s   3f                      | VEM10: a slot pick changed its machine: named
4:      btst    %d1,%d6
        bne.s   .vn_n                   | on before (or a bulk change)
        move.l  %d2,%d0
        andi.l  #0xffffff00,%d0
        bne.s   .vn_n                   | its machine or TSTR changed
        tst.l   %d2
        beq.s   3f                      | its slot unchanged: what the slot plays changed
        mvz.b   -1(%a1),%d0             | its slot changed: named when the live byte agrees
        move.l  %d1,%d2
        lsl.l   #3,%d2
        movea.l %d2,%a0                 | 8t
        lsl.l   #3,%d2
        adda.l  %d2,%a0                 | + 64t
        adda.l  #LIVE_SLOT,%a0
        cmp.b   (%a0),%d0
        bne.s   .vn_n
3:      bset    %d1,%d3
.vn_n:  addq.l  #1,%d1
        moveq   #8,%d0
        cmp.l   %d0,%d1
        blt.s   .vn_t
        move.b  %d4,(vg_gon).l
        move.l  %d3,%d0
        movem.l (%sp),%d1-%d7/%a0-%a1
        lea     36(%sp),%sp
        rts

| vg_pick_src / vg_pick_ae (VEM10, spec "6b, option B extended"): the slot columns of the two
| machine / slot choosers that reach the slot assign 0x40079424 -- the SRC menu's
| (0x4005a5a8, its column 0x460d1a48 = 1: `jsr 0x4003d014` at 0x4005a760 -> `jsr vg_pick_src`)
| and the audio editor's (0x400796a0, its column 0x460e739a = 1: `move.l 0x460e738e,%d4` at
| 0x400796d6 -> `jsr vg_pick_ae`). Each marks the chooser's track (0x100b14cc) in vg_pick,
| then does what it displaced. Either column then changes the machine when the slot picked
| is the other machine's -- through the slot assign (0x40079522), or, when that machine's
| slot byte already holds the slot, straight (0x4005a826 / via 0x400798fe to 0x400797cc).
| Their machine columns (0x4005a5c2; 0x400798fe) reach neither site: the machine selector.
| UI task (key handlers). Keep every register (vg_pick_ae: all but d4, which it loads).
vg_pick_src:
        bsr.s   vg_pick_t
        jmp     (SRC_SLOT_SEL).l        | displaced: the call (its rts returns behind the site)
vg_pick_ae:
        bsr.s   vg_pick_t
        move.l  (AE_PICK_M).l,%d4       | displaced
        rts
vg_pick_t:
        move.l  %d0,-(%sp)
        move.l  %a0,-(%sp)
        mvz.b   (UI_TRACK_M).l,%d0
        lea     vg_pick(%pc),%a0
        bset    %d0,(%a0)
        movea.l (%sp)+,%a0
        move.l  (%sp)+,%d0
        rts

| vg_tick: `jmp` from 0x40062d1c, the UI task's message-loop tail (C, stock: every message
| the UI task takes -- keys, encoders, and DTIM1's 60 Hz tick, type 5 -- ends here, at one
| stack depth, no handler in flight; stock's own message cases 27/29/31 raise NOTIFY at
| this level and branch here). The safety net: when the inputs' signature differs from
| the last one checked, vg_fix. Before the net, the tracks that ONE track's change put on
| VARI get the first step: vg_fix on them alone, so on an over-budget core THEIR EMUS goes
| to OT -- a TSTR / ATTR TIMESTRETCH edit (VEM7: vg_pend, vg_entered) and any other change
| that turned a track's gate on with its TSTR untouched (option B, VEM8: vg_new); among
| several, the net's order. The net then takes whatever is still over, in its order. Then
| the toast when flagged (a refusal in the handler that just ran, the entering track's step,
| or the net): MAX DSP: EMU LIMIT, 1.2 s. The ONLY NOTIFY of this unit.
| d0/d1/a0/a1 are free at this point (the loop's next act is a call); the rest is kept.
vg_tick:
        tst.l   (DB_PTR).l
        beq.s   2f                      | no bank blob yet (early boot)
        tst.b   (vem_depth).l
        bne.s   2f                      | a bulk write holds the Part (not the UI task's)
        move.l  %d2,-(%sp)
        moveq   #0,%d2                  | stepped?
        jsr     (vg_sig).l
        cmp.l   (vg_last).l,%d0
        beq.s   4f                      | nothing the estimate reads has changed
        move.l  %d0,(vg_last).l
        bsr     vg_new                  | the tracks that came onto VARI indirectly
        move.l  %d0,%d1
        mvz.b   (vg_pend).l,%d0         | a TSTR / ATTR edit just ran
        beq.s   5f
        jsr     (vg_entered).l          | the tracks it put on VARI
        or.l    %d0,%d1
5:      move.l  %d1,%d0
        beq.s   6f
        bsr     vg_fix                  | over budget: THEIR EMUS to OT first
        move.l  %d0,%d2
6:      moveq   #-1,%d0
        bsr     vg_fix                  | the net's order for whatever is still over
        or.l    %d0,%d2
        beq.s   4f
        jsr     (vg_sig).l              | it stepped: the signature of the fixed settings
        move.l  %d0,(vg_last).l
4:      clr.b   (vg_pend).l
        move.l  (%sp)+,%d2
        jsr     (vgx_tick).l            | VEM11, fix 1: a Part switch on its way, priced whole
2:      clr.b   (vg_pick).l             | VEM10: a slot pick counts for its own message only
        tst.b   (vg_toast).l
        beq.s   3f
        clr.b   (vg_toast).l
        pea     (TOAST_DUR).w
        pea     str_emu_limit(%pc)
        jsr     (NOTIFY).l              | NOTIFY(text, 0x48): self-timing, closes itself
        addq.l  #8,%sp
3:      tst.l   (UI_FLUSH).l            | displaced: the loop's own test, its beq follows
        jmp     (UI_TAIL_BACK).l

| ---------------------------------------------------------------------------
| THE UI SECTION (VEM11): guard code only the UI task runs -- the net's signature (vg_sig) and
| the transition pricing (vgx_tick). The standalone builder links it apart from the unit, as a
| DRAM unit behind tools/dram/'s loader (`as --defsym VEM_UI_SECTION=1`): the classic cave has
| no room left for it. Without the symbol (octabam's assembly of this file) it stays in .text,
| one unit as before. Its code reaches the unit, and the unit it, by absolute address only.
        .ifdef  VEM_UI_SECTION
        .section .vemui,"ax"
        .balign 4
        .endif

| vg_tkey: d1 = track -> d0 = its key in the current Part: machine << 16 | that machine's
| TSTR << 8 | its slot byte (ST / FL); machine << 16 alone above FL. Keeps all but d0.
| In the UI section since VARIG2 (the cave needed the room for rp_swap_m's first sight).
vg_tkey:
        lea     -20(%sp),%sp
        movem.l %d1-%d4/%a0,(%sp)
        jsr     (db_mach).l             | d2 = m
        jsr     (part_base).l           | a0 = the Part
        move.l  %d2,%d0
        lsl.l   #8,%d0
        moveq   #1,%d3
        cmp.l   %d3,%d2
        bhi.s   1f                      | THRU / NEIGHBOR / PICKUP
        moveq   #30,%d3
        mulu.l  %d1,%d3
        move.l  %d2,%d4
        add.l   %d4,%d4
        add.l   %d2,%d4
        add.l   %d4,%d4                 | 6m
        add.l   %d4,%d3
        addi.l  #OFF_P2+TSTR_SLOT2,%d3
        mvz.b   0(%a0,%d3.l),%d4
        or.l    %d4,%d0                 | TSTR
        lsl.l   #8,%d0
        move.l  %d1,%d3
        lsl.l   #2,%d3
        add.l   %d1,%d3
        add.l   %d2,%d3                 | 5t + m
        addi.l  #OFF_SLOT5,%d3
        mvz.b   0(%a0,%d3.l),%d4
        or.l    %d4,%d0                 | the slot
        bra.s   2f
1:      lsl.l   #8,%d0
2:      movem.l (%sp),%d1-%d4/%a0
        lea     20(%sp),%sp
        rts

| rp_pend: d1 = track, d2 = machine (0 ST / 1 FL) of a track whose gate is on in the current
| Part -> d0 = 1 when that machine's EMUS is still the remembered one (VM), the swap into VARI
| to come: rp_prev 0, or forgotten (0xff) over bytes that have still to enter VARI (rp_unent:
| the next poll's first sight enters, VARIG2); else 0 (the TSNS slot).
| Keeps everything else. UI task.
rp_pend:
        lea     -16(%sp),%sp
        movem.l %d5-%d7/%a0,(%sp)
        lea     (rp_prev).l,%a0
        move.l  %d1,%d0
        add.l   %d0,%d0
        add.l   %d2,%d0
        mvs.b   0(%a0,%d0.l),%d0
        beq.s   2f                      | 0: to come
        addq.l  #1,%d0
        bne.s   1f                      | 1, HOLD: EMUS in the slot
        jsr     (part_base).l
        jsr     (rp_offs).l
        jsr     (rp_unent).l            | forgotten: what the next poll's first sight does
        bra.s   4f
1:      moveq   #0,%d0
        bra.s   4f
2:      moveq   #1,%d0
4:      movem.l (%sp),%d5-%d7/%a0
        lea     16(%sp),%sp
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
        jsr     (rp_ui_gate).l
        tst.l   %d0
        beq.s   2f
        bset    %d1,%d3
2:      subq.l  #1,%d1
        bpl.s   1b
        move.l  %d3,%d0
        movem.l (%sp),%d1-%d3
        lea     12(%sp),%sp
        rts

| vg_sig -> d0: a cheap signature of everything vg_scan and vg_est read: the current Part
| (its block), its 16 FX type bytes, whether the project tempo is in range, and per track
| its machine and, on ST / FL, that machine's TSTR; when TSTR is AUTO or VARI (the only
| values that can open the gate) also its sample slot, that sample's TSMODE and tempo, the
| rp_prev byte, the TSNS slot and VM_m. h = 33 h + x over them (any one input changing
| changes it but for a collision). rp_sync first: rp_prev must describe this Part. About
| 15 instructions per track off AUTO / VARI, 50 on them. Uses d0, d1, a0, a1 (the tail's).
vg_sig:
        lea     -20(%sp),%sp
        movem.l %d2-%d5/%a2,(%sp)
        jsr     (rp_sync).l
        jsr     (part_base).l
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
        jsr     (vg_tempo_ok).l
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
        lea     (rp_prev).l,%a1
        move.l  %d1,%d0
        add.l   %d0,%d0
        add.l   %d3,%d0
        mvz.b   0(%a1,%d0.l),%d0
        swap    %d0
        lsl.l   #8,%d0
        add.l   %d0,%d2                 | rp_prev
        movea.l %a2,%a0
        adda.l  #OFF_SLOT5+VM_ST,%a0
        move.l  %d1,%d0
        lsl.l   #2,%d0
        add.l   %d1,%d0
        add.l   %d3,%d0                 | 5t + m
        mvz.b   0(%a0,%d0.l),%d0
        lsl.l   #3,%d0
        add.l   %d0,%d2                 | VM_m (the remembered EMUS, or the parked TSNS)
.sg_n:  addq.l  #1,%d1
        moveq   #8,%d0
        cmp.l   %d0,%d1
        blt     .sg_t
        move.l  %d2,%d0
        movem.l (%sp),%d2-%d5/%a2
        lea     20(%sp),%sp
        rts

| ---------------------------------------------------------------------------
| VEM11 (VEMG2, the author's decisions of 2026-11-18): THE TRANSITION. A sequencer Part switch does
| not move a track to the new Part's FX and engine until that track's own first trig there: the
| stock trig handler copies its live FX types then (0x4000c40e / 0x4000c41e), and its live bytes and
| the engine latch (vem_frame) move at the same trig; until then the old Part's carried tracks and
| the new Part's triggered ones play MIXED. Each Part fits its core alone, the mix need not. So while
| a switch is on its way the guard prices the TRANSITION per core,
|     base + the sum over its four tracks of
|         new                  for a track CERTAIN to trig on the new pattern's first step (vgx_cert:
|                              a note trig, no trig-type layer, no swing, its trig word 0 -- no
|                              condition, no probability, no micro-timing, one trig): it switches at once;
|         max(old, new)        for every other one, which carries its old note,
|     old = the live FX types + the engine it carries (or the live EMUS an old-Part trig may still
|           latch before the switch; OT when clamped), new = the next Part's FX + its engine there,
| and, over the budget, decides in two stages, each in the net's order (SP12 first, then S950, the
| highest track first), a step that does not lower the estimate skipped:
|   1. clamp carried notes to OT (temporary: vem_frame clamps the note on the real switch frame; the
|      note's own next trig plays the new Part's engine);
|   2. only when every carried note clamped is still not enough, the next Part's EMUS to OT (for the
|      whole Part).
| NOTHING IS WRITTEN UNTIL THE SWITCH. The decisions are pending state in the unit (vgx_tgt,
| vgx_ovr, vgx_cl), recomputed on every pass while the switch is on its way; vem_frame applies
| them on the switch frame (APPLIED_B / APPLIED_P = vgx_tgt): the clamp on the carried notes, the cap
| on every trig of the incoming Part (its boundary trigs included). The first pass that sees the
| switch done commits the step-downs to the Part (DB, SRAM copy, dirty flags; the live byte of a
| track that has switched) and raises the toast. A cue cancelled or changed before its switch
| leaves nothing: the pending state is dropped.
| "On its way": the transport runs (0x800065b8 == 1; stopped, a cue applies at once, 0x400a05aa) and
|   (1) a pattern is cued (PEND 0x800065bf / c0 set and not PLAY 0x800065bd / be) in the working
|       bank, whose Part (the pattern's byte +0x8e57) is not the current one: that Part's DB block,
|       EMUS in its TSNS slot (not current: rp_prev does not describe it); or
|   (2) PART_B or the bank has moved and the frame has not applied that Part yet (APPLIED is not the
|       current Part; UI message 20, ~7 ticks before the boundary): the current Part as the net sees
|       it (vg_scan), the pattern PLAY. A cue into another bank is priced here.
| With every carried note and every next engine on OT the transition is at most base + 8 x the
| dearest stock FX (3,253 on core 0 with the VG_* table): every switch can be made to fit.
| UI task only. d0/d1/a0/a1 free (vg_tick's tail); the rest kept.
vgx_tick:
        move.w  (vgx_tgt).l,%d0
        bmi     1f                      | nothing pending
        cmp.w   (APPLIED_B).l,%d0
        beq     .xt_commit              | its switch has come
1:      moveq   #1,%d0
        cmp.l   (SEQ_RUN).l,%d0
        bne     .xt_none                | stopped: a cue applies at once
        moveq   #0,%d0
        move.b  (APPLIED_P).l,%d0
        cmp.b   (PART_B).l,%d0
        bne     .xt_cur                 | (2) PART_B moved ahead of the apply
        move.b  (APPLIED_B).l,%d0
        move.l  #BANK_STRIDE,%d1
        mulu.l  %d1,%d0
        addi.l  #BANK0_DB,%d0
        cmp.l   (DB_PTR).l,%d0
        bne     .xt_cur                 | (2) the bank moved ahead of the apply
        mvs.b   (PEND_P).l,%d0          | (1) a cue waiting for its boundary?
        bmi     .xt_none
        mvs.b   (PEND_B).l,%d1
        bmi     .xt_none
        cmp.b   (PLAY_P).l,%d0
        bne     1f
        cmp.b   (PLAY_B).l,%d1
        beq     .xt_none                | nothing cued
1:      lea     -40(%sp),%sp
        movem.l %d2-%d7/%a2-%a5,(%sp)
        move.l  %d1,%d3                 | the cued bank
        move.l  #BANK_STRIDE,%d2
        mulu.l  %d2,%d1
        addi.l  #BANK0_DB,%d1
        cmp.l   (DB_PTR).l,%d1
        bne     .xt_drop                | another bank: priced at (2)
        move.l  #PAT_STRIDE,%d2
        mulu.l  %d2,%d0
        add.l   %d1,%d0
        movea.l %d0,%a4                 | a4 = the cued pattern
        movea.l %a4,%a0
        adda.l  #PAT_PART,%a0
        moveq   #0,%d6
        move.b  (%a0),%d6
        moveq   #3,%d0
        and.l   %d0,%d6                 | d6 = its Part
        cmp.b   (PART_B).l,%d6
        beq     .xt_drop                | the same Part: nothing changes hands
        move.l  #PART_STRIDE,%d0
        mulu.l  %d6,%d0
        movea.l (DB_PTR).l,%a2
        adda.l  %d0,%a2                 | a2 = its block
        lsl.l   #8,%d3
        or.l    %d6,%d3                 | d3 = its pair
        moveq   #1,%d7                  | another Part than the current one
        bsr     vgx_price
        bra     .xt_out
.xt_cur:
        lea     -40(%sp),%sp
        movem.l %d2-%d7/%a2-%a5,(%sp)
        jsr     (part_base).l
        movea.l %a0,%a2                 | a2 = the current Part, the next to play
        move.l  (DB_PTR).l,%d0
        subi.l  #BANK0_DB,%d0
        move.l  #BANK_STRIDE,%d1
        divu.l  %d1,%d0                 | its bank
        move.l  %d0,%d3
        moveq   #0,%d6
        move.b  (PART_B).l,%d6
        lsl.l   #8,%d3
        or.l    %d6,%d3                 | d3 = its pair
        mvs.b   (PLAY_P).l,%d0          | the pattern that plays from the boundary (committed)
        move.l  #PAT_STRIDE,%d1
        mulu.l  %d1,%d0
        add.l   (DB_PTR).l,%d0
        movea.l %d0,%a4
        moveq   #0,%d7
        bsr     vgx_price
.xt_out:
        movem.l (%sp),%d2-%d7/%a2-%a5
        lea     40(%sp),%sp
        rts
.xt_drop:
        movem.l (%sp),%d2-%d7/%a2-%a5
        lea     40(%sp),%sp
.xt_none:
        tst.w   (vgx_tgt).l
        bmi     9f
        bsr     vgx_clear               | a cue cancelled or changed: nothing was written
9:      rts
| the switch to vgx_tgt has come (vem_frame applied the decisions on its frame): commit the next
| Part's step-downs (vgx_ovr) to that Part, now the current one, and raise the toast for any decision
.xt_commit:
        lea     -40(%sp),%sp
        movem.l %d2-%d7/%a2-%a5,(%sp)
        jsr     (part_base).l
        movea.l %a0,%a2
        moveq   #0,%d6
        move.b  (PART_B).l,%d6          | (d6 / a2 / d7 = 1: vgx_step's Part, the TSNS slot)
        moveq   #1,%d7
        move.w  (APPLIED_B).l,%d5       | = vgx_tgt: the pair a switched track's live bytes have
        bsr     vgx_scan                | vg_eng: the Part's engines as stored
        lea     (vgx_ovr).l,%a3
        lea     (vg_eng).l,%a1
        moveq   #7,%d1
1:      mvz.b   0(%a3,%d1.l),%d0
        beq     2f                      | no cap here
        subq.l  #1,%d0
        cmp.b   0(%a1,%d1.l),%d0
        bcc     2f                      | the Part is within it already (cap >= engine)
        bsr     vgx_step                | EMUS = OT in the Part (the only cap stage 2 sets)
        lea     (LIVE_PB).l,%a0         | a track that has switched: its live byte too (a carried
        mvz.b   0(%a0,%d1.l),%d0        |   one keeps the old Part's until its trig, which loads
        lsl.l   #8,%d0                  |   the committed EMUS)
        move.b  8(%a0,%d1.l),%d0
        cmp.w   %d5,%d0
        bne     2f
        move.l  %d1,%d0
        mulu.w  #72,%d0
        lea     (LIVE_P2+TSNS_SLOT2).l,%a0
        moveq   #1,%d2
        move.b  %d2,0(%a0,%d0.l)
2:      subq.l  #1,%d1
        bpl     1b
        tst.b   (vgx_any).l
        beq     3f
        moveq   #1,%d0
        move.b  %d0,(vg_toast).l        | MAX DSP: EMU LIMIT, from vg_tick's tail
3:      bsr     vgx_clear
        movem.l (%sp),%d2-%d7/%a2-%a5
        lea     40(%sp),%sp
        rts

| vgx_clear: no pending decision (interrupts masked across: vem_frame reads it). Keeps all.
vgx_clear:
        move.l  %d0,-(%sp)
        move.l  %d1,-(%sp)
        move.w  %sr,%d1
        move.w  #0x2700,%sr
        moveq   #-1,%d0
        move.w  %d0,(vgx_tgt).l
        clr.l   (vgx_ovr).l
        clr.l   (vgx_ovr+4).l
        clr.l   (vgx_cl).l
        clr.l   (vgx_cl+4).l
        clr.b   (vgx_any).l
        move.w  %d1,%sr
        move.l  (%sp)+,%d1
        move.l  (%sp)+,%d0
        rts

| vgx_price: a2 = the next Part's block, d7 = 0 (it is the current Part) / 1 (another), d3 = its pair,
| a4 = the pattern it plays from the boundary. Prices the transition, decides the two stages, and
| publishes them as the pending state (with interrupts masked). Uses d0-d6, a0, a1, a3, a5.
vgx_price:
        tst.l   %d7
        bne     1f
        jsr     (vg_scan).l             | vg_eng: the current Part's engines, as the net's
        bra     2f
1:      bsr     vgx_scan                | vg_eng: the other Part's engines
2:      bsr     vgx_cert                | vgx_crt: the tracks sure to trig on its first step
        bsr     vgx_olde                | vgx_oe: the engine each carried note runs (0 if none)
        lea     (vgx_ne).l,%a0          | vgx_ne: the next engines, as the decisions leave them
        lea     (vg_eng).l,%a1
        move.l  (%a1),(%a0)
        move.l  4(%a1),4(%a0)
        moveq   #0,%d5                  | decided anything?
        moveq   #0,%d4                  | g = 0 (T1-T4, core 1), then 4 (T5-T8, core 0)
.xp_core:
        move.l  %d4,%d0
        bsr     vgx_est
        lea     (vg_budget).l,%a0
        cmp.l   0(%a0,%d4.l),%d0
        ble     .xp_next                | it fits
        move.l  %d0,%d2                 | the estimate now
        lea     (vgx_oe).l,%a5          | stage 1: the carried notes
        bsr     vgx_stage
        tst.l   %d0
        bne     .xp_core                | one clamped: again
        lea     (vgx_ne).l,%a5          | stage 2: the next Part's engines
        bsr     vgx_stage
        tst.l   %d0
        bne     .xp_core
.xp_next:
        addq.l  #4,%d4
        moveq   #8,%d0
        cmp.l   %d0,%d4
        blt     .xp_core
        | publish: a clamp where vgx_oe was lowered to OT, a cap where vgx_ne was
        lea     (vgx_olde_b).l,%a0      | the carried engines before the decisions
        lea     (vg_eng).l,%a1
        lea     (vgx_oe).l,%a3
        lea     (vgx_ne).l,%a5
        moveq   #7,%d1
        moveq   #0,%d6                  | any decision?
        lea     (vgx_pcl).l,%a4         | staging, then copied under the mask
3:      moveq   #0,%d0
        tst.b   0(%a0,%d1.l)
        beq     4f
        tst.b   0(%a3,%d1.l)
        bne     4f
        moveq   #1,%d0                  | clamped to OT: 1 + 0
        moveq   #1,%d6
4:      move.b  %d0,0(%a4,%d1.l)
        moveq   #0,%d0
        tst.b   0(%a1,%d1.l)
        beq     5f
        tst.b   0(%a5,%d1.l)
        bne     5f
        moveq   #1,%d0                  | capped at OT
        moveq   #1,%d6
5:      move.b  %d0,8(%a4,%d1.l)
        subq.l  #1,%d1
        bpl     3b
        move.w  %sr,%d1
        move.w  #0x2700,%sr
        move.w  %d3,(vgx_tgt).l
        move.l  (%a4),%d0
        move.l  %d0,(vgx_cl).l
        move.l  4(%a4),%d0
        move.l  %d0,(vgx_cl+4).l
        move.l  8(%a4),%d0
        move.l  %d0,(vgx_ovr).l
        move.l  12(%a4),%d0
        move.l  %d0,(vgx_ovr+4).l
        move.b  %d6,(vgx_any).l
        move.w  %d1,%sr
        rts

| vgx_stage: a5 -> the engines of a stage (vgx_oe or vgx_ne), d4 = g, d2 = the estimate now ->
| d0 = 1 when one track of the core was lowered to OT (SP12 first, then S950, the highest track
| first; only where that lowers the estimate), else 0. Keeps all but d0.
vgx_stage:
        lea     -12(%sp),%sp
        movem.l %d1/%d3/%a3,(%sp)
        moveq   #2,%d3                  | SP12 first, then S950
1:      moveq   #3,%d1                  | the core's highest track first
2:      move.l  %d4,%d0
        add.l   %d1,%d0
        movea.l %d0,%a3                 | t
        cmp.b   0(%a5,%d0.l),%d3
        bne     3f
        clr.b   0(%a5,%d0.l)            | priced on OT
        move.l  %d4,%d0
        bsr     vgx_est
        cmp.l   %d2,%d0
        blt     4f                      | lower: keep it
        move.l  %a3,%d0
        move.b  %d3,0(%a5,%d0.l)        | not lower: back
3:      subq.l  #1,%d1
        bpl     2b
        subq.l  #1,%d3
        bne     1b
        moveq   #0,%d0
        bra     5f
4:      moveq   #1,%d0
5:      movem.l (%sp),%d1/%d3/%a3
        lea     12(%sp),%sp
        rts

| vgx_cert: a4 = the pattern -> vgx_crt (bit t): track t is sure to trig on its first step -- a
| note trig there (mask +0, step 1 = bit 0 of byte 7), none of the trig-type layers (+8, +0x10,
| +0x18: trigless / one-shot) nor swing (+0x38) on it, its trig word (+0x89a) 0: no condition or
| probability (bits 6-0, the step handler's test, 0x4009d33e), no micro-timing, one trig. Any
| doubt: not sure (it is priced as carrying). Keeps all.
vgx_cert:
        lea     -16(%sp),%sp
        movem.l %d0-%d2/%a0,(%sp)
        moveq   #0,%d2
        moveq   #7,%d1
1:      move.l  #TRAC_STRIDE,%d0
        mulu.l  %d1,%d0
        movea.l %a4,%a0
        adda.l  %d0,%a0                 | the track's sequence
        btst    #0,7(%a0)
        beq     2f                      | no note trig on step 1
        btst    #0,0x0f(%a0)
        bne     2f
        btst    #0,0x17(%a0)
        bne     2f
        btst    #0,0x1f(%a0)
        bne     2f
        btst    #0,0x3f(%a0)
        bne     2f
        tst.w   TRIG_WORD(%a0)
        bne     2f
        bset    %d1,%d2
2:      subq.l  #1,%d1
        bpl     1b
        move.b  %d2,(vgx_crt).l
        movem.l (%sp),%d0-%d2/%a0
        lea     16(%sp),%sp
        rts

| vgx_olde -> vgx_oe[t] = the engine track t's carried note runs at the switch, 0 for a track sure
| to trig on the first step (vgx_crt): the engine it carries -- none unless the frame hook engaged
| it (vf_eng) -- or, playing VARI, the live EMUS an old-Part trig may still latch, the dearer;
| vgx_olde_b = the same, kept. Keeps all.
vgx_olde:
        lea     -24(%sp),%sp
        movem.l %d0-%d3/%a0-%a1,(%sp)
        moveq   #7,%d1
1:      moveq   #0,%d2
        mvz.b   (vgx_crt).l,%d0
        btst    %d1,%d0
        bne     3f                      | it switches at once
        lea     (vf_eng).l,%a0
        tst.b   0(%a0,%d1.l)
        beq     3f
        move.l  %d1,%d0
        mulu.w  #RENDER_STRIDE,%d0
        lea     (RENDER).l,%a0
        move.l  36(%a0,%d0.l),%d2       | its increment: bits 2-3 = the engine latched
        lsr.l   #2,%d2
        moveq   #3,%d0
        and.l   %d0,%d2
        move.l  %d1,%d0
        mulu.w  #72,%d0
        lea     (LIVE_P2).l,%a0
        adda.l  %d0,%a0
        moveq   #0,%d3
        move.b  TSTR_SLOT2(%a0),%d3
        subq.l  #TSTR_AUTO,%d3
        beq     2f
        subq.l  #VARI-TSTR_AUTO,%d3
        bne     3f
2:      mvs.b   TSNS_SLOT2(%a0),%d0
        jsr     (emus_idx).l
        cmp.l   %d2,%d0
        bls     3f
        move.l  %d0,%d2
3:      lea     (vgx_oe).l,%a0
        move.b  %d2,0(%a0,%d1.l)
        lea     (vgx_olde_b).l,%a0
        move.b  %d2,0(%a0,%d1.l)
        subq.l  #1,%d1
        bpl     1b
        movem.l (%sp),%d0-%d3/%a0-%a1
        lea     24(%sp),%sp
        rts

| vgx_est: d0 = g, a2 = the next Part's block, vgx_ne / vgx_oe / vgx_crt -> d0 = the core's
| transition estimate (see vgx_tick). Keeps all but d0.
vgx_est:
        lea     -32(%sp),%sp
        movem.l %d1-%d6/%a0-%a1,(%sp)
        move.l  %d0,%d6                 | g
        lea     (vg_base).l,%a0
        move.l  0(%a0,%d6.l),%d5        | the sum
        moveq   #3,%d4
.xe_t:  move.l  %d6,%d1
        add.l   %d4,%d1                 | t
        lea     (vg_engp).l,%a1
        lea     (vgx_ne).l,%a0
        mvz.b   0(%a0,%d1.l),%d3
        lsl.l   #2,%d3
        move.l  0(%a1,%d3.l),%d3
        movea.l %a2,%a0
        adda.l  #OFF_FX1,%a0
        adda.l  %d1,%a0
        bsr     vgx_fx2
        add.l   %d0,%d3                 | new: the next Part's FX + its engine
        mvz.b   (vgx_crt).l,%d0
        btst    %d1,%d0
        bne     4f                      | sure to trig on the first step: new alone
        lea     (vgx_oe).l,%a0
        mvz.b   0(%a0,%d1.l),%d2
        lsl.l   #2,%d2
        move.l  0(%a1,%d2.l),%d2
        lea     (LIVE_FX1).l,%a0
        adda.l  %d1,%a0
        bsr     vgx_fx2
        add.l   %d0,%d2                 | old: the live FX + the carried note's engine
        cmp.l   %d2,%d3
        bge     4f
        move.l  %d2,%d3
4:      add.l   %d3,%d5
        subq.l  #1,%d4
        bpl     .xe_t
        move.l  %d5,%d0
        movem.l (%sp),%d1-%d6/%a0-%a1
        lea     32(%sp),%sp
        rts

| vgx_fx2: a0 -> a track's FX1 type byte (its FX2 at +8) -> d0 = their two prices. Keeps all
| but d0.
vgx_fx2:
        lea     -12(%sp),%sp
        movem.l %d1-%d2/%a1,(%sp)
        lea     (vg_fxp).l,%a1
        moveq   #0x1f,%d2
        mvz.b   (%a0),%d1
        and.l   %d2,%d1
        add.l   %d1,%d1
        mvz.w   0(%a1,%d1.l),%d0
        mvz.b   8(%a0),%d1
        and.l   %d2,%d1
        add.l   %d1,%d1
        mvz.w   0(%a1,%d1.l),%d1
        add.l   %d1,%d0
        movem.l (%sp),%d1-%d2/%a1
        lea     12(%sp),%sp
        rts

| vgx_scan: a2 = a Part's block, not the current one -> vg_eng[t] = the engine its settings run:
| 0 unless its machine is ST / FL with that machine's gate on (rp_gate_m on that Part) and the
| project tempo in range; then its EMUS, in the TSNS slot (a Part that is not current keeps its
| VARI tracks swapped; rp_prev does not describe it). Keeps every register.
vgx_scan:
        lea     -24(%sp),%sp
        movem.l %d0-%d3/%a0-%a1,(%sp)
        lea     (vg_eng).l,%a1
        clr.l   (%a1)
        clr.l   4(%a1)
        jsr     (vg_tempo_ok).l
        bne     9f
        moveq   #0,%d1
1:      movea.l %a2,%a0
        adda.l  #OFF_MACH,%a0
        moveq   #0,%d2
        move.b  0(%a0,%d1.l),%d2        | m
        moveq   #1,%d0
        cmp.l   %d0,%d2
        bhi     3f
        movea.l %a2,%a0
        bsr     rp_gate_a
        tst.l   %d0
        beq     3f
        move.l  %d2,%d0
        mulu.w  #6,%d0
        move.l  %d1,%d3
        mulu.w  #30,%d3
        add.l   %d3,%d0
        addi.l  #OFF_P2+TSNS_SLOT2,%d0
        mvs.b   0(%a2,%d0.l),%d0
        jsr     (emus_idx).l
        move.b  %d0,0(%a1,%d1.l)
3:      addq.l  #1,%d1
        moveq   #8,%d0
        cmp.l   %d0,%d1
        blt     1b
9:      movem.l (%sp),%d0-%d3/%a0-%a1
        lea     24(%sp),%sp
        rts

| rp_gate_a: rp_gate_m on the Part block in a0 (d1 = track 0..7, d2 = machine 0 / 1) -> d0.
| Keeps all but d0.
rp_gate_a:
        lea     -16(%sp),%sp
        movem.l %d1/%d3/%a0-%a1,(%sp)   | rp_gate_m's own frame: its epilogue restores it
        jmp     (rp_gate_blk).l

| vgx_step: d1 = t, d7 / a2 / d6 as vgx_fix: the next Part's EMUS of track t becomes OT (stored
| 1). The current Part (d7 = 0): vg_step_ot (where EMUS lives now; the live byte only when the
| live bytes are this Part's, which they are not yet). Another Part (d7 = 1): the TSNS slot of
| its machine in that block, the SRAM copy (the working bank's four Parts: vgx_tick checked the
| bank) and that Part's dirty flags, as the swap writes them; never a live byte. Interrupts
| masked across the write (the frame hook's swaps write the DB too). Keeps every register.
vgx_step:
        lea     -24(%sp),%sp
        movem.l %d0-%d3/%a0-%a1,(%sp)
        move.w  %sr,%d2
        move.w  #0x2700,%sr
        tst.l   %d7
        bne     1f
        jsr     (vg_step_ot).l
        bra     9f
1:      movea.l %a2,%a0
        adda.l  #OFF_MACH,%a0
        moveq   #0,%d0
        move.b  0(%a0,%d1.l),%d0        | m (ST / FL: vgx_scan gave it an engine)
        mulu.w  #6,%d0
        move.l  %d1,%d3
        mulu.w  #30,%d3
        add.l   %d3,%d0
        addi.l  #OFF_P2+TSNS_SLOT2,%d0  | its TSNS slot: the EMUS
        moveq   #1,%d3                  | OT
        move.b  %d3,0(%a2,%d0.l)        | the Part
        move.l  #PART_STRIDE,%d1
        mulu.l  %d6,%d1
        add.l   %d1,%d0
        lea     (SHADOW_ADJ).l,%a0
        move.b  %d3,0(%a0,%d0.l)        | its SRAM copy
        movea.l (DB_PTR).l,%a1          | that Part's dirty flags (the swap's: BYTE masks, bset)
        movea.l %a1,%a0
        adda.l  #DIRTY_PARTS,%a0
        bset    %d6,(%a0)
        lea     (DIRTY_SRAM).l,%a0
        bset    %d6,(%a0)
        movea.l %a1,%a0
        adda.l  #DIRTY_DB2,%a0
        move.l  %d3,(%a0)
        lea     (DIRTY_GLOBAL).l,%a0
        move.l  %d3,(%a0)
9:      move.w  %d2,%sr
        movem.l (%sp),%d0-%d3/%a0-%a1
        lea     24(%sp),%sp
        rts

| the transition's working state (UI task only)
        .balign 2
vgx_pcl:                                | staging: the clamps, then the caps, published together
        .byte   0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0
vgx_oe:                                 | the engine each carried note runs (0: none / clamped)
        .byte   0, 0, 0, 0, 0, 0, 0, 0
vgx_olde_b:                             | the same before the decisions
        .byte   0, 0, 0, 0, 0, 0, 0, 0
vgx_ne:                                 | the next Part's engines as the decisions leave them
        .byte   0, 0, 0, 0, 0, 0, 0, 0
vgx_crt:                                | the tracks sure to trig on the new pattern's step 1
        .byte   0
vgx_any:                                | a decision is pending (the toast at the commit)
        .byte   0
        .balign 2

        .ifdef  VEM_UI_SECTION
        .text
        .endif

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

| d1 = track, d2 = machine (0 ST / 1 FL) -> d0 = the EMUS machine m's VM remembers off VARI, as
| the TSNS slot stores it (emus_stops; 0 = none: enters as OT). Keeps everything else.
db_park2:
        move.l  %a0,-(%sp)
        bsr     part_base
        move.l  %d1,%d0
        lsl.l   #2,%d0
        add.l   %d1,%d0
        add.l   %d2,%d0                 | 5t + m
        adda.l  #OFF_SLOT5+VM_ST,%a0
        mvz.b   0(%a0,%d0.l),%d0
        lsr.l   #4,%d0
        andi.l  #3,%d0                  | the stop + 1
        beq.s   1f
        lea     (emus_stops-1).l,%a0
        mvz.b   0(%a0,%d0.l),%d0
1:      movea.l (%sp)+,%a0
        rts
        .endif                          | VEM_EMUS: EMUS and the DSP load guard

        .ifdef  VEM_UI_SECTION          | VRG3: UI-task code, in the UI section (see THE UI SECTION)
        .section .vemui,"ax"
        .balign 2
        .endif
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
        bsr     vh_pgsave               | VRG3: VARISPEED's four bytes, kept across the paste
        move.l  24(%sp),-(%sp)
        move.l  24(%sp),-(%sp)
        move.l  24(%sp),-(%sp)
        move.l  24(%sp),-(%sp)
        move.l  24(%sp),-(%sp)
        move.l  24(%sp),-(%sp)
        jsr     vb_srcpaste
        lea     24(%sp),%sp
        bsr     vh_pgrest
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

| vh_pgsave / vh_pgrest (VRG3), around the SRC page paste 0x40027e4c(buf, part, t, page, midi), whose
| arguments they read at 12(sp)..: a paste writes one machine's twelve page bytes and its slot byte, so
| a THRU page also writes THRU page 1 slots 2 / 5 and THRU's slot byte, a NEIGHBOR page NEIGHBOR's slot
| byte -- VARISPEED's four bytes, which no page shows. They are kept across it, both copies (an UNDO of
| the paste comes through here too). A pasted STATIC / FLEX page brings that machine's twelve bytes from
| another track, so what VARISPEED kept for the old ones is cleared (VP_m, VM_m: a VARI page is then
| adopted as it is, rp_unent) -- unless the track is a BLKPYRAMD after the paste (its FLEX bytes are the
| voice's knobs; FLEX's pair belongs to the stashed FLEX, BLACKPYRAMIDS_303's page paste). A MIDI or
| other page, or nothing pasted (d0 = 0): only kept. Keep every register (d0 = the paste's result).
vh_pgsave:
        lea     -12(%sp),%sp
        movem.l %d0-%d1/%d3,(%sp)
        move.l  12+12(%sp),%d0          | part
        move.l  12+16(%sp),%d1          | t
        moveq   #0,%d3
        bsr     pgx
        movem.l (%sp),%d0-%d1/%d3
        lea     12(%sp),%sp
        rts
vh_pgrest:
        lea     -20(%sp),%sp
        movem.l %d0-%d3/%a0,(%sp)
        move.l  %d0,%d2                 | pasted?
        move.l  20+12(%sp),%d0
        move.l  20+16(%sp),%d1
        moveq   #1,%d3
        bsr     pgx                     | the four bytes back
        tst.l   %d2
        beq.s   9f
        tst.l   20+24(%sp)              | a MIDI page
        bne.s   9f
        tst.l   20+20(%sp)              | not SRC
        bne.s   9f
        movea.l 20+8(%sp),%a0
        moveq   #0,%d3
        move.b  19(%a0),%d3             | the pasted machine
        moveq   #1,%d2
        cmp.l   %d2,%d3
        bhi.s   9f                      | not STATIC / FLEX
        addq.l  #2,%d3
        bsr     pgx                     | its pair cleared
9:      movem.l (%sp),%d0-%d3/%a0
        lea     20(%sp),%sp
        rts
| pgx: d0 = part, d1 = t, d3 = 0 save VARISPEED's four bytes (vh_pgbuf) / 1 put them back / 2 + m clear
| machine m's pair (not on a BLKPYRAMD track); both copies. Nothing for another part or track. Keeps all.
pgx:
        lea     -32(%sp),%sp
        movem.l %d0-%d4/%a0-%a2,(%sp)
        moveq   #3,%d2
        cmp.l   %d2,%d0
        bhi     9f
        moveq   #7,%d2
        cmp.l   %d2,%d1
        bhi     9f
        move.l  #PART_STRIDE,%d2
        mulu.l  %d2,%d0
        movea.l (DB_PTR).l,%a0
        adda.l  %d0,%a0                 | the DB's block
        lea     (SHADOW_ADJ).l,%a1
        adda.l  %d0,%a1                 | its SRAM copy
        moveq   #2,%d2
        cmp.l   %d2,%d3
        blt.s   1f
        jsr     (rp_bpt).l
        tst.l   %d0
        bne     9f                      | a BLKPYRAMD track: FLEX's pair is the stashed FLEX's
1:      move.l  %d1,%d0
        mulu.w  #30,%d0
        addi.l  #OFF_P1+VP_ST,%d0       | d0 = VP_ST
        mulu.w  #5,%d1
        addi.l  #OFF_SLOT5+VM_ST,%d1    | d1 = VM_ST
        cmp.l   %d2,%d3
        blt.s   4f
        moveq   #3,%d2                  | clear: machine m = d3 - 2
        cmp.l   %d2,%d3
        bne.s   2f
        addq.l  #VP_FL-VP_ST,%d0
        addq.l  #VM_FL-VM_ST,%d1
2:      moveq   #0,%d2
        move.b  %d2,0(%a0,%d0.l)
        move.b  %d2,0(%a1,%d0.l)
        move.b  %d2,0(%a0,%d1.l)
        move.b  %d2,0(%a1,%d1.l)
        bra.s   9f
4:      lea     (vh_pgbuf).l,%a2
        bsr.s   5f                      | the DB's block
        movea.l %a1,%a0
        bsr.s   5f                      | its SRAM copy
9:      movem.l (%sp),%d0-%d4/%a0-%a2
        lea     32(%sp),%sp
        rts
5:      tst.l   %d3
        bne.s   6f
        move.b  0(%a0,%d0.l),%d4        | save
        move.b  %d4,(%a2)+
        move.b  VP_FL-VP_ST(%a0,%d0.l),%d4
        move.b  %d4,(%a2)+
        move.b  0(%a0,%d1.l),%d4
        move.b  %d4,(%a2)+
        move.b  VM_FL-VM_ST(%a0,%d1.l),%d4
        move.b  %d4,(%a2)+
        rts
6:      move.b  (%a2)+,%d4              | put back
        move.b  %d4,0(%a0,%d0.l)
        move.b  (%a2)+,%d4
        move.b  %d4,VP_FL-VP_ST(%a0,%d0.l)
        move.b  (%a2)+,%d4
        move.b  %d4,0(%a0,%d1.l)
        move.b  (%a2)+,%d4
        move.b  %d4,VM_FL-VM_ST(%a0,%d1.l)
        rts

        .ifdef  VEM_BP
| vh_bptake(part, t) / vh_bpback(part, t), C ABI (KYOTI V1.8BC: BLACKPYRAMIDS_303's ot_assign calls them,
| tools/ot303/cf/control.c KYOTI_VARI_TAKE / _BACK), once per Part copy (`part`: the Part as the voice sees
| it, the DB's or its SRAM copy). take: before the voice stashes FLEX and takes the track. Both machines'
| older NEIGHBOR park moves in first (rp_migrate: the voice is about to write NEIGHBOR's bytes); FLEX leaves
| VARI when its bytes are on it (PTCH back in the slot, QUAN remembered: the stash keeps FLEX as it is off
| VARI); a FLEX TSTR of VARI is remembered in VM bit 6 (the stash keeps TSTR in two bits). back: after FLEX
| is put back -- TSTR VARI again when it was (bit 6 cleared); the next poll enters VARI with the remembered
| QUAN. Both forget rp_prev: the next poll decides by the bytes. STATIC's bytes are not the voice's: kept.
vh_bptake:
        lea     -28(%sp),%sp
        movem.l %d2-%d7/%a2,(%sp)
        movea.l 32(%sp),%a0
        suba.l  #OFF_FX1,%a0            | the voice's Part -> VARISPEED's block (offsets from the blob)
        move.l  36(%sp),%d1
        movea.l %a0,%a1                 | one copy
        moveq   #0,%d2
1:      jsr     (rp_offs).l
        jsr     (rp_gate_a).l
        move.l  %d0,%d4
        jsr     (rp_migrate).l
        addq.l  #1,%d2
        moveq   #1,%d0
        cmp.l   %d0,%d2
        bls.s   1b
        moveq   #1,%d2                  | FLEX: its rp_offs and gate are the last pass's
        jsr     (rp_unent).l
        tst.l   %d0
        bne.s   3f                      | off VARI already
        moveq   #0,%d0
        move.b  (%a0,%d7.l),%d0
        subq.l  #4,%d0
        bpl.s   2f                      | PTCH parked
        tst.l   %d4                     | nothing kept under a QUAN stop: on VARI with the gate on
        beq.s   3f
2:      moveq   #0,%d4
        jsr     (rp_xfer).l                 | out of VARI, this copy
3:      movea.l %d6,%a2
        lea     OFF_P2-OFF_P1+TSTR_SLOT2(%a2),%a2
        moveq   #VARI,%d0
        cmp.b   (%a0,%a2.l),%d0
        bne.s   4f
        moveq   #0,%d0
        move.b  (%a0,%d5.l),%d0
        bset    #VM_BPV,%d0             | TSTR was VARI
        move.b  %d0,(%a0,%d5.l)
4:      jsr     (rp_forget).l
        movem.l (%sp),%d2-%d7/%a2
        lea     28(%sp),%sp
        rts
vh_bpback:
        lea     -16(%sp),%sp
        movem.l %d2/%d5-%d7,(%sp)
        movea.l 20(%sp),%a0
        suba.l  #OFF_FX1,%a0
        move.l  24(%sp),%d1
        moveq   #1,%d2
        jsr     (rp_offs).l
        moveq   #0,%d0
        move.b  (%a0,%d5.l),%d0
        bclr    #VM_BPV,%d0
        beq.s   1f                      | not taken on VARI
        move.b  %d0,(%a0,%d5.l)
        movea.l %d6,%a1
        lea     OFF_P2-OFF_P1+TSTR_SLOT2(%a1),%a1
        moveq   #VARI,%d0
        move.b  %d0,(%a0,%a1.l)         | FLEX's TSTR: VARI again
1:      jsr     (rp_forget).l
        movem.l (%sp),%d2/%d5-%d7
        lea     16(%sp),%sp
        rts
        .if VEM_EMUS == 0
| rp_gate_a: rp_gate_m on the Part block in a0 (d1 = track 0..7, d2 = machine 0 / 1) -> d0.
| Keeps all but d0. (VARISPEED_EMUS has its own, VEM11.)
rp_gate_a:
        lea     -16(%sp),%sp
        movem.l %d1/%d3/%a0-%a1,(%sp)   | rp_gate_m's own frame: its epilogue restores it
        jmp     (rp_gate_blk).l
        .endif
        .endif                          | VEM_BP

| RELOAD PART (stock 0x4004aab4(part)) copies the saved Part in and refreshes, through
| neither Part apply: the same hold/forget (16 bytes).
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
        lea     (vem_depth).l,%a0
        move.b  (%a0),%d1
        addq.l  #1,%d1
        move.b  %d1,(%a0)
        lea     (rp_prev).l,%a0
        move.l  #0xfefefefe,%d1
        move.l  %d1,(%a0)+
        move.l  %d1,(%a0)+
        move.l  %d1,(%a0)+
        move.l  %d1,(%a0)
        rts
vh_leave:
        lea     (vem_depth).l,%a0
        move.b  (%a0),%d1
        subq.l  #1,%d1
        bpl.s   1f
        moveq   #0,%d1
1:      move.b  %d1,(%a0)
        jmp     (rp_forget).l           | rts to our caller, d0 kept
        .ifdef  VEM_UI_SECTION
        .text
        .endif

| ============================================================================
| PART 2 -- RETAINED (VARISPEED_RETAINED.s), extended for VARISPEED_EMUS:
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
| sample's BPM x 24 in 720..7200; never on a BLKPYRAMD track (rp_bpt: its FLEX TSTR byte
| is the voice's VOL). Keeps everything but d0.
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
rp_gate_blk:                            | rp_gate_a's landing (VEM11, VRG3): a0 = the Part given
        bsr     rp_bpt
        tst.l   %d0
        bne     .gm_no                  | a BLKPYRAMD track (VRG3): never VARI
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
        cmp.b   (%a0),%d0               | forgotten? its first sight, Part bytes only (VARIG2:
        bne.s   2f                      |   it may still have to enter VARI)
        move.l  %d3,-(%sp)
        moveq   #0,%d3
        bsr     rp_swap_m
        move.l  (%sp)+,%d3
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
| live bytes + base word too). On a gate transition, swap BOTH pairs of machine m.
| VRG3 (2026-11-19): what VARISPEED keeps per machine lives in four bytes of the track's Part record
| that stock never edits or shows (VP_* / VM_* above; NOTES 2026-11-19 VRG3), no longer in NEIGHBOR's
| page bytes (BLACKPYRAMIDS_303 keeps its signature, stash and parked knobs there):
|   VP_m  on VARI: the PTCH the slot held (4..124, never below 4); else 0;
|   VM_m  off VARI: the remembered QUAN + 1 (bits 0-3; 0 none), [EMUS: the remembered EMUS stop
|         + 1 (bits 4-5)], bit 6 (FLEX): BLACKPYRAMIDS_303 took the track on VARI; on VARI:
|         [EMUS: the TSNS the slot held; VARISPEED: 0].
| Every value <= 127: stock's Part validator (every load) keeps them (VARIG2's bit-7 memory was
| zeroed by it).
|   PTCH (p1 slot 0) <-> VP: into VARI, QUAN is 1/1 unless VM remembers the QUAN of the track's
|     last exit from VARI; PTCH is parked, never below 4. Out of VARI, PTCH comes back (none
|     parked: PTCH 0) and QUAN is remembered in VM.
|   TSNS (p2 slot 5) <-> VM: into VARI, EMUS = the remembered one (none: OT), TSNS parked; out
|     of VARI, TSNS comes back verbatim, EMUS remembered.
|     (VARISPEED_EMUS only. VARISPEED swaps PTCH <-> QUAN alone: TSNS stays TSNS.)
| in the working DB and the SRAM part copy, with the writer's own dirty flags.
| rp_prev notices that something may have changed (first sight 0xff: after a Part apply, a bulk
| write, another Part; or a gate transition); the bytes then decide:
|   gate on:  PTCH parked (entered already: a missed poll) -> nothing moves; a transition -> the
|             entry; first sight -> rp_unent: nothing kept under a QUAN stop (a VARI page an SRC
|             page paste brought) is adopted, else the entry is made now.
|   gate off: PTCH parked -> the exit is made now (also on first sight: a gate that went off
|             while nothing polled the track); nothing kept under a QUAN stop on a transition
|             from on (that pasted VARI page) -> the exit, PTCH 0; else nothing moves.
| First sight also moves an older build's NEIGHBOR park in (rp_migrate). A BLKPYRAMD track
| (FLEX + 'O','T',1) is never touched, on either machine (rp_bpt: rp_gate_m reads 0, nothing
| moves, rp_prev stays). HOLD (a RELOAD or bulk write in progress) touches nothing. Returns
| d0 = domain<<1 | swapped. Keeps everything else.
rp_swap_m:
        lea     -36(%sp),%sp
        movem.l %d1-%d7/%a0-%a1,(%sp)
        bsr     rp_gate_m               | d0 = g (0 on a BLKPYRAMD track)
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
        mvs.b   (%a0),%d0               | current Part? (forgotten now if it was not)
        cmp.l   %d0,%d4
        beq     .sm_same
        moveq   #-2,%d5
        cmp.l   %d5,%d0
        beq     .sm_same                | HOLD: the Part is being written
        move.l  %d0,%d3                 | d3 = the byte before
        movea.l %a0,%a1                 | a1 -> rp_prev[2t + m]
        bsr     part_base               | a0 = the part's block
        bsr     rp_bpt
        tst.l   %d0
        bne     .sm_same                | a BLKPYRAMD track: VARISPEED keeps off it
        move.b  %d4,(%a1)
        moveq   #0,%d0
        move.b  (PART_B).l,%d0
        move.l  #PART_STRIDE,%d5
        mulu.l  %d5,%d0
        lea     (SHADOW_ADJ).l,%a1
        adda.l  %d0,%a1                 | a1 = the SRAM copy's block
        bsr     rp_offs                 | d5 = VM, d6 = PTCH slot, d7 = VP (offsets)
        moveq   #1,%d0
        cmp.l   %d0,%d3
        bls.s   1f                      | 0/1: a transition
        bsr     rp_migrate              | first sight: an older build's park moves in
1:      tst.l   %d4
        beq.s   2f
        moveq   #0,%d0                  | gate on: PTCH parked -- entered already
        move.b  (%a0,%d7.l),%d0
        subq.l  #4,%d0
        bpl     .sm_adopt
        moveq   #1,%d0
        cmp.l   %d0,%d3
        bls.s   .sm_move                | a transition: the entry
        bsr     rp_unent                | first sight: the bytes say (a pasted VARI page:
        tst.l   %d0                     |   nothing kept under a QUAN stop, adopted)
        beq     .sm_adopt
        bra.s   .sm_move
2:      moveq   #0,%d0                  | gate off: leave over a PTCH park
        move.b  (%a0,%d7.l),%d0
        subq.l  #4,%d0
        bpl.s   .sm_move
        moveq   #1,%d0                  | or, on a transition from on, a pasted VARI page
        cmp.l   %d0,%d3                 |   (nothing kept under a QUAN stop): PTCH 0
        bne     .sm_adopt
        bsr     rp_unent
        tst.l   %d0
        bne     .sm_adopt
.sm_move:
        bsr     rp_xfer                 | d3 = the new PTCH-slot value; EMUS: d0 = the new TSNS
        .if VEM_EMUS
        move.l  %d0,%d2                 | (m is no longer needed)
        .endif
        tst.l   4*2(%sp)                | the caller's d3: live?
        beq.s   3f
        move.l  %d1,%d0
        lsl.l   #3,%d0
        move.l  %d1,%d6
        lsl.l   #6,%d6
        add.l   %d6,%d0                 | 72t
        lea     (LIVE_P1).l,%a1
        move.b  %d3,(%a1,%d0.l)         | live PTCH-slot byte
        .if VEM_EMUS
        lea     (LIVE_P2+TSNS_SLOT2).l,%a1
        move.b  %d2,(%a1,%d0.l)         | live TSNS byte (page 2 has no base word)
        .endif
        | The BASE word, not the lane: the lane is rebuilt from it every frame.
        lea     (BASE_W).l,%a1
        move.l  %d3,%d0
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
        move.l  4(%sp),%d2              | m (the caller's)
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

| rp_offs: d1 = track, d2 = machine (0/1) -> d5 = VM_m, d6 = the PTCH slot, d7 = VP_m (offsets in a
| Part block). Keeps everything else.
rp_offs:
        moveq   #30,%d6
        mulu.l  %d1,%d6                 | 30t
        move.l  %d6,%d7
        addi.l  #OFF_P1+VP_ST,%d7
        tst.l   %d2
        beq.s   1f
        addq.l  #VP_FL-VP_ST,%d7
1:      move.l  %d2,%d5
        add.l   %d5,%d5
        add.l   %d2,%d5
        add.l   %d5,%d5                 | 6m
        add.l   %d5,%d6
        addi.l  #OFF_P1,%d6
        move.l  %d1,%d5
        lsl.l   #2,%d5
        add.l   %d1,%d5                 | 5t
        add.l   %d2,%d5
        addi.l  #OFF_SLOT5+VM_ST,%d5
        rts

| rp_xfer: the swap's byte moves. a0 = the Part block it reads and writes, a1 = a second copy it
| writes the same bytes to (a1 = a0: one copy), d4 = 1 into VARI / 0 out of it, d5 / d6 / d7 =
| rp_offs. -> d3 = the PTCH slot's new value; VARISPEED_EMUS: d0 = the TSNS slot's new value.
| Keeps everything else.
rp_xfer:
        lea     -12(%sp),%sp
        movem.l %d1-%d2/%a2,(%sp)
        moveq   #0,%d1
        move.b  (%a0,%d5.l),%d1         | d1 = VM
        moveq   #0,%d2
        move.b  (%a0,%d6.l),%d2         | d2 = the slot
        .if VEM_EMUS
        movea.l %d6,%a2
        lea     OFF_P2-OFF_P1+TSNS_SLOT2(%a2),%a2   | a2 = the TSNS slot (offset)
        .endif
        tst.l   %d4
        beq.s   .xf_out
| into VARI: QUAN = the remembered one (else 1/1), PTCH parked (never below 4)
        moveq   #VM_QUAN,%d3
        and.l   %d1,%d3
        beq.s   1f
        subq.l  #1,%d3
        mulu.w  #15,%d3
        addq.l  #4,%d3                  | its stop: 4 + 15 idx
        bra.s   2f
1:      moveq   #64,%d3                 | 1/1
2:      moveq   #4,%d0
        cmp.l   %d0,%d2
        bge.s   3f
        move.l  %d0,%d2
3:      move.b  %d2,(%a0,%d7.l)         | VP = PTCH
        move.b  %d2,(%a1,%d7.l)
        .if VEM_EMUS
        moveq   #0,%d2
        move.b  (%a0,%a2.l),%d2         | TSNS
        move.b  %d2,(%a0,%d5.l)         | VM = the TSNS, parked
        move.b  %d2,(%a1,%d5.l)
        lsr.l   #4,%d1
        moveq   #3,%d0
        and.l   %d1,%d0                 | the remembered EMUS stop + 1
        beq.s   4f
        lea     (emus_stops-1).l,%a2    | (a2 is the offset again below)
        move.b  (%a2,%d0.l),%d0
        bra.s   5f
4:      moveq   #1,%d0                  | none: OT
5:      movea.l %d6,%a2
        lea     OFF_P2-OFF_P1+TSNS_SLOT2(%a2),%a2
        move.b  %d0,(%a0,%a2.l)         | TSNS slot = EMUS
        move.b  %d0,(%a1,%a2.l)
        .else
        moveq   #0,%d0
        move.b  %d0,(%a0,%d5.l)         | VM: nothing on VARI
        move.b  %d0,(%a1,%d5.l)
        .endif
        bra.s   .xf_slot
| out of VARI: PTCH back (none parked: PTCH 0), QUAN remembered
.xf_out:
        moveq   #0,%d3
        move.b  (%a0,%d7.l),%d3         | VP
        moveq   #4,%d0
        cmp.l   %d0,%d3
        bge.s   1f
        moveq   #64,%d3                 | none parked: PTCH 0
1:      move.l  %d2,%d0
        bsr     rk_bucket
        addq.l  #1,%d0                  | the QUAN + 1
        .if VEM_EMUS
        move.l  %d0,%d2
        mvs.b   (%a0,%a2.l),%d0         | EMUS (the TSNS slot)
        bsr     emus_idx
        addq.l  #1,%d0
        lsl.l   #4,%d0
        or.l    %d0,%d2                 | + the EMUS stop + 1
        move.b  %d1,(%a0,%a2.l)         | TSNS back
        move.b  %d1,(%a1,%a2.l)
        move.l  %d1,-(%sp)
        move.l  %d2,%d0
        .endif
        move.b  %d0,(%a0,%d5.l)         | VM = remembered
        move.b  %d0,(%a1,%d5.l)
        moveq   #0,%d0
        move.b  %d0,(%a0,%d7.l)         | VP = 0
        move.b  %d0,(%a1,%d7.l)
        .if VEM_EMUS
        move.l  (%sp)+,%d0              | the TSNS slot's new value
        .endif
.xf_slot:
        move.b  %d3,(%a0,%d6.l)         | the PTCH slot
        move.b  %d3,(%a1,%d6.l)
        movem.l (%sp),%d1-%d2/%a2
        lea     12(%sp),%sp
        rts

| rp_unent: a0 = a Part block, d5 / d6 / d7 = rp_offs -> d0 = 1 when machine m's bytes are off
| VARI (an entry would move them): VM remembers a QUAN, or nothing is kept (VP below 4, VM's QUAN
| 0) and the slot holds no QUAN stop (4 + 15k: PTCH then). 0: on VARI -- PTCH parked (VP 4..127),
| or nothing kept under a QUAN stop (a VARI page an SRC page paste brought, PTCH 0 behind it).
| Keeps everything but d0.
rp_unent:
        moveq   #0,%d0
        move.b  (%a0,%d7.l),%d0         | VP
        subq.l  #4,%d0
        bpl.s   3f                      | PTCH parked
        moveq   #0,%d0
        move.b  (%a0,%d5.l),%d0         | VM
        andi.l  #VM_QUAN,%d0
        bne.s   2f                      | a remembered QUAN
        move.b  (%a0,%d6.l),%d0         | nothing kept: the slot
        subq.l  #4,%d0
        bmi.s   2f
1:      beq.s   3f                      | a QUAN stop
        subi.l  #15,%d0
        bpl.s   1b
2:      moveq   #1,%d0
        rts
3:      moveq   #0,%d0
        rts

| rp_bpt: d1 = track, a0 = a Part block -> d0 = 1 on a BLKPYRAMD track (BLACKPYRAMIDS_303: FLEX
| with 'O','T',1 in NEIGHBOR's page-1 bytes 0..2), else 0. Keeps everything else.
rp_bpt:
        lea     -8(%sp),%sp
        movem.l %d1/%a0,(%sp)
        adda.l  #OFF_MACH,%a0
        mvz.b   0(%a0,%d1.l),%d0
        subq.l  #1,%d0
        bne.s   1f                      | not FLEX
        mulu.w  #30,%d1
        adda.l  %d1,%a0                 | + 30t: NEIGHBOR page 1 at OFF_P1 - OFF_MACH + 18
        mvz.b   OFF_P1-OFF_MACH+OLD_P1(%a0),%d0
        cmpi.l  #0x4f,%d0                | 'O'
        bne.s   1f
        mvz.b   OFF_P1-OFF_MACH+OLD_P1+1(%a0),%d0
        cmpi.l  #0x54,%d0                | 'T'
        bne.s   1f
        mvz.b   OFF_P1-OFF_MACH+OLD_P1+2(%a0),%d0
        subq.l  #1,%d0
        bne.s   1f
        moveq   #1,%d0
        bra.s   2f
1:      moveq   #0,%d0
2:      movem.l (%sp),%d1/%a0
        lea     8(%sp),%sp
        rts

| rp_migrate: a0 / a1 = the Part block and its second copy, d1 = track, d2 = machine, d4 = its gate,
| d5 / d7 = rp_offs. The park an older build left in NEIGHBOR's page bytes (VARISPEED / VARISPEED_EMUS up
| to VRG2 / VEMG3, KYOTI up to V1.8BC: page 1 byte 0 STATIC's PTCH park, byte 5 FLEX's; VARISPEED_EMUS:
| page 2 byte 5 STATIC's TSNS park, byte 3 FLEX's) moves into VP_m / VM_m and is cleared there (both
| copies) -- only on a track whose NEIGHBOR bytes hold nothing but VARISPEED's: page 1 bytes 1-4 and page 2
| bytes 0-2 and 4 all 0. VARISPEED never wrote those eight; BLACKPYRAMIDS_303 writes all twelve (its
| signature, its stash and mark, or its own mark and parked knobs), so a track with any of them keeps
| NEIGHBOR's bytes as BLACKPYRAMIDS_303's -- but for byte 0 as STATIC's park when it is neither the voice's
| mark (0x50) nor its signature: there KYOTI V1.8BC FINAL wrote STATIC's park over the mark, which comes
| back (0x50, so the voice's parked knobs count again) as the park moves in. FLEX's byte 5 is the voice's
| stash or parked DEC then: not read. Gate on:
| a PTCH park 4..127 is the PTCH, parked (the bytes are on VARI) [EMUS: and the TSNS park]; gate off: an old
| park is no memory (VARIG2's rule) [EMUS: a parked EMUS is remembered]. VARISPEED moves only page 1's
| park; VARISPEED_EMUS both. Keeps everything.
rp_migrate:
        lea     -28(%sp),%sp
        movem.l %d0-%d3/%d6/%a2-%a3,(%sp)
        movea.l %a0,%a2
        moveq   #30,%d0
        mulu.l  %d1,%d0
        adda.l  %d0,%a2
        adda.l  #OFF_P1+OLD_P1,%a2      | a2 -> NEIGHBOR page 1, byte 0 (page 2 at + OLD_P2_AT)
        moveq   #0,%d0
        moveq   #4,%d3
1:      mvz.b   0(%a2,%d3.l),%d6        | page 1 bytes 4..1
        or.l    %d6,%d0
        subq.l  #1,%d3
        bne.s   1b
        mvz.b   OLD_P2_AT(%a2),%d6      | page 2 bytes 0, 1, 2, 4
        or.l    %d6,%d0
        mvz.b   OLD_P2_AT+1(%a2),%d6
        or.l    %d6,%d0
        mvz.b   OLD_P2_AT+2(%a2),%d6
        or.l    %d6,%d0
        mvz.b   OLD_P2_AT+4(%a2),%d6
        movea.l %a2,%a3
        suba.l  %a0,%a3
        adda.l  %a1,%a3                 | a3 = the same bytes in the second copy
        or.l    %d6,%d0
        beq.s   1f                      | VARISPEED's alone
        tst.l   %d2                     | BLACKPYRAMIDS_303's bytes beside it: only STATIC's park in
        bne     9f                      |   byte 0 is still known -- the voice writes nothing there but
        mvz.b   (%a2),%d3               |   its mark (0x50) or its signature; FLEX's byte 5 is its too
        beq     9f
        moveq   #0x50,%d0
        cmp.l   %d0,%d3
        beq     9f                      | the voice's mark
        cmpi.l  #0x4f,%d3
        bne.s   2f
        mvz.b   1(%a2),%d0
        cmpi.l  #0x54,%d0
        bne.s   2f
        mvz.b   2(%a2),%d0
        subq.l  #1,%d0
        beq     9f                      | the voice's signature
2:      moveq   #0x50,%d0               | V1.8BC FINAL wrote this park over the voice's mark: the mark
        move.b  %d0,(%a2)               |   back (its parked knobs follow it), the park moves in
        move.b  %d0,(%a3)
        moveq   #0,%d6
        bra.s   4f
1:      moveq   #OLD_PK1_ST,%d1
        tst.l   %d2
        beq.s   2f
        moveq   #OLD_PK1_FL,%d1
2:      mvz.b   0(%a2,%d1.l),%d3        | d3 = the old PTCH park
        clr.b   0(%a2,%d1.l)
        clr.b   0(%a3,%d1.l)
        moveq   #0,%d6
        .if VEM_EMUS
        move.l  #OLD_P2_AT+OLD_PK2_ST,%d1
        tst.l   %d2
        beq.s   3f
        move.l  #OLD_P2_AT+OLD_PK2_FL,%d1
3:      mvz.b   0(%a2,%d1.l),%d6        | d6 = the old TSNS park
        clr.b   0(%a2,%d1.l)
        clr.b   0(%a3,%d1.l)
        .endif
        move.l  %d3,%d0
        or.l    %d6,%d0
        beq     9f                      | nothing parked there
4:      tst.l   %d4
        beq.s   5f
        moveq   #4,%d0                  | gate on: a PTCH park 4..127 stays parked
        cmp.l   %d0,%d3
        blt.s   3f
        cmpi.l  #127,%d3
        ble.s   6f
3:      moveq   #0,%d3                  | none: nothing kept
        moveq   #0,%d6
        bra.s   6f
5:      moveq   #0,%d3                  | gate off: no memory, but a parked EMUS
        .if VEM_EMUS
        tst.l   %d6
        beq.s   6f
        move.l  %d6,%d0
        bsr     emus_idx
        addq.l  #1,%d0
        lsl.l   #4,%d0
        move.l  %d0,%d6
        .endif
6:      move.b  %d3,(%a0,%d7.l)         | VP_m
        move.b  %d3,(%a1,%d7.l)
        move.b  %d6,(%a0,%d5.l)         | VM_m
        move.b  %d6,(%a1,%d5.l)
9:      movem.l (%sp),%d0-%d3/%d6/%a2-%a3
        lea     28(%sp),%sp
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

        .ifdef  VEM_UI_SECTION          | VRG3: UI-task code, in the UI section (see THE UI SECTION)
        .section .vemui,"ax"
        .balign 2
        .endif
| Poll every track, both machines (UI task: the ATTR editor). A gate change of a
| machine that is not current (an ATTR edit of the sample the other machine plays)
| swaps that machine's Part bytes now, live bytes only for the current one. Keeps all.
rp_poll_all:
        lea     -20(%sp),%sp
        movem.l %d0-%d4,(%sp)
        move.w  %sr,%d4
        move.w  #0x2700,%sr
        moveq   #0,%d1
1:      jsr     (db_mach).l
        move.l  %d2,%d0                 | the current machine
        moveq   #0,%d2
2:      moveq   #0,%d3
        cmp.l   %d0,%d2
        bne.s   3f
        moveq   #1,%d3                  | live bytes for the current machine
3:      move.l  %d0,-(%sp)
        jsr     (rp_swap_m).l
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
        jsr     (rp_ui_gate).l
        tst.l   %d0
        bne.s   .qs_quan
        move.l  (%sp)+,%d1
        jmp     (STEP_PTCH).l
.qs_quan:
        move.l  %d2,-(%sp)
        move.l  20(%sp),%d0             | current (arg 3, two pushes deep)
        jsr     (rk_bucket).l               | -> zone 0..8
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
| dial, rebuilt with the fresh live byte when this very draw swapped. On VARI: a
| 9-position rotary switch (tools/ui_switch.s, Spectrum's LADR knob in 22.5-degree steps)
| on the value's QUAN stop, read out by quant_fmt; the stored value stays the stock
| editor's, so locks are untouched.
quant_widget:
        move.l  %d2,-(%sp)              | (args now 8..32)
        moveq   #0,%d1
        move.b  (UI_TRACK).l,%d1
        jsr     (db_mach).l
        moveq   #1,%d0
        cmp.l   %d0,%d2
        bls.s   1f
        move.l  (%sp)+,%d2
        jmp     (KNOB).l                | not ST/FL: stock, no poll
1:      jsr     (rp_swap_ui).l
        andi.l  #1,%d0
        movea.l %d0,%a1                 | the swap flag
        moveq   #72,%d0
        mulu.l  %d1,%d0
        lea     (LIVE_P1).l,%a0
        adda.l  %d0,%a0                 | -> this track's live PTCH byte
        jsr     (rp_gate_m).l
        jsr     (caption_m).l
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
        bmi.s   .qw_frame               | an empty cell keeps the bare frame (the dial's)
        move.l  %d0,%d1                 | quant_fmt reads the value
        jsr     (rk_bucket).l               | d0 = its stop 0..8
        move.l  (%sp)+,%d2
        .ifdef  UIS_SW9_AT
        jmp     (UIS_SW9_AT).l          | KYOTI: SIDECHAIN's ui_switch unit has it
        .else
        jmp     (sw9_draw).l
        .endif
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
        jsr     (rk_bucket).l
        lsl.l   #2,%d0
        lea     (q_labels).l,%a0
        adda.l  %d0,%a0
        move.l  %a0,8(%sp)
        jmp     (SPRINTF).l
.qf_unk:
        lea     (STR_UNK).l,%a0
        move.l  %a0,8(%sp)
        jmp     (SPRINTF).l

        .ifdef  VEM_UI_SECTION
        .text
        .endif

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
        .if VEM_EMUS
        moveq   #1,%d1                  | the guard: Parts were rewritten wholesale, so no
        move.b  %d1,(vg_bulk).l         |   single track can be named (vg_new)
        .endif
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
vh_pgbuf:                               | VRG3: VARISPEED's four bytes across an SRC page paste
        .byte   0, 0, 0, 0, 0, 0, 0, 0  |   (the DB's, then its SRAM copy's)
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
        .long   0, VG_S950, VG_SP12, VG_S950    | (3 is never stored; the kernel would run S950)
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
        .if VEM_EMUS == 0
vf_eng:                                 | the frame poll's verdict per track (1: QUAN on the
        .byte   0, 0, 0, 0, 0, 0, 0, 0  |   rendering machine), kept while a track is frozen
        .endif
        .if VEM_EMUS
vg_eng:                                 | vg_scan: the engine each track's settings run
        .byte   0, 0, 0, 0, 0, 0, 0, 0
vg_toast:                               | MAX DSP: EMU LIMIT is due (vg_tick raises it)
        .byte   0
vg_pend:                                | tracks noted off VARI before a TSTR / ATTR edit (bit t)
        .byte   0
vg_gon:                                 | vg_new: each track's gate at the last check (bit t)
        .byte   0
vg_bulk:                                | vg_new: Parts rewritten wholesale since (rp_forget)
        .byte   1
vg_pick:                                | vg_new: a slot pick's track (bit t), this message only
        .byte   0
        .balign 4
vg_key:                                 | vg_new: each track's key at the last check (vg_tkey)
        .long   0, 0, 0, 0, 0, 0, 0, 0
vgx_tgt:                                | VEM11: the incoming Part the decisions below are for
        .word   -1                      |   (bank << 8 | part; -1: none). Written by vgx_tick only
vgx_ovr:                                | its engine cap per track (0 none, 1 + the engine)
        .byte   0, 0, 0, 0, 0, 0, 0, 0
vgx_cl:                                 | the clamp per carried track (0 none, 1 + the engine)
        .byte   0, 0, 0, 0, 0, 0, 0, 0
vf_eng:                                 | VEM11: the frame poll's verdict per track (1: QUAN on
        .byte   0, 0, 0, 0, 0, 0, 0, 0  |   the rendering machine), kept through the window
        .endif

| QUAN's and EMUS's rotary switch: tools/ui_switch.s, shared with SIDECHAIN_COMPRESSOR
| (the builders put it on the include path; no clip_knob here, no sw3_draw without EMUS).
| UIS_SW9_AT (KYOTI, which also carries SIDECHAIN's ui_switch unit): its sw9_draw, and no
| copy here.
        .ifndef UIS_SW9_AT
        .equ    UIS_LOCAL, 1
        .equ    UIS_NO_CLIP, 1
        .if     VEM_EMUS == 0
        .equ    UIS_NO_SW3, 1
        .endif
        .include "ui_switch.s"
        .endif

        .balign 4
vem_end:
