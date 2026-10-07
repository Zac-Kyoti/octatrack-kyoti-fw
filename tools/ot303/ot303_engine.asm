; SPDX-License-Identifier: MIT
; SPDX-FileCopyrightText: 2026 Zac-Kyoti
; ===========================================================================
; OT-303 Phase 2b -- the DSP engine (DSP56300), standalone.
; Contract: tools/ot303/twin.h (Engine::tick, the lean options: 24-bit phase, 48-bit MEG,
; 15+43-tap half-bands, top rounding on, FBS 4), bit for bit. Checked by
; tools/ot303/engine_check.py on dsp56kEmu.
; Assembled by tools/dsp_xasm.py (equ, dc, XY+ALU moves; branches are relative, so the code
; is position-independent).
;
; ENTRY ot303: renders r7 (>= 1) output samples into x:(r3)+ (one word each).
; The host (ColdFire, later the hook) has written the HOST words; a note trigger has
; written S48 / M48 / AMP2 (later: the DSP does that itself from a trig flag).
; Clobbers a b x y r0-r2 r4-r7 n0-n7; restores m0-m7 = $ffffff; r3 advances r7 words.
;
; v2 (cycle-tuned). The 4x loop keeps its constants in X (block XC, walked by r1 modulo 9)
; and its state in Y, double-buffered (PP: bank A = PP+0..7, bank B = PP+8..15; r4 reads
; the old bank, r5 writes the new one, both modulo 16, so they swap banks every sample and
; are back where they started after the four). Between output samples bank A holds the
; state. One dual move then feeds both multiplier operands (X -> x0/x1, Y -> y0/y1).
; The ladder uses acc(Y) - B2*Y = (1 - 2b0)*Y exactly (OB2 = $800000 - B2).
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
; ---- state (X; L = x hi, y lo)
S48     equ     VB+18
M48     equ     VB+19
RC2     equ     VB+20
AMP2    equ     VB+21
PH      equ     VB+22
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
OUTP    equ     VB+42           ; the caller's output pointer
; ---- per output sample scratch
INC     equ     VB+43
MEG2    equ     VB+44
ADS     equ     VB+48
OSC     equ     VB+49           ; 4 words
OSC4    equ     VB+53           ; L scratch
DT      equ     VB+54           ; L scratch: W1 * INC
; ---- constants (X), written by the host once
LMAX    equ     VB+56
S70     equ     VB+57
C437    equ     VB+58
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
; ---- the 4x loop's constants (X, read in this order by r1 every sample)
XC      equ     VB+80
K64     equ     XC+0            ; per output sample
HP1B    equ     XC+1            ; host, once
HP1A    equ     XC+2
FBB     equ     XC+3
FBA     equ     XC+4
B2      equ     XC+5            ; per output sample: 2 b0
OB2     equ     XC+6            ;                    $800000 - 2 b0
B0      equ     XC+7            ;                    b0
G8      equ     XC+8            ;                    g / 8
; ---- the 4x loop's state (Y, double-buffered; bank A between output samples)
PP      equ     $1080           ; 16-aligned
HPX     equ     PP+0
HPY     equ     PP+1
FBX     equ     PP+2
FBY     equ     PP+3
YY1     equ     PP+4
YY2     equ     PP+5
YY3     equ     PP+6
YY4     equ     PP+7
PPB     equ     PP+8            ; bank B
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
        move    r3,x:>OUTP
        move    x:>HB1P,r2
        move    #14,m2
        move    #>$fffff8,n2            ; centre of the 15-tap: pos - 8
        move    #14,m3
        move    #>$fffffe,n3
        move    #>XC,r1
        move    #8,m1
        move    #>PP,r4
        move    #>PPB,r5
        move    #15,m4
        move    #15,m5
        move    #>$fffffe,n0
        move    #>$ffffea,n7            ; centre of the 43-tap: pos - 22
        do      r7,zsend
        move    x:>HB2P,r7
        move    #42,m7
; ---- pitch slew (24-bit): S48 += CS * (INC_T - hi)
        move    #>S48,r6
        move    x:>INC_T,a
        move    x:>S48,x0
        sub     x0,a            x:>CS,x1
        move    a1,y0
        move    l:(r6),a
        mac     x1,y0,a
        move    a10,l:(r6)
        move    a1,x:>INC
zcmeg:
; ---- main envelope, 48 bits: M48 = C*hi + (C*lo >> 24)
        move    #>M48,r6
        move    x:>C_MEG,x0
        move    l:(r6),b
        move    b0,y0
        mpysu   x0,y0,a
        asr     #24,a,a
        move    b1,y1
        mac     x0,y1,a
        move    a10,l:(r6)
        move    a1,x:>MEG2
; ---- accent attack rc2: in = MEG2 & AGFM; RC2 = rnd(in + C2 (RC2 - in))
        move    a1,b
        move    x:>AGFM,x0
        and     x0,b            x:>RC2,a
        sub     b,a             x:>C2,x1
        move    a1,y0
        mpy     x1,y0,a
        add     b,a
        rnd     a
        move    a,x:>RC2
zccut:
; ---- log cutoff L/16, clamped to 200 Hz .. 20 kHz
        move    a,y1
        move    x:>AG8,x1
        mpy     y1,x1,a         x:>MEG2,y0
        move    x:>ES8,x0
        mac     y0,x0,a         x:>L0_16,b
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
        move    b1,r6
        move    a1,x0
        move    y:(r6)+,b
        move    y:(r6)+,y0
        mac     y0,x0,b         y:(r6)+,a       ; b = b0 ; a = kp/64 (start)
        move    b,x1                            ; b0 (limited)
        move    y:(r6)+,y0
        mac     y0,x0,a         x1,x:>B0
        move    a,y1                            ; kp/64
        move    x1,b
        asl     b
        move    b1,x:>B2
        move    b1,x0
        move    #>$400000,b
        sub     x0,b
        add     #>$400000,b                     ; $800000 - B2 (as a positive word)
        move    b1,x:>OB2
        move    x:>RS,x0
        mpy     x0,y1,a         x:>BG,x0
        move    a,x:>K64
        mpy     x0,y1,a         x:>AG_8,x1
        add     x1,a
        move    a,x:>G8
zcamp:
; ---- amp envelope + the MEG into the declicker (amp / 16)
        move    x:>AMP2,x0
        move    x:>M_AMP,y0
        mpy     y0,x0,a
        move    a,x0
        move    x0,x:>AMP2
        move    #>$100000,y0
        mpy     y0,x0,a         x:>K8,x1
        move    x:>MEG2,y1
        mac     y1,x1,a
        move    a,x0
; declicker SVF (s2 0, s3 8): x0 = u
        move    x:>DIC2,y1
        tfr     x0,a
        sub     y1,a            x:>DA2,x1
        move    a,y0                    ; v3
        mpy     x1,y0,a         x:>DIC1,x0
        move    x:>DA1,y1
        mac     x0,y1,a         x:>DA3,y1
        rnd     a
        move    a,x1                    ; v1
        mpy     y1,y0,b         x:>DA2,y1
        asr     #8,b,b
        mac     x0,y1,b         x:>DIC2,y1
        add     y1,b
        rnd     b
        move    b,y0                    ; v2 = AD16
        tfr     x1,a
        asl     a
        sub     x0,a
        move    a,x:>DIC1
        tfr     y0,b
        asl     b
        sub     y1,b            x:>SC,x0
        move    b,x:>DIC2
        mpy     y0,x0,a
        move    a,x:>ADS
zcosc:
; ---- oscillator: 4 samples into OSC
        move    #>OSC,r0
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
        move    #>DT,r6
        move    x0,y0
        move    x:>W1,x1
        mpy     x1,y0,b                 ; W1 * INC
        move    b10,l:(r6)
        move    a,y0
        mpy     x1,y0,b         l:(r6),y        ; W1 * P0 ; y = W1 * INC (48 bits)
        add     y,b
        add     y,b             b,x:(r0)+
        add     y,b             b,x:(r0)+
        add     y,b             b,x:(r0)+
        move    b,x:(r0)+
        move    x0,b                    ; PH = P0 + 4 INC (no wrap on the fast path)
        asl     #2,b,b
        add     b,a
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
        move    b,x:(r0)+
        move    x:>PH,a
        move    x:>INC,x0
zswl:
        bra     zosc
zsqr:                                   ; saw + square, the BLEP check every sample
        do      #4,zsqe
        add     x0,a
        move    a1,a
        move    a1,x:>PH
        bsr     zblep
        move    x:>W1,y1
        move    a1,y0
        mpy     y1,y0,b
        move    #>OSC4,r6
        move    x:>PH,a
        move    b10,l:(r6)              ; the saw part, exact (x: b1, y: b0)
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
        move    b1,r6
        move    a1,y0
        move    y:(r6)+,x1
        move    y:(r6)+,x0
        mpy     y0,x0,a
        add     x1,a
        move    a,y0                    ; tanh
        move    #>OSC4,r6
        move    x:>W2,x1
        move    l:(r6),b
        mac     x1,y0,b
        move    x:>W3,x1
        add     x1,b
        move    b,x:(r0)+
        move    x:>PH,a
        move    x:>INC,x0
zsqe:
zosc:
; ---- 4x: pre-HP, the TB-303 filter, into the first half-band (two samples per output of it)
        move    #>OSC,r0
        move    y:>YY4,y1
        do      #2,zfl
        bsr     zfs
        bsr     zfs
zchb1:
        lua     (r2)+n2,r3              ; ---- the first half-band: centre pos - 8
        move    #>HB1C,r6
        move    x:(r3),a
        asr     a
        lua     (r2)-,r3                ; newest
        nop
        move    x:(r3)+n3,x0    y:(r6)+,y0
        rep     #7
        mac     y0,x0,a         x:(r3)+n3,x0    y:(r6)+,y0
        mac     y0,x0,a
        move    a,x:(r7)+               ; into the second half-band
zfl:
zchb2:
; ---- the second half-band: one output sample
        move    #42,m0
        lua     (r7)+n7,r0              ; centre pos - 22
        move    #>HB2C,r6
        move    x:(r0),a
        asr     a
        lua     (r7)-,r0                ; newest
        nop
        move    x:(r0)+n0,x0    y:(r6)+,y0
        rep     #21
        mac     y0,x0,a         x:(r0)+n0,x0    y:(r6)+,y0
        mac     y0,x0,a
        move    #>$ffffff,m0
        move    a,x0                    ; fs 8
zcpost:
; ---- post: allpass 14 Hz, high-pass 24 Hz, notch 7.5 Hz
        move    x:>APB,x1
        mpy     x1,x0,a         x:>APX,b
        add     b,a             x:>APA,x1
        move    x:>APY,y0
        mac     x1,y0,a         x0,x:>APX
        rnd     a
        move    a,x0
        move    x0,x:>APY
        move    x:>HP2B,x1
        mpy     x1,x0,a         x:>H2X,y0
        mac     -x1,y0,a        x:>HP2A,x1
        move    x:>H2Y,y0
        mac     x1,y0,a         x0,x:>H2X
        rnd     a
        move    a,x0                    ; x0 = x (notch input), kept
        move    x0,x:>H2Y
; notch SVF (s2 8, s3 16, sk 3)
        move    x:>NIC2,y1
        tfr     x0,a
        sub     y1,a            x:>NA2,x1
        move    a,y0                    ; v3
        mpy     x1,y0,a         x:>NIC1,y1
        asr     #8,a,a
        move    x:>NA1,x1
        mac     y1,x1,a
        rnd     a
        move    a,x1                    ; v1
        move    x:>NA3,y1
        mpy     y1,y0,a         x:>NA2,y0
        asr     #16,a,a
        move    x:>NIC1,y1
        mpy     y1,y0,b
        asr     #8,b,b
        add     b,a             x:>NIC2,y1
        add     y1,a
        rnd     a
        move    a,y0                    ; v2
        tfr     x1,a            x:>NIC1,y1
        asl     a
        sub     y1,a
        move    a,x:>NIC1
        tfr     y0,a            x:>NIC2,y1
        asl     a
        sub     y1,a
        move    a,x:>NIC2
        move    x:>NKK,y1               ; notch = x - (k/8) v1 * 8
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
        sub     y1,a            x:>TOPA,x1
        move    a,y0
        mpy     x1,y0,a
        rnd     a
        move    a,x1                    ; v
        tfr     x1,a
        add     y1,a
        move    a,y0                    ; yy
        tfr     y0,b
        add     x1,b
        move    b,x:>TOPS
        move    x:>OUTP,r6
        move    r7,x:>HB2P
        move    y0,x:(r6)+
        move    r6,x:>OUTP
zsend:
        move    r2,x:>HB1P
        move    x:>OUTP,r3
        move    #>$ffffff,m1
        move    #>$ffffff,m2
        move    #>$ffffff,m3
        move    #>$ffffff,m4
        move    #>$ffffff,m5
        move    #>$ffffff,m7
        rts

; ---- one 4x sample: pre-HP, the TB-303 filter, the output into the first half-band.
; In: y1 = Y4, r0 -> OSC[n], r1 -> XC, r4 -> the old bank, r5 -> the new bank.
; Out: y1 = the new Y4; x:(r2)+ = 2 g y4 / 8.
zfs:
        move    x:(r1)+,x0                      ; K64
        mpy     x0,y1,a         x:(r0)+,x1      y:(r4)+,y0     ; k y4 ; osc ; hpx
        asl     #5,a,a     ; HP1B ; hpy
        move    x:(r1)+,x0      y:(r4)+,y1
        mpy     x1,x0,b         x1,y:(r5)+                      ; HB osc ; HPX' = osc
        mac     -y0,x0,b        a,x1                            ; - HB hpx ; x1 = fbin
        move    x:(r1)+,x0                      ; HP1A
        macr    x0,y1,b         x:(r1)+,x0      y:(r4)+,y0     ; hpy' ; FBB ; fbx
        mpy     x1,x0,a         b,y:(r5)+                       ; FBB fbin ; HPY'
        mac     -y0,x0,a        x1,y:(r5)+                      ; - FBB fbx ; FBX' = fbin
        move    x:(r1)+,x0      y:(r4)+,y1                      ; FBA ; fby
        macr    x0,y1,a                                         ; fby'
        asr     #2,b,b                       ; hpy'/4 ; FBY'
        move    a,y:(r5)+
        asl     a               x:(r1)+,x0      y:(r4)+,y1     ; 2 fby' ; B2 ; Y1
        sub     a,b             x:(r1)+,x1                      ; y0in ; OB2
        mpy     y1,x1,a         b,y0                            ; OB2 Y1 ; y0 = y0in
        mac     y0,x0,a         y:(r4)+,y1                      ; B2 y0in ; Y2
        macr    x0,y1,a         x:(r1)+,x0      y:(r4)+,y0     ; B2 Y2 -> Y1' ; B0 ; Y3
        mpy     y1,x1,b         a,y1                            ; OB2 Y2 ; y1 = Y1'
        mac     y0,x0,b         a,y:(r5)+                       ; B0 Y3 ; Y1'
        macr    x0,y1,b         y:(r4)+,y1                      ; B0 Y1' -> Y2' ; Y4
        mpy     x1,y0,a         b,y0                            ; OB2 Y3 ; y0 = Y2'
        mac     x0,y1,a         b,y:(r5)+                       ; B0 Y4 ; Y2'
        macr    y0,x0,a                                         ; B0 Y2' -> Y3'
        mpy     y1,x1,b         a,y0                            ; OB2 Y4 ; y0 = Y3'
        macr    y0,x0,b         x:(r1)+,x0      a,y:(r5)+      ; B0 Y3' -> Y4' ; G8 ; Y3'
        move    b,y1                                            ; y1 = Y4'
        mpy     x0,y1,a         b,y:(r5)+                       ; G8 Y4' ; Y4'
        asl     #4,a,a
        move    a,x:(r2)+
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
