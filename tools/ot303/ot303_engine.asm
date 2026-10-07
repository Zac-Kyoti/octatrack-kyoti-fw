; SPDX-License-Identifier: MIT
; SPDX-FileCopyrightText: 2026 Zac-Kyoti
; ===========================================================================
; OT-303 Phase 2b -- the DSP engine (DSP56300), standalone.
; Contract: tools/ot303/twin.h (Engine::tick, the lean options: 24-bit phase, 48-bit MEG,
; 15+43-tap half-bands, top rounding on, FBS 4), bit for bit. Checked by
; tools/ot303/engine_check.py on dsp56kEmu.
; Assembled by tools/dsp_xasm.py (equ, dc, XY+ALU moves).
;
; ENTRY ot303: renders r7 (>= 1) output samples into x:(r3)+ (one word each).
; The host (ColdFire, later the hook) has written the HOST words; a note trigger has
; written S48 / M48 / AMP2 (later: the DSP does that itself from a trig flag).
; Clobbers a b x y r0-r2 r4 r5 n0-n5 m0-m2; leaves m0-m2 = $ffffff. r3 advances r7 words.
;
; This first version addresses its variables absolutely (correctness first);
; the cycle-tuned layout comes after it is bit-exact.
; ===========================================================================
VB      equ     $1000           ; the voice block, X and Y (L pairs live here)
; ---- HOST words (X)
INC_T   equ     VB+0
CS      equ     VB+1
C_MEG   equ     VB+2
C2      equ     VB+3
M_AMP   equ     VB+4
L0_16   equ     VB+5
ES8     equ     VB+6
AG8     equ     VB+7
AGFM    equ     VB+8            ; 0 or $ffffff: rc2 is fed by the MEG (accent)
RS      equ     VB+9
AG_8    equ     VB+10
BG      equ     VB+11
K8      equ     VB+12
SC      equ     VB+13
W1      equ     VB+14
W2      equ     VB+15
W3      equ     VB+16
SQ      equ     VB+17           ; 0: saw only
; ---- state (L = x hi, y lo)
S48     equ     VB+18
M48     equ     VB+19
RC2     equ     VB+20
AMP2    equ     VB+21
PH      equ     VB+22
HPX     equ     VB+23
HPY     equ     VB+24
FBX     equ     VB+25
FBY     equ     VB+26
YY1     equ     VB+27
YY2     equ     VB+28
YY3     equ     VB+29
YY4     equ     VB+30
APX     equ     VB+31
APY     equ     VB+32
H2X     equ     VB+33
H2Y     equ     VB+34
TOPS    equ     VB+35
NIC1    equ     VB+36
NIC2    equ     VB+37
DIC1    equ     VB+38
DIC2    equ     VB+39
HB1P    equ     VB+40           ; half-band write pointers
HB2P    equ     VB+41
; ---- per output sample scratch
INC     equ     VB+42
MEG2    equ     VB+43
B0      equ     VB+44
B2      equ     VB+45
K64     equ     VB+46
G8      equ     VB+47
ADS     equ     VB+48
OSC     equ     VB+49           ; 4 words
OSC4    equ     VB+53           ; L scratch
; ---- constants (X), written by the host once
LMAX    equ     VB+56
S70     equ     VB+57
C437    equ     VB+58
HP1B    equ     VB+59
HP1A    equ     VB+60
FBB     equ     VB+61
FBA     equ     VB+62
APB     equ     VB+63
APA     equ     VB+64
HP2B    equ     VB+65
HP2A    equ     VB+66
TOPA    equ     VB+67
NA1     equ     VB+68
NA2     equ     VB+69           ; x 2^8
NA3     equ     VB+70           ; x 2^16
NKK     equ     VB+71           ; k / 8
DA1     equ     VB+72
DA2     equ     VB+73
DA3     equ     VB+74           ; x 2^8
; ---- tables (Y)
LT      equ     $1100           ; 215 entries x 4: b0, db0, kp/64, dkp
TH      equ     $1500           ; 513 entries x 2: tanh, slope
THM     equ     $1700           ; TH + 2*256: x = 0
HB1C    equ     $1980           ; 8 odd taps
HB2C    equ     $1990           ; 22 odd taps
; ---- half-band buffers (X), modulo
HB1B    equ     $1a00           ; 15 words (16-aligned)
HB2B    equ     $1a40           ; 43 words (64-aligned)

ot303:
        move    x:>HB1P,r0
        move    #14,m0
        move    x:>HB2P,r2
        move    #42,m2
        do      r7,zsend
; ---- pitch slew (24-bit): S48 += CS * (INC_T - hi)
        move    x:>INC_T,a
        move    x:>S48,x0
        sub     x0,a
        move    a1,y0
        move    x:>CS,x1
        move    #>S48,r1
        nop
        move    l:(r1),a
        mac     x1,y0,a
        move    a10,l:(r1)
        move    a1,x:>INC
; ---- main envelope, 48 bits: M48 = C*hi + (C*lo >> 24)
        move    #>M48,r1
        nop
        move    l:(r1),b
        move    x:>C_MEG,x0
        move    b0,y0
        mpysu   x0,y0,a
        asr     #24,a,a
        move    b1,y1
        mac     x0,y1,a
        move    a10,l:(r1)
        move    a1,x:>MEG2
; ---- accent attack rc2: in = MEG2 & AGFM; RC2 = rnd(in + C2 (RC2 - in))
        move    a1,b
        move    x:>AGFM,x0
        and     x0,b
        move    x:>RC2,a
        sub     b,a
        move    a1,y0
        move    x:>C2,x1
        mpy     x1,y0,a
        add     b,a
        rnd     a
        move    a,x:>RC2
; ---- log cutoff L/16, clamped to 200 Hz .. 20 kHz
        move    x:>ES8,x0
        move    x:>MEG2,y0
        mpy     y0,x0,a
        move    x:>AG8,x1
        move    x:>RC2,y1
        mac     y1,x1,a
        move    x:>L0_16,b
        add     b,a
        move    a,x0
        move    x0,a
        move    #0,x0
        cmp     x0,a
        tlt     x0,a
        move    x:>LMAX,x0
        cmp     x0,a
        tgt     x0,a
; ---- the coefficient tables: entry (L >> 14), fraction (L << 9) & $7fffff
        asr     #12,a,b
        and     #>$fffffc,b
        add     #>LT,b
        asl     #9,a,a
        and     #>$7fffff,a
        move    b1,r4
        move    a1,y0
        move    y:(r4)+,x1
        move    y:(r4)+,x0
        mpy     y0,x0,a
        add     x1,a
        move    a,x:>B0
        move    x:>B0,a
        asl     a
        move    a1,x:>B2
        move    y:(r4)+,x1
        move    y:(r4)+,x0
        mpy     y0,x0,a
        add     x1,a
        move    a,y1
        move    x:>RS,x0
        mpy     x0,y1,a
        move    a,x:>K64
        move    x:>BG,x0
        mpy     x0,y1,a
        move    x:>AG_8,x1
        add     x1,a
        move    a,x:>G8
; ---- amp envelope + the MEG into the declicker (amp / 16)
        move    x:>AMP2,x0
        move    x:>M_AMP,y0
        mpy     y0,x0,a
        move    a,x:>AMP2
        move    a,x0
        move    #>$100000,y0
        mpy     y0,x0,a
        move    x:>K8,x1
        move    x:>MEG2,y1
        mac     y1,x1,a
        move    a,x0
; declicker SVF (s2 0, s3 8): x0 = u
        move    x:>DIC2,y1
        tfr     x0,a
        sub     y1,a
        move    a,y0                    ; v3
        move    x:>DA2,x1
        mpy     x1,y0,a
        move    x:>DIC1,x0
        move    x:>DA1,y1
        mac     x0,y1,a
        rnd     a
        move    a,x1                    ; v1
        move    x:>DA3,y1
        mpy     y1,y0,b
        asr     #8,b,b
        move    x:>DA2,y1
        mac     x0,y1,b
        move    x:>DIC2,y1
        add     y1,b
        rnd     b
        move    b,y0                    ; v2 = AD16
        tfr     x1,a
        asl     a
        sub     x0,a
        move    a,x:>DIC1
        tfr     y0,b
        asl     b
        sub     y1,b
        move    b,x:>DIC2
        move    x:>SC,x0
        mpy     y0,x0,a
        move    a,x:>ADS
; ---- oscillator: 4 samples into OSC
        move    #>OSC,r5
        move    x:>PH,a
        move    x:>INC,x0
        move    x:>SQ,b
        tst     b
        bne     zsqr
; saw only: fast unless a wrap is within 5 steps
        tfr     x0,b
        asl     #2,b,b
        add     x0,b
        add     a,b
        cmp     #>$7fffff,b
        bgt     zsws
        move    x:>W1,y1
        do      #4,zswf
        add     x0,a
        move    a1,a
        move    a1,y0
        mpy     y1,y0,b
        move    b,x:(r5)+
zswf:
        move    a1,x:>PH
        bra     zosc
zsws:                                   ; saw, with the BLEP check every sample
        do      #4,zswl
        add     x0,a
        move    a1,a
        move    a1,x:>PH
        bsr     zblep
        move    x:>W1,y1
        move    a1,y0
        mpy     y1,y0,b
        move    b,x:(r5)+
        move    x:>PH,a
        move    x:>INC,x0
zswl:
        bra     zosc
zsqr:                                    ; saw + square, the BLEP check every sample
        do      #4,zsqe
        add     x0,a
        move    a1,a
        move    a1,x:>PH
        bsr     zblep
        move    x:>W1,y1
        move    a1,y0
        mpy     y1,y0,b
        move    #>OSC4,r1
        nop
        move    b10,l:(r1)              ; the saw part, exact (x: b1, y: b0)
        move    x:>PH,a
        eor     #>$800000,a             ; half a cycle on (A1 only:
        move    a1,a                    ;  re-extend the sign)
        move    x:>INC,x0
        bsr     zblep
        move    a1,y0
        move    x:>S70,x1
        mpy     x1,y0,a
        move    x:>C437,x0
        add     x0,a
        asl     #4,a,a
        move    a,x0                    ; x/8, saturating
        tfr     x0,a
        asr     #14,a,b
        and     #>$fffffe,b
        add     #>THM,b
        asl     #8,a,a
        and     #>$7fff00,a
        move    b1,r4
        move    a1,y0
        move    y:(r4)+,x1
        move    y:(r4)+,x0
        mpy     y0,x0,a
        add     x1,a
        move    a,y0                    ; tanh
        move    #>OSC4,r1
        nop
        move    l:(r1),b
        move    x:>W2,x1
        mac     x1,y0,b
        move    x:>W3,x1
        add     x1,b
        move    b,x:(r5)+
        move    x:>PH,a
        move    x:>INC,x0
zsqe:
zosc:
; ---- 4x: pre-HP, the TB-303 filter, the first half-band
        move    #>OSC,r5
        do      #4,zfl
        move    x:(r5)+,y0              ; osc
        move    x:>HP1B,x1
        mpy     x1,y0,a
        move    x:>HPX,x0
        mac     -x1,x0,a
        move    x:>HP1A,x1
        move    x:>HPY,x0
        mac     x1,x0,a
        rnd     a
        move    y0,x:>HPX
        move    a,x:>HPY
        move    x:>K64,x0                ; fbin = k y4 / 16
        move    x:>YY4,y0
        mpy     y0,x0,a
        asl     #5,a,a
        move    a,y0
        move    x:>FBB,x1
        mpy     x1,y0,a
        move    x:>FBX,x0
        mac     -x1,x0,a
        move    x:>FBA,x1
        move    x:>FBY,x0
        mac     x1,x0,a
        rnd     a
        move    y0,x:>FBX
        move    a,x:>FBY
        move    a,y1                    ; fby
        move    x:>HPY,a                 ; y0 = hpy/4 - 2 fby
        asr     #2,a,a
        move    y1,b
        asl     b
        sub     b,a
        move    a,y0
        move    x:>B2,x0                 ; Y1 += 2b0 (y0 - Y1 + Y2)
        move    x:>YY1,a
        mac     y0,x0,a
        move    x:>YY1,y1
        mac     -x0,y1,a
        move    x:>YY2,y1
        mac     x0,y1,a
        rnd     a
        move    a,x:>YY1
        move    a,y0                    ; Y2 += b0 Y1 - 2b0 Y2 + b0 Y3
        move    x:>B0,x1
        move    x:>YY2,a
        mac     x1,y0,a
        move    x:>YY2,y1
        mac     -x0,y1,a
        move    x:>YY3,y1
        mac     y1,x1,a
        rnd     a
        move    a,x:>YY2
        move    a,y0                    ; Y3 += b0 Y2 - 2b0 Y3 + b0 Y4
        move    x:>YY3,a
        mac     x1,y0,a
        move    x:>YY3,y1
        mac     -x0,y1,a
        move    x:>YY4,y1
        mac     y1,x1,a
        rnd     a
        move    a,x:>YY3
        move    a,y0                    ; Y4 += b0 Y3 - 2b0 Y4
        move    x:>YY4,a
        mac     x1,y0,a
        move    x:>YY4,y1
        mac     -x0,y1,a
        rnd     a
        move    a,x:>YY4
        move    a,y0                    ; out = 2 g y4 / 8
        move    x:>G8,x0
        mpy     y0,x0,a
        asl     #4,a,a
        move    a,x:(r0)+               ; into the first half-band
        move    r5,b                    ; odd sample (2nd, 4th): the half-band's output
        move    #>OSC,x0
        sub     x0,b
        btst    #0,b1                   ; 1 or 3 done: even sample, nothing out
        bcs     zfnx
        bsr     zhb1
zfnx:
        nop
zfl:
; ---- the second half-band: one output sample
        move    r2,r1
        move    #42,m1
        move    #>$fffffe,n1
        move    (r1)-
        move    #>HB2C,r4
        clr     a
        do      #22,zh2l
        move    x:(r1)+n1,x0
        move    y:(r4)+,y0
        mac     y0,x0,a
zh2l:
        move    #>$ffffea,n1
        move    r2,r1
        nop
        move    (r1)+n1
        move    x:(r1),x0
        move    #>$400000,y0
        mac     y0,x0,a
        move    a,x0                    ; fs 8
        move    #>$ffffff,m1
; ---- post: allpass 14 Hz, high-pass 24 Hz, notch 7.5 Hz
        move    x:>APB,x1
        mpy     x1,x0,a
        move    x:>APX,b
        add     b,a
        move    x:>APA,x1
        move    x:>APY,y0
        mac     x1,y0,a
        rnd     a
        move    x0,x:>APX
        move    a,x:>APY
        move    a,x0
        move    x:>HP2B,x1
        mpy     x1,x0,a
        move    x:>H2X,y0
        mac     -x1,y0,a
        move    x:>HP2A,x1
        move    x:>H2Y,y0
        mac     x1,y0,a
        rnd     a
        move    x0,x:>H2X
        move    a,x:>H2Y
        move    a,x0                    ; x0 = x (notch input), kept
; notch SVF (s2 8, s3 16, sk 3)
        move    x:>NIC2,y1
        tfr     x0,a
        sub     y1,a
        move    a,y0                    ; v3
        move    x:>NA2,x1
        mpy     x1,y0,a
        asr     #8,a,a
        move    x:>NIC1,b
        move    b,y1
        move    x:>NA1,x1
        mac     y1,x1,a
        rnd     a
        move    a,x1                    ; v1
        move    x:>NA3,y1
        mpy     y1,y0,a
        asr     #16,a,a
        move    x:>NA2,y0
        move    x:>NIC1,y1
        mpy     y1,y0,b
        asr     #8,b,b
        add     b,a
        move    x:>NIC2,y1
        add     y1,a
        rnd     a
        move    a,y0                    ; v2
        tfr     x1,a
        asl     a
        move    x:>NIC1,y1
        sub     y1,a
        move    a,x:>NIC1
        tfr     y0,a
        asl     a
        move    x:>NIC2,y1
        sub     y1,a
        move    a,x:>NIC2
        move    x:>NKK,y1                ; notch = x - (k/8) v1 * 8
        mpy     y1,x1,b
        asl     #3,b,b
        tfr     x0,a
        sub     b,a
        move    a,x0
; ---- amp, level, top rounding
        move    x:>ADS,y0
        mpy     y0,x0,a
        asl     #5,a,a
        move    a,x0                    ; y
        move    x:>TOPS,y1
        tfr     x0,a
        sub     y1,a
        move    a,y0
        move    x:>TOPA,x1
        mpy     x1,y0,a
        rnd     a
        move    a,x1                    ; v
        tfr     x1,a
        add     y1,a
        move    a,y0                    ; yy
        tfr     y0,b
        add     x1,b
        move    b,x:>TOPS
        move    y0,x:(r3)+
zsend:
        move    r0,x:>HB1P
        move    r2,x:>HB2P
        move    #>$ffffff,m0
        move    #>$ffffff,m2
        rts

; ---- the first half-band output -> the second half-band's buffer (r0 = write pointer)
zhb1:
        move    r0,r1
        move    #14,m1
        move    #>$fffffe,n1
        move    (r1)-
        move    #>HB1C,r4
        clr     a
        do      #8,zh1l
        move    x:(r1)+n1,x0
        move    y:(r4)+,y0
        mac     y0,x0,a
zh1l:
        move    #>$fffff8,n1
        move    r0,r1
        nop
        move    (r1)+n1
        move    x:(r1),x0
        move    #>$400000,y0
        mac     y0,x0,a
        move    a,x:(r2)+
        move    #>$ffffff,m1
        rts

; ---- BLEP: a1 = phase p (A0 = 0), x0 = inc  ->  a1 = the saw with its polyBLEP (limited)
zblep:
        move    a,b                     ; (= tfr: p is in range; dsp_asm mis-encodes a bare tfr a,b)
        add     #>$400000,b
        add     #>$400000,b             ; b = p + 1 (just after the wrap)
        cmp     x0,b
        blt     zbla
        move    a,b                     ; (= tfr: p is in range; dsp_asm mis-encodes a bare tfr a,b)
        neg     b
        add     #>$400000,b
        add     #>$400000,b             ; b = 1 - p (just before the wrap)
        cmp     x0,b
        ble     zblb
        rts
zbla:
        neg     b
        add     x0,b                    ; inc - (p + 1)
        andi    #$fe,ccr
        rep     #24
        div     x0,b
        move    b0,y0
        mpy     y0,y0,b
        add     a,b
        move    b,x1
        move    x1,a
        rts
zblb:
        neg     b
        add     x0,b                    ; inc - (1 - p)
        andi    #$fe,ccr
        rep     #24
        div     x0,b
        move    b0,y0
        mpy     -y0,y0,b
        add     a,b
        move    b,x1
        move    x1,a
        rts
