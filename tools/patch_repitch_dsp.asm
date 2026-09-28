; SPDX-License-Identifier: MIT
; SPDX-FileCopyrightText: 2026 Zac-Kyoti
; ===========================================================================
; repitch-kyoti rev 11 -- DSP side: the "virtual sampler" behind RPS9 / RPSP.
; Model (the ground truth this must match): tools/repitch_engine_model.py.
; Scope: reference/handoffs/REPITCH_FIDELITY_SCOPE.md. Plumbing: NOTES
; Session 110. Assembled by tools/dsp_xasm.py (NOT plain dsp_asm: this uses
; XY+ALU moves, movem, equ and dc, and every word is disassembled back and
; checked); tools/repitch_dsp_src.py prepends the constants and appends the
; tables, both generated from the model.
;
; WHERE IT RUNS. Unchanged from rev 10: the stock voice engine (payload A
; P:0x3a1, B P:0x1a4) is detoured at its kernel prologue (A P:0x40b, B
; P:0x20e): `move x:(r5),n6 / move y:(r5)+,a` becomes `bsr zqrp`, and both
; moves run at this routine's tail. For RPCH nothing else happens and the stock
; kernel runs. For RPS9/RPSP this routine writes the pass's output samples
; itself and sets r7 = 0, so the stock `do r7` skips (the DSP56300 skips a DO
; whose count is 0 -- stock relies on that for its own empty passes, measured).
;
; STATE ON ENTRY (measured in ot_emu against the real firmware):
;   r5  = table: x:(r5+i) = ring word offset of output i's frame (even),
;         y:(r5+i) = its fraction (Q24, unsigned)
;   r7  = outputs in this pass (0..16; the passes of a frame add up to 16)
;   r3  = output pointer (x, 2 words per output), r2 = ring base (128-aligned
;         64-frame stereo ring, continuous across passes and frames)
;   r0  = the record pointer (live -- untouched), m6 = $7f
;   l:$40 = the increment r: x:$40 integer part, y:$40 fraction; the mode is
;         in y:$40 bits 0-1 (tools/patch_repitch_kyoti.s, rate_hook)
;   x:$418 = this track's offset in the core's 4-track loop (0,$20,$40,$60)
;
; MEMORY (Y:$795..$FFF is free on stock on both cores -- octabam, measured on
; hardware; SIDECHAIN3 takes $800-$9ff):
;   Y:STBASE + x:$418   per-track RPSP state (24 words)
;   Y:TABTAG            table tag; != TAGVAL => expand the tables (once/core)
;   Y:SPTAB, Y:R9TAB    the virtual-ADC tables, 32 phases each
;   X:PCOEF             the SP output filter's coefficients, copied per pass
;                       (X:$20-$ff is stock's per-call scratch)
;
; REGISTERS. Uses a, b, x0, x1, y0, y1, r1, r4, r6, r7, m1 (saved and
; restored), n1, n2, n4, n5, n7. Leaves r0, r2, m6 alone; advances r3 by two
; words per output. m1 is $7f only while r1 walks the ring: an XY dual move
; needs its X pointer in r0-r3, and the ring's own modulo register is m6.
;
; LABELS: no label may be a prefix of another (dsp_asm's lookup). zq*.
; ===========================================================================

; ---- state block offsets (Y:STBASE + x:$418)
S_TAG   equ     0
S_TAU   equ     1       ; SP: time of the next tick from the start of the next interval, Q20
S_PHI   equ     2       ; SP: accumulator fraction, Q24
S_HL    equ     3       ; SP: current staircase step, L
S_HR    equ     4
S_PKF   equ     5       ; SP: previous output's ring frame (0..63)
S_PF    equ     6       ; SP: previous output's fraction, Q24
S_POSTL equ     7       ; SP: output filter state, L (4 words)
S_POSTR equ     11      ; SP: output filter state, R (4 words)
S_SIZE  equ     15
S_DPOST equ     S_POSTR-S_POSTL

zqrp:
        clr     a
        move    y:>$40,a1
        and     #<3,a
        tst     a
        beq     zqstk                   ; RPCH: stock, untouched
        move    a1,n1                   ; n1 = mode
        move    y:>TABTAG,a
        cmp     #>TAGVAL,a
        beq     zqtok
        bsr     zqinit                  ; first use on this core (or a new build)
zqtok:
        move    n1,a
        cmp     #<2,a
        beq     zqsp

; ============================================================ RPS9 (Akai)
; output i = 12-bit(virtual ADC at p_i - c - 1): a 16-tap polyphase kernel over
; ring frames k_i-2c-1 .. k_i, all delivered. (NOT k_i+1: at a zero fraction
; the OT does not deliver it -- the stock kernel weights it 0. Measured.)
        move    m1,n4
        move    #$7f,m1
        move    #>$fff000,y1
        do      r7,zq9e
        move    x:(r5),a                ; a1 = ring word offset of k_i
        sub     #<R9SW,a                ; first tap = k_i - 2c - 1 frames
        and     #>$7e,a
        move    a1,n1
        move    y:(r5)+,b               ; b1 = fraction
        lsr     #19,b                   ; phase 0..31
        lsl     #4,b                    ; x 16 taps
        add     #>R9TAB,b
        move    r2,r1
        move    b1,r7                   ; the phase's row (the loop count is in LC now)
        nop
        move    (r1)+n1                 ; modulo 128 under m1
        nop
        clr     a       x:(r1)+,x0      y:(r7)+,y0
        clr     b       x:(r1)+,x1
        do      #R9NM1,zq9f
        mac     y0,x0,a x:(r1)+,x0
        mac     x1,y0,b x:(r1)+,x1      y:(r7)+,y0
zq9f:
        mac     y0,x0,a
        mac     x1,y0,b
        move    a,x0                    ; limit
        move    x0,a
        and     y1,a                    ; 12 bits: floor to a 1/2048 step
        move    a1,x:(r3)+
        move    b,x0
        move    x0,b
        and     y1,b
        move    b1,x:(r3)+
zq9e:
        move    n4,m1
        bra     zqdone

; ============================================================ RPSP (SP-1200)
; Output i is the staircase averaged over [i-1, i). The SP's clock period is
; 1.69 output samples, so an interval holds at most one tick: at u the step
; changes from old to new and the average is new + u*(old - new).
zqsp:
        move    x:>$418,x0
        move    #>STBASE,a
        add     x0,a
        move    a1,r4                   ; this track's state block
        add     #<S_POSTL,a
        move    a1,n5                   ; its output filter state, L
        add     #<S_DPOST,a
        move    a1,n7                   ; ... and R
        move    y:(r4),b
        move    #>TAGSP,x1
        cmp     x1,b
        beq     zqsok
        clr     b                       ; stale or first use: clean state
        move    r4,r6
        do      #S_SIZE,zqsz
        move    b,y:(r6)+
zqsz:
        move    x1,y:(r4)
        move    x:(r5),b                ; "previous output" = this pass's first
        asr     b
        move    b1,y:(r4+S_PKF)
        move    y:(r5),b
        move    b1,y:(r4+S_PF)
zqsok:
        move    x:(r5),a                ; resync "previous" if this pass does not
        asr     a                       ; continue it: ring positions advance
        move    y:(r4+S_PKF),x0         ; continuously through trigs (measured),
        sub     x0,a                    ; so a jump of more than 2 frames means
        and     #<$3f,a                 ; the state is stale (the track has been
        move    a1,x0                   ; in another mode meanwhile)
        move    x0,a
        cmp     #<2,a
        ble     zqsnj
        move    x:(r5),b
        asr     b
        move    b1,y:(r4+S_PKF)
        move    y:(r5),b
        move    b1,y:(r4+S_PF)
zqsnj:
        move    #>zqdpc,r1              ; the output filter's coefficients -> X
        move    #>PCOEF,r6
        do      #PCN,zqsc
        movem   p:(r1)+,x0
        move    x0,x:(r6)+
zqsc:
        move    m1,n4
        move    #$7f,m1
        do      r7,zqoe
        move    y:(r4+S_TAU),a
        move    #>$100000,x0
        cmp     x0,a
        blt     zqtk
        sub     x0,a                    ; no tick: the step holds
        move    a1,y:(r4+S_TAU)
        move    y:(r4+S_HL),a
        move    y:(r4+S_HR),b
        bra     zqout
zqtk:
        asl     #3,a,a
        move    a1,n2                   ; u, Q23 (kept out of the FIR's registers)
        move    a1,x0
        lsr     #3,a                    ; tau += PSP - 1 interval
        add     #>PSPM1,a
        move    a1,y:(r4+S_TAU)
        move    y:(r4+S_PHI),a          ; phi = frac(phi + r)
        move    y:>$40,y0
        add     y0,a
        move    a1,y:(r4+S_PHI)
        lsr     a                       ; Q24 phi >> 1 = the same phi as Q23
        move    a1,y0
        move    #>PSPH,x1
        mpy     x1,y0,b                 ; (PSP/2)*phi = PSP*phi * 2^46
        asr     #22,b,b                 ; -> frames, 24.24
        move    y:>$40,a
        lsr     a
        move    a1,y0                   ; frac(r) as Q23 (the dropped LSB is the mode tag's)
        mpy     y0,x0,a                 ; u*frac(r) * 2^47
        asr     #23,a,a                 ; -> frames, 24.24
        sub     b,a
        move    x:>$40,b                ; + u*int(r) (0 or 1): only bit 0 -- on the unit
        and     #<1,b                   ; x:$40 reads $c1 at 1.0x (the table builder
        tst     b                       ; masks it too), measured in ot_emu
        beq     zqri
        clr     b
        move    x0,b0
        asl     b
        add     b,a
zqri:
        clr     b                       ; + the previous output's position
        move    y:(r4+S_PF),b0
        move    y:(r4+S_PKF),b1
        add     b,a
        sub     #<SPC2,a                ; first tap = floor(pos) - 2c - 1
        move    a0,b
        lsr     #19,b                   ; phase 0..31
        lsl     #3,b                    ; x 8 taps
        add     #>SPTAB,b
        move    b1,r7
        asl     a                       ; frames -> words
        and     #>$7e,a
        move    a1,n1
        move    r2,r1
        nop
        move    (r1)+n1
        nop
        clr     a       x:(r1)+,x0      y:(r7)+,y0
        clr     b       x:(r1)+,x1
        do      #SPNM1,zqsf
        mac     y0,x0,a x:(r1)+,x0
        mac     x1,y0,b x:(r1)+,x1      y:(r7)+,y0
zqsf:
        mac     y0,x0,a
        mac     x1,y0,b
        move    #>$fff000,y1
        move    a,x0                    ; the new step, 12 bits
        move    x0,a
        and     y1,a
        move    b,x1
        move    x1,b
        and     y1,b
        move    n2,x0                   ; u
        move    y:(r4+S_HL),y0          ; old L
        move    a1,y:(r4+S_HL)
        move    a1,x1
        mac     y0,x0,a                 ; new + u*old
        mac     -x1,x0,a                ;     - u*new
        move    y:(r4+S_HR),y0          ; old R
        move    b1,y:(r4+S_HR)
        move    b1,x1
        mac     y0,x0,b
        mac     -x1,x0,b
; ---- the output channel's filter, then out
zqout:
        move    n5,r6
        move    #>PCOEF,r1
        bsr     zqpost
        move    a,x:(r3)+
        move    b,a
        move    n7,r6
        move    #>PCOEF,r1
        bsr     zqpost
        move    a,x:(r3)+
        move    x:(r5),a                ; this output becomes "previous"
        asr     a
        move    a1,y:(r4+S_PKF)
        move    y:(r5)+,a
        move    a1,y:(r4+S_PF)
zqoe:
        move    n4,m1

zqdone:
        move    #$0,r7                  ; the stock kernel's `do r7` skips
zqstk:
        move    x:(r5),n6               ; displaced from the hook site
        move    y:(r5)+,a
        rts

; ---------------------------------------------------------------------------
; zqpost: the SP output channel's filter, one channel, one sample.
; in: a = input; r1 -> X coefficients (b0/2, -a1/2) the real pole with its
; zero at Nyquist, then (b0/2, -a1/2, -a2/2) the all-pole pair (run second:
; it peaks ~1.7x near 10 kHz, and first it would clip before being tamed);
; r6 -> Y state (x1, y1, y1, y2). out: a. b untouched. Coefficients are
; halved (|a1| can exceed 1) and each section's result doubled with asl.
zqpost:
        move    a,x0                                    ; section 1: b0(x + x1) - a1 y1
        move    x:(r1)+,x1      y:(r6)+,y0              ; b0/2, x1
        mpy     x1,x0,a         y:(r6)-,y1              ; y1
        mac     x1,y0,a         x:(r1)+,x1              ; -a1/2
        mac     y1,x1,a
        asl     a
        move    x0,y:(r6)+
        move    a,x0
        move    x0,y:(r6)+
        move    x:(r1)+,x1      y:(r6)+,y0              ; section 2: all-pole; b0/2, y1
        mpy     x1,x0,a         x:(r1)+,x1      y:(r6)-,y1      ; -a1/2, y2
        mac     x1,y0,a         x:(r1)+,x1              ; -a2/2
        mac     y1,x1,a
        asl     a
        move    a,x0
        move    x0,y:(r6)+
        move    y0,y:(r6)+
        move    x0,a
        rts

; ---------------------------------------------------------------------------
; zqinit: expand both virtual-ADC tables into Y from their stored halves.
; Row 31-ph is row ph reversed, so one forward pass writes row ph going up
; and its mirror going down from the table's end. Preserves r5, r7.
zqinit:
        move    r7,n2
        move    #>zqdsp,r1
        move    #>SPTAB,r4
        move    #>SPEND,r7
        do      #SPHALF,zqi1
        movem   p:(r1)+,x0
        move    x0,y:(r4)+
        move    x0,y:(r7)-
zqi1:
        move    #>zqdr9,r1
        move    #>R9TAB,r4
        move    #>R9END,r7
        do      #R9HALF,zqi2
        movem   p:(r1)+,x0
        move    x0,y:(r4)+
        move    x0,y:(r7)-
zqi2:
        move    #>TAGVAL,x0
        move    x0,y:>TABTAG
        move    n2,r7
        rts
