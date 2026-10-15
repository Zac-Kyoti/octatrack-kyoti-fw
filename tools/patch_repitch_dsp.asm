; SPDX-License-Identifier: MIT
; SPDX-FileCopyrightText: 2026 Zac-Kyoti
; ===========================================================================
; VARISPEED_EMUS (repitch-kyoti rev 17) -- DSP side: the "virtual sampler" behind
; S950 (RPS9) and SP12 (RPSP). Model (the ground truth this must match, bit for bit):
; tools/repitch_engine_model.py, DspExact. Scope: reference/handoffs/REPITCH_FIDELITY_SCOPE.md;
; rev 17: NOTES Session 120 continued (10). The VEM DSP optimisation (fewer cycles, the
; same output word for word): reference/handoffs/VARISPEED_EMUS_DSP_OPT.md.
; Assembled by tools/dsp_xasm.py (NOT plain dsp_asm: this uses XY+ALU moves,
; equ and dc, and every word is disassembled back and checked);
; tools/repitch_dsp_src.py prepends the constants -- the table DATA lives in X
; memory (SPRING REVERB's own X tables, rewritten by the builder) and zqinit copies
; it into Y. Only RPSP's raw build (outputs 7/8) is kept here: the channel 6 and
; channel 1/2 builds (RPK_OUT=ch6/ch12) were dropped with the VEM optimisation (git
; history has them; the model still renders them for listening packs).
;
; WHERE IT RUNS. The stock voice engine (payload A P:0x3a1, B P:0x1a4) is detoured
; at its kernel prologue (A P:0x40b, B P:0x20e): `move x:(r5),n6 / move y:(r5)+,a`
; becomes `bsr zqrp`, and both moves run at this routine's tail. For RPCH nothing
; else happens and the stock kernel runs. For RPS9/RPSP this routine writes the
; pass's output samples itself and sets r7 = 0, so the stock `do r7` skips (the
; DSP56300 skips a DO whose count is 0 -- stock relies on that for its own empty
; passes, measured).
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
; Every frame runs this hook twice (the voice module's `do #2`: LC = 2, then 1);
; on a trig frame the first pass is the old sound's tail, the second starts the
; new one. An EMPTY pass (the first, when nothing is split) has no increment:
; y:$40 = 0, so it takes the RPCH exit and never reaches the engines (measured).
;
; MEMORY (Y:$795..$FFF is free on stock on both cores -- octabam, measured on
; hardware; SIDECHAIN3 takes $7f0-$9ff on both cores):
;   Y:STBASE + x:$418   per-track RPSP slot ($20 words): the mid's residual
;                       ring (modulo-addressed, so it starts the slot), then the state
;   Y:TABTAG            table tag; != TAGVAL => copy the tables in (once/core)
;   Y:SPTAB, Y:R9TAB    the virtual-ADC tables, 32 phases each (8 / 16 taps),
;                       from their 16 stored half-rows in X (rows 16-31 mirror)
;   Y:BTAB              the render's step table: row j = the L taps' (T, D) pairs, rows
;                       BROW words apart (the tail of each row is padding)
;
; REGISTERS. Uses a, b, x0, x1, y0, y1, r1, r4, r6, r7, m1 and m7 (kept in n5 and n7,
; restored), n1, n2, n4, n6; r5 is parked in n1 during an RPSP tick. Leaves
; r0, r2 and m6 alone; r3 advances by two words per output. An (Rn)+Nn update always
; takes its own Nn. m1 is $7f from zqtok on: an XY dual move needs its X pointer in
; r0-r3, and the ring's own modulo register is m6. r1 and r6 (m6 = $7f) wrap at a
; 128-word boundary, so every table walk uses r4/r5/r7 (linear); r6 only walks inside
; one RPSP slot.
; Hardware stack: at most bsr + two nested DOs below zqrp.
; Pipeline: no address register is used for addressing in the instruction right after
; the one that loads it (the DSP56300 stalls a cycle there; dsp56kEmu does not price it).
;
; LABELS: no label may be a prefix of another (dsp_asm's lookup). zq*.
; ===========================================================================

; ---- the RPSP slot (Y:STBASE + x:$418, $20 words): the mid's residual ring
; (RINGM1+1 words, modulo-addressed, residuals / 4), then:
S_OH    equ     $0a     ; W0: r6 walks OH .. RB once per output, in this order: the side's
S_OL    equ     $0b     ;   offset behind the OT (2 x integer part, fraction; this pass's),
S_PF    equ     $0c     ;   the previous output's fraction (Q24), the current step (the
S_HM    equ     $0d     ;   mid), the previous output's ring word offset (2 x frame), $7e,
S_PKW   equ     $0e     ;   the ring's base (r2, this pass's)
S_MASK  equ     $0f
S_RB    equ     $10
S_RF    equ     $11     ; the tick block (r1 walks it in a tick): frac(r), Q24, with the
S_PHI   equ     $12     ;   mode tag (this pass's); the accumulator fraction, Q24; r / 2,
S_RH    equ     $13     ;   unsigned Q23 (this pass's); the smoothed read shift (the SP's
S_LS    equ     $14     ;   truncation), Q22 frames
S_TAU   equ     $15     ; time of the next tick (from the start of the next interval, Q20)
S_RW    equ     $16     ; the ring slot (absolute address) of the next output
S_TAG   equ     $17
S_SIZE  equ     $18     ; (track 3's slot ends in TABTAG at +$1f)
; in the output loop r6 rests on OH: these are the fields' displacements from it
D_PF    equ     S_PF-S_OH
D_HM    equ     S_HM-S_OH
D_PKW   equ     S_PKW-S_OH
D_RF    equ     S_RF-S_OH
D_TAU   equ     S_TAU-S_OH
D_RW    equ     S_RW-S_OH
NWALK   equ     $1000000-(S_RB-S_OH)    ; r6 back from RB to OH
STTAG   equ     STBASE+S_TAG
R9B     equ     128-R9SW                ; RPS9's first tap, from r2, mod 128
LSMUL   equ     ((1<<LSSH)-1)<<(23-LSSH)        ; (2^LSSH - 1) / 2^LSSH, Q23
BRM1    equ     BR-1
BTNEG2  equ     $1000000-2*BR

zqrp:
        move    y:>$40,a
        and     #<3,a                   ; the mode (Z from bits 47-24, a1)
        beq     zqstk                   ; RPCH: stock, untouched
        move    a1,n1                   ; n1 = mode
        move    y:>TABTAG,a
        cmp     #>TAGVAL,a
        beq     zqtok
        bsr     zqinit                  ; first use on this core (or a new build)
zqtok:
; ---- a trig (rev 14). The engines read the ring BEHIND the OT's position, and
; at a trig the frames behind the new sound hold stale audio (the last voice's,
; unscaled -- its AMP silenced it later in the chain). Stock reads only floor(p)
; and floor(p)+1; RPS9/RPSP would replay 8-13 frames of it at the new trig's
; full AMP: the crack at every trig start (user, rev 13; measured in ot_emu).
; So at the pass that starts the new sound, the 16 frames before its first
; frame become silence, and RPSP's slot starts clean (tag cleared: zqsp).
        move    x:>$419,r4              ; this track's unpacked per-voice record
        move    m1,n5                   ; restored at zqdone
        move    x:(r4+$1e),a            ; its word +$1E (m4 is linear: x:$419 + $1E can
        move    #$7f,m1                 ;  straddle a 128-word block)
        jclr    #12,a1,zqnh             ; a trig starts in this frame?
        move    lc,b                    ; ... and this is the frame's second pass (the
        cmp     #<1,b                   ; voice module's `do #2`: LC 2, then 1), where
        bne     zqnh                    ; the new sound starts. (Not a count of visits:
                                        ; an empty first pass carries mode 0 and never
                                        ; reaches this code -- rev 14 missed every trig
                                        ; landing on a frame boundary that way.)
        move    x:(r5),a                ; the new sound's first frame (ring word offset)
        move    x:>$418,n6              ; the track offset
        sub     #<32,a
        and     #>$7e,a
        move    a1,n2
        move    #>STTAG,r6
        lua     (r2)+n2,r1              ; (r2 is 128-aligned: r1 stays in the ring,
        clr     a                       ;  and m1 = $7f wraps it)
        do      #<32,zqnr               ; (a DO, not a REP: interruptible, as octabam's)
        move    a,x:(r1)+
zqnr:
        move    a,y:(r6+n6)             ; RPSP: a clean slot at zqsp
zqnh:
        jclr    #0,n1,zqsp              ; mode 2: RPSP (1 and 3: RPS9)

; ============================================================ RPS9 (Akai)
; output i = 12-bit(virtual ADC at p_i - c - 1): a 16-tap polyphase kernel over
; ring frames k_i-2c-1 .. k_i, all delivered. (NOT k_i+1: at a zero fraction
; the OT does not deliver it -- the stock kernel weights it 0. Measured.)
        move    #<R9B,n2
        move    #>$fff000,y1            ; the 12-bit mask
        lua     (r2)+n2,r6              ; r6 = r2 + the first tap's offset (in the block)
        do      r7,zq9e
        move    y:(r5),b                ; b1 = the fraction
        move    x:(r5)+,n1              ; n1 = ring word offset of k_i
        move    r6,r1
        lsr     #19,b                   ; phase 0..31
        move    (r1)+n1                 ; r1 = the first tap, k_i - 2c - 1 (m1 = $7f wraps it)
        lsl     #4,b                    ; x 16 taps
        add     #>R9TAB,b
        move    b1,r7                   ; the phase's row (the loop count is in LC now)
        clr     a       x:(r1)+,x0
        clr     b       x:(r1)+,x1      y:(r7)+,y0
; taps 1..15, unrolled (rev 17): a DO here cost 5 cycles per output, 8% of RPS9
        mac     y0,x0,a x:(r1)+,x0
        mac     x1,y0,b x:(r1)+,x1      y:(r7)+,y0
        mac     y0,x0,a x:(r1)+,x0
        mac     x1,y0,b x:(r1)+,x1      y:(r7)+,y0
        mac     y0,x0,a x:(r1)+,x0
        mac     x1,y0,b x:(r1)+,x1      y:(r7)+,y0
        mac     y0,x0,a x:(r1)+,x0
        mac     x1,y0,b x:(r1)+,x1      y:(r7)+,y0
        mac     y0,x0,a x:(r1)+,x0
        mac     x1,y0,b x:(r1)+,x1      y:(r7)+,y0
        mac     y0,x0,a x:(r1)+,x0
        mac     x1,y0,b x:(r1)+,x1      y:(r7)+,y0
        mac     y0,x0,a x:(r1)+,x0
        mac     x1,y0,b x:(r1)+,x1      y:(r7)+,y0
        mac     y0,x0,a x:(r1)+,x0
        mac     x1,y0,b x:(r1)+,x1      y:(r7)+,y0
        mac     y0,x0,a x:(r1)+,x0
        mac     x1,y0,b x:(r1)+,x1      y:(r7)+,y0
        mac     y0,x0,a x:(r1)+,x0
        mac     x1,y0,b x:(r1)+,x1      y:(r7)+,y0
        mac     y0,x0,a x:(r1)+,x0
        mac     x1,y0,b x:(r1)+,x1      y:(r7)+,y0
        mac     y0,x0,a x:(r1)+,x0
        mac     x1,y0,b x:(r1)+,x1      y:(r7)+,y0
        mac     y0,x0,a x:(r1)+,x0
        mac     x1,y0,b x:(r1)+,x1      y:(r7)+,y0
        mac     y0,x0,a x:(r1)+,x0
        mac     x1,y0,b x:(r1)+,x1      y:(r7)+,y0
        mac     y0,x0,a x:(r1)+,x0
        mac     x1,y0,b x:(r1)+,x1      y:(r7)+,y0
        mac     y0,x0,a
        mac     x1,y0,b a,x0            ; limit L
        tfr     x0,a    b,x0            ; limit R
        and     y1,a    x0,b            ; 12 bits: floor to a 1/2048 step
        and     y1,b    a1,x:(r3)+
        move    b1,x:(r3)+
zq9e:
        move    n5,m1                   ; (zqdone's tail, inline: no branch)
        move    #$0,r7
        move    x:(r5),n6
        move    y:(r5)+,a
        rts

; ============================================================ RPSP (SP-1200)
; Rev 17: the mid (L + R)/2 goes through the SP -- the virtual ADC (8 taps) at
; the SP's clock, 12 bits, the band-limited render to 44.1 kHz -- out raw, as the
; SP's outputs 7/8; the side (L - R)/2 is read clean, as far behind the OT's
; position as the mid's path delays it, and L, R = mid +/- side. The SP's clock
; period is 1.69 output samples, so an output interval holds at most one tick. A
; tick at u stores a new step; the render spreads the step (new - old) over this
; and the next L-1 outputs with the band-limited step response (the residual
; ring); the mid = current step + its ring slot.
zqsp:
        move    r7,b                    ; an empty pass: nothing to render, and x:(r5)
        tst     b                       ; is not this track's -- the slot waits for a
        beq     zqdone                  ; real pass (on the unit an empty pass is mode 0)
        move    x:>$418,n6              ; the track offset
        move    #>STBASE,r6
        move    r7,n2                   ; n2 = the pass count
        move    (r6)+n6                 ; r6 = this track's slot (m6 = $7f: the slot does
        move    #$40,r4                 ;  not straddle 128 words)
        move    y:(r6+S_TAG),b
        cmp     #>TAGSP,b
        beq     zqsok
        clr     b                       ; stale, first use or a trig: clean ring + state
        move    r6,r1
        do      #S_SIZE,zqsz
        move    b,y:(r1)+
zqsz:
        move    #>TAGSP,x1
        move    x1,y:(r6+S_TAG)
        move    #>$7e,x0
        move    r6,y:(r6+S_RW)          ; the ring starts the slot
        move    x0,y:(r6+S_MASK)
        move    #>LS0,x0                ; the read shift starts at its mean
        move    x0,y:(r6+S_LS)
        bra     zqsrs                   ; "previous output" = this pass's first
zqsok:
        move    x:(r5),a                ; resync "previous" if this pass does not
        move    y:(r6+S_PKW),x0         ; continue it: ring positions advance
        sub     x0,a                    ; continuously while a sound plays, so a
        and     #>$7e,a                 ; jump of more than 2 frames (4 words) means
        move    a1,b                    ; the state is stale (the track has been in
        cmp     #<4,b                   ; another mode meanwhile)
        ble     zqsnj
zqsrs:
        move    x:(r5),x0
        move    x0,y:(r6+S_PKW)
        move    y:(r5),x0
        move    x0,y:(r6+S_PF)
zqsnj:
; ---- this pass's constants. r = int(r) + frac(r) as the DSP holds it (x:$40 is
; read for bit 0 only -- on the unit it reads $c1 at 1.0x; the table builder
; masks it too, measured in ot_emu -- and y:$40 carries the mode tag in its low
; bits, as the twin's r does): RF = frac(r); RH = r / 2, unsigned Q23 (the tick's
; u x r); the side's offset behind the OT = c + 1 frames + MS_SIDE_DELAY
; increments + the smoothed read shift, its integer part doubled (ring words;
; the fraction stays one)
        move    l:(r4),a                ; a = l:$40 = r as 24.24 (r4 = $40)
        and     #<1,a                   ; (a1 only; a0 stays)
        move    a0,y:(r6+S_RF)
        asr     a                       ; a0 = RH = r x 2^23, unsigned (a1 = 0)
        move    a0,y0
        move    y0,y:(r6+S_RH)
        move    #>KD,x0
        mpyuu   y0,x0,a                 ; (MS_SIDE_DELAY / 16) r x 2^47 (RH unsigned; < 2^47)
        move    y:(r6+S_LS),b
        asr     #19,a,a                 ; -> MS_SIDE_DELAY r, 24.24
        asr     #22,b,b                 ; the read shift (Q22 -> 24.24)
        add     #<SIDEC,a               ; + c + 1 frames
        add     b,a
        move    a1,x0
        add     x0,a                    ; integer part x 2
        move    a1,y:(r6+S_OH)
        move    a0,y:(r6+S_OL)
        move    r2,y:(r6+S_RB)
        move    m7,n7                   ; restored at zqoe
        move    #RINGM1,m7
        move    y:(r6+S_RW),r7
        move    y:(r6+S_TAU),r4         ; r4 = tau through the pass; n4 = one interval
        move    #>$100000,n4
        lua     (r6+S_OH),r6            ; r6 rests on OH
        move    #>NWALK,n6              ; r6 walks OH .. RB once per output
        do      n2,zqoe
        jset    #20,r4,zqout            ; tau >= 1 (tau < PSP < 2 always): no tick here
; ---- a tick at u = tau (PSP > 1: at most one per output interval). r1 walks the
; tick block RF, PHI, RH, LS; r5 is the ADC's and then the render's table pointer
; (the output table parked in n1).
        lua     (r6+D_RF),r1
        move    r4,b
        asl     #3,b,a                  ; a1 = u = tau, Q23
        add     #>PSPQ20,b              ; tau += PSP (the out block's (r4)-n4 takes this interval)
        move    a,x1    y:(r1)+,y0      ; x1 = u (x1 is free until the render); y0 = RF
        move    y:(r1),a
        add     y0,a    b1,r4           ; phi = frac(phi + r); r4 = tau + PSP
        lsr     a       a1,y:(r1)+
        move    a1,y0                   ; Q24 phi >> 1 = the same phi as Q23
        mpyi    #>PSPH,y0,b             ; (PSP/2)*phi = PSP*phi * 2^46: the read shift
        tfr     b,a     y:(r1)+,y0      ; (b1 = the shift, Q22) into its one-pole mean; y0 = RH
        move    y:(r1),y1               ; LS
        asr     #LSSH,a,a               ; LS += (shift - LS) >> LSSH, as
        maci    #>LSMUL,y1,a            ;   (shift + (2^LSSH - 1) LS) >> LSSH (b0 cannot carry)
        asr     #22,b,b                 ; the shift -> frames, 24.24
        move    a1,y:(r1)
        mpyuu   x1,y0,a                 ; u*r * 2^47 (u r/2, unsigned)
        asr     #23,a,a                 ; -> frames, 24.24
        sub     b,a
        move    y:(r6+D_PKW),b          ; + the previous output's position
        asr     b       r5,n1           ; (ring words -> frames; even, so b0 stays 0)
        move    y:(r6+D_PF),b0
        add     b,a
        sub     #<SPC2,a                ; first tap = floor(pos) - 2c - 1
        move    a0,b
        asl     a                       ; frames -> words
        lsr     #19,b                   ; phase 0..31
        and     #>$7e,a
        lsl     #3,b                    ; x 8 taps
        add     #>SPTAB,b
        move    a1,n2
        move    b1,r5
        lua     (r2)+n2,r1              ; (r2 is 128-aligned: m1 = $7f wraps r1 in the ring)
        move    y:(r6+D_HM),y1          ; the step it replaces
; ---- the mid's virtual ADC: 8 taps over L + R (the sum, halved below)
        clr     a       x:(r1)+,x0      y:(r5)+,y0
        mac     y0,x0,a x:(r1)+,x0
        mac     y0,x0,a x:(r1)+,x0      y:(r5)+,y0
        mac     y0,x0,a x:(r1)+,x0
        mac     y0,x0,a x:(r1)+,x0      y:(r5)+,y0
        mac     y0,x0,a x:(r1)+,x0
        mac     y0,x0,a x:(r1)+,x0      y:(r5)+,y0
        mac     y0,x0,a x:(r1)+,x0
        mac     y0,x0,a x:(r1)+,x0      y:(r5)+,y0
        mac     y0,x0,a x:(r1)+,x0
        mac     y0,x0,a x:(r1)+,x0      y:(r5)+,y0
        mac     y0,x0,a x:(r1)+,x0
        mac     y0,x0,a x:(r1)+,x0      y:(r5)+,y0
        mac     y0,x0,a x:(r1)+,x0
        mac     y0,x0,a x:(r1)+,x0      y:(r5)+,y0
        mac     y0,x0,a x:(r1)+,x0
        mac     y0,x0,a
; ---- the step: 12 bits of (L + R)/2; the render's row j = floor(uR) and fraction
; frac(uR) (R = 16); the weight is T + frac D
        asr     a       x1,b            ; (L + R) / 2; b = u
        lsr     #19,b                   ; j
        move    a,x0                    ; limited
        lsl     #BRSH,b                 ; x BROW
        add     #>BTAB,b
        tfr     x0,a    b1,r5           ; r5 = row j: the taps' (T, D) pairs
        and     #>$fff000,a             ; the new step, 12 bits
        move    a1,y:(r6+D_HM)
        sub     y1,a    x1,b
        asr     a                       ; (new - old)/2
        lsl     #5,b
        lsr     b       a,y1            ; frac(uR), Q23; y1 = the step / 2
        move    b,x0    y:(r5)+,a       ; x0 = frac(uR); T
        move    y:(r5)+,y0              ; D
; the L taps, unrolled (a DO cost 5 cycles a tick, and the last tap restores r5 for free)
        mac     y0,x0,a y:(r7),b        ; a = weight/2 = T + frac D; b = the ring
        move    a,x1    y:(r5)+,a       ; next T
        mac     y1,x1,b y:(r5)+,y0      ; b += step/2 x weight/2; next D
        move    b,y:(r7)+
        mac     y0,x0,a y:(r7),b        ; a = weight/2 = T + frac D; b = the ring
        move    a,x1    y:(r5)+,a       ; next T
        mac     y1,x1,b y:(r5)+,y0      ; b += step/2 x weight/2; next D
        move    b,y:(r7)+
        mac     y0,x0,a y:(r7),b        ; a = weight/2 = T + frac D; b = the ring
        move    a,x1    y:(r5)+,a       ; next T
        mac     y1,x1,b y:(r5)+,y0      ; b += step/2 x weight/2; next D
        move    b,y:(r7)+
        mac     y0,x0,a y:(r7),b        ; a = weight/2 = T + frac D; b = the ring
        move    a,x1    y:(r5)+,a       ; next T
        mac     y1,x1,b y:(r5)+,y0      ; b += step/2 x weight/2; next D
        move    b,y:(r7)+
        mac     y0,x0,a y:(r7),b        ; a = weight/2 = T + frac D; b = the ring
        move    a,x1    y:(r5)+,a       ; next T
        mac     y1,x1,b y:(r5)+,y0      ; b += step/2 x weight/2; next D
        move    b,y:(r7)+
        mac     y0,x0,a y:(r7),b        ; a = weight/2 = T + frac D; b = the ring
        move    a,x1    y:(r5)+,a       ; next T
        mac     y1,x1,b y:(r5)+,y0      ; b += step/2 x weight/2; next D
        move    b,y:(r7)+
        mac     y0,x0,a y:(r7),b        ; a = weight/2 = T + frac D; b = the ring
        move    a,x1    y:(r5)+,a       ; next T
        mac     y1,x1,b y:(r5)+,y0      ; b += step/2 x weight/2; next D
        move    b,y:(r7)+
        mac     y0,x0,a y:(r7),b        ; a = weight/2 = T + frac D; b = the ring
        move    a,x1    y:(r5)+,a       ; next T
        mac     y1,x1,b y:(r5)+,y0      ; b += step/2 x weight/2; next D
        move    b,y:(r7)+
        mac     y0,x0,a y:(r7),b        ; a = weight/2 = T + frac D; b = the ring
        move    a,x1    y:(r5)+,a       ; next T
        mac     y1,x1,b y:(r5)+,y0      ; b += step/2 x weight/2; next D
        move    b,y:(r7)+
        mac     y0,x0,a y:(r7),b
        move    a,x1
        mac     y1,x1,b n1,r5           ; the output table back
        move    b,y:(r7)+
; ---- out: the mid = the current step + what the render still owes this output
; (4 x the slot, limited); the side, clean: (L - R)/2 at the OT's position less the
; offset, linear between its two frames. l:(r5) = (ring words, fraction): less (2 int,
; frac) of the offset, the words' LSB is the fraction's borrow, which the $7e mask
; drops; after the mask and the base, `asr a` leaves g = the fraction / 2 in a0.
; side = (M - g) s0 + g s1 = M s0 - g s0 + g s1 (M = $7fffff; exact in a), and never
; saturates (a convex mix of two 24-bit values), so L = mid + side keeps a's fraction
; bits and R = mid - lim(side).
zqout:
        move    l:(r5)+,a               ; a1 = ring words k, a0 = the fraction f
        move    a,x0    y:(r7),b        ; x0 = k; b = the slot
        asl     b       y:(r6)+,y1      ; OH
        asl     b       y:(r6)+,y0      ; OL; b = 4 x the slot
        sub     y,a     a0,y:(r6)+      ; PF = f (this output becomes "previous")
        move    y:(r6)+,y1              ; HM
        add     y1,b    x0,y:(r6)+      ; the mid; PKW = k
        move    y:(r6)+,x1              ; $7e
        and     x1,a    y:(r6)+n6,y1    ; RB (r6 back to OH: the ring is 128-aligned, so
        or      y1,a    b,x0            ;  OR adds it); x0 = the mid (limited)
        asr     a       a1,r1           ; a0 = g, Q23; r1 = L0's address
        clr     b       a0,y0           ; y0 = g
        move    x:(r1)+,a       b,y:(r7)+       ; L0; the slot is spent
        move    x:(r1)+,x1              ; R0
        sub     x1,a    x:(r1)+,b       ; L1
        asr     a       x:(r1)+,x1      ; (L0 - R0)/2; R1
        sub     x1,b    a,x1
        asr     b       (r4)-n4         ; (L1 - R1)/2; tau -= one interval
        mpyi    #>$7fffff,x1,a
        mac     -x1,y0,a        b,x1
        mac     x1,y0,a x0,b            ; the side; b = the mid
        add     x0,a    a,x1            ; L = mid + side; x1 = the side
        sub     x1,b    a,x:(r3)+
        move    b,x:(r3)+               ; R = mid - side
zqoe:
        move    r7,y:(r6+D_RW)
        move    r4,y:(r6+D_TAU)
        move    n7,m7

zqdone:
        move    n5,m1
        move    #$0,r7                  ; the stock kernel's `do r7` skips
zqstk:
        move    x:(r5),n6               ; displaced from the hook site
        move    y:(r5)+,a
        rts

; ---------------------------------------------------------------------------
; zqboot (rev 17): the table copy at boot, outside every audio pass (the KYOTI
; load audit: on a core's first RPS9/RPSP pass it cost one frame ~5,000
; instructions on top of its audio). Hooked at the payload's one-time memory
; clear, before its frame loop exists: A P:0x46 / B P:0x47, `do b,LA` with
; a = 0, b = the count, r4/r5 its two pointers. This runs the clear's passes
; but the last; the stock body at the return address runs that one, so the
; memory the clear leaves is stock's (an extra pass would write one word past
; each run -- on payload A, Y:$38000, payload B's entry in the shared window).
; Then zqinit, with the registers it uses kept on the hardware stack. zqrp's
; tag check stays: it rebuilds Y if anything ever overwrites the tables. (Placed
; before zqinit: octabam's dsp_asm sizes a backward call differently per pass.)
zqboot:
        move    #>1,x0
        sub     x0,b
        do      b,zqbz
        move    a,y:(r4)+
        move    a,y:(r5)+
zqbz:
        add     x0,b                    ; the count, as the stock DO leaves it
        move    b1,ssh                  ; the registers zqinit uses, on the hardware
        move    r1,ssh                  ; stack (the boot path is shallow: jsr + five +
        move    r4,ssh                  ; bsr + one DO)
        move    n2,ssh
        move    n4,ssh
        bsr     zqinit
        move    ssh,n4
        move    ssh,n2
        move    ssh,r4
        move    ssh,r1
        move    ssh,b
        clr     a
        rts

; ---------------------------------------------------------------------------
; zqinit: copy the tables into Y (first use on a core, or a new build). The
; virtual-ADC tables arrive as their 16 stored half-rows; the render as T[0..LR/2].
; Preserves r5 and r7 (hardware stack: one bsr and one DO below zqrp).
zqinit:
        move    r7,n2
        move    #>XBL,r1
        move    #>TTMP,r4               ; T[0..LR] into a scratch run first (RPS9's
        move    #>TTEND,r7              ;  table's place: that table is copied last)
        move    #>$c00000,y0            ; -1/2
        do      #BHALF,zqi3             ; T[k] stored for k = 0..LR/2; T[LR-k] = -1/2 - T[k]
        move    x:(r1)+,x0
        move    x0,y:(r4)+
        move    y0,a
        sub     x0,a
        move    a1,y:(r7)-
zqi3:
; the render's table: row j (one per segment) holds the L taps' (T[k], D[k] = T[k+1] -
; T[k]) pairs in tap order, tap m at segment k = (L-1-m)R + j, so a tick walks one row
; with (r5)+; rows are BROW words apart. One DO (the hardware stack's budget): every L
; pairs the next row starts one segment up.
        move    #>BTAB,r1
        move    #>TTAP0,r7              ; row 0, tap 0
        move    r7,r4
        move    #>BTNEG,n4              ; k+1 -> k-R (n1 holds zqrp's mode)
        move    #>BL,b
        do      #BPAIRS,zqi4
        move    y:(r4)+,x0              ; T[k]
        move    y:(r4)+n4,a             ; T[k+1]
        sub     x0,a    x0,y:(r1)+
        move    a1,y:(r1)+
        sub     #<1,b
        bne     zqi5
        move    (r7)+
        lua     (r1+BPAD),r1            ; past the row's padding
        move    r7,r4
        move    #>BL,b
zqi5:
        nop                             ; (the loop's last word: a branch target)
zqi4:
; the virtual-ADC tables: row 31-ph is row ph reversed, so one forward pass writes row
; ph going up and its mirror going down from the table's end (rev 12's copy)
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
        move    #>TAGVAL,x0
        move    x0,y:>TABTAG
        move    n2,r7
        rts
