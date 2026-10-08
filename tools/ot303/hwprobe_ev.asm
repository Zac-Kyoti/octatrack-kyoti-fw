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

; ---- PRE: in the RIFF band, 303 = 32 + p spends 24 * p cycles per sample BEFORE the render
; (p = 0..31; DIAG2's WATCH, clean, started the engine ~120 cycles a sample later: p ~ 5).
; r5 = XM, n7 the caller's. Uses a, x0, y1.
hq_pre:
        move    x:(r5+D_KNB),a                  ; 303 << 8
        move    #>$2000,x0
        sub     x0,a                            ; (303 - 32) << 8
        ble     hq_pzero
        cmp     x0,a
        bge     hq_pzero                        ; 303 >= 64: not the riff
        asl     #8,a,a                          ; p << 16
        move    a1,y1
        move    n7,x0
        mpy     x0,y1,a
        asl     #$a,a,a                         ; 8 * p * n7
        beq     hq_pzero
        do      a1,hq_pzero
        nop
        nop
        nop
hq_pzero:
        rts

