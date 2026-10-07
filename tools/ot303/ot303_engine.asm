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
; v3 (cycle-tuned). Coefficients live in X and data in Y, each block laid out in the order the
; code reads it, so one dual move feeds both multiplier operands (X -> x0/x1, Y -> y0/y1):
;   control  CX (X, r3) / CY (Y, r6); S48, M48 as L pairs at SM (r0)
;   4x loop  XC (X, r1 modulo 9) / PP (Y, double-buffered: bank A = PP+0..7, bank B =
;            PP+8..15; r4 reads the old bank, r5 writes the new one, both modulo 16, so they
;            swap banks every sample and are back where they started after the four)
;   post     PX (X, r3) / PY (Y, r6)
; State goes back with absolute single moves. The ladder uses acc(Y) - B2*Y = (1 - 2b0)*Y
; exactly (OB2 = $800000 - B2). Truncating stores obey floor(A/2^24) - k = floor((A - k 2^24)
; /2^24), so a difference may be taken before the store without changing the stored word.
; dsp_asm cannot encode the X:R / R:Y move classes (it drops a half): none are used.
; ===========================================================================
; ---- control, X (read in this order by r3)
CX      equ     $1000
CS      equ     CX+0
C_MEG   equ     CX+1
AGFM    equ     CX+2            ; 0 or $ffffff: rc2 is fed by the MEG (accent)
C2      equ     CX+3
ES8     equ     CX+4
AG8     equ     CX+5
LMAX    equ     CX+6
RS      equ     CX+7
BG      equ     CX+8
M_AMP   equ     CX+9
K8      equ     CX+10
DA2     equ     CX+11
DA1     equ     CX+12
DA3     equ     CX+13           ; x 2^8
DA2B    equ     CX+14           ; DA2 again
SC      equ     CX+15
; ---- control, Y (read in this order by r6)
CY      equ     $1000
INC_T   equ     CY+0
RC2     equ     CY+1
L0_16   equ     CY+2
AG_8    equ     CY+3
AMP2    equ     CY+4
DIC1    equ     CY+5
DIC2    equ     CY+6
; ---- L pairs (x hi, y lo)
SM      equ     $1010
S48     equ     SM+0
M48     equ     SM+1
; ---- other host words and state (X unless noted)
W1      equ     $1014
W2      equ     $1015
W3      equ     $1016
SQ      equ     $1017           ; 0: saw only
PH      equ     $1018
HB1P    equ     $1019           ; half-band write pointers
HB2P    equ     $101a
OUTP    equ     $101b           ; the caller's output pointer
INC     equ     $101c
ADS     equ     $101d
S70     equ     $101e
C437    equ     $101f
TOPA    equ     $1020
OSC     equ     $1028           ; 4 words
OSC4    equ     $102c           ; L scratch
DT      equ     $102d           ; L scratch: W1 * INC
MEG2    equ     $1030           ; (Y)
TOPS    equ     $1031           ; (Y)
; ---- post, X (r3) / Y (r6)
PX      equ     $1038
APB     equ     PX+0
APA     equ     PX+1
HP2B    equ     PX+2
HP2A    equ     PX+3
NA2     equ     PX+4            ; x 2^8
NA1     equ     PX+5
NA3     equ     PX+6            ; x 2^16
NKK     equ     PX+7            ; k / 8
PY      equ     $1038
APX     equ     PY+0
APY     equ     PY+1
H2X     equ     PY+2
H2Y     equ     PY+3
NIC2    equ     PY+4
NIC1    equ     PY+5
; ---- the 4x loop's constants (X, read in this order by r1 every sample)
XC      equ     $1050
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
        move    #>CX,r3
        move    #>CY,r6
        move    #>SM,r0
        move    #>$ffffff,m3                  ; (r3 walks CX linearly here)
; ---- pitch slew (24-bit): S48 += CS INC_T - CS hi
        move    x:(r3)+,x1      y:(r6)+,y0      ; CS ; INC_T
        move    l:(r0),a                        ; S48
        mac     x1,y0,a         a,y1            ; + CS T ; y1 = hi
        mac     -y1,x1,a        x:(r3)+,x0      ; - CS hi ; C_MEG
        move    a10,l:(r0)+
        move    a1,x:>INC
zcmeg:
; ---- main envelope, 48 bits: M48 = C*hi + (C*lo >> 24)
        move    l:(r0),b
        move    b0,y0
        mpysu   x0,y0,a
        asr     #24,a,a
        move    b,y1
        mac     x0,y1,a         x:(r3)+,x0      ; M48' ; AGFM
        move    a10,l:(r0)
; ---- accent attack rc2: in = MEG2 & AGFM; RC2 = rnd(in + C2 RC2 - C2 in)
        move    a1,b
        and     x0,b            x:(r3)+,x1      y:(r6)+,y1     ; in ; C2 ; RC2
        mac     y1,x1,b         b,y0            ; + C2 RC2 ; y0 = in
        macr    -x1,y0,b        a,y0            ; - C2 in -> RC2' ; y0 = MEG2
        move    b,y1                            ; RC2'
zccut:
; ---- log cutoff L/16 = L0_16 + ES8 MEG2 + AG8 RC2', clamped to 200 Hz .. 20 kHz
        move    x:(r3)+,x0      y:(r6)+,a       ; ES8 ; L0_16
        mac     y0,x0,a         x:(r3)+,x1      ; + ES8 MEG2 ; AG8
        mac     y1,x1,a         y1,y:>RC2       ; + AG8 RC2' ; RC2
        move    a,x1                            ; (the store's limit)
        move    x1,a
        clr     b               x:(r3)+,x0      ; LMAX
        max     a,b
        cmp     x0,b            y0,y:>MEG2
        tgt     x0,b
; ---- the coefficient tables: entry (L >> 14), fraction (L << 9) & $7fffff
        asr     #12,b,a
        and     #>$fffffc,a
        add     #>LT,a
        asl     #9,b,b
        and     #>$7fffff,b
        move    a1,r0
        move    b1,x0                           ; f
        move    y:(r0)+,b                       ; b0[i]
        move    y:(r0)+,y0                      ; db0
        mac     y0,x0,b         y:(r0)+,a       ; B0 ; kp[i]
        move    y:(r0)+,y0                      ; dkp
        mac     y0,x0,a         b,x1            ; KP ; x1 = B0
        move    a,y1                            ; KP
        move    x1,b
        asl     b               x1,x:>B0        ; 2 b0 ; B0
        neg     b               b,x:>B2         ; ; B2
        add     #>$400000,b
        add     #>$400000,b                     ; $800000 - B2
        move    b,x:>OB2
        move    x:(r3)+,x0      y:(r6)+,b       ; RS ; AG_8
        mpy     x0,y1,a         x:(r3)+,x0      ; KP RS ; BG
        mac     x0,y1,b         a,x:>K64        ; AG_8 + BG KP ; K64
        move    b,x:>G8
zcamp:
; ---- amp envelope + the MEG into the declicker (amp / 16)
        move    x:(r3)+,x0      y:(r6)+,y0      ; M_AMP ; AMP2
        mpy     y0,x0,a         x:(r3)+,x1      ; AMP2 M ; K8
        move    a,y0                            ; AMP2'
        mpy     y0,#3,a                         ; AMP2'/8
        move    y:>MEG2,y1
        mac     y1,x1,a         y0,y:>AMP2      ; + K8 MEG2 = u (unstored) ; AMP2
; declicker SVF (s2 0, s3 8)
        move    x:(r3)+,x0      y:(r6)+,y1      ; DA2 ; ic1
        move    y:(r6)+,b                       ; ic2
        sub     b,a                             ; u - ic2
        move    a,y0                            ; v3
        mpy     y0,x0,a         x:(r3)+,x0      ; DA2 v3 ; DA1
        macr    x0,y1,a         x:(r3)+,x0      ; v1 ; DA3
        mpy     y0,x0,a         a,x1            ; DA3 v3 ; x1 = v1
        asr     #8,a,a
        add     a,b             x:(r3)+,x0      ; ic2 + (DA3 v3 >> 8) ; DA2
        macr    x0,y1,b                         ; v2
        tfr     x1,a            b,y0            ; v1 ; y0 = v2
        asl     a
        sub     y1,a                            ; 2 v1 - ic1
        asl     b               a,y:>DIC1       ; 2 v2 ; ic1'
        move    y:>DIC2,y1
        sub     y1,b            x:(r3)+,x1      ; 2 v2 - ic2 ; SC
        mpy     x1,y0,a         b,y:>DIC2       ; v2 SC ; ic2'
        move    a,x:>ADS
        move    #14,m3
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
; ---- post: allpass 14 Hz, high-pass 24 Hz, notch 7.5 Hz (x in a, fs 8)
        move    #>PX,r3
        move    #>PY,r6
        move    #>$ffffff,m3
        move    a,y0                                    ; x
        move    x:(r3)+,x1      y:(r6)+,b               ; APB ; apx
        mac     x1,y0,b         x:(r3)+,x1      y:(r6)+,y1     ; apx + APB x ; APA ; apy
        macr    y1,x1,b         y0,y:>APX               ; apy' ; apx = x
        move    b,y0                                    ; x2
        move    x:(r3)+,x1      y:(r6)+,y1              ; HP2B ; h2x
        mpy     x1,y0,a         y0,y:>APY               ; HP2B x2 ; APY
        mac     -y1,x1,a        x:(r3)+,x1      y:(r6)+,y1     ; - HP2B h2x ; HP2A ; h2y
        macr    y1,x1,a         y0,y:>H2X               ; h2y' ; h2x = x2
        move    a,y0                                    ; x3
        move    y:(r6)+,b                               ; ic2
        sub     b,a             y0,y:>H2Y               ; x3 - ic2 ; H2Y = x3
        move    a,y1                                    ; v3
        move    x:(r3)+,x1      y:(r6)+,y0              ; NA2 ; ic1
        mpy     y1,x1,a         x:(r3)+,x0              ; NA2 v3 ; NA1
        asr     #8,a,a
        macr    y0,x0,a                                 ; v1
        mpy     x1,y0,a         a,x0                    ; NA2 ic1 ; x0 = v1
        asr     #8,a,a
        add     a,b             x:(r3)+,x1              ; ic2 + (NA2 ic1 >> 8) ; NA3
        mpy     y1,x1,a                                 ; NA3 v3
        asr     #16,a,a
        add     a,b
        rnd     b                                       ; v2
        tfr     x0,a            b,y1                    ; v1 ; y1 = v2
        asl     a
        sub     y0,a                                    ; 2 v1 - ic1
        asl     b               a,y:>NIC1               ; 2 v2 ; ic1'
        move    y:>NIC2,y0
        sub     y0,b            x:(r3)+,x1              ; 2 v2 - ic2 ; NKK
        mpy     x1,x0,a         b,y:>NIC2               ; NKK v1 ; ic2'
        asl     #3,a,a
        move    y:>H2Y,b                                ; x3
        sub     a,b                                     ; notch
        move    b,y0
; ---- amp, level, top rounding
        move    x:>ADS,x1
        mpy     x1,y0,a         y:>TOPS,y1
        asl     #5,a,a                                  ; y (unstored)
        sub     y1,a            x:>TOPA,x1              ; y - tops
        move    a,y0
        mpyr    x1,y0,a                                 ; v
        move    a,x0
        add     y1,a                                    ; v + tops
        move    a,y0                                    ; yy
        add     x0,a                                    ; yy + v
        move    a,y:>TOPS
        move    #14,m3
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
