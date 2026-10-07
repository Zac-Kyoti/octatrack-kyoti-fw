; SPDX-License-Identifier: MIT
; SPDX-FileCopyrightText: 2026 Zac-Kyoti
; ===========================================================================
; OT-303 hardware probe -- the wrapper (DIAGNOSTIC image only; reference/handoffs/OT303_SCOPE.md).
; Appended to tools/ot303/ot303_engine.asm (its layout equates and the `ot303` routine) by
; tools/ot303/hwprobe_image.py, placed in SPRING REV's program words.
;
; Reached instead of DJ EQ's process routine (X:$235[$0d]); leaves through DJ EQ's stock proc,
; whose rts returns to the dispatcher. DJ EQ's proc reads r0, r6, r7, n7 and loads its ALU
; registers itself, so this keeps r0 r6 r7 n7 and may use everything else (the burn probe's
; contract, hardware-proven). m0-m7 are linear on entry and on exit (the engine restores them).
;
; Page 2 of DJ EQ (r6+$c):
;   slot 6 BURN  bits 16-23: burns 24 * BURN cycles per sample (burn_djeq.asm, unchanged)
;   slot 7 303   bits 8-15: 0 off; 1-63 the engine with the saw, 64-127 with the square. The
;                engine REPLACES the track's audio (both channels) ahead of DJ EQ, playing a
;                built-in 16-step riff (the Hot scene's first bar, 130 BPM, 50 % gate).
;                The square is COST ONLY: its tanh table is not built (no room for its data
;                beside the code in SPRING's words), it stays zero, and the square renders silence
;                through the same code path, so its cycles are the real voice's.
; One engine per core: its state is global, so a second DJ EQ with 303 > 0 on the same core
; renders the same voice again (twice the speed). Use it on one track per core.
;
; The filter's coefficient tables (Y, 860 words at LT) are built on the first calls, 16 entries
; a call (15 calls, ~6 ms), from b0 and kp/64 (215 + 1 each) the loader puts in SPRING's X records;
; the slopes are differences. The engine stays silent (the track passes untouched) until then.
; The step events (hq_event) live after DARK REV's helper: tools/ot303/hwprobe_ev.asm.
; ===========================================================================
R2      equ     $8afc           ;@LAYOUT X run 2 (packed b0, kp)
HQEV    equ     $15a9           ;@LAYOUT hq_event, after DARK REV's helper (hwprobe_ev.asm)

PB      equ     XB-$1c          ; X, 28 words before the engine's block (reached by pointer)
SAWW    equ     PB+0            ; W1 W2 W3 SQ for the saw
SQRW    equ     PB+4            ; W1 W2 W3 SQ for the square
L0C     equ     PB+8            ; L0_16 (Y host word, constant)
AG8C    equ     PB+9            ; AG_8 (Y host word, constant)
HB1I    equ     PB+11           ; 16: the 15-tap's odd taps (YW's HB1C), copied at stage 0

; r5 = XM through the wrapper: one-word moves x:(r5+d), -64 <= d <= 63, reach the engine's host
; words below it and the wrapper's words above it. (Address registers take two words either way.)
XM      equ     XB+$40
WB      equ     XB+$70          ; X, 76 words after the engine's block
STG     equ     WB+0            ; 0..1 building the tables, 2 running
SV_R0   equ     WB+6
SV_R6   equ     WB+7
SV_R7   equ     WB+8
SV_N7   equ     WB+9
AMPT    equ     WB+14           ; the trigger's AMP2
RBUF    equ     WB+16           ; 16: the engine's output
PAT     equ     WB+32           ; 16 steps: bit 23 rest, bit 22 accent, bits 0-15 the pitch increment
VARS    equ     WB+48           ; 4 x 5 host words C_MEG M_AMP AG8 AGFM K8:
VAR_AOF equ     VARS+5          ;   accent on (VARS), accent gate off,
VAR_NON equ     VARS+10         ;   normal on,
VAR_NOF equ     VARS+15         ;   normal gate off
TRIG    equ     WB+68           ; M48 hi, lo for an accent, then for a normal note
TRIGN   equ     TRIG+2
; displacements from XM (the operand's sign is written out: the assembler wants small numbers)
D_STG   equ     $30             ; +: WB+0..15
D_CNK   equ     $31             ; chunk within the stage
D_EVC   equ     $32             ; samples to the next event (0: an event is due)
D_HALF  equ     $33             ; 0: the next event starts a step, 1: it ends the gate
D_STEP  equ     $34
D_CURW  equ     $35             ; this step's pattern word
D_REM   equ     $3a             ; samples still to render in this call
D_OUTA  equ     $3b             ; the audio block pointer (interleaved L/R)
D_KNB   equ     $3c             ; the 303 knob << 8
D_KCNT  equ     $3d             ; this render's sample count
D_AMPT  equ     $3e             ; the trigger's AMP2
D_W1A   equ     $24             ; +: OCB's W1A W2 W3
D_W2    equ     $25
D_W3    equ     $26
N_CMEG  equ     $3f             ; -: XW's host words
N_AGFM  equ     $3e
N_AG8   equ     $3b
N_MAMP  equ     $34
N_K8    equ     $33
N_SQ    equ     $2d
N_W1    equ     $2b
; Y host words from YS (r4)
E_INCT  equ     0
E_S48H  equ     1
E_S48L  equ     2
E_M48H  equ     3
E_M48L  equ     4
E_L016  equ     6
E_AG_8  equ     7
E_AMP2  equ     8

BX      equ     R2              ; b0[0..214], b0[214] again
KX      equ     R2+216          ; kp[0..214], kp[214] again

hq_entry:
; ---- BURN: page-2 slot 6 (octabam's RIG BURN body; tools/ot303/burn_djeq.asm). The zero guard
; is load-bearing: DO with a count of 0 loops 65536 times; asl sets Z.
        move    x:(r6+$c),a
        and     #>$7f0000,a
        move    a1,y1
        move    n7,x0
        mpy     x0,y1,a
        asl     #$a,a,a
        beq     hq_noburn
        do      a1,hq_burnend
        nop
        nop
        nop
hq_burnend:
hq_noburn:
; ---- the 303 knob: page-2 slot 7 (bits 8-15); 0 = off. n7 = 0 (the dispatcher's second call
; can carry none) = nothing to do.
        move    x:(r6+$c),a
        and     #>$7f00,a
        beq     hq_out
        move    n7,b
        tst     b
        beq     hq_out
        move    #>XM,r5
        move    a1,x:(r5+D_KNB)
        move    r0,x:>SV_R0
        move    r6,x:>SV_R6
        move    r7,x:>SV_R7
        move    n7,x:>SV_N7
        move    x:(r5+D_STG),a
        move    #>2,x0
        cmp     x0,a
        beq     hq_run
        bsr     hq_init
        bra     hq_rest
hq_run:
; the wave words: knob >= 64 = the square
        move    #>SAWW,r1
        move    x:(r5+D_KNB),a
        move    #>$4000,x0
        cmp     x0,a
        blt     hq_saw
        move    #>SQRW,r1
hq_saw:
        move    x:(r1)+,x0
        move    x0,x:(r5-N_W1)
        move    x0,x:(r5+D_W1A)
        move    x:(r1)+,x0
        move    x0,x:(r5+D_W2)
        move    x:(r1)+,x0
        move    x0,x:(r5+D_W3)
        move    x:(r1)+,x0
        move    x0,x:(r5-N_SQ)
        move    b,x:(r5+D_REM)                  ; b = n7
        move    r0,x:(r5+D_OUTA)
; render up to each event, then the event
hq_loop:
        move    x:(r5+D_EVC),a
        tst     a
        bne     hq_noev
hq_callev:
        dc      $0d1080,0                       ; bsr >hq_event (HQEV): the builder writes the displacement
        move    x:(r5+D_EVC),a
hq_noev:
        move    x:(r5+D_REM),b
        move    a,x1
        cmp     x1,b
        tgt     x1,b                            ; b = min(REM, EVC)
        move    b,x:(r5+D_KCNT)
        move    b1,r7
        move    #>RBUF,r3
        bsr     ot303
        move    #>XM,r5
        move    #>RBUF,r1
        move    x:(r5+D_OUTA),r0
        move    x:(r5+D_KCNT),x0
        do      x0,hq_cpend
        move    x:(r1)+,a
        move    a,x:(r0)+                       ; L
        move    a,x:(r0)+                       ; R
hq_cpend:
        move    r0,x:(r5+D_OUTA)
        move    x:(r5+D_EVC),b
        sub     x0,b
        move    b,x:(r5+D_EVC)
        move    x:(r5+D_REM),a
        sub     x0,a
        move    a,x:(r5+D_REM)
        bne     hq_loop
hq_rest:
        move    x:>SV_R0,r0
        move    x:>SV_R6,r6
        move    x:>SV_R7,r7
        move    x:>SV_N7,n7
hq_out:
        dc      $0d10c0,0                       ; bra >DJ EQ's stock proc: the builder writes the
                                                ; displacement and checks it by disassembly

; ---- the tables, one chunk per call
hq_init:
        tst     a
        bne     hq_st1
; stage 0: clear the Y state block (YW, PP, the 43-tap's branches) and the tanh table (the
; square's, not built: it renders silence), then YW's constants
        clr     a
        move    #>YS,r0
        rep     #172
        move    a,y:(r0)+
        move    #>TH,r0
        rep     #1026
        move    a,y:(r0)+
        move    #>HB1I,r1
        move    #>HB1C,r0
        do      #16,hq_s0cp
        move    x:(r1)+,x0
        move    x0,y:(r0)+
hq_s0cp:
        move    #>YS,r4
        move    #>L0C,r1
        move    x:(r1)+,x0
        move    x0,y:(r4+E_L016)
        move    x:(r1)+,x0
        move    x0,y:(r4+E_AG_8)
        move    #>1,x1                          ; one chunk
        bra     hq_next
hq_st1:
; stage 1: LT, 16 entries a call: b0[i], b0[i+1] - b0[i], kp[i], kp[i+1] - kp[i]
        move    x:(r5+D_CNK),a
        asl     #4,a,a                          ; i0
        move    a1,n1
        move    a1,n2
        move    #>BX,r1
        move    #>KX,r2
        move    (r1)+n1
        move    (r2)+n2
        asl     #2,a,b                          ; 4 i0
        move    b1,n4
        move    #>LT,r4
        move    (r4)+n4
        move    #>215,b
        sub     a,b
        move    #>16,x0
        cmp     x0,b
        tgt     x0,b
        do      b1,hq_s1lp
        move    x:(r1)+,a
        move    x:(r1),b
        sub     a,b             a,y:(r4)+
        move    b,y:(r4)+
        move    x:(r2)+,a
        move    x:(r2),b
        sub     a,b             a,y:(r4)+
        move    b,y:(r4)+
hq_s1lp:
        move    #>14,x1                         ; 14 chunks: 13 x 16 + 7
        bra     hq_next
; next chunk; at the stage's last, the next stage
hq_next:
        move    #>XM,r5
        move    x:(r5+D_CNK),a
        move    #>1,x0
        add     x0,a
        cmp     x1,a
        blt     hq_keep
        clr     a
        move    x:(r5+D_STG),b
        add     x0,b
        move    b1,x:(r5+D_STG)
hq_keep:
        move    a1,x:(r5+D_CNK)
        rts
