; SPDX-License-Identifier: MIT
; SPDX-FileCopyrightText: 2026 Zac-Kyoti
; ===========================================================================
; OT-303 hardware probe -- the step events (DIAGNOSTIC image only). Assembled on its own at
; HQEV (after DARK REV's 35-word helper in SPRING's module) with the equates of
; ot303_engine.asm and hwprobe.asm; hwprobe.asm calls it with jsr >HQEV, r5 = XM.
; ===========================================================================
; ---- an event: a step's start (pitch, host words, trigger) or its gate's end (host words)
hq_event:
        move    #>2544,x0
        move    x0,x:(r5+D_EVC)
        move    #>YS,r4
        move    x:(r5+D_HALF),a
        tst     a
        bne     hq_gateoff
        move    #>1,x0
        move    x0,x:(r5+D_HALF)
        move    #>PAT,r1
        move    x:(r5+D_STEP),n1
        move    x:(r1+n1),a
        move    a,x:(r5+D_CURW)
        btst    #23,a1
        bcs     hq_evret
        move    #>VARS,r2
        move    #>TRIG,r1
        btst    #22,a1
        bcs     hq_accon
        move    #>VAR_NON,r2
        move    #>TRIGN,r1
hq_accon:
        bsr     hq_vars
        and     #>$00ffff,a
        move    a1,y:(r4+E_INCT)
        move    a1,y:(r4+E_S48H)
        clr     b
        move    b,y:(r4+E_S48L)
        move    x:(r1)+,x0
        move    x0,y:(r4+E_M48H)
        move    x:(r1)+,x0
        move    x0,y:(r4+E_M48L)
        move    x:(r5+D_AMPT),x0
        move    x0,y:(r4+E_AMP2)
hq_evret:
        rts
hq_gateoff:
        clr     b
        move    b,x:(r5+D_HALF)
        move    x:(r5+D_STEP),b
        move    #>1,x0
        add     x0,b
        move    #>15,x0
        and     x0,b
        move    b1,x:(r5+D_STEP)
        move    x:(r5+D_CURW),a
        btst    #23,a1
        bcs     hq_evret
        move    #>VAR_AOF,r2
        btst    #22,a1
        bcs     hq_vars
        move    #>VAR_NOF,r2
hq_vars:
        move    x:(r2)+,x0
        move    x0,x:(r5-N_CMEG)
        move    x:(r2)+,x0
        move    x0,x:(r5-N_MAMP)
        move    x:(r2)+,x0
        move    x0,x:(r5-N_AG8)
        move    x:(r2)+,x0
        move    x0,x:(r5-N_AGFM)
        move    x:(r2)+,x0
        move    x0,x:(r5-N_K8)
        rts


; ---- BURN: page-2 slot 6, 24 * BURN cycles per sample over this call's n7 samples (octabam's RIG
; BURN body, hardware-proven; tools/ot303/burn_djeq.asm). r6 and n7 are the caller's. Uses a, x0,
; y1. The zero guard is load-bearing: DO with a count of 0 loops 65536 times; asl sets Z.
hq_burn:
        move    x:(r6+$c),a
        and     #>$7f0000,a
        move    a1,y1
        move    n7,x0
        mpy     x0,y1,a
        asl     #$a,a,a
        beq     hq_bzero
        do      a1,hq_bzero
        nop
        nop
        nop
hq_bzero:
        rts

; ---- STRESS (303 >= 64; DIAG10): before the render, whose tone is heard, n7 x 128 iterations of a
; three-instruction body. Mode (303 - 64) >> 3, safest first:
;   0 div, no memory         1 mac, no memory          2 Y reads (YS)          3 Y writes (Y:$ff0)
;   4 X:Y parallel reads     5 mac + X:Y parallel reads (the half-band's shape)
;   6 the engine itself (n7 samples, no events)        7 X reads (the engine's X block)
; DIAG8D/9: with the track muted, the riff leaks into the master on ~29 % of frames; the tone + BURN
; does not. Which workload leaks? r5 = XM; uses a b x0 x1 y0 y1 r1 r3 r4 r7 m1 m4.
hq_stress:
        move    x:(r5+D_KNB),a
        sub     #>$4000,a
        blt     hq_sret
        asr     #11,a,a
        move    n7,b
        asl     #7,b,b
        cmp     #<6,a
        bne     hq_snot6
        move    n7,r7
        move    #>RBUF,r3
hq_cot1:
        dc      $0d1080,0                       ; bsr >ot303
        move    #>XM,r5
        rts
hq_snot6:
        move    #>63,x1
        move    x1,m1
        move    x1,m4
        move    #>XB,r1
        move    #>YS,r4
        cmp     #<1,a
        blt     hq_w0a
        beq     hq_w1a
        cmp     #<3,a
        blt     hq_w2a
        beq     hq_w3a
        cmp     #<5,a
        blt     hq_w4a
        beq     hq_w5a
        do      b1,hq_w7z                       ; 7: X reads
        move    x:(r1)+,x0
        move    x:(r1)+,x0
        move    x:(r1)+,x0
hq_w7z:
        bra     hq_sdone
hq_w0a:
        do      b1,hq_w0z
        div     x0,a
        div     x0,a
        div     x0,a
hq_w0z:
        bra     hq_sdone
hq_w1a:
        do      b1,hq_w1z
        mac     y0,x0,a
        mac     y0,x0,a
        mac     y0,x0,a
hq_w1z:
        bra     hq_sdone
hq_w2a:
        do      b1,hq_w2z
        move    y:(r4)+,y0
        move    y:(r4)+,y0
        move    y:(r4)+,y0
hq_w2z:
        bra     hq_sdone
hq_w3a:
        move    #>$ff0,r4
        move    #>15,x1
        move    x1,m4
        do      b1,hq_w3z
        move    y0,y:(r4)+
        move    y0,y:(r4)+
        move    y0,y:(r4)+
hq_w3z:
        bra     hq_sdone
hq_w4a:
        do      b1,hq_w4z
        move    x:(r1)+,x0      y:(r4)+,y0
        move    x:(r1)+,x0      y:(r4)+,y0
        move    x:(r1)+,x0      y:(r4)+,y0
hq_w4z:
        bra     hq_sdone
hq_w5a:
        do      b1,hq_w5z
        mac     y0,x0,a         x:(r1)+,x0      y:(r4)+,y0
        mac     y0,x0,a         x:(r1)+,x0      y:(r4)+,y0
        mac     y0,x0,a         x:(r1)+,x0      y:(r4)+,y0
hq_w5z:
hq_sdone:
        move    #>$ffffff,x1
        move    x1,m1
        move    x1,m4
hq_sret:
        rts
