; SPDX-License-Identifier: MIT
; SPDX-FileCopyrightText: 2026 Zac-Kyoti
; ===========================================================================
; SIDE-CHAIN COMPRESSOR -- step 3 DSP code.
;
; Superset of tools/patch_sc_dsp.asm (step 2).  Same two detour sites in the
; stock payload (dispatcher FX1 entry -> sctap ; COMPRESSOR proc+0 -> scdet)
; plus a THIRD hook at COMPRESSOR proc-end -> sctail for SC LISTEN.
;
; New page-2 controls the DSP acts on (packing = octabam PARAM_PAGES;
; emu_sc_dsp3.py -params index in parens):
;   KEY      x:(r6+$d) bits 16-23   0..4    OFF / same-core track    (8)
;   KEY FLT  x:(r6+$d) bits  8-15   0..127  64=bypass  <64 LP  >64 HP (9)
;   KEY GAIN x:(r6+$e) bits 16-23   0..127  64=unity  ~+/-24 dB       (10)
;   SC LISTN x:(r6+$e) bits  8-15   0..1    OFF / ON  (audition key)  (11)
;
; dsp_asm quirks (see patch_sc_dsp.asm header): no directives / constants /
; jmp / jcc -- literals only, labels substituted textually (raw substring, so
; every label here is `zzNN`, all 4 chars, all distinct => none is a prefix of
; another), every routine ends `rts` (the build hand-encodes `jsr <cave>` at
; each site, control returns via rts).  Build tokens, rewritten per payload:
;   @KADJ@   "add #3,a" (payload A, CORE_BASE 4) / "sub #1,a" (payload B, 0)
;   @GTAB@   absolute P addr of the 16-word KEY GAIN table (gain/64, Q23)
;   @FTAB@   absolute P addr of the 32-word KEY FLT  table (f=2 sin(pi fc/fs), Q23)
; The tables are appended after the code by build_sidechain3.py; @GTAB@/@FTAB@
; are resolved in a first sizing pass so the `move #>imm` widths never shift.
;
; keybus ring (Y): slot(track,gen) = $800 + track*$80 + (gen&3)*$20.
;   gen 0 = the per-frame publish (sctap).  gen 1 = the SC LISTEN stash --
;   scdet writes the *processed* key there, sctail copies it to the dry buffer.
;
; SVF integrator state, per compressor instance, in the compressor's own r7
; block at r7+$16 (lp) / r7+$17 (bp) -- unused by the stock module (RE: state
; block r7+$f..$1b; disassembly of the real init routine at P:0x1864 confirms
; it zero-fills only $11/$12/$13/$1a/$1b/$f, leaving $14/$16/$17/$18 untouched
; and therefore NOT guaranteed zero -- whatever DSP memory held before this
; track's compressor instance was assigned lands there unchanged).  r7+$18 is
; OUR OWN dedicated "have I ever seeded lp/bp myself" latch (never touched by
; stock or by any other hook here): do not gate on the stock "first-block" bit
; (r7+$f) instead -- it can legitimately go warm from ordinary stock activity
; before our KEY FLT code has ever run once (e.g. KFLT parked at bypass for a
; while, then turned to LP/HP for the first time), which would otherwise seed
; the integrator from garbage at $16/$17.
;
; AUDIT THE OUTPUT BY DISASSEMBLY.  No `mpy x0,y0` (assembles as mpysu) --
; only x1,x0 / x1,y0 operand orders, which emit true signed mpy.
; ===========================================================================

; ---- HOOK 1 : publish tap (identical to step 2) ---------------------------
sctap:
        move    x:>$420,a               ; a1 = track index 0..7
        asl     #7,a,a                  ; a1 = index * $80
        move    a1,n1
        move    #>$800,r1
        lua     (r1)+n1,r1              ; r1 -> keybus slot (gen 0)
        move    #0,r0
        do      #<$20,>zz01
        move    x:(r0)+,x0
        move    x0,y:(r1)+
zz01:
        move    x:>$208,r6              ; --- displaced (move #$6,n6 stays stock) ---
        rts

; ---- HOOK 2 : detector redirect + KEY GAIN + KEY FLT ----------------------
; dsp56kEmu / DSP quirks worked around here (all fixes are also correct on real
; hardware -- verified by emu_sc_dsp3.py's probe suite):
;   (q1) `move x:(rN+disp),a` reads the wrong word -- use dest `b`, then move.
;   (q2) `move #imm,x0` short-form is LEFT-aligned -- compare via `cmp #>imm,acc`.
;   (q3) `asr #n,acc,acc` leaves the shifted-out bits in acc0, and `tst`/`cmp`
;        see the FULL accumulator -- normalise with `move acc1,otheracc` first.
scdet:
        move    r0,n6                   ; --- displaced: dry-path anchor ---
        move    x:(r6+$d),b            ; (q1) KEY|KFLT word
        asr     #$10,b,b
        move    b1,a                  ; (q3) a = KEY 0..4, a0 clean
        tst     a
        beq     zz20                   ; KEY OFF -> self-detect, skip all
        @KADJ@                         ; KEY 1..4 -> absolute track 0..7
        asl     #7,a,a
        move    a1,n1
        move    #>$800,r1
        lua     (r1)+n1,r1            ; r1 -> keybus[abs] gen 0
        move    r1,r5                 ; r5 = slot base (SC LISTEN stash)
        move    #$40,r0
        do      #<$20,>zz02
        move    y:(r1)+,x0
        move    x0,x:(r0)+
zz02:

; -- KEY GAIN : x:(r6+$e) bits 16-23, 0..127 ; 64 = unity --
        move    x:(r6+$e),b           ; (q1) KGAIN|MON word
        asr     #$10,b,b
        move    b1,a                 ; (q3) a = KEY GAIN 0..127
        cmp     #>$40,a
        beq     zz03                   ; unity -> skip
        asr     #$3,a,a               ; a1 = gain table index 0..15
        move    a1,n1
        move    #>@GTAB@,r1
        move    p:(r1+n1),x1          ; x1 = gain / 64  (Q23)
        move    #$40,r0
        do      #<$20,>zz04
        move    x:(r0),x0
        mpy     x1,x0,a
        asl     #6,a,a                ; * 64
        move    a,x:(r0)+
zz04:
zz03:

; -- KEY FLT : x:(r6+$d) bits 8-15, 0..127 ; 64 = bypass ; <64 LP ; >64 HP --
; One Chamberlin SVF loop (q = 1); n0 marks LP vs HP for the per-sample output
; select.  Input is (L+R)/2, output is written to both L and R slots.
        move    x:(r6+$d),b           ; (q1)
        asr     #$8,b,b
        move    b1,a                 ; (q3) a1 = (KEY<<8)|KFLT, a0 clean
        and     #>$ff,a              ; a = KEY FLT 0..127
        cmp     #>$40,a
        beq     zz10                   ; bypass -> no filter
        move    a1,b                  ; b = KEY FLT (b0 clean)
        cmp     #>$40,b
        blt     zz05                   ; KEY FLT < 64 -> LP
;   HP : idx = (KEY FLT - 64) >> 1 (0..31) ; marker n0 = 0
        move    b,a
        sub     #>$40,a
        asr     #$1,a,a
        move    a1,n1
        move    #0,n0
        bra     zz06
zz05:
;   LP : idx = KEY FLT >> 1 (0..31) ; marker n0 != 0
        asr     #$1,b,b
        move    b,n1
        move    #>$10,n0
zz06:
        move    #>@FTAB@,r1
        move    p:(r1+n1),x1          ; x1 = f coefficient (Q23, < 0.32)
;   NOTE: do NOT gate on the stock "first-block" bit (r7+$f) here -- it can go
;   warm from ordinary stock compressor activity before OUR code has ever run
;   a KEY FLT block (e.g. KFLT sits at bypass for a while, then gets turned to
;   LP/HP for the first time). $16/$17 are untouched by stock's own init
;   (0x1864's zero-fill list is $11/$12/$13/$1a/$1b/$f only -- confirmed by
;   disassembly), so reading them on the stock bit's word risks seeding the
;   integrator from garbage. Own the gate: $18 is ALSO untouched by stock and
;   by every other hook here, so use it as OUR single "have I ever seeded
;   lp/bp myself" latch, set only below, never by anything else.
        move    x:(r7+$18),a
        tst     a
        bne     zz07
        move    #0,y1                 ; never seeded -> lp = bp = 0
        move    #0,y0
        bra     zz08
zz07:
        move    x:(r7+$16),y1        ; warm: lp
        move    x:(r7+$17),y0        ;       bp
zz08:
        move    #$40,r0
        do      n7,>zz13
        move    x:(r0)+,x0
        move    x:(r0)-,a
        tfr     x0,b
        add     b,a
        asr     #$1,a,a               ; a = (L + R) / 2 = filter input
        move    a,x0
        mpy     x1,y0,b               ; b = f * bp
        add     y1,b                  ; b = lp + f*bp = lp'
        move    b,y1
        tfr     x0,a
        sub     b,a                   ; a = in - lp'
        sub     y0,a                  ; a = in - lp' - bp = hp   (q = 1)
        move    a,x0                  ; x0 = hp
        mpy     x1,x0,b               ; b = f * hp
        add     y0,b                  ; b = bp + f*hp = bp'
        move    b,y0
        move    n0,a                 ; marker: 0 = HP (keep x0=hp), != 0 = LP
        tst     a
        beq     zz14
        move    y1,x0                ; LP -> output lp'
zz14:
        move    x0,x:(r0)+
        move    x0,x:(r0)+
zz13:
zz12:
        move    y1,x:(r7+$16)
        move    y0,x:(r7+$17)
        move    #1,a
        move    a,x:(r7+$18)          ; latch: lp/bp are now genuinely ours

zz10:
; -- SC LISTEN : if on, stash the processed key -> keybus[key] gen 1 --
        move    x:(r6+$e),b           ; (q1)
        asr     #$8,b,b
        move    b1,a                 ; (q3)
        and     #>$ff,a
        tst     a
        beq     zz16
        move    r5,r1
        move    #$20,n1
        lua     (r1)+n1,r1
        move    #$40,r0
        do      #<$20,>zz15
        move    x:(r0)+,x0
        move    x0,y:(r1)+
zz15:
zz16:
        move    #$40,r0              ; detector streams from the processed key
        move    #$61,r4             ; --- displaced ---
        rts
zz20:
        move    #$61,r4             ; --- displaced ; r0 unchanged ---
        rts

; ---- HOOK 3 : SC LISTEN output (spliced over proc-end `move m0,x:(r7+$f)`) --
sctail:
        move    m0,x:(r7+$f)          ; --- displaced ---
        move    x:(r6+$e),b           ; (q1) KGAIN|MON
        asr     #$8,b,b
        move    b1,a                 ; (q3)
        and     #>$ff,a
        tst     a
        beq     zz30                   ; SC LISTEN off
        move    x:(r6+$d),b           ; (q1) KEY|KFLT
        asr     #$10,b,b
        move    b1,a                 ; (q3)
        tst     a
        beq     zz30                   ; KEY OFF -> nothing stashed
        @KADJ@                         ; abs track 0..7
        asl     #7,a,a
        move    a1,n1
        move    #>$820,r1            ; $800 + gen-1 offset $20
        lua     (r1)+n1,r1           ; r1 -> keybus[abs] gen 1
        move    n6,r0                ; r0 -> the dry/wet output buffer
        do      #<$20,>zz31
        move    y:(r1)+,x0
        move    x0,x:(r0)+
zz31:
zz30:
        rts
