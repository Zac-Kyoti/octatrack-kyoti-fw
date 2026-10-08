; SPDX-License-Identifier: MIT
; SPDX-FileCopyrightText: 2026 Zac-Kyoti
; ===========================================================================
; OT-303 Phase 2b -- the DSP engine (DSP56300), standalone.
; Contract: tools/ot303/twin.h (Engine::tick, the lean options: 24-bit phase, 48-bit MEG,
; 15+43-tap half-bands, top rounding on, FBS 4), bit for bit. Checked by
; tools/ot303/engine_check.py on dsp56kEmu.
; Assembled by tools/dsp_xasm.py with octabam's 4 Oct 2026 dsp_asm (OT303_DSP=new: it encodes an
; ALU op with two parallel moves and the X:R / R:Y classes; the old one drops a half), after
; tools/ot303/asm_macros.py expands `NAME macro` .. `endm` blocks.
; Branches are relative, so the code is position-independent.
;
; ENTRY ot303: renders r7 (>= 1) output samples into x:(r3)+ (one word each).
; The host (ColdFire, later the hook) has written the HOST words; a note trigger has
; written S48H/L, M48H/L, AMP2 (later: the DSP does that itself from a trig flag).
; Clobbers a b x y r0-r7 n0-n7; restores m0-m7 = $ffffff; r3 advances r7 words.
;
; v4 (cycle-tuned against the emulator's cycle table, which counts an absolute address or a long
; immediate as extra cycles and a long branch as 5). Every once-per-sample word is read by one of
; two walkers in the order the code uses it, so its load rides an ALU op as a parallel move:
;   r2  X walker, block XW (coefficients and host words), modulo 53, back at its start after
;       each output sample
;   r6  Y walker, block YW (data, state, the first half-band's taps), modulo 35, the same; a
;       state is read with (r6) and written back with (r6)+; the two 48-bit states (S48, M48)
;       are Y pairs, hi then lo (not L moves: on the unit no address has both its X and its Y
;       word free -- Y $795..$FFF is free, X there is stock's curve bank)
; Persistent pointers, saved across calls in PTRS: r1 XC (the 4x loop's constants, modulo 9),
; r3 the first half-band's odd branch (X, modulo 8), r4 / r5 the 4x loop's state banks (Y,
; four banks of 9: the oscillator's sample, then 8 states; r4 reads bank n, r5 writes bank n+1,
; skipping its oscillator word), r7 the second half-band's odd branch (Y, modulo 22); the even
; branches (pure delays, the centre taps) are reached through r0 from n2 / n7.
; Half-bands as polyphase pairs: the odd branch is read oldest to newest with (rN)+ and comes
; back to where it started, so no pointer arithmetic; the coefficients are stored reversed.
; n-registers: n0 INC / scratch, n1 5 (XC: K64 then B2..G8), n2 the 15-tap's even branch,
; n3 ADS, n4 9 (r4: one bank per oscillator sample), n5 2 (r5: skip the next bank's oscillator
; word), n6 MEG2 / scratch, n7 the 43-tap's even branch.
; The ladder uses acc(Y) - B2*Y = (1 - 2b0)*Y exactly (OB2 = $800000 - B2). Truncating stores
; obey floor(A/2^24) - k = floor((A - k 2^24)/2^24), so a difference may be taken before the
; store without changing the stored word.
; ===========================================================================
; ---- placement: three bases, rewritten per payload by the builders (asm_macros.layout)
XB      equ     $1000           ;@LAYOUT X block, 64-aligned, $6d words
YS      equ     $1040           ;@LAYOUT Y state block, 64-aligned, $ab words
LT      equ     $1200           ;@LAYOUT Y coefficient table, 860 words
TH      equ     $155c           ;@LAYOUT Y tanh table, 1,026 words (the square's)
; ---- the X walker's block (r2), in reading order
XW      equ     XB              ; 64-aligned
CS      equ     XW+0
C_MEG   equ     XW+1
AGFM    equ     XW+2            ; 0 or $ffffff: rc2 is fed by the MEG (accent)
C2      equ     XW+3
ES8     equ     XW+4
AG8     equ     XW+5
LMAX    equ     XW+6
MASK4   equ     XW+7            ; $fffffc
LTBASE  equ     XW+8            ; LT
MASKF   equ     XW+9            ; $7fffff
RS      equ     XW+10
BG      equ     XW+11
M_AMP   equ     XW+12
K8      equ     XW+13
DA2     equ     XW+14
DA1     equ     XW+15
DA3     equ     XW+16           ; x 2^8
DA2B    equ     XW+17           ; DA2 again
SC      equ     XW+18
SQ      equ     XW+19           ; 0: saw only
SEVENF  equ     XW+20           ; $7fffff
W1      equ     XW+21
HB2C    equ     XW+22           ; 22 odd taps of the 43-tap, REVERSED (oldest first)
APB     equ     XW+44
APA     equ     XW+45
HP2B    equ     XW+46
HP2A    equ     XW+47
NA2     equ     XW+48           ; x 2^8
NA1     equ     XW+49
NA3     equ     XW+50           ; x 2^16
NKK     equ     XW+51           ; k / 8
TOPA    equ     XW+52
XWM     equ     52              ; modulo - 1
; ---- the Y walker's block (r6), in reading order
YW      equ     YS              ; 64-aligned
INC_T   equ     YW+0
S48H    equ     YW+1            ; S48, high word (48-bit pitch slew: two Y words, hi then lo)
S48L    equ     YW+2
M48H    equ     YW+3            ; M48, high word (48-bit main envelope)
M48L    equ     YW+4
RC2     equ     YW+5
L0_16   equ     YW+6
AG_8    equ     YW+7
AMP2    equ     YW+8
DIC2    equ     YW+9
DIC1    equ     YW+10
PH      equ     YW+11
HB1C    equ     YW+12           ; 8 odd taps of the 15-tap, REVERSED, twice (two outputs a sample)
APX     equ     YW+28
APY     equ     YW+29
H2X     equ     YW+30
H2Y     equ     YW+31
NIC2    equ     YW+32
NIC1    equ     YW+33
TOPS    equ     YW+34
YWM     equ     34
; ---- the 4x loop's constants (X, read in this order by r1 every 4x sample)
XC      equ     XB+$40          ; 16-aligned
K64     equ     XC+0            ; per output sample
HP1B    equ     XC+1            ; host, once
HP1A    equ     XC+2
FBB     equ     XC+3
FBA     equ     XC+4
B2      equ     XC+5            ; per output sample: 2 b0
OB2     equ     XC+6            ;                    $800000 - 2 b0
B0      equ     XC+7            ;                    b0
G8      equ     XC+8            ;                    g / 8
; ---- the 4x loop's state (Y): four banks of 9 (OSC, HPX, HPY, FBX, FBY, Y1..Y4); bank 0
; holds the state between output samples (the probe and a reset address it by these names)
PP      equ     YS+$40          ; 64-aligned
OSCW    equ     PP+0
HPX     equ     PP+1
HPY     equ     PP+2
FBX     equ     PP+3
FBY     equ     PP+4
YY1     equ     PP+5
YY2     equ     PP+6
YY3     equ     PP+7
YY4     equ     PP+8
PPW     equ     PP+10           ; r5's start: bank 1, past its oscillator word
; ---- the half-band branches
HB1A    equ     XB+$50          ; X, 8 (8-aligned): the 15-tap's odd samples
HB1B    equ     XB+$58          ; X, 4 (4-aligned): its even samples, the centre = the oldest
HB2A    equ     YS+$80          ; Y, 22 (32-aligned): the 43-tap's odd samples
HB2B    equ     YS+$a0          ; Y, 11 (16-aligned): its even samples, the centre = the oldest
; ---- pointers saved across calls (X), and the square path's words (X, absolute)
PTRS    equ     XB+$68          ; r3, r7, n2, n7, the output pointer
P_R3    equ     PTRS+0
P_R7    equ     PTRS+1
P_N2    equ     PTRS+2
P_N7    equ     PTRS+3
OUTP    equ     PTRS+4
OCB     equ     XB+$60          ; the square path's words (8-aligned), read in this order
S70     equ     OCB+0
C437    equ     OCB+1
MASKE   equ     OCB+2           ; $fffffe
THMW    equ     OCB+3           ; THM
W1A     equ     OCB+4           ; W1 again; W1..W3 are a ring (4-aligned)
W2      equ     OCB+5
W3      equ     OCB+6
; ---- tables (Y)
; LT: 215 entries x 4: b0, db0, kp/64, dkp; TH: 513 entries x 2: tanh, slope
THM     equ     TH+512          ; TH + 2*256: x = 0
;@Y INC_T S48H S48L M48H M48L RC2 L0_16 AG_8 AMP2 DIC2 DIC1 PH HB1C APX APY H2X H2Y NIC2 NIC1 TOPS OSCW HPX HPY FBX FBY YY1 YY2 YY3 YY4 PP HB2A HB2B LT TH THM

ot303:
        move    r3,x:>OUTP
        move    r7,n6                           ; the count (r7 becomes the 43-tap's pointer)
        move    x:>P_R3,r3
        move    x:>P_R7,r7
        move    x:>P_N2,n2
        move    x:>P_N7,n7
        move    #>XW,r2
        move    #XWM,m2
        move    #>YW,r6
        move    #YWM,m6
        move    #>XC,r1
        move    #8,m1
        move    #5,n1
        move    #7,m3
        move    #>PP,r4
        move    #>PPW,r5
        move    #35,m4
        move    #35,m5
        move    #9,n4
        move    #2,n5
        move    #21,m7
        do      n6,zsend
; ---- pitch slew (24-bit): S48 += CS INC_T - CS hi
        move    x:(r2)+,x1      y:(r6)+,y0      ; CS ; INC_T
        move    y:(r6)+,a                       ; S48 hi (A0 = 0)
        move    y:(r6)-,a0                      ; S48 lo
        mac     x1,y0,a         a,y1            ; + CS T ; y1 = hi
        mac     -y1,x1,a        x:(r2)+,x0      ; - CS hi ; C_MEG
        move    a1,y:(r6)+
        move    a0,y:(r6)+
        move    a1,n0                           ; INC
zcmeg:
; ---- main envelope, 48 bits: M48 = C*hi + (C*lo >> 24)
        move    y:(r6)+,y1                      ; M48 hi
        move    y:(r6)-,y0                      ; M48 lo
        mpysu   x0,y0,a
        asr     #24,a,a
        mac     x0,y1,a         x:(r2)+,x0      ; M48' ; AGFM
        move    a1,y:(r6)+
        move    a0,y:(r6)+
; ---- accent attack rc2: in = MEG2 & AGFM; RC2 = rnd(in + C2 RC2 - C2 in)
        move    a1,b
        and     x0,b            x:(r2)+,x1      y:(r6),y1      ; in ; C2 ; RC2
        mac     y1,x1,b         b,y0                            ; + C2 RC2 ; y0 = in
        macr    -x1,y0,b        a,y0                            ; RC2' ; y0 = MEG2
        move    y0,n6                                           ; MEG2
zccut:
; ---- log cutoff L/16 = L0_16 + ES8 MEG2 + AG8 RC2', clamped to 200 Hz .. 20 kHz
        move    x:(r2)+,x0      b,y1                            ; ES8 ; y1 = RC2'
        mpy     y0,x0,a         x:(r2)+,x1      y1,y:(r6)+     ; ES8 MEG2 ; AG8 ; RC2
        mac     y1,x1,a         y:(r6)+,b                       ; + AG8 RC2' ; L0_16
        add     b,a             x:(r2)+,x0                      ; L ; LMAX
        move    a,x1                                            ; (the store's limit)
        clr     b               x1,a
        max     a,b             x:(r2)+,x1                      ; max(L, 0) ; MASK4
        cmp     x0,b
        tgt     x0,b
; ---- the coefficient tables: entry (L >> 14), fraction (L << 9) & $7fffff
        asr     #12,b,a
        and     x1,a            x:(r2)+,x1                      ; 4 i ; LT
        add     x1,a            x:(r2)+,x1                      ; ; $7fffff
        asl     #9,b,b
        and     x1,b
        move    a1,r0
        move    b1,x0                                           ; f
        move    y:(r0)+,b                                       ; b0[i]
        move    y:(r0)+,y0                                      ; db0
        mac     y0,x0,b         y:(r0)+,a                       ; B0 ; kp[i]
        move    y:(r0)+,y0                                      ; dkp
        mac     y0,x0,a         b,x1                            ; KP ; x1 = B0
        move    x:(r2)+,x0      a,y1                            ; RS ; y1 = KP
        mpy     x0,y1,a         x:(r2)+,x0      y:(r6)+,y0     ; K64 ; BG ; AG_8
        mpy     x0,y1,b         a,x:(r1)+n1                     ; BG KP ; K64
        add     y0,b            x1,a                            ; G8 ; B0
        asl     a                                               ; B2
        neg     a               a,x:(r1)+                       ; ; B2
        eor     #>$800000,a                                     ; $800000 - B2 (A1)
        move    a1,x:(r1)+                                      ; OB2
        move    x1,x:(r1)+                                      ; B0
        move    b,x:(r1)+                                       ; G8
zcamp:
; ---- amp envelope + the MEG into the declicker (amp / 16)
        move    x:(r2)+,x0      y:(r6),y0                       ; M_AMP ; AMP2
        mpy     y0,x0,a         x:(r2)+,x1                      ; AMP2 M ; K8
        move    n6,y1                                           ; MEG2
        move    a,y0                                            ; AMP2'
        mpy     y0,#3,a                                         ; AMP2'/8
        mac     y1,x1,a         y0,y:(r6)+                      ; + K8 MEG2 = u (unstored) ; AMP2
; declicker SVF (s2 0, s3 8)
        move    x:(r2)+,x0      y:(r6)+,b                       ; DA2 ; ic2
        sub     b,a             y:(r6),y1                       ; u - ic2 ; ic1
        move    a,y0                                            ; v3
        mpy     y0,x0,a         x:(r2)+,x0                      ; DA2 v3 ; DA1
        macr    x0,y1,a         x:(r2)+,x0                      ; v1 ; DA3
        mpy     y0,x0,a         a,x1                            ; DA3 v3 ; x1 = v1
        asr     #8,a,a
        add     a,b             x:(r2)+,x0                      ; ic2 + (DA3 v3 >> 8) ; DA2
        macr    x0,y1,b                                         ; v2
        tfr     x1,a            b,y0                            ; v1 ; y0 = v2
        asl     a
        sub     y1,a                                            ; 2 v1 - ic1
        asl     b               a,y:(r6)-                       ; 2 v2 ; ic1'
        move    y:(r6),y1                                       ; ic2
        sub     y1,b            x:(r2)+,x1                      ; 2 v2 - ic2 ; SC
        mpy     x1,y0,a         b,y:(r6)+                       ; v2 SC ; ic2'
        move    (r6)+
        move    a,n3                                            ; ADS
zcosc:
; ---- oscillator: 4 samples into the state banks' oscillator words (r4, step 9)
        move    x:(r2)+,b       y:(r6),a                        ; SQ ; PH
        tst     b               x:(r2)+,y1                      ; ; $7fffff
        move    x:(r2)+,x1                                      ; W1
        move    n0,x0                                           ; INC
        bne     zsqr
        tfr     x0,b
        asl     #2,b,b
        add     x0,b
        add     a,b                                             ; P0 + 5 INC
        cmp     y1,b
        bgt     zsws
; saw only, no wrap within 5 steps: osc_k = W1 (P0 + k INC)
        add     x0,a
        add     x0,a            a,y0
        mpy     x1,y0,b         a,y0
        add     x0,a            b,y:(r4)+n4
        mpy     x1,y0,b         a,y0
        add     x0,a            b,y:(r4)+n4
        mpy     x1,y0,b         a,y0
        mpy     x1,y0,b         b,y:(r4)+n4
        move    b,y:(r4)+n4
        move    a,y:(r6)+                                       ; PH
zosc:
; ---- 4x: pre-HP, the TB-303 filter, the first half-band (even samples to its delay, odd to
; the taps), two outputs into the second half-band
        move    n2,r0
        move    #3,m0
        move    y:>YY4,y1
ZFS     macro
        move    x:(r1)+,x0      y:(r4)+,y0                      ; K64 ; osc
        mpy     x0,y1,a         x:(r1)+,x0      y:(r4)+,y1     ; k y4 ; HP1B ; hpx
        asl     #5,a,a
        mpy     y0,x0,b         y0,y:(r5)+                      ; HB osc ; HPX' = osc
        mac     -x0,y1,b        x:(r1)+,x0      y:(r4)+,y1     ; - HB hpx ; HP1A ; hpy
        macr    x0,y1,b         a,x1                            ; hpy' ; x1 = fbin
        move    x:(r1)+,x0      y:(r4)+,y0                      ; FBB ; fbx
        mpy     x1,x0,a         b,y:(r5)+                       ; FBB fbin ; HPY'
        mac     -y0,x0,a        x1,y:(r5)+                      ; - FBB fbx ; FBX' = fbin
        move    x:(r1)+,x0      y:(r4)+,y1                      ; FBA ; fby
        macr    x0,y1,a                                         ; fby'
        asr     #2,b,b
        move    a,y:(r5)+                                       ; FBY'
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
        mpy     x0,y1,a         b,y:(r5)+n5                     ; G8 Y4' ; Y4' (and skip the next bank's oscillator word)
        asl     #4,a,a                                          ; 2 g y4 / 8 (unstored)
        endm
ZHB1    macro
        move    a,x:(r3)+                                       ; odd sample into the taps
        move    x:(r0),a                                        ; the centre: the even branch's oldest
        asr     a
        move    x:(r3)+,x0      y:(r6)+,y0
        mac     y0,x0,a         x:(r3)+,x0      y:(r6)+,y0
        mac     y0,x0,a         x:(r3)+,x0      y:(r6)+,y0
        mac     y0,x0,a         x:(r3)+,x0      y:(r6)+,y0
        mac     y0,x0,a         x:(r3)+,x0      y:(r6)+,y0
        mac     y0,x0,a         x:(r3)+,x0      y:(r6)+,y0
        mac     y0,x0,a         x:(r3)+,x0      y:(r6)+,y0
        mac     y0,x0,a         x:(r3)+,x0      y:(r6)+,y0
        mac     y0,x0,a
        endm
        ZFS
        move    a,x:(r0)+                                       ; even sample into the delay
        ZFS
        ZHB1
        move    a,n0                                            ; first output (even, for the delay)
        ZFS
        move    a,x:(r0)+
        ZFS
        ZHB1
        move    a,y:(r7)+                                       ; second output (odd, into the taps)
zchb2:
; ---- the second half-band: one output sample
        move    r0,n2
        move    n7,r0
        move    #10,m0
        move    n0,y0
        move    y0,y:(r0)+                                      ; the first output into the delay
        move    y:(r0),a                                        ; the centre: the delay's oldest
        asr     a
        move    r0,n7
        move    x:(r2)+,x0      y:(r7)+,y0
        do      #10,zhbl                        ; no REP: stock never uses one (a REP holds off
        mac     y0,x0,a         x:(r2)+,x0      y:(r7)+,y0      ; interrupts, and the host-port
        mac     y0,x0,a         x:(r2)+,x0      y:(r7)+,y0      ; handlers must answer at once)
zhbl:
        mac     y0,x0,a         x:(r2)+,x0      y:(r7)+,y0
        mac     y0,x0,a
        move    #>$ffffff,m0
zcpost:
; ---- post: allpass 14 Hz, high-pass 24 Hz, notch 7.5 Hz (x in a, fs 8)
        move    x:(r2)+,x1      a,y0                            ; APB ; y0 = x
        move    y:(r6),b                                        ; apx
        mac     x1,y0,b         x:(r2)+,x1      y0,y:(r6)+     ; apx + APB x ; APA ; APX = x
        move    y:(r6),y1                                       ; apy
        macr    y1,x1,b                                         ; apy'
        move    x:(r2)+,x1      b,y0                            ; HP2B ; y0 = x2
        mpy     x1,y0,a         y0,y:(r6)+                      ; HP2B x2 ; APY
        move    y:(r6),y1                                       ; h2x
        mac     -y1,x1,a        x:(r2)+,x1      y0,y:(r6)+     ; - HP2B h2x ; HP2A ; H2X = x2
        move    y:(r6),y1                                       ; h2y
        macr    y1,x1,a                                         ; x3 = h2y'
        move    a,y0
        move    y0,n0                                           ; x3
        move    x:(r2)+,x1      y0,y:(r6)+                      ; NA2 ; H2Y
; notch SVF (s2 8, s3 16, sk 3)
        move    y:(r6)+,b                                       ; ic2
        sub     b,a             y:(r6),y1                       ; x3 - ic2 ; ic1
        move    a,y0                                            ; v3
        mpy     x1,y0,a         x:(r2)+,x0                      ; NA2 v3 ; NA1
        asr     #8,a,a
        macr    x0,y1,a                                         ; v1
        mpy     y1,x1,a         a,x0                            ; NA2 ic1 ; x0 = v1
        asr     #8,a,a
        add     a,b             x:(r2)+,x1                      ; ic2 + (NA2 ic1 >> 8) ; NA3
        mpy     x1,y0,a                                         ; NA3 v3
        asr     #16,a,a
        add     a,b
        rnd     b                                               ; v2
        tfr     x0,a            b,y0                            ; v1 ; y0 = v2
        asl     a
        sub     y1,a                                            ; 2 v1 - ic1
        asl     b               a,y:(r6)-                       ; 2 v2 ; ic1'
        move    y:(r6),y1                                       ; ic2
        sub     y1,b            x:(r2)+,x1                      ; 2 v2 - ic2 ; NKK
        mpy     x1,x0,a         b,y:(r6)+                       ; NKK v1 ; ic2'
        move    (r6)+
        asl     #3,a,a
        move    n0,b                                            ; x3
        sub     a,b                                             ; notch
        move    b,y0
; ---- amp, level, top rounding
        move    n3,x1                                           ; ADS
        mpy     x1,y0,a         y:(r6),y1                       ; ; tops
        asl     #5,a,a                                          ; y (unstored)
        sub     y1,a            x:(r2)+,x1                      ; y - tops ; TOPA
        move    a,y0
        mpyr    x1,y0,a                                         ; v
        move    a,x0
        add     y1,a                                            ; v + tops
        move    a,y0                                            ; yy
        add     x0,a                                            ; yy + v
        move    a,y:(r6)+                                       ; TOPS
        move    x:>OUTP,r0
        nop
        move    y0,x:(r0)+
        move    r0,x:>OUTP
zsend:
        move    r3,x:>P_R3
        move    r7,x:>P_R7
        move    n2,x:>P_N2
        move    n7,x:>P_N7
        move    x:>OUTP,r3
        move    #>$ffffff,m0
        move    #>$ffffff,m1
        move    #>$ffffff,m2
        move    #>$ffffff,m3
        move    #>$ffffff,m4
        move    #>$ffffff,m5
        move    #>$ffffff,m6
        move    #>$ffffff,m7
        rts

; ---- saw, with the BLEP check every sample (the phase lives in PH while zblep runs)
zsws:
        move    x1,y1                                           ; W1
        do      #4,zswl
        move    y:(r6),a
        add     x0,a
        move    a1,a
        move    a,y:(r6)
        bsr     zblep
        move    a,y0
        mpy     y1,y0,b
        move    b,y:(r4)+n4
        move    n0,x0
zswl:
        move    (r6)+
        bra     zosc

; ---- saw + square: fast unless either phase wraps within 5 steps
zsqr:
        tfr     x0,b
        asl     #2,b,b
        add     x0,b
        move    b,y0                                            ; 5 INC
        add     a,b
        cmp     y1,b
        bgt     zsqs
        move    a,b
        eor     #>$800000,b                                     ; the square's phase, half a cycle on
        move    b1,b
        add     y0,b
        cmp     y1,b
        bgt     zsqs
; fast square, in three passes over the state banks' oscillator words (r4, step 9, back at the
; start after each): the shaper's argument and the saw part are both linear in k on this path.
;  A: x8_k = sat(16 (S70 S_k + C437)), S_k = S0 + k INC
;  B: th_k = tanh[i] + f slope[i] from x8_k, in place
;  C: osc_k = W1 P_k + W2 th_k + W3, in place
        move    #>OCB,r0
        move    a,y0                                            ; (a = P0, y1 = $7fffff, x0 = INC)
        tfr     y0,b            x:(r0)+,x1                      ; ; S70
        eor     #>$800000,b
        move    b1,y1                                           ; S0
        mpy     y1,x1,a         x:(r0)+,y1                      ; S70 S0 ; C437
        mpy     x1,x0,b                                         ; S70 INC (48 bits)
        add     y1,a                                            ; + C437
        move    b1,y1
        move    b0,y0                                           ; y = S70 INC
        add     y,a
        asl     #4,a,b
        add     y,a             b,y:(r4)+n4
        asl     #4,a,b
        add     y,a             b,y:(r4)+n4
        asl     #4,a,b
        add     y,a             b,y:(r4)+n4
        asl     #4,a,b
        move    b,y:(r4)+n4
        move    x:(r0)+,x0                                      ; $fffffe
        move    x:(r0)+,x1                                      ; THM
        move    r0,n6                                           ; (the block's next word: W1)
        do      #4,zsqb
        move    y:(r4),a                                        ; x8
        asr     #14,a,b
        and     x0,b
        add     x1,b
        asl     #8,a,a
        and     #>$7fff00,a                                     ; frac
        move    b1,r0
        move    a1,y0
        move    y:(r0)+,a                                       ; tanh[i]
        move    y:(r0)+,y1                                      ; slope[i]
        mac     y1,y0,a
        move    a,y:(r4)+n4                                     ; th_k
zsqb:
        move    n6,r0
        move    #2,m0                                           ; W1, W2, W3 as a ring
        move    n0,x0                                           ; INC
        move    y:(r6),a                                        ; P0
        do      #4,zsqc
        add     x0,a            x:(r0)+,y0                      ; P_k ; W1
        move    a,x1            y:(r4),y1                       ; x1 = P_k ; th_k
        mpy     x1,y0,b         x:(r0)+,y0                      ; W1 P_k ; W2
        mac     y1,y0,b         x:(r0)+,y0                      ; + W2 th_k ; W3
        add     y0,b
        move    b,y:(r4)+n4                                     ; osc_k
zsqc:
        move    #>$ffffff,m0
zsqf:
        move    a,y:(r6)+                                       ; PH
        bra     zosc
zsqs:                                   ; saw + square, the BLEP check every sample
        do      #4,zsqe
        move    y:(r6),a
        move    n0,x0
        add     x0,a
        move    a1,a
        move    a,y:(r6)
        bsr     zblep
        move    a1,n6                                           ; the saw
        move    y:(r6),a
        eor     #>$800000,a                                     ; half a cycle on (A1 only:
        move    a1,a                                            ;  re-extend the sign)
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
        move    b1,r0
        move    a1,y0
        move    y:(r0)+,x1
        move    y:(r0)+,x0
        mpy     y0,x0,a
        add     x1,a
        move    a,y0                    ; tanh
        move    x:>W2,x1
        mpy     x1,y0,b         x:>W1A,x1
        move    n6,y0
        mac     x1,y0,b         x:>W3,x1                        ; + W1 saw
        add     x1,b
        move    b,y:(r4)+n4
zsqe:
        move    (r6)+
        bra     zosc

; ---- BLEP: a1 = phase p (A0 = 0), x0 = inc  ->  a1 = the saw with its polyBLEP (limited)
zblep:
        tfr     a,b
        add     #>$400000,b
        add     #>$400000,b             ; b = p + 1 (just after the wrap)
        cmp     x0,b
        blt     zbla
        tfr     a,b
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
        do      #12,zdva                        ; no REP (above)
        div     x0,b
        div     x0,b
zdva:
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
        do      #12,zdvb                        ; no REP (above)
        div     x0,b
        div     x0,b
zdvb:
        move    b0,y0
        mpy     -y0,y0,b
        add     a,b
        move    b,x1
        move    x1,a
        rts
