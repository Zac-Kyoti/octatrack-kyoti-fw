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

; ---- RELOC (payload A; the builder nops the call on B): on the first call with 303 up, copy the
; engine's X block (run 1) and the packed tables (run 2) from where the loader put them (XD above)
; to their run-time addresses. RFLAG, in the loader's copy, marks it done until power-off.
; m1 is linear (hq_entry). Uses a, r1, n1; keeps x0 x1 y1. Paced: on core 0 the loader's block shares
; a memory block with the ESAI DMA, and back-to-back reads there starve it (DIAG6's XHAM crashed).
hq_reloc:
        move    x:>RFLAG,a
        tst     a
        bne     hq_rldone
        move    #>NXD,n1
        move    #>OLD1,r1
        do      #216,hq_rla
        move    x:(r1),a
        nop                                     ; one read of the loader's block in four cycles
        move    a,x:(r1+n1)
        nop
        move    (r1)+
hq_rla:
        move    #>OLD2,r1
        do      #500,hq_rlb
        move    x:(r1),a
        nop                                     ; one read of the loader's block in four cycles
        move    a,x:(r1+n1)
        nop
        move    (r1)+
hq_rlb:
        move    #>1,a
        move    a,x:>RFLAG
hq_rldone:
        rts

; ---- the render (r7 = KCNT, r3 = RBUF): the engine, or with 303 >= 64 the METER. METER mode m =
; (303 - 64) >> 3: 0 the engine (the riff, unheard), 1-7 a calibration loop over 32 x KCNT
; iterations of three instructions, one of them a read from MTAB[m]'s 64-word block: 1 none,
; 2 X the engine's block, 3 X its loader copy, 4 X stock's instance state, 5 Y the engine's state,
; 6 Y an FX1 slot, 7 Y the engine's coefficient table.
; Timer 0 (CLK/2) restarts at the render's start; RBUF[0] = ticks << 7, RBUF[1..KCNT-1] = -(KCNT << 16).
hq_meng:
        move    x:(r5+D_KNB),a
        sub     #>$4000,a
        bge     hq_meter
hq_cot0:
        dc      $0d10c0,0                       ; bra >ot303 (its rts returns to our caller)
hq_meter:
        asr     #11,a,a                         ; m = (303 - 64) >> 3
        move    a1,n1
        clr     b
        move    b,x:>$ffff8f                    ; TCSR0: stop
        move    b,x:>$ffff8e                    ; TLR0 = 0
        move    #>1,x0
        move    x0,x:>$ffff8f                   ; TCSR0: TE, timer mode, CLK/2: TCR0 from 0
        tst     a
        bne     hq_mcal
hq_cot1:
        dc      $0d1080,0                       ; bsr >ot303
        bra     hq_mend
hq_mcal:
        move    #>MTAB,r1
        move    x:(r5+D_KCNT),b
        asl     #5,b,b
        move    #>63,x1
        move    x1,m1
        move    x:(r1+n1),r1                    ; the mode's block
        cmp     #<1,a
        beq     hq_mnop                         ; 1: no access
        cmp     #<5,a
        bge     hq_ylp                          ; 5-7: Y; 2-4: X
        do      b1,hq_mxe
        move    x:(r1)+,x0
        nop
        nop
hq_mxe:
        bra     hq_mlin
hq_ylp:
        do      b1,hq_yend
        move    y:(r1)+,x0
        nop
        nop
hq_yend:
        bra     hq_mlin
hq_mnop:
        do      b1,hq_mne
        nop
        nop
        nop
hq_mne:
hq_mlin:
        move    #>$ffffff,x1
        move    x1,m1
hq_mend:
        move    x:>$ffff8c,a                    ; TCR0: ticks since the start
        move    #>XM,r5
        move    #>RBUF,r1
        asl     #7,a,a                          ; ticks << 7 (a render's ticks stay under 65,536)
        move    a1,x:(r1)+
        move    x:(r5+D_KCNT),a
        asl     #16,a,a                         ; -(KCNT << 16): a gain-proof ruler for the ticks
        neg     a
        move    a1,x0
        move    x:(r5+D_KCNT),a
        sub     #<1,a
        beq     hq_mret
        do      a1,hq_mret
        move    x0,x:(r1)+
        nop
        nop
hq_mret:
        rts
