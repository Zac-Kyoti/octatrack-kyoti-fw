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
; One Chamberlin SVF loop; n0 marks LP vs HP for the per-sample output
; select.  Input is (L+R)/2, output is written to both L and R slots.
;
; DAMPING q = 2, NOT the textbook q = 1 (Session 64, hardware-driven): this is
; a SIDECHAIN KEY filter, not a musical one -- both the SC LISTEN audition and
; the actual signal reaching the compressor's detector are this filter's
; output, so any resonant peak here both sounds wrong AND biases which
; frequencies trigger gain reduction. q = 1 (zeta = 0.5 in the equivalent
; continuous 2nd-order system) is UNDERdamped -- confirmed by hardware
; listening test (audible ringing on a fast-transient kick, tracking KFLT
; position, gone at OFF) and independently by solving this loop's own
; characteristic equation (2x2 state matrix from lp'=lp+f*bp,
; hp=in-lp'-q*bp, bp'=bp+f*hp): complex (oscillatory) poles at the higher end
; of the FTAB range at q=1. q >= ~1.688 is the exact point the poles go real
; (non-oscillatory) across the WHOLE 32-entry FTAB (checked numerically, all
; 32 indices); q=2 clears that with margin and stays stable (max |pole| 0.82
; across the range). Implemented as a literal SECOND `sub y0,a` below rather
; than a coefficient multiply -- q=2 needs no new register or table entry,
; just one extra word. Both LP and HP outputs come off the SAME 2-state
; system, so this one change makes both non-resonant, not just HP.
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
; SIDECHAIN3 ringing bug (Session 74, NOTES.md): this loop used to run `do n7`,
; matching the STOCK compressor's own per-call sample count -- but `n7` is
; segment-scoped for a mid-block trig split (the dispatcher sets it to
; `x:0x20c` or `x:0x20d`, each < 16, confirmed by fresh disassembly of both
; payloads' `P:0x4a7`/`0x29c` dispatch sites), while the sibling loops right
; below (zz02/zz04/zz15, and the gen-0 copy-in above) all hardcode a FIXED
; 32-word/16-pair extent. On a split frame this filtered only the first `n7`
; pairs of `x:$40`, leaving the rest of the SAME buffer holding unfiltered
; (KEY-GAIN-only) key audio from the fixed-extent stages that already ran --
; a hard filtered/raw splice published straight to MON via the SC LISTEN
; gen-1 stash (zz15) on every trig that lands mid-block. `x:0x40` is always a
; FULLY VALID 16-sample block regardless of split (sctap publishes it before
; any split-handling runs, at the very top of the dispatch), so there is no
; reason this filter needs to track the compressor's own per-call segment
; count -- fix is to always process the whole block, matching the other
; three loops instead of the one outlier.
        move    #$40,r0
        do      #<$10,>zz13
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
        sub     y0,a                  ; a = in - lp' - bp
        sub     y0,a                  ; a = in - lp' - 2*bp = hp   (q = 2, overdamped)
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
; -- SC LISTEN : if on, stash the processed key -> keybus[key] gen 1, and
;    publish MON_ON[track]/MON_KEY[track] so the dispatcher-level `moncommit`
;    hook (spliced at the per-track COMMIT step, well after this WHOLE module
;    -- including its own undocumented envelope/gain math -- has returned)
;    can independently redo the substitution outside any shared execution
;    context with the compressor's own code. MON_ON/MON_KEY live at
;    Y:(0x800 + track*0x80 + 0x40/0x41) -- the gen-2 slot of THIS track's own
;    keybus stride, never written by sctap/scdet's gen-0/gen-1 use, so no new
;    memory-safety question versus what's already proven (NOTES.md Session 17
;    / octabam BUS.md: Y >= 0x800 is safe).
;
;    REGISTER DISCIPLINE (Session 59, hardware-forced): this tail runs
;    strictly BEFORE this routine's own rts, so anything left in a register
;    here becomes an INPUT to the REST of the real stock compressor body
;    (P:0x1873 onward) once we return -- unlike moncommit (a separate splice,
;    see below), there is no "the very next instructions reset it anyway"
;    guarantee to lean on except for the registers the ORIGINAL, hardware-
;    proven scdet tail already touched (a, b, x0, r0, r1, n1, r4). A first
;    version of this block additionally used n0 and x1 as scratch -- BOTH
;    are live/relied-on elsewhere in this exact routine (n0 as the KEY FLT
;    LP/HP marker just above, x1 as the KEY FLT tuning coefficient), and
;    leaving them holding OUR values instead broke the sequencer transport
;    outright on real hardware (a hung/confused DSP, not an audio glitch --
;    the ColdFire side's button/LED handling kept working independently).
;    Do not reintroduce n0/x1/any register beyond the proven set here without
;    a fresh hardware test.
        move    x:(r6+$e),b           ; (q1)
        asr     #$8,b,b
        move    b1,a                 ; (q3)
        and     #>$ff,a
        tst     a
        beq     zz17                   ; MON off -> publish OFF, then join zz16
        move    r5,r1
        move    #$20,n1
        lua     (r1)+n1,r1
        move    #$40,r0
        do      #<$20,>zz15
        move    x:(r0)+,x0
        move    x0,y:(r1)+
zz15:
; publish MON_ON[my track]=1 and MON_KEY[my track]=redirect track in ONE
; address pass (r1 -> MON_ON, post-incremented to MON_KEY) -- recomputes the
; redirect track fresh rather than threading a live register across the
; whole routine.
        move    x:(r6+$d),b
        asr     #$10,b,b
        move    b1,a
        @KADJ@                         ; a = absolute key track 0..7 (kept until the end)
        move    x:>$420,b              ; b = MY track 0..7
        asl     #7,b,b
        move    b1,n1
        move    #>$840,r1              ; 0x800 + 0x40 (MON_ON[my track])
        lua     (r1)+n1,r1
        move    #1,b
        move    b,y:(r1)+              ; MON_ON = 1 ; r1 -> MON_KEY[my track]
        move    a,y:(r1)               ; MON_KEY[my track] = key track (still in a)
        bra     zz16
zz17:
; MON off -> publish MON_ON[my track] = 0.  Shared with zz20 via `jsr zz18`
; (zz18 is placed at the END of scdet, after zz20's own rts, specifically so
; the ONE extra internal rts it introduces lands AFTER the rts
; build_sidechain3.py's sc_assemble() counts on to find moncommit's start --
; that index was bumped rts[2]->rts[3] there to match. This used to be
; duplicated inline instead (fear of disturbing that indexing), which cost
; ~9 words per copy for a 1-word `jsr`; reclaimed to make room for the
; moncommit MON_ON exact-match fix below (see moncommit's own header comment).
        jsr     zz18
zz16:
        move    #$40,r0              ; detector streams from the processed key
        move    #$61,r4             ; --- displaced ---
        rts
zz20:
; KEY OFF -> publish MON_ON[my track] = 0 (no key selected, nothing to show)
        jsr     zz18
        move    #$61,r4             ; --- displaced ; r0 unchanged ---
        rts

; shared by zz17/zz20 (see comment at zz17). Deliberately placed AFTER
; scdet's other two rts (zz16's, zz20's) so it becomes the THIRD internal
; rts, matching sc_assemble()'s updated rts[3] lookup for moncommit's start.
zz18:
        move    x:>$420,a
        asl     #7,a,a
        move    a1,n1
        move    #>$840,r1
        lua     (r1)+n1,r1
        move    #0,b
        move    b,y:(r1)
        rts

; ---- HOOK 3 : dispatcher-level MON commit (replaces the old proc-end splice)
; Spliced at the per-track COMMIT step in the DISPATCHER itself (payload A:
; P:0x50e, payload B: P:0x303 -- both `move x:>$206,r0`, reading this track's
; per-track output-slot pointer immediately before its copy-to-output-slot
; call). This runs strictly AFTER this track's entire FX1+FX2 processing --
; including all of the compressor's own envelope/gain math -- has already
; returned to the dispatcher, sharing NO execution context or timing with it.
; Reads the flag `scdet` published this same frame and, if set, overwrites
; X:0 (this track's about-to-be-committed audio) with a fresh re-fetch of
; keybus[key] gen 1 -- not a value carried across the compressor's own call.
;
; REGISTER DISCIPLINE (Session 59, hardware-forced): `r0` holds the just-
; replayed `x:$206` and MUST reach the stock `jsr func_00034f` right after us
; UNCHANGED -- unlike r1/n1/r3 (all explicitly overwritten by the three stock
; instructions between this splice and that call: `move #$0,r1` / `move #$1,
; n1` / `move x:>$419,r3`), nothing resets r0 for us, so it is never touched
; again below. A first version additionally used r2/n2 as scratch for the
; second address computation -- neither is reset by that intervening stock
; code, and using them broke the sequencer transport outright on real
; hardware. Reuse r1/n1 for the second lookup instead (safe by the same
; "the very next stock instructions overwrite it anyway" logic) and route the
; output through r3 (also explicitly reset next) -- do not reintroduce r2/n2
; or touch r0 here without a fresh hardware test.
;
; UNINITIALIZED-SLOT HAZARD (found post-Session-59-flash: transport still
; broken with the register fix alone): this hook runs for EVERY track's
; commit, every frame -- but Y:0x800+track*0x80+0x40 (MON_ON) is only ever
; WRITTEN by `scdet`, which only runs for the one track actively processing a
; COMPRESSOR. For every other track this slot is real, never-zeroed DSP
; memory: dumping the actual baseline .mem (tools/emu_sc_dsp3_moncommit.py's
; own MEM_B) shows EVERY track's slot already holds large nonzero garbage
; (~0x7fffff-ish, i.e. Q23-scale audio residue, not silence) even before any
; of this project's code runs. A plain `tst b` ("nonzero = on") is true for
; essentially all of that garbage, so on real hardware this hook fires for
; nearly every non-compressor track on nearly every frame, deriving a source
; address from garbage MON_KEY and overwriting that track's committed audio
; from it -- a very plausible cause of DSP-side chaos severe enough to take
; the sequencer transport down (the same failure CLASS Session 59 already
; proved: DSP state disturbance desyncing something transport-critical),
; independent of the register-clobber bug already fixed there. Fix: gate on
; the EXACT sentinel `scdet` publishes for ON, not "nonzero" -- `move #1,b`'s
; left-aligned short-immediate quirk (q2, top of file) means that sentinel is
; actually `$10000`, not `1`; matching it exactly by chance is not plausible
; for garbage in this value range (the dumped baseline's own garbage sits in
; the millions, Q23-audio-scale, nowhere near $10000 = 65536).
moncommit:
        move    x:>$206,r0           ; --- displaced --- (must survive untouched)
        move    x:>$420,a             ; a = my track 0..7
        asl     #7,a,a
        move    a1,n1
        move    #>$840,r1
        lua     (r1)+n1,r1            ; r1 -> MON_ON[my track]
        move    y:(r1)+,b             ; b = MON_ON ; r1 now -> MON_KEY[my track]
        cmp     #>$10000,b             ; (q2) exact match vs scdet's ON sentinel,
        beq     mc09                   ; NOT "nonzero" -- see hazard note above.
        rts                            ; no match (incl. garbage or real OFF=0) -> done.
                                        ; (`bne` is not a valid dsp_asm mnemonic, so the
                                        ; match case below jumps IN instead of skipping
                                        ; OVER.)
mc09:
        move    y:(r1),b              ; b = MON_KEY 0..7 (still via r1, no r2/n2 needed)
        asl     #7,b,b
        move    b1,n1                 ; reuse n1 (stock resets it right after us anyway)
        move    #>$820,r1             ; reuse r1
        lua     (r1)+n1,r1            ; r1 -> keybus[key] gen 1
        move    #0,r3                  ; reuse r3 (stock resets it right after us anyway)
        do      #<$20,>mc11
        move    y:(r1)+,x0
        move    x0,x:(r3)+
mc11:
        rts
