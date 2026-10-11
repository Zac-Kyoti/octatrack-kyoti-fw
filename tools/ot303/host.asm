; SPDX-License-Identifier: MIT
; SPDX-FileCopyrightText: 2026 Zac-Kyoti
; ===========================================================================
; OT-303 machine -- the DSP host (reference/handoffs/OT303_SCOPE.md §12 item 1b). Appended to
; tools/ot303/ot303_engine.asm by tools/ot303/hwprobe_image.py (HOST=1), placed in SPRING REV's
; program words (DARK REV's 35-word helper moved to the region's end by the builder).
;
; The voice runs at the per-track SOURCE seam (octabam ANALOG BD's host; DIAG14 proved it on the
; unit): the stock `move a,x:>$20e` before the source (payload A P:$39c, B P:$1a2) is a jsr to
; sg_entry. An OT-303 track's record is the control record tools/ot303/cf/control.c writes:
;   w0 $3303, w2 $0909  the signature;  w3  1 when this frame carries the track's trig (its sample
;   offset is the stock x:$20c);  w8..w19  the twelve knob bytes (not read yet)
; Any other record returns into the stock source untouched (b, x0, r4 and the CCR changed; the
; stock source loads them before it reads).
; One voice per core (the ColdFire admits one OT-303 per four tracks): the first signed track
; claims it (OWN) and refreshes the claim every frame (LIVE = 2); the core's first track ages it
; each frame, so a track that stops being an OT-303 frees the voice 2 frames later. Another signed
; track on the same core renders silence. Its frame: 16 samples, L and R, into X:0, and the stock
; code continues after the source (A P:$426, B P:$221): AMP, FX1, FX2 run on the voice.
; Notes (the built-in Hot bar, until the sequencer drives the voice -- item 2): each trig starts
; the next of the bar's 16 steps at the trig's sample; the gate closes 2,544 samples later (a 16th
; at 130 BPM) or at the next trig. Silence while the tables build (the first 15 frames).
;
; Rules (both broke the unit): no REP; no dense working data in a DMA's 8K partition: run 1 (the
; engine's X working set and these words) runs at X:$7b24 on both cores, in stock's unreferenced
; $7a92-$7fff; hq_reloc copies it there from SPRING's records (XD above) on the first frame.
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
WB      equ     XB+$70          ; X, 76 words after the engine's block
STG     equ     WB+0            ; 0..1 building the tables, 2 running
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
OWN     equ     XB-$3b          ; the core's voice: its track's x:$418 + 1 ($1 $21 $41 $61), 0 = none
LIVE    equ     XB-$3a          ; frames the claim lasts without a refresh
TRF     equ     XB-$39          ; this frame's trig flag (the record's w3)
; displacements from XM (the operand's sign is written out: the assembler wants small numbers)
D_STG   equ     $30             ; +: WB+0..15
D_CNK   equ     $31             ; chunk within the stage
D_EVC   equ     $32             ; samples to the next event (0: an event is due)
D_HALF  equ     $33             ; 0: the next event starts a step, 1: it ends the gate
D_STEP  equ     $34
D_CURW  equ     $35             ; this step's pattern word
D_REM   equ     $3a             ; samples still to render in this call
D_OUTA  equ     $3b             ; the audio block pointer (interleaved L/R)
D_KCNT  equ     $3d             ; this render's sample count
D_AMPT  equ     $3e             ; the trigger's AMP2
D_TRG   equ     $3f             ; samples to this frame's trig ($7fffff: none)
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

; ---- the source seam (jsr from A P:$39c / B P:$1a2)
sg_entry:
        move    a,x:>$20e                       ; the stock instruction the jsr replaced
        move    x:>$418,b
        tst     b
        bne     sg_sig
        move    x:>LIVE,b                       ; the core's first track: the claim ages
        tst     b
        beq     sg_sig
        move    #>1,x0
        sub     x0,b
        move    b1,x:>LIVE
        bne     sg_sig
        move    b1,x:>OWN                       ; b = 0: the voice is free
sg_sig:
        move    x:>$209,r4                      ; this track's record
        move    #>$003303,x0
        move    x:(r4),b
        and     #>$ffff,b
        cmp     x0,b
        bne     sg_stock
        move    #>$000909,x0
        move    x:(r4+$2),b
        and     #>$ffff,b
        cmp     x0,b
        beq     sg_ours
sg_stock:
        rts
sg_ours:
        move    x:(r4+$3),b                     ; the trig flag
        and     #>$ffff,b
        move    b1,x:>TRF
        move    m1,x1                           ; run 1 into place first (MSAV is inside it): m1
        move    #>$ffffff,x0                    ; linear for the copy, then as found
        move    x0,m1
        bsr     hq_reloc
        move    x1,m1
        bsr     hq_msave
; the next track's ring base, as the stock source would leave it (payload A: not on the raw path,
; bit 18 of the track word; an OT-303 track is FLEX, but the stock rule is kept)
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
; the claim: this track when the voice is free or already ours
        move    x:>$418,b
        add     #<$1,b
        move    x:>OWN,a
        tst     a
        beq     sg_claim
        cmp     b,a
        bne     sg_silent                       ; another OT-303 on this core has it
sg_claim:
        move    b1,x:>OWN
        move    #>2,x0
        move    x0,x:>LIVE
        move    #>XM,r5
        move    x:(r5+D_STG),a
        move    #>2,x0
        cmp     x0,a
        beq     sg_voice
        bsr     hq_init                         ; a table chunk; this frame is silent
sg_silent:
        clr     a
        move    #0,r0
        do      #32,sg_z
        move    a,x:(r0)+
sg_z:
        bra     sg_out
sg_voice:
        move    #>16,x0
        move    x0,x:(r5+D_REM)
        move    #0,x0
        move    x0,x:(r5+D_OUTA)
        move    #>$7fffff,a                     ; no trig this frame
        move    x:>TRF,b
        tst     b
        beq     sg_notrig
        move    x:>$20c,a                       ; the trig's sample in this frame
sg_notrig:
        move    a,x:(r5+D_TRG)
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
; render up to each event (the gate's end, the trig), then the event
hq_loop:
        move    x:(r5+D_EVC),a
        tst     a
        bne     hq_noeoff
        bsr     hq_gateoff
hq_noeoff:
        move    x:(r5+D_TRG),a
        tst     a
        bne     hq_notrg
        bsr     hq_start
hq_notrg:
        move    x:(r5+D_REM),b
        move    x:(r5+D_EVC),x1
        cmp     x1,b
        tgt     x1,b
        move    x:(r5+D_TRG),x1
        cmp     x1,b
        tgt     x1,b                            ; b = min(REM, EVC, TRG)
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
        move    x:(r5+D_TRG),b
        sub     x0,b
        move    b,x:(r5+D_TRG)
        move    x:(r5+D_REM),a
        sub     x0,a
        move    a,x:(r5+D_REM)
        bne     hq_loop
; m0-m7 back as found; drop the seam's return: the stock source is skipped
sg_out:
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

; ---- a trig: the bar's next step starts (pitch, host words, trigger); a gate still open closes
; first. r5 = XM.
hq_start:
        move    x:(r5+D_HALF),a
        tst     a
        beq     hq_st_open
        bsr     hq_gateoff
hq_st_open:
        move    #>$7fffff,x0
        move    x0,x:(r5+D_TRG)
        move    #>2544,x0
        move    x0,x:(r5+D_EVC)
        move    #>YS,r4
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
; ---- the gate's end: the step's host words go to their gate-off values, the bar moves on
hq_gateoff:
        move    #>$7fffff,x0
        move    x0,x:(r5+D_EVC)
        move    x:(r5+D_HALF),a
        tst     a
        beq     hq_evret
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
