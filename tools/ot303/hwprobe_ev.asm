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


; ---- the mode (DIAG12), once per call before the render: K = 303
;   1-47 tone | 48-71 engine + tone (the riff's work, events included) | 72-87 riff / 8 |
;   88-103 riff | 104-127 X reads + tone (n7 x 384 reads of the engine's X block, 3 a loop pass)
; r5 = XM; uses a b x0 x1 r1 m1.
hq_mode:
        move    x:(r5+D_KNB),a                  ; K << 8
        clr     b
        cmp     #>$6800,a
        bge     hq_mx                           ; 104-127
        cmp     #>$5800,a
        bge     hq_mriff                        ; 88-103
        cmp     #>$4800,a
        bge     hq_mr8                          ; 72-87
        cmp     #>$3000,a
        blt     hq_mset                         ; 1-47: the tone
        move    #>1,b                           ; 48-71
        bra     hq_mset
hq_mriff:
        move    #>2,b
        bra     hq_mset
hq_mr8:
        move    #>3,b
hq_mset:
        move    b1,x:(r5+D_BAND)
        rts
hq_mx:
        move    b1,x:(r5+D_BAND)
        move    n7,b
        asl     #7,b,b
        move    #>63,x1
        move    x1,m1
        move    #>XB,r1
        do      b1,hq_xrdz
        move    x:(r1)+,x0
        move    x:(r1)+,x0
        move    x:(r1)+,x0
hq_xrdz:
        move    #>$ffffff,x1
        move    x1,m1
        rts

; ---- RELOC (payload A; the builder nops the call on B). DIAG12: the engine's run-1 block (216
; words: its X working set and the wrapper's words) runs from inside the host's own FX1 instance
; block (T6: X:$6400-$64ff), a memory partition no DMA touches; the loader puts it XD words above
; (SPRING's records, X:$89a4, the partition of core 0's ESAI DMA). DJ EQ writes its own state at
; r7 + 4 whenever it runs (303 = 0): SIGA there is our mark; when it is gone, copy again (and the
; tables rebuild from STG = 0). m1 is linear (hq_entry). Uses a, r1, n1; keeps x0 x1 y1.
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
