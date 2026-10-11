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

; ---- the mode (DIAG13), once per call before the render: 303 1-31 the tone, 32-127 the riff
hq_mode:
        move    x:(r5+D_KNB),a                  ; 303 << 8
        clr     b
        cmp     #>$2000,a
        blt     hq_mset
        move    #>2,b
hq_mset:
        move    b1,x:(r5+D_BAND)
        rts

; ---- RELOC (both payloads, DIAG13): the engine's run-1 block (216 words: its X working set and the
; wrapper's words) runs at X:$7b24-$7bfb, in stock's unreferenced X:$7a92-$7fff: a memory partition
; with no DMA on either core (DIAG12: dense core work in a DMA's partition stalls the DMA; on core 0
; that slips the ColdFire handoff). The loader puts the words XD above, in SPRING's records. SIGA
; (X:$7b04, unused) marks the copy done until power-off. m1 is linear (hq_entry). Uses a, r1, n1.
hq_reloc:
        move    x:>SIGA,a
        cmp     #>$5a5a5a,a
        beq     hq_rldone
        move    #>NXD,n1
        move    #>OLD1,r1
        do      #216,hq_rla
        move    x:(r1),a
        nop                                     ; one read of the loader's block in four cycles
        move    a,x:(r1+n1)
        nop
        move    (r1)+
hq_rla:
        move    #>$5a5a5a,a
        move    a,x:>SIGA
hq_rldone:
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
