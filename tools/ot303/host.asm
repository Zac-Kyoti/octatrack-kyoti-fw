; SPDX-License-Identifier: MIT
; SPDX-FileCopyrightText: 2026 Zac-Kyoti
; ===========================================================================
; OT-303 machine -- the DSP host (reference/handoffs/OT303_SCOPE.md §12 items 1b, 2). Appended to
; tools/ot303/ot303_engine.asm by tools/ot303/hwprobe_image.py (HOST=1), placed in SPRING REV's
; program words (DARK REV's 35-word helper moved to the region's end by the builder).
;
; The voice runs at the per-track SOURCE seam (octabam ANALOG BD's host; DIAG14 proved it on the
; unit): the stock `move a,x:>$20e` before the source (payload A P:$39c, B P:$1a2) is a jsr to
; sg_entry. An OT-303 track's record is the control record tools/ot303/cf/record.c writes. The
; transport carries each ColdFire long as two 16-bit words (high half first, the DSP word's top 8
; bits not ours); a 24-bit word v rides one long, bits 23-8 in the high half, 7-0 in the low:
;   w0 $3303, w2 $0909  the signature;  w1  the record's number (one more each frame)
;   w3                  bit 0: a note starts at the frame's trig sample (the stock x:$20c);
;                       bit 1: it slides (no retrigger when the gate is still open)
;   w4..w27             12 continuous words, every frame (Open303's setters act at once):
;                       CS ES8 RS BG SC SQ W1 W1 W2 W3 L0_16 AG_8
;   w28..w49            11 note words, read only with bit 0: C_MEG AG8 AGFM K8 MOFF (M_AMP at the
;                       gate's end) GL (gate samples, $7fffff: held) M_AMP INC_T M48H M48L AMP2
;   w50..w53            a table chunk: its Y address and length, then w54.. its words. The
;                       ColdFire cycles through the voice's Y image (tanh, the coefficient table,
;                       the state block); the DSP takes the chunks in order until the image is
;                       complete, and renders silence until then.
; A record whose number is this track's last one taken or the one before is old: the track's voice
; stopped rendering and both ping-pong slots still hold its last records (a Part change, a hard
; stop). It renders silence and does not refresh the claim, so the voice is freed 2 frames later
; and never replays an old note.
; Any other record returns into the stock source untouched (b, x0, r4 and the CCR changed; the
; stock source loads them before it reads).
; One voice per core (the ColdFire admits one OT-303 per four tracks): the first signed track
; claims it (OWN) and refreshes the claim every frame (LIVE = 2); its own track's first stock
; record frees it at once, and the core's first track ages it each frame (a claim not refreshed
; lapses 2 frames later). Another signed
; track on the same core renders silence. Its frame: 16 samples, L and R, into X:0, and the stock
; code continues after the source (A P:$426, B P:$221): AMP, FX1, FX2 run on the voice.
; Notes: a note's words take effect at its sample; its gate closes GL samples later (M_AMP to the
; release, K8 to 0) unless the next note comes first. A slide into an open gate only moves the
; pitch target and the accent words (Open303 slideToNote); anything else retriggers (triggerNote).
; A retrigger from silence (the amp envelope under IDLE) also restarts the saw just before its edge: Open303's
; oscillator runs free after its first note, so a low note's first edge could come up to a period
; after its trig (MT6 on the unit: late, galloping low notes).
;
; Rules (both broke the unit): no REP; no dense working data in a DMA's 8K partition: run 1 (the
; engine's X working set and these words) runs at X:$7b24 on both cores, in stock's unreferenced
; $7a92-$7fff; hq_reloc copies it there from SPRING's records (XD above) on the first frame.
; ===========================================================================
XD      equ     $0              ;@LAYOUT the loader's copy is XD words above
NXD     equ     $0              ;@LAYOUT -XD (24 bits)
CONT    equ     $426            ;@LAYOUT the stock code after the source (A $426, B $221)
RAWP    equ     1               ;@LAYOUT 1: this payload's source has the raw path (A: bit 18)

PB      equ     XB-$1c          ; X, 28 words before the engine's block (run 1's start)
; r5 = XM through the wrapper: one-word moves x:(r5+d), -64 <= d <= 63, reach the engine's host
; words below it and the wrapper's words above it. (Address registers take two words either way.)
XM      equ     XB+$40
MSAV    equ     XB+$35          ; m0..m7 on entry (the gap after XW)
WB      equ     XB+$70          ; X, 76 words after the engine's block
RBUF    equ     WB+16           ; 16: the engine's output
CDST    equ     WB+32           ; 10: the continuous X words' addresses (CS .. W3, in record order)
NDST    equ     WB+42           ; 6: the note words' X addresses (C_MEG AG8 AGFM K8, WB's MOFF, EVC)
OLD1    equ     PB+XD           ; the loader's copy of PB..PB+215 (X run 1)
SIGA    equ     XB-$3c          ; X:$7b04, below run 1 in the unreferenced region: the copy's mark
OWN     equ     XB-$3b          ; the core's voice: its track's x:$418 + 1 ($1 $21 $41 $61), 0 = none
LIVE    equ     XB-$3a          ; frames the claim lasts without a refresh
TRF     equ     XB-$39          ; this frame's event bits (the record's w3); bit 7: an old record
LSEQ    equ     XB-$38          ; 4: each track's last record number taken (x:$418 / $20)
LSEQ1   equ     XB-$37
LSEQ2   equ     XB-$36
LSEQ3   equ     XB-$35
; Y staging, in the gap between the coefficient table and the state block (the image's zeros:
; written by the chunks only before the voice runs)
CB      equ     YS-$3c          ; 12: the continuous words
NB      equ     CB+12           ; 11: the note words
CHH     equ     NB+11           ; 2: the chunk's address and length
YBEG    equ     TH              ; the Y image: TH .. the state block's end
YEND    equ     YS+172
W_CONT  equ     4               ; record words
W_CHK   equ     50
; displacements from XM (the operand's sign is written out: the assembler wants small numbers)
D_STG   equ     $30             ; +: WB+0..15. 0 the tables arriving, 2 running
D_EXP   equ     $31             ; the next chunk's Y address
D_EVC   equ     $32             ; samples to the gate's end ($7fffff: none)
D_HALF  equ     $33             ; 1: the gate is open
D_MOFF  equ     $34             ; M_AMP for the gate's end
D_REM   equ     $3a             ; samples still to render in this call
D_OUTA  equ     $3b             ; the audio block pointer (interleaved L/R)
D_KCNT  equ     $3d             ; this render's sample count
D_TRG   equ     $3f             ; samples to this frame's note ($7fffff: none)
N_MAMP  equ     $34             ; -: XW's host words
N_K8    equ     $33
; Y host words from YS (r4)
E_INCT  equ     0
E_S48H  equ     1
E_S48L  equ     2
E_M48H  equ     3
E_M48L  equ     4
E_L016  equ     6
E_AG_8  equ     7
E_AMP2  equ     8
E_PH    equ     11
IDLE    equ     $000400         ; AMP2 below this (-66 dB under a note's start): the voice is silent

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
        eor     x0,b                            ; Z on B1 alone (the transport's top bits are not ours)
        bne     sg_stock
        move    #>$000909,x0
        move    x:(r4+$2),b
        and     #>$ffff,b
        eor     x0,b
        beq     sg_ours
sg_stock:
        move    x:>$418,b                       ; the voice's own track now stock (a Part change,
        add     #<$1,b                          ;  the machine changed): free the voice at once, so
        move    x:>OWN,x0                       ;  a later track can claim it this same frame
        eor     x0,b
        bne     sg_sret
        clr     b
        move    b1,x:>OWN
        move    b1,x:>LIVE
sg_sret:
        rts
sg_ours:
        move    x:(r4+$3),b                     ; the event bits
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
; the record's number: new, or an old record (silence, no claim)
        move    x:>$418,a
        lsr     #5,a
        move    #>LSEQ,r1
        move    a1,n1
        move    x:(r4+$1),b
        and     #>$ffff,b
        move    b1,x1
        move    x:(r1+n1),x0                    ; the last one taken
        eor     x0,b
        beq     sg_silent                       ; the same
        move    x1,b
        add     #<$1,b
        and     #>$ffff,b
        eor     x0,b
        beq     sg_silent                       ; the one before
        move    x1,x:(r1+n1)
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
; the record's words: the continuous ones, then the note's (they follow) when a note starts here
        move    x:>$209,r4
        move    #>W_CONT,n4
        move    #>CB,r1
        move    (r4)+n4
        move    #>12,x1
        bsr     hq_unp
        move    #>$7fffff,a                     ; no note this frame
        move    x:>TRF,b
        btst    #0,b1
        bcc     sg_notrig
        move    #>11,x1                         ; r1 = NB
        bsr     hq_unp
        move    x:>$20c,a                       ; the note's sample in this frame
sg_notrig:
        move    a,x:(r5+D_TRG)
        move    #>CB,r1
        move    #>CDST,r2
        move    #>10,x1
        bsr     hq_copy
        move    #>YS,r4
        move    y:(r1)+,x0
        move    x0,y:(r4+E_L016)
        move    y:(r1)+,x0
        move    x0,y:(r4+E_AG_8)
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

; ---- x1 record word pairs at r4 -> 24-bit words at y:(r1)+ (the high word's low 16 bits are
; bits 23-8, the low word's low 8 bits are bits 7-0). Uses a b x0; r4, r1 advance.
hq_unp:
        do      x1,hq_upend
        move    x:(r4)+,a
        asl     #8,a,a
        move    x:(r4)+,b
        and     #>$ff,b
        move    b1,x0
        or      x0,a
        move    a1,y:(r1)+
hq_upend:
        rts
; ---- x1 Y words at r1 -> the X addresses listed at r2. Uses r0 x0; r1, r2 advance.
hq_copy:
        do      x1,hq_cyend
        move    x:(r2)+,r0
        move    y:(r1)+,x0
        move    x0,x:(r0)
hq_cyend:
        rts

; ---- the tables: the record's chunk, when it is the next one (D_EXP); the last one starts the
; voice (STG 2). r5 = XM.
hq_init:
        move    x:>$209,r4
        move    #>W_CHK,n4
        move    #>CHH,r1
        move    (r4)+n4
        move    #>2,x1
        bsr     hq_unp                          ; r4 -> the chunk's words
        move    #>CHH,r1
        move    x:(r5+D_EXP),x0
        move    y:(r1)+,a
        cmp     x0,a
        bne     hq_evret                        ; not the next one
        move    y:(r1),x1
        move    a1,r1
        add     x1,a
        move    a1,x:(r5+D_EXP)
        bsr     hq_unp
        move    x:(r5+D_EXP),a
        move    #>YEND,x0
        cmp     x0,a
        blt     hq_evret
        move    #>2,x0
        move    x0,x:(r5+D_STG)
        rts

; ---- a note at its sample: the words both kinds take, then (unless it slides into an open gate)
; the retrigger: the pitch slew, the main envelope and the amp envelope restart. r5 = XM.
hq_start:
        move    #>$7fffff,x0
        move    x0,x:(r5+D_TRG)
        move    #>NB,r1
        move    #>NDST,r2
        move    #>6,x1
        bsr     hq_copy                         ; C_MEG AG8 AGFM K8, MOFF, GL -> EVC
        move    #>YS,r4
        move    y:(r1)+,x1                      ; M_AMP (the gate open)
        move    y:(r1)+,x0                      ; INC_T
        move    x0,y:(r4+E_INCT)
        move    x:>TRF,a
        btst    #1,a1
        bcc     hq_trig
        move    x:(r5+D_HALF),a
        tst     a
        bne     hq_evret                        ; a slide into an open gate
hq_trig:
        move    y:(r4+E_AMP2),b                 ; a note from silence starts its saw 22 samples
        move    #>IDLE,a                        ;  (0.5 ms) before its edge: the edge lands as the
        cmp     a,b                             ;  amp has opened, so the note sounds 1-2 ms after
        bge     hq_live                         ;  its trig at any pitch; a note into a sounding one
        move    #>44,y0                         ;  keeps its phase
        mpy     y0,x0,a                         ; a1:a0 = 88 INC_T, an integer (22 samples x 4)
        move    a0,y1
        move    #>$7fffff,b
        sub     y1,b
        move    b1,y:(r4+E_PH)                  ; the phase, modulo 2
hq_live:
        move    x1,x:(r5-N_MAMP)
        move    x0,y:(r4+E_S48H)
        clr     a
        move    a,y:(r4+E_S48L)
        move    y:(r1)+,x0
        move    x0,y:(r4+E_M48H)
        move    y:(r1)+,x0
        move    x0,y:(r4+E_M48L)
        move    y:(r1)+,x0
        move    x0,y:(r4+E_AMP2)
        move    #>1,x0
        move    x0,x:(r5+D_HALF)
hq_evret:
        rts
; ---- the gate's end: the amp envelope releases (MOFF), the declicker's MEG feed stops (K8 0)
hq_gateoff:
        move    #>$7fffff,x0
        move    x0,x:(r5+D_EVC)
        move    x:(r5+D_HALF),a
        tst     a
        beq     hq_evret
        clr     a
        move    a,x:(r5+D_HALF)
        move    a,x:(r5-N_K8)
        move    x:(r5+D_MOFF),x0
        move    x0,x:(r5-N_MAMP)
        rts


; ---- RELOC: the engine's run-1 block (216 words: its X working set and the wrapper's words) runs
; at X:$7b24-$7bfb, in stock's unreferenced X:$7a92-$7fff: a memory partition with no DMA on either
; core. The loader puts the words XD above, in SPRING's records. SIGA (X:$7b04, unused) marks the
; copy done until power-off; the copy also frees the voice (OWN, LIVE) and clears the record numbers. m1 is linear. Uses a, r1, n1.
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
        move    a,x:>LSEQ
        move    a,x:>LSEQ1
        move    a,x:>LSEQ2
        move    a,x:>LSEQ3
        move    #>$5a5a5a,a
        move    a,x:>SIGA
hq_rldone:
        rts
