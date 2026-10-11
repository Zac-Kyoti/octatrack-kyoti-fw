; SPDX-License-Identifier: MIT
; SPDX-FileCopyrightText: 2026 Zac-Kyoti
; ===========================================================================
; OT-303 hardware probe -- the wrapper (DIAGNOSTIC image only; reference/handoffs/OT303_SCOPE.md).
; Appended to tools/ot303/ot303_engine.asm (its layout equates and the `ot303` routine) by
; tools/ot303/hwprobe_image.py, placed in SPRING REV's program words (DARK REV's 35-word helper
; moved to the region's end by the builder: one contiguous 1,028-word block).
;
; DIAG14: the voice runs at the per-track SOURCE seam (octabam ANALOG BD's host). The stock
; `move a,x:>$20e` just before the source (payload A P:$39c, B P:$1a2) is a jsr to sg_entry. On
; the core's 303 track the engine renders the frame's 16 samples into X:0 (L, R interleaved, where
; the stock source puts them), and the stock code continues after the source (A P:$426, B P:$221):
; AMP, FX1, FX2 run on the voice. Every other track returns into the stock source untouched (the
; glue clobbers b, x0 and the condition codes only; the stock source loads them before it reads).
;
; DJ EQ is the remote control (its process routine, X:$235[$0d], enters hq_entry). Page 2:
;   slot 6 BURN  bits 16-23: 24 * BURN cycles per sample, before DJ EQ, always (the burn probe)
;   slot 7 303   bits 8-15: 0 off; 1-31 TONE (a 110 Hz saw, no engine), 32-127 RIFF (the engine,
;                saw: a built-in 16-step bar of the Hot voice, 130 BPM). A DJ EQ with 303 up
;                CLAIMS its track for its core's voice (OWN, first claim wins) and refreshes the
;                claim every frame (LIVE = 2); the seam counts LIVE down on each render and frees
;                the voice when it reaches 0 (303 back to 0, DJ EQ removed: 2 frames later).
;                DJ EQ itself then processes the voice like any source (it is no longer bypassed).
; One engine per core: a second claim on the same core waits until the first is released.
;
; Rules (both broke the unit): no REP (it holds off the host-port IRQs: torn transfers); no dense
; working data in a DMA's 8K partition (core 0: $0000, $2000, $4000, $8000): run 1 (the engine's X
; working set and these words) runs at X:$7b24 on both cores, in stock's unreferenced $7a92-$7fff.
; hq_reloc copies it there from SPRING's records (XD above) on the first claim.
; The filter's coefficient tables (Y, 860 words at LT) build at the seam on the claimed track's
; first frames, 16 entries a frame (15 frames, the track's own source heard meanwhile), from b0 and
; kp/64 in SPRING's X records; then the voice.
; ===========================================================================
R2      equ     $8afc           ;@LAYOUT X run 2 (packed b0, kp), at run time
XD      equ     $0              ;@LAYOUT the loader's copy is XD words above
NXD     equ     $0              ;@LAYOUT -XD (24 bits)
CONT    equ     $426            ;@LAYOUT the stock code after the source (A $426, B $221)
RAWP    equ     1               ;@LAYOUT 1: this payload's source has the raw path (A: bit 18)

PB      equ     XB-$1c          ; X, 28 words before the engine's block (reached by pointer)
SAWW    equ     PB+0            ; W1 W2 W3 SQ for the saw
SQRW    equ     PB+4            ; W1 W2 W3 SQ for the square
L0C     equ     PB+8            ; L0_16 (Y host word, constant)
AG8C    equ     PB+9            ; AG_8 (Y host word, constant)
HB1I    equ     PB+11           ; 16: the 15-tap's odd taps (YW's HB1C), copied at stage 0

; r5 = XM through the wrapper: one-word moves x:(r5+d), -64 <= d <= 63, reach the engine's host
; words below it and the wrapper's words above it. (Address registers take two words either way.)
XM      equ     XB+$40
MSAV    equ     XB+$35          ; m0..m7 on entry (the gap after XW)
TPH     equ     XB+$49          ; the tone's phase (the gap after XC)
TINC    equ     XB+$4a          ; the tone's increment
T110    equ     $a3a3           ; 110 Hz: 2^24 * 110 / 44100
WB      equ     XB+$70          ; X, 76 words after the engine's block
STG     equ     WB+0            ; 0..1 building the tables, 2 running
SV_R2   equ     WB+6            ; the seam's r2 while the tables build
AMPT    equ     WB+14           ; the trigger's AMP2
RBUF    equ     WB+16           ; 16: the engine's output
PAT     equ     WB+32           ; 16 steps: bit 23 rest, bit 22 accent, bits 0-15 the pitch increment
VARS    equ     WB+48           ; 4 x 5 host words C_MEG M_AMP AG8 AGFM K8:
VAR_AOF equ     VARS+5          ;   accent on (VARS), accent gate off,
VAR_NON equ     VARS+10         ;   normal on,
VAR_NOF equ     VARS+15         ;   normal gate off
TRIG    equ     WB+68           ; M48 hi, lo for an accent, then for a normal note
TRIGN   equ     TRIG+2
OLD1    equ     PB+XD           ; the loader's copy of PB..PB+215 (X run 1)
SIGA    equ     XB-$3c          ; X:$7b04, below run 1 in the unreferenced region: the copy's mark
OWN     equ     XB-$3b          ; the claimed track: x:$418 + 1 ($1 $21 $41 $61), 0 = none
LIVE    equ     XB-$3a          ; frames the claim lasts without a refresh
KNB     equ     XB-$39          ; the claiming DJ EQ's 303 knob << 8
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
D_BAND  equ     $3f             ; the render: 0 tone, 2 riff (hq_mode)
D_TINC  equ     $a              ; +: TINC
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

; ---- DJ EQ's process routine: the remote control. With 303 up it claims the voice for its track
; (the first claim also copies run 1 into place); it always leaves through BURN and DJ EQ's stock
; proc (which reads r0 r6 r7 n7 and the m registers on entry: all kept here; a, b, x, y1, r1, n1
; change).
hq_entry:
        move    x:(r6+$c),a
        and     #>$7f00,a
        beq     hq_out                          ; 303 = 0: no claim
        move    a1,y1                           ; the knob
        move    m1,x1
        move    #>$ffffff,x0
        move    x0,m1
        bsr     hq_reloc
        move    x1,m1
        move    x:>$418,b                       ; this track: x:$418 + 1
        add     #<$1,b
        move    x:>OWN,a
        tst     a
        beq     hq_claim                        ; the voice is free
        cmp     b,a
        bne     hq_out                          ; another track has it
hq_claim:
        move    b1,x:>OWN
        move    #>2,x0
        move    x0,x:>LIVE
        move    y1,x:>KNB
hq_out:
        bsr     hq_burn
hq_djeq:
        dc      $0d10c0,0                       ; bra >DJ EQ's stock proc: the builder writes the
                                                ; displacement and checks it by disassembly

; ---- the source seam (jsr from A P:$39c / B P:$1a2). Not the 303 track: back into the stock
; source with b, x0 and the CCR changed. The 303 track: while the tables build, one chunk, then
; the stock source (r2 kept: payload A's reads the track word through it); then the voice, and
; on at CONT.
sg_entry:
        move    a,x:>$20e                       ; the stock instruction the jsr replaced
        move    x:>$418,b
        add     #<$1,b
        move    x:>OWN,x0
        cmp     x0,b
        bne     sg_stock
        move    x:>SIGA,b
        move    #>$5a5a5a,x0
        cmp     x0,b
        bne     sg_stock
        move    x:>LIVE,b
        tst     b
        beq     sg_free
        move    #>1,x0
        sub     x0,b
        move    b1,x:>LIVE
        bsr     hq_msave
        move    #>XM,r5
        move    x:(r5+D_STG),a
        move    #>2,x0
        cmp     x0,a
        beq     sg_voice
        move    r2,x:>SV_R2
        bsr     hq_init
        bsr     hq_mrest
        move    x:>SV_R2,r2
        rts
sg_free:
        move    b1,x:>OWN                       ; b = 0: the claim lapsed
sg_stock:
        rts
sg_voice:
; the next track's ring base, as the stock source would leave it (payload A: not on the raw path,
; bit 18 of the track word; payload B has no raw path)
        move    #>RAWP,b
        tst     b
        beq     sg_ring
        move    x:(r2+$1e),b
        btst    #18,b1
        bcs     sg_noring
sg_ring:
        move    x:>$20b,b
        move    #>$80,x0
        add     x0,b
        move    b1,x:>$20b
sg_noring:
        move    x:>KNB,x0
        move    x0,x:(r5+D_KNB)
; the wave words: the saw
        move    #>SAWW,r1
        move    x:(r1)+,x0
        move    x0,x:(r5-N_W1)
        move    x0,x:(r5+D_W1A)
        move    x:(r1)+,x0
        move    x0,x:(r5+D_W2)
        move    x:(r1)+,x0
        move    x0,x:(r5+D_W3)
        move    x:(r1)+,x0
        move    x0,x:(r5-N_SQ)
        move    #>16,x0
        move    x0,x:(r5+D_REM)
        move    #0,x0
        move    x0,x:(r5+D_OUTA)
        bsr     hq_mode                         ; D_BAND: 0 tone, 2 riff
; render up to each event, then the event
hq_loop:
        move    x:(r5+D_EVC),a
        tst     a
        bne     hq_noev
        bsr     hq_event
        move    x:(r5+D_EVC),a
hq_noev:
        move    x:(r5+D_REM),b
        move    a,x1
        cmp     x1,b
        tgt     x1,b                            ; b = min(REM, EVC)
        move    b,x:(r5+D_KCNT)
        move    x:(r5+D_BAND),a
        tst     a
        beq     hq_tone                         ; 0: TONE, no engine
        move    b1,r7
        move    #>RBUF,r3
        bsr     ot303
        move    #>XM,r5
        bra     hq_copy
hq_tone:
; TONE: KCNT samples of a 110 Hz (TINC) saw at -12 dBFS into RBUF
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
hq_copy:
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
; m0-m7 back as found; drop the seam's return: the stock source is skipped
        bsr     hq_mrest
        move    ssh,x0
        dc      $0af080,CONT                    ; jmp >CONT (checked by disassembly)

; ---- m0-m7: saved as found into MSAV, then all linear (m1 first: r1 is the save pointer). Uses
; x0 x1 r1.
hq_msave:
        move    m1,x0
        move    #>$ffffff,x1
        move    x1,m1
        move    #>MSAV,r1
        move    m0,x:(r1)+
        move    x0,x:(r1)+
        move    m2,x:(r1)+
        move    m3,x:(r1)+
        move    m4,x:(r1)+
        move    m5,x:(r1)+
        move    m6,x:(r1)+
        move    m7,x:(r1)+
        move    x1,m0
        move    x1,m2
        move    x1,m3
        move    x1,m4
        move    x1,m5
        move    x1,m6
        move    x1,m7
        rts
; ---- m0-m7 back from MSAV (m1..m7 through r0, m0 still linear, m0 last). Uses r0.
hq_mrest:
        move    #>MSAV,r0
        move    (r0)+
        move    x:(r0)+,m1
        move    x:(r0)+,m2
        move    x:(r0)+,m3
        move    x:(r0)+,m4
        move    x:(r0)+,m5
        move    x:(r0)+,m6
        move    x:(r0)+,m7
        move    x:>MSAV,m0
        rts

; ---- the tables, one chunk per call (a = STG)
hq_init:
        tst     a
        bne     hq_st1
; stage 0: clear the Y state block (YW, PP, the 43-tap's branches) and the tanh table (the
; square's, not built: it renders silence), then YW's constants
        clr     a
        move    #>YS,r0
        do      #172,hq_z1
        move    a,y:(r0)+
        nop
hq_z1:
        move    #>TH,r0
        do      #1026,hq_z2
        move    a,y:(r0)+
        nop
hq_z2:
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

; ---- the mode, once per render: 303 1-31 the tone, 32-127 the riff
hq_mode:
        move    x:(r5+D_KNB),a                  ; 303 << 8
        clr     b
        cmp     #>$2000,a
        blt     hq_mset
        move    #>2,b
hq_mset:
        move    b1,x:(r5+D_BAND)
        rts

; ---- RELOC: the engine's run-1 block (216 words: its X working set and the wrapper's words) runs
; at X:$7b24-$7bfb, in stock's unreferenced X:$7a92-$7fff: a memory partition with no DMA on either
; core. The loader puts the words XD above, in SPRING's records. SIGA (X:$7b04, unused) marks the
; copy done until power-off; the copy also frees the voice (OWN, LIVE). m1 is linear. Uses a, r1, n1.
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
        clr     a
        move    a,x:>OWN
        move    a,x:>LIVE
        move    #>$5a5a5a,a
        move    a,x:>SIGA
hq_rldone:
        rts
