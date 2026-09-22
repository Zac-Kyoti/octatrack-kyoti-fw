; SPDX-License-Identifier: MIT
; SPDX-FileCopyrightText: 2026 Zac-Kyoti
; ===========================================================================
; SIDE-CHAIN COMPRESSOR -- step 2 DSP code (publish tap + detector redirect).
;
; dsp_asm supports NO directives/constants and NO jmp/jcc -- only relative
; b-forms, and it substitutes labels textually.  So:
;   * every value is a literal;
;   * the one payload-specific spot is the token @KADJ@, rewritten by
;     build_sidechain2.py to  "add #3,a"  (payload A, CORE_BASE 4)  or
;     "sub #1,a"  (payload B, CORE_BASE 0):  abs_track = KEY - 1 + CORE_BASE;
;   * both routines END WITH rts.  The build hand-encodes a `jsr <cave>` at
;     each detour site, so control returns here via rts -- no branch-back.
;
; Detours the build patches into the stock DSP payload:
;   sctap  <- dispatcher func_0004a7 (A) / func_00029c (B):
;             jsr sctap (1w, donor <= $fff) + nop (1w)  over  move x:>$208,r6 (2w).
;             The following  move #$6,n6  is LEFT IN STOCK.  Cave reproduces
;             only  move x:>$208,r6 , then rts -> nop -> stock move #$6,n6.
;   scdet  <- COMPRESSOR proc+0  0x1ab1 (A) / 0x1871 (B):
;             jsr scdet (1w) + nop (1w)  over  [ move r0,n6 ; move #$61,r4 ].
;             Cave reproduces both, then rts to proc+2.
;
; keybus ring (Y):  slot(track,gen) = $800 + track*$80 + (gen&3)*$20
;   $20 words = one 16-stereo-sample block.  Quad-buffer layout reserved;
;   step 2 (same DSP core) uses gen 0, so the buffer term is 0 and omitted.
;
; Clobber budget (audited): stock reloads a,b,r0,r1,n1,x0 right after each
; rejoin.  We must leave n6 and r4 as the displaced ops set them, and not
; disturb SR across the rts (we don't -- last op before rts is a move).
;
; NO `mpy`.  Labels prefix-distinct.  AUDIT THE OUTPUT BY DISASSEMBLY.
; ===========================================================================

; ---------------------------------------------------------------------------
; HOOK 1 -- publish tap.  X:0 = this track's FX-chain input; x:$420 = its
; absolute 0..7 index.  Copy $20 words X:0 -> keybus[idx], run the two
; displaced dispatcher moves, return.
; ---------------------------------------------------------------------------
sctap:
        move    x:>$420,a               ; a1 = track index 0..7
        asl     #7,a,a                  ; a1 = index * $80
        move    a1,n1
        move    #>$800,r1
        lua     (r1)+n1,r1              ; r1 -> Y:keybus slot (buffer 0)
        move    #0,r0                   ; X:0 source
        do      #<$20,>sctpend
        move    x:(r0)+,x0
        move    x0,y:(r1)+
sctpend:
        move    x:>$208,r6              ; --- displaced (move #$6,n6 stays in stock) ---
        rts

; ---------------------------------------------------------------------------
; HOOK 2 -- detector redirect.  r0 = compressor audio buffer on entry.
; KEY (page-2 param x:(r6+$d)) == 0 -> leave r0 (stock self-detection).
; else stage keybus[key] -> X:$40 (free during detector stages 1-5; the wet
; path first writes X:$40 in stage 6) and point r0 there.  Dry/wet path
; re-anchors from n6, untouched.
; ---------------------------------------------------------------------------
scdet:
        move    r0,n6                   ; --- displaced: dry-path anchor ---
        move    x:(r6+$d),b             ; KEY param, value<<16
        asr     #$10,b,b               ; b = 0..4
        tst     b
        beq     scdrun                  ; KEY OFF: r0 unchanged (self-detect)
        move    b,a
        @KADJ@                          ; KEY 1..4 -> absolute track 0..7
        asl     #7,a,a                  ; a1 = abs * $80
        move    a1,n1
        move    #>$800,r1
        lua     (r1)+n1,r1
        move    #$40,r0                 ; X:$40 staging destination
        do      #<$20,>scdcpend
        move    y:(r1)+,x0
        move    x0,x:(r0)+
scdcpend:
        move    #$40,r0                 ; detector now streams from the key copy
scdrun:
        move    #$61,r4                 ; --- displaced ---
        rts
