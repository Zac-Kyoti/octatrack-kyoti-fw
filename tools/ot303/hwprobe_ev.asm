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


; ---- the mode (DIAG11), once per call before the render: K = 303
;   1-15 tone | 16-47 STRESS (K - 16) >> 3 + tone | 48-71 engine + tone (the riff's work, events
;   included) | 72-87 riff / 8 | 88-103 riff | 104-127 STRESS 4 (X reads) + tone
; STRESS: n7 x 128 iterations of a three-instruction body: 0 Y reads (YS), 1 Y writes (Y:$ff0),
; 2 mac + X:Y reads (the half-band's shape), 3 the engine itself (no events), 4 X reads (the
; engine's X block). r5 = XM; uses a b x0 x1 y0 y1 r1 r3 r4 r7 m1 m4.
hq_mode:
        move    x:(r5+D_KNB),a                  ; K << 8
        clr     b
        cmp     #>$6800,a
        bge     hq_m5                           ; 104-127
        cmp     #>$5800,a
        bge     hq_mriff                        ; 88-103
        cmp     #>$4800,a
        bge     hq_mr8                          ; 72-87
        cmp     #>$3000,a
        bge     hq_meng                         ; 48-71
        move    b1,x:(r5+D_BAND)                ; 1-47: the tone
        sub     #>$1000,a
        blt     hq_sret                         ; 1-15
        asr     #11,a,a                         ; STRESS 0-3
        bra     hq_mst
hq_mriff:
        move    #>2,b
        bra     hq_mset
hq_mr8:
        move    #>3,b
        bra     hq_mset
hq_meng:
        move    #>1,b
hq_mset:
        move    b1,x:(r5+D_BAND)
        rts
hq_m5:
        move    b1,x:(r5+D_BAND)
        move    #>4,a                           ; (falls into the STRESS run)
hq_mst:
        move    n7,b
        asl     #7,b,b
        cmp     #<3,a
        bne     hq_snot4
        move    n7,r7
        move    #>RBUF,r3
hq_cot1:
        dc      $0d1080,0                       ; bsr >ot303
        move    #>XM,r5
        rts
hq_snot4:
        move    #>63,x1
        move    x1,m1
        move    x1,m4
        move    #>XB,r1
        move    #>YS,r4
        cmp     #<1,a
        blt     hq_w2a
        beq     hq_w3a
        cmp     #<2,a
        beq     hq_w5a
        do      b1,hq_w7z                       ; 4: X reads
        move    x:(r1)+,x0
        move    x:(r1)+,x0
        move    x:(r1)+,x0
hq_w7z:
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

; ---- the engine's render (r7 = KCNT, r3 = RBUF); band 3 scales it by 1/8
hq_reng:
hq_cot2:
        dc      $0d1080,0                       ; bsr >ot303
        move    #>XM,r5
        move    x:(r5+D_BAND),a
        cmp     #<3,a
        bne     hq_rgx
        move    #>RBUF,r1
        move    x:(r5+D_KCNT),x0
        do      x0,hq_rgx
        move    x:(r1),a
        asr     #3,a,a
        move    a,x:(r1)+
hq_rgx:
        rts
