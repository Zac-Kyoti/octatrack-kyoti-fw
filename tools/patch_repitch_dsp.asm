; SPDX-License-Identifier: MIT
; SPDX-FileCopyrightText: 2026 Zac-Kyoti
; ===========================================================================
; repitch-kyoti rev 14 -- DSP side: the "virtual sampler" behind RPS9 / RPSP.
; Model (the ground truth this must match): tools/repitch_engine_model.py.
; Scope: reference/handoffs/REPITCH_FIDELITY_SCOPE.md and REPITCH_SP_CH12_SCOPE.md.
; Plumbing: NOTES Session 110; rev 12/13: Session 111; rev 14: Session 112.
; Assembled by tools/dsp_xasm.py (NOT plain dsp_asm: this uses XY+ALU moves,
; equ and dc, and every word is disassembled back and checked);
; tools/repitch_dsp_src.py prepends the constants (and drops the ;+CH12 ..
; ;-CH12 blocks for the raw 7/8 build) -- the table DATA lives in X memory
; since rev 14 (SPRING REVERB's own X tables, rewritten by the builder).
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
;   r7  = outputs in this pass (0..16; the two passes of a frame add up to 16)
;   r3  = output pointer (x, 2 words per output), r2 = ring base (128-aligned
;         64-frame stereo ring)
;   r0  = the record pointer (live -- untouched), m6 = $7f
;   l:$40 = the increment r: x:$40 integer part, y:$40 fraction; the mode is
;         in y:$40 bits 0-1 (tools/patch_repitch_kyoti.s, rate_hook)
;   x:$418 = this track's offset in the core's 4-track loop (0,$20,$40,$60)
;   x:$419 = this track's unpacked per-voice record (set before the voice
;         module): word +$1E bit 12 = a trig starts in this frame (the driver
;         clears it after the frame), bits 8-11 = its sample offset
;   x:$20a = this track's AMP stage state (X:$6000 + $300 x track); +8 = its
;         level at the end of the last frame, linear Q23 (the AMP stage runs
;         after the voice module)
; Every frame runs this hook twice (the voice module's `do #2`); on a trig
; frame the first visit is the old sound's tail, the second starts the new one.
;
; MEMORY (Y:$795..$FFF is free on stock on both cores -- octabam, measured on
; hardware; SIDECHAIN3 takes $800-$9ff):
;   Y:STBASE + x:$418   per-track RPSP slot ($20 words): the render's residual
;                       ring (RINGW words, modulo-addressed, so it starts the
;                       slot), then the state (S_SIZE words in all)
;   Y:TABTAG            table tag; != TAGVAL => copy the tables in (once/core)
;   Y:SPTAB, Y:R9TAB    the virtual-ADC tables, 32 phases each (12 / 16 taps),
;                       from their 16 stored half-rows in X (rows 16-31 mirror)
;   Y:BTAB              the render's step table: (T[k], T[k+1]-T[k]) pairs
;   Y:FBASE + x:$418/2  per-track aux block: the trig parity, and channel 1/2's
;                       envelope, coefficients and filter state
;   X:GTAB              channel 1/2's cutoff table (read in place)
;
; REGISTERS. Uses a, b, x0, x1, y0, y1, r1, r4, r6, r7, m1 and m7 (saved and
; restored), n1, n2, n4, n5, n6, n7; r5 is borrowed during an RPSP tick and
; restored. Leaves r0, r2, m6 alone; advances r3 by two words per output. m1
; is $7f from zqtok on: an XY dual move needs its X pointer in r0-r3, and the
; ring's own modulo register is m6. So every other walk uses r4 (m4 linear:
; rev 11-13 walked it across whole tables on the unit) -- r1 under $7f wraps
; at a 128-word boundary (rev 14's first cutoff table did, on payload A only).
; Hardware stack: at most bsr + two nested DOs below zqrp (as rev 11-13).
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
STTAG   equ     STBASE+S_TAG
; ---- the aux block (Y:FBASE + x:$418/2)
A_VIS   equ     0       ; $1000 after the first visit of a trig frame, else 0
A_ENV   equ     1       ; channel 1/2: the capacitor (env, Q23)
A_G     equ     2       ; this pass's stage coefficient g
A_G1    equ     3       ; ... and 1 - g
A_ST    equ     4       ; the 4-pole's state: L 0..3, R 0..3

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
; ---- a trig (rev 14). The engines read the ring BEHIND the OT's position, and
; at a trig the frames behind the new sound hold stale audio (the last voice's,
; unscaled -- its AMP silenced it later in the chain). Stock reads only floor(p)
; and floor(p)+1; RPS9/RPSP would replay 8-13 frames of it at the new trig's
; full AMP: the crack at every trig start (user, rev 13; measured in ot_emu).
; So at the pass that starts the new sound, the 16 frames before its first
; frame become silence, and RPSP's slot starts clean (tag cleared: zqsp).
        move    x:>$418,a
        move    a1,n6                   ; the track offset
        asr     a
        add     #>FBASE,a
        move    a1,r6                   ; this track's aux block (m6 = $7f: the
        move    x:>$419,r4              ; blocks never straddle 128 words, asserted)
        move    #$7f,m1                 ; (not for r4's reads: its m4 is linear --
        clr     a                       ; x:$419 + $1E can straddle a 128-word block)
        move    x:(r4+$1e),a1           ; this track's unpacked per-voice word +$1E
        and     #>$1000,a               ; a trig starts in this frame?
        beq     zqnh
        move    y:(r6+A_VIS),x0
        eor     x0,a                    ; the first visit leaves $1000, the second 0
        bne     zqnh
        move    x:(r5),a                ; the new sound's first frame (ring word offset)
        sub     #<32,a
        and     #>$7e,a
        move    r2,x0
        add     x0,a                    ; (r2 is 128-aligned: r1 stays in the ring,
        move    a1,r1                   ;  and m1 = $7f wraps it)
        clr     a
        rep     #<32
        move    a,x:(r1)+
        move    n6,b
        add     #>STTAG,b
        move    b1,r1
        nop
        move    a,y:(r1)                ; RPSP: a clean slot at zqsp
zqnh:
        move    a1,y:(r6+A_VIS)
        move    #>$fff000,y1            ; the 12-bit mask (RPS9; RPSP reloads it)
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
; response (the residual ring); output = current step + its ring slot. Rev 14:
; then channel 1/2 (;+CH12 blocks): an SSM2044-style 4-pole, resonance 0,
; whose cutoff the OT's own AMP level pushes open through the SP's diode + RC.
zqsp:
;+CH12
; ---- channel 1/2: this visit's cutoff (every visit: two per frame). The SP's cutoff CV is its channel GAIN
; through a diode into 10 uF: it follows a rising level at once and falls no
; faster than the capacitor discharges. The OT's AMP level is that GAIN.
        move    x:>$20a,r4              ; this track's AMP stage (r4: m4 is linear;
        nop                             ;  under m1's $7f a table walk would wrap)
        move    x:(r4+8),b              ; its level (end of the last frame)
        move    y:(r6+A_ENV),x0
        move    #>DEC8,y0               ; the discharge over half a frame (a visit)
        mpy     y0,x0,a
        max     a,b                     ; the diode
        move    b,y:(r6+A_ENV)
        move    b1,a
        lsr     #17,b
        and     #>$3e,b                 ; env x 32: one (G, D) pair per 1/8 octave
        add     #>GTAB,b
        move    b1,r4
        lsl     #5,a
        and     #>$7fffff,a
        move    a1,y1                   ; the fraction between pairs, Q23
        move    x:(r4)+,a               ; G
        move    x:(r4),x0               ; D
        mac     x0,y1,a                 ; g = G + frac x D
        move    a,y:(r6+A_G)
        move    a,x1
        move    #>$7fffff,a
        sub     x1,a
        move    a1,y:(r6+A_G1)          ; 1 - g (one LSB short: unity DC to 2^-21)
;-CH12
        move    r7,b                    ; an empty visit (a frame's first pass, as a
        tst     b                       ; rule): nothing to render, and x:(r5) is not
        beq     zqdone                  ; this track's -- the slot waits for a real pass
        move    n6,a
        add     #>STBASE,a
        move    a1,r4                   ; this track's slot
        move    #>TAGSP,x1
        move    y:(r4+S_TAG),b
        cmp     x1,b
        beq     zqsok
        clr     b                       ; stale, first use or a trig: clean ring + state
        move    r4,r1
        do      #S_SIZE,zqsz
        move    b,y:(r1)+
zqsz:
        lua     (r6+A_ST),r1            ; ... and the 4-pole's state (the capacitor
        nop                             ; keeps its charge: any Q23 value is in range)
        rep     #<8
        move    b,y:(r1)+
        move    x1,y:(r4+S_TAG)
        move    r4,y:(r4+S_RW)
        bra     zqsrs                   ; "previous output" = this pass's first
zqsok:
        move    x:(r5),a                ; resync "previous" if this pass does not
        asr     a                       ; continue it: ring positions advance
        move    y:(r4+S_PKF),x0         ; continuously while a sound plays, so a
        sub     x0,a                    ; jump of more than 2 frames means the
        and     #<$3f,a                 ; state is stale (the track has been in
        move    a1,x0                   ; another mode meanwhile)
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
        move    #>$fff000,y1            ; the 12-bit mask (channel 1/2 used y1)
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
;+CH12
; ---- channel 1/2: four one-pole stages per channel, y += g (x - y) written as
; g x + (1 - g) y (no intermediate can leave [-1, 1)), in place on the output
        move    (r3)-
        move    (r3)-
        move    y:(r6+A_G),y0
        move    y:(r6+A_G1),x1
        lua     (r6+A_ST),r1
        do      #2,zqcf
        move    x:(r3),x0
        mpy     y0,x0,a y:(r1),y1
        mac     y1,x1,a
        move    a,x0
        move    x0,y:(r1)+
        mpy     y0,x0,a y:(r1),y1
        mac     y1,x1,a
        move    a,x0
        move    x0,y:(r1)+
        mpy     y0,x0,a y:(r1),y1
        mac     y1,x1,a
        move    a,x0
        move    x0,y:(r1)+
        mpy     y0,x0,a y:(r1),y1
        mac     y1,x1,a
        move    a,x0
        move    x0,y:(r1)+
        move    x0,x:(r3)+
zqcf:
;-CH12
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
; zqinit: copy the tables into Y (first use on a core, or a new build). The
; virtual-ADC tables arrive as their 16 stored half-rows; row 31-ph is row ph
; reversed, so one forward pass writes row ph going up and its mirror going
; down from the table's end (rev 12's copy). The render arrives as T[0..LR/2].
; Preserves r5 and r7 (hardware stack: one bsr and one DO below zqrp).
zqinit:
        move    r7,n2
        move    #>XSP,r1
        move    #>SPTAB,r4
        move    #>SPEND,r7
        do      #SPHALF,zqi1
        move    x:(r1)+,x0
        move    x0,y:(r4)+
        move    x0,y:(r7)-
zqi1:
        move    #>R9TAB,r4              ; r1 is at XR9: it follows XSP
        move    #>R9END,r7
        do      #R9HALF,zqi2
        move    x:(r1)+,x0
        move    x0,y:(r4)+
        move    x0,y:(r7)-
zqi2:
        move    #>XBL,r1
        move    #>BTAB,r4
        move    #>BEND,r7
        move    #<2,n4
        move    #<2,n7
        move    #>$c00000,y0            ; -1/2
        do      #BHALF,zqi3             ; T[k] stored for k = 0..LR/2; T[LR-k] = -1/2 - T[k]
        move    x:(r1)+,x0
        move    x0,y:(r4)+n4
        move    y0,a
        sub     x0,a
        move    a1,y:(r7)-n7
zqi3:
        move    #>BTAB,r4               ; D[k] = T[k+1] - T[k], beside T[k]
        move    #<1,n4
        do      #BPAIRS,zqi4
        move    y:(r4)+,x0
        move    y:(r4+n4),a
        sub     x0,a
        move    a1,y:(r4)+
zqi4:
        move    #>FBASE,r4              ; the aux blocks start clean (Y is dirty after
        clr     a                       ; a reflash; channel 1/2's capacitor would
        rep     #<64                    ; start anywhere)
        move    a,y:(r4)+
        move    #>TAGVAL,x0
        move    x0,y:>TABTAG
        move    n2,r7
        rts
