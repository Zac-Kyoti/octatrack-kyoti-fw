; SPDX-License-Identifier: MIT
; SPDX-FileCopyrightText: 2026 Zac-Kyoti
; ===========================================================================
; repitch-kyoti rev 13 -- DSP side: the "virtual sampler" behind RPS9 / RPSP.
; Model (the ground truth this must match): tools/repitch_engine_model.py.
; Scope: reference/handoffs/REPITCH_FIDELITY_SCOPE.md. Plumbing: NOTES
; Session 110; rev 12/13: Session 111. Assembled by tools/dsp_xasm.py (NOT
; plain dsp_asm: this uses XY+ALU moves, movem, equ and dc, and every word is
; disassembled back and checked); tools/repitch_dsp_src.py prepends the
; constants and appends the tables, both generated from the model.
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
;   Y:STBASE + x:$418   per-track RPSP slot ($20 words): the render's residual
;                       ring (RINGW words, modulo-addressed, so it starts the
;                       slot), then the state (S_SIZE words in all)
;   Y:TABTAG            table tag; != TAGVAL => expand the tables (once/core)
;   Y:SPTAB, Y:R9TAB    the virtual-ADC tables, 32 phases each (12 / 16 taps),
;                       rebuilt from 9 stored rows each (zqexp)
;   Y:BTAB              the render's step table: (T[k], T[k+1]-T[k]) pairs
;
; RPSP is heard as the SP-1200's raw outputs 7/8 since rev 12: no output
; filter. Rev 13 renders its staircase through a band-limited kernel (the
; converter a real SP is recorded through), not rev 11/12's box.
;
; REGISTERS. Uses a, b, x0, x1, y0, y1, r1, r4, r6, r7, m1 and m7 (saved and
; restored), n1, n2, n4, n5, n6, n7; r5 is borrowed during an RPSP tick and
; restored. Leaves r0, r2, m6 alone; advances r3 by two words per output. m1
; is $7f only while r1 walks the ring: an XY dual move needs its X pointer in
; r0-r3, and the ring's own modulo register is m6.
; Hardware stack: at most bsr + two nested DOs below zqrp (as rev 11/12's
; FIR inside the output loop); zqinit's loops are not nested for that reason.
;
; LABELS: no label may be a prefix of another (dsp_asm's lookup). zq*.
; ===========================================================================

; ---- the RPSP slot (Y:STBASE + x:$418): ring 0..RINGW-1 (L,R interleaved,
; one frame per output, residuals / 4), then:
S_TAG   equ     RINGW+0
S_TAU   equ     RINGW+1 ; time of the next tick from the start of the next interval, Q20
S_PHI   equ     RINGW+2 ; accumulator fraction, Q24
S_HL    equ     RINGW+3 ; current staircase step, L
S_HR    equ     RINGW+4
S_PKF   equ     RINGW+5 ; previous output's ring frame (0..63)
S_PF    equ     RINGW+6 ; previous output's fraction, Q24
S_RW    equ     RINGW+7 ; the ring slot (absolute address) of the next output

zqrp:
        clr     a
        move    y:>$40,a1
        and     #<3,a                   ; (Z from a1; a2 and a0 are clear)
        beq     zqstk                   ; RPCH: stock, untouched
        move    a1,n1                   ; n1 = mode
        move    y:>TABTAG,a
        cmp     #>TAGVAL,a
        beq     zqtok
        bsr     zqinit                  ; first use on this core (or a new build)
zqtok:
        move    m1,n4                   ; restored at zqdone
        move    #$7f,m1
        move    #>$fff000,y1            ; the 12-bit mask, both modes
        move    n1,a
        cmp     #<2,a
        beq     zqsp

; ============================================================ RPS9 (Akai)
; output i = 12-bit(virtual ADC at p_i - c - 1): a 16-tap polyphase kernel over
; ring frames k_i-2c-1 .. k_i, all delivered. (NOT k_i+1: at a zero fraction
; the OT does not deliver it -- the stock kernel weights it 0. Measured.)
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
        bra     zqdone

; ============================================================ RPSP (SP-1200)
; The SP's clock period is 1.69 output samples, so an output interval holds at
; most one tick. A tick at u stores a new step; the render spreads the step
; (new - old) over this and the next L-1 outputs with the band-limited step
; response (the residual ring); output = current step + its ring slot.
zqsp:
        move    x:>$418,a
        add     #>STBASE,a
        move    a1,r4                   ; this track's slot
        move    #>TAGSP,x1
        move    y:(r4+S_TAG),b
        cmp     x1,b
        beq     zqsok
        clr     b                       ; stale or first use: clean ring + state
        move    r4,r6
        do      #S_SIZE,zqsz
        move    b,y:(r6)+
zqsz:
        move    x1,y:(r4+S_TAG)
        move    r4,y:(r4+S_RW)
        bra     zqsrs                   ; "previous output" = this pass's first
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
zqsrs:
        move    x:(r5),b
        asr     b
        move    b1,y:(r4+S_PKF)
        move    y:(r5),b
        move    b1,y:(r4+S_PF)
zqsnj:
        move    r7,n1                   ; the pass count (r7 becomes the ring pointer)
        move    m7,n7                   ; restored at zqoe
        move    #RINGM1,m7
        move    y:(r4+S_RW),r7
        do      n1,zqoe
        move    y:(r4+S_TAU),a
        move    #>$100000,x0
        cmp     x0,a
        blt     zqtk
        sub     x0,a                    ; no tick: the step holds
        move    a1,y:(r4+S_TAU)
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
        beq     zqri                    ; masks it too), measured in ot_emu
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
        lsl     #2,b                    ; x 12 taps = x4 + x8
        move    b1,x1
        lsl     #1,b
        add     x1,b
        add     #>SPTAB,b
        move    r5,n6                   ; r5 (this pass's table) is borrowed until zqbl
        move    b1,r5
        asl     a                       ; frames -> words
        and     #>$7e,a
        move    a1,n1
        move    r2,r1
        nop
        move    (r1)+n1
        nop
        clr     a       x:(r1)+,x0      y:(r5)+,y0
        clr     b       x:(r1)+,x1
        do      #SPNM1,zqsf
        mac     y0,x0,a x:(r1)+,x0
        mac     x1,y0,b x:(r1)+,x1      y:(r5)+,y0
zqsf:
        mac     y0,x0,a
        mac     x1,y0,b
        move    a,x0                    ; the new step, 12 bits
        move    x0,a
        and     y1,a
        move    b,x1
        move    x1,b
        and     y1,b
; ---- the step, halved (it can span 2.0), into the render
        move    y:(r4+S_HL),x0
        move    a1,y:(r4+S_HL)
        sub     x0,a
        asr     a
        move    a,y1                    ; (new - old)/2, L
        move    y:(r4+S_HR),x0
        move    b1,y:(r4+S_HR)
        sub     x0,b
        asr     b
        move    b,x1                    ; (new - old)/2, R
        move    n2,a                    ; u x R: the table's segment and fraction
        lsr     #18,a
        and     #<$3e,a                 ; 2 floor(uR): one (T, D) pair per segment
        add     #>BSTART,a              ; tap 0 reads segment (L-1)R + floor(uR)
        move    a1,r5
        move    n2,a
        lsl     #4,a
        and     #>$7fffff,a
        move    a1,y0                   ; frac(uR), Q23
        move    #>BSTRIDE,n5            ; each tap: R segments down, (T, D) pairs
        nop
        move    y:(r5)+,a               ; T
        move    y:(r5)+n5,x0            ; D
        do      #BL,zqbl
        mac     y0,x0,a y:(r7),b        ; a = weight/2 = T + frac D; b = ring L
        move    a,x0
        mac     x0,y1,b y:(r5)+,a       ; b += step/2 x weight/2; next T
        move    b,y:(r7)+
        move    y:(r7),b
        mac     x1,x0,b y:(r5)+n5,x0    ; ring R; next D
        move    b,y:(r7)+
zqbl:
        move    n6,r5
        move    #>$fff000,y1            ; the 12-bit mask again
; ---- out: the current step + what the render still owes this output
zqout:
        clr     b
        move    y:(r7),a
        asl     #2,a,a
        move    y:(r4+S_HL),x0
        add     x0,a    b,y:(r7)+       ; (the slot is spent)
        move    a,x:(r3)+
        move    y:(r7),a
        asl     #2,a,a
        move    y:(r4+S_HR),x0
        add     x0,a    b,y:(r7)+
        move    a,x:(r3)+
        move    x:(r5),a                ; this output becomes "previous"
        asr     a
        move    a1,y:(r4+S_PKF)
        move    y:(r5)+,a
        move    a1,y:(r4+S_PF)
zqoe:
        move    r7,y:(r4+S_RW)
        move    n7,m7

zqdone:
        move    n4,m1
        move    #$0,r7                  ; the stock kernel's `do r7` skips
zqstk:
        move    x:(r5),n6               ; displaced from the hook site
        move    y:(r5)+,a
        rts

; ---------------------------------------------------------------------------
; zqinit: expand the tables into Y (first use on a core, or a new build).
; Preserves r5 and r7 (hardware stack: one bsr and one DO below zqrp).
zqinit:
        move    r7,n2
        move    #>zqdsp,r1
        move    #>SPTAB,r4
        move    #>SPN,n4
        bsr     zqexp
        move    #>R9TAB,r4              ; r1 is at zqdr9: it follows zqdsp
        move    #>R9N,n4
        bsr     zqexp
        move    #>BTAB,r4               ; ... and zqdbl follows zqdr9
        move    #>BEND,r7
        move    #<2,n4
        move    #<2,n7
        move    #>$c00000,y0            ; -1/2
        do      #BHALF,zqi1             ; T[k] stored for k = 0..LR/2; T[LR-k] = -1/2 - T[k]
        movem   p:(r1)+,x0
        move    x0,y:(r4)+n4
        move    y0,a
        sub     x0,a
        move    a1,y:(r7)-n7
zqi1:
        move    #>BTAB,r4               ; D[k] = T[k+1] - T[k], beside T[k]
        move    #<1,n4
        do      #BPAIRS,zqi2
        move    y:(r4)+,x0
        move    y:(r4+n4),a
        sub     x0,a
        move    a1,y:(r4)+
zqi2:
        move    #>TAGVAL,x0
        move    x0,y:>TABTAG
        move    n2,r7
        rts

; zqexp: one virtual-ADC table from its 9 stored rows (0,2,..,14 then 15).
; in: r1 -> P rows (left just past them), r4 = row 0, n4 = taps N.
; 1) the stored rows into place; 2) each odd row 1..13 = the floor of its
; neighbours' mean; 3) rows 16..31 = rows 15..0 reversed (one backward copy).
; tools/repitch_engine_model.fir_q23 builds the table exactly this way.
; Outer loops count in b, not DO: see the stack note in the header.
zqexp:
        move    r4,n6                   ; row 0
        move    #>8,b                   ; (a short #imm to an accumulator is left-aligned)
zqe1:
        do      n4,zqe2                 ; rows 0,2,..,14: copy, skip one
        movem   p:(r1)+,x0
        move    x0,y:(r4)+
zqe2:
        move    (r4)+n4
        sub     #<1,b
        bne     zqe1
        move    (r4)-n4                 ; row 15
        do      n4,zqe3
        movem   p:(r1)+,x0
        move    x0,y:(r4)+
zqe3:
        move    n6,r7                   ; row ph-1
        move    n6,r4
        move    n4,n7
        nop
        move    (r4)+n4                 ; row ph (from 1); row ph+1 is at +N
        move    #>7,b
zqe4:
        do      n4,zqe5
        move    y:(r4+n4),a
        move    y:(r7)+,x0
        add     x0,a
        asr     a
        move    a1,y:(r4)+
zqe5:
        move    (r7)+n7
        move    (r4)+n4
        sub     #<1,b
        bne     zqe4
        move    n4,a
        asl     #4,a,a
        move    a1,n5                   ; 16N words
        move    n6,x0
        add     x0,a
        move    a1,r4                   ; row 16, going up
        move    a1,r7
        nop
        move    (r7)-                   ; row 15's last word, going down
        do      n5,zqe6
        move    y:(r7)-,x0
        move    x0,y:(r4)+
zqe6:
        rts
