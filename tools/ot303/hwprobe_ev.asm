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


; ---- TONE (hq_tgen): KCNT samples of a 110 Hz (TINC) saw at -12 dBFS into RBUF
hq_tgen:
        move    #>RBUF,r1
        move    x:>TPH,a
        move    x:(r5+D_TINC),x1
        move    x:(r5+D_KCNT),x0
        do      x0,hq_tloop
        add     x1,a
        move    a1,a                            ; the phase wraps at 24 bits
        asr     #2,a,b
        move    b,x:(r1)+
hq_tloop:
        move    a1,x:>TPH
        rts

; ---- WATCH: a checksum of the engine's constant memory; the first call takes it, a later one that
; differs latches the alarm; while latched, this call is the TONE at 880 Hz
hq_watch:
        clr     a
        move    #>LT,r0
        do      #860,hq_w1
        move    y:(r0)+,x0
        add     x0,a
hq_w1:
        move    #>HB1C,r0
        do      #16,hq_w2
        move    y:(r0)+,x0
        add     x0,a
hq_w2:
        move    #>HB2C,r0                       ; HB2C .. TOPA: the X block's constant tail
        do      #31,hq_w3
        move    x:(r0)+,x0
        add     x0,a
hq_w3:
        move    #>PAT,r0                        ; the riff's pattern, host-word sets, triggers
        do      #40,hq_w4
        move    x:(r0)+,x0
        add     x0,a
hq_w4:
        move    x:>RFLG,b
        tst     b
        bne     hq_wcmp
        move    a2,x:>REF2
        move    a1,x:>REF1
        move    a0,x:>REF0
        move    #>1,x0
        move    x0,x:>RFLG
        rts
hq_wcmp:
        move    x:>REF1,b
        move    x:>REF0,b0
        move    x:>REF2,b2
        sub     b,a
        beq     hq_wok
        move    #>1,x0
        move    x0,x:>ALRM
hq_wok:
        move    x:>ALRM,b
        tst     b
        beq     hq_wret
        clr     b
        move    b,x:(r5+D_BAND)
        move    #>T880,x0
        move    x0,x:(r5+D_TINC)
hq_wret:
        rts

; ---- NOPS (mode 4) / READS (mode 5): ~400 cycles a sample, KCNT samples
hq_burnx:
        move    x:(r5+D_KCNT),x0
        move    x:(r5+D_BAND),a
        move    #>4,x1
        cmp     x1,a
        bne     hq_readsx
        do      x0,hq_nopsend
        rep     #400
        nop
        nop
hq_nopsend:
        rts
hq_readsx:
        move    #>RBUF,r1
        move    #>YS,r4
        move    #15,m1
        move    #63,m4
        do      x0,hq_readsend
        rep     #400
        move    x:(r1)+,x1      y:(r4)+,y0
        nop
hq_readsend:
        move    #>$ffffff,m1
        move    #>$ffffff,m4
        rts
