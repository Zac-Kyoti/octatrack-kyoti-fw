; SPDX-License-Identifier: MIT
; SPDX-FileCopyrightText: 2026 Zac-Kyoti
; ===========================================================================
; SIDE-CHAIN COMPRESSOR -- DIAGNOSTIC / TESTING-ONLY BUILD.
;
; Derived from patch_sc_dsp3.asm (step 3). Same three hooks, same three
; detour sites, but with every piece of the actual COMPRESSOR left out:
;
;   KEPT     KEY (page-2 slot 8, live) -- the sidechain source chooser.
;   KEPT     MON / SC LISTEN (slot 11, live) -- the monitor/audition path.
;   FIXED    KEY FLT is no longer read from page 2 at all -- the SVF always
;            runs with a hardcoded mid-LP coefficient (FTAB index 16 of 32,
;            n0 marker forced to LP). Turning the KFLT knob does nothing.
;   REMOVED  KEY GAIN (slot 10) -- the whole stage is gone; behaves as
;            permanent unity. Turning the KGN knob does nothing.
;   REMOVED  the actual compressor: RMS/peak detection, the envelope
;            follower (including the one carry/overflow-flag-dependent
;            branch NOTES.md Session 72 chased through an emulator repin),
;            and the final gain-multiply stage (stock P:comp_proc+2 through
;            the module's own tail, ~140 words) NEVER RUNS. scdet jumps
;            straight to the module's own two-instruction bookkeeping tail
;            (`move m0,x:(r7+$f)` then the module's real `rts`) instead of
;            falling through into that code, via a per-payload literal
;            address (@CTAIL@, resolved by build_sidechain_diag.py the same
;            way @KADJ@/@GTAB@/@FTAB@ already are). Verified by disassembly
;            that this tail is a pure constant-offset relocation between
;            payloads (B: P:0x1915, A: P:0x1b55 = B + 0x240, matching
;            comp_proc's own A-vs-B offset exactly) -- not assumed.
;
; Purpose: isolate whether the reported "metallic, resonant" ringing (MON on,
; KFLT != OFF) lives in the KEY-select/KEY-FLT/MON plumbing this build keeps,
; or in the actual compressor math (envelope follower, gain application)
; this build removes entirely. If the ringing still reproduces on this
; build, the compressor's own math is innocent and the bug is upstream of
; it; if it's gone, the opposite.
;
; NOT A SHIPPING BUILD. Testing/diagnostic only.
;
; Same dsp_asm quirks as patch_sc_dsp3.asm (see that file's own header for
; the (q1)/(q2)/(q3) notes) -- no directives / constants / jmp / jcc,
; literals only, labels substituted textually (raw substring -- every label
; here is `zzNN`, 4 chars, none a prefix of another), every routine ends
; `rts`. Build tokens, rewritten per payload:
;   @KADJ@   "add #3,a" (payload A, CORE_BASE 4) / "sub #1,a" (payload B, 0)
;   @CTAIL@  absolute P addr of the stock module's own 2-instruction tail
;            (`move m0,x:(r7+$f)` / `rts`) -- $1b55 (A) / $1915 (B).
; No @GTAB@/@FTAB@ needed for KGAIN (removed) but @FTAB@ is still needed for
; the (now-fixed-index) KEY FLT coefficient lookup; the 16-word gain table
; is dropped entirely (no KEY GAIN code references it).
; ===========================================================================

; ---- HOOK 1 : publish tap (identical to patch_sc_dsp3.asm) -----------------
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

; ---- HOOK 2 : detector redirect (KEY) + FIXED mid-LP KEY FLT --------------
; dsp56kEmu / DSP quirks worked around here (identical to patch_sc_dsp3.asm):
;   (q1) `move x:(rN+disp),a` reads the wrong word -- use dest `b`, then move.
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

; -- KEY FLT : FIXED mid-LP, page-2 value ignored entirely -------------------
; One Chamberlin SVF loop, unchanged math from patch_sc_dsp3.asm (q = 2,
; overdamped -- see that file's own header for the derivation). Input is
; (L+R)/2, output written to both L and R slots. n1/n0 are hardcoded instead
; of read from x:(r6+$d) -- no bypass path exists any more, the filter always
; runs. n1 = 16 is the middle index of the 32-entry LP half of FTAB (raw
; KEY FLT byte ~32, the midpoint of patch_sc_dsp3.asm's own 0..63 LP range).
        move    #16,n1                 ; FIXED: FTAB index 16 of 32 (mid-LP)
        move    #>$10,n0                ; FIXED: LP marker (n0 != 0 -> LP)
        move    #>@FTAB@,r1
        move    p:(r1+n1),x1          ; x1 = f coefficient (Q23, < 0.32) -- fixed
;   NOTE: do NOT gate on the stock "first-block" bit (r7+$f) here -- same
;   reasoning as patch_sc_dsp3.asm: $16/$17 are untouched by stock's own init
;   (0x1864's zero-fill list is $11/$12/$13/$1a/$1b/$f only), so reading them
;   on the stock bit's word risks seeding the integrator from garbage. $18 is
;   OUR OWN "have I ever seeded lp/bp myself" latch, same as step 3.
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
        sub     y0,a                  ; a = in - lp' - bp
        sub     y0,a                  ; a = in - lp' - 2*bp = hp   (q = 2, overdamped)
        move    a,x0                  ; x0 = hp
        mpy     x1,x0,b               ; b = f * hp
        add     y0,b                  ; b = bp + f*hp = bp'
        move    b,y0
        move    n0,a                 ; marker: 0 = HP (keep x0=hp), != 0 = LP
        tst     a
        beq     zz14
        move    y1,x0                ; LP -> output lp' (always taken -- n0 is fixed LP)
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
; -- SC LISTEN : identical to patch_sc_dsp3.asm -- if on, stash the processed
;    key -> keybus[key] gen 1, and publish MON_ON[track]/MON_KEY[track] so
;    the dispatcher-level `moncommit` hook (unchanged, HOOK 3 below) can
;    independently redo the substitution outside any shared execution
;    context. MON_ON/MON_KEY live at Y:(0x800 + track*0x80 + 0x40/0x41).
;
;    REGISTER DISCIPLINE: unlike patch_sc_dsp3.asm, this tail no longer
;    feeds into the real stock compressor body at all (that whole 140-word
;    region never runs on this build -- see zz16/zz20 below), so the
;    original "registers here become an input to P:comp_proc+2 onward"
;    constraint is MOOT. Kept the same proven register set (a, b, x0, r0,
;    r1, n1, r4) anyway rather than re-deriving a smaller one -- no cost to
;    doing so, and it keeps this file a minimal diff against patch_sc_dsp3.asm
;    in the one section most likely to get re-diffed against it later.
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
; build_sidechain_diag.py's sc_assemble() counts on to find moncommit's
; start -- unchanged from patch_sc_dsp3.asm, same rts[0..3] convention).
        jsr     zz18
zz16:
; NEW (diagnostic build only): instead of falling through into the real
; compressor body (which patch_sc_dsp3.asm reaches by simply `rts`-ing back
; to the detour site's own continuation), explicitly jump PAST that entire
; ~140-word region to the stock module's own bookkeeping tail. `move
; #$40,r0` (patch_sc_dsp3.asm's "detector streams from the processed key"
; setup) is dropped -- nothing downstream reads it any more, since the
; instruction that consumed it (P:comp_proc+2's own `move x:(r0)+,x0`) is
; exactly what we're skipping past.
        move    #$61,r4             ; --- displaced --- (kept: the module's
                                     ; own tail doesn't need it, but costs
                                     ; nothing and preserves stock timing/
                                     ; state fidelity for whatever calls proc)
        move    #>@CTAIL@,r1
        jsr     (r1)                 ; run the module's own 2-word tail
                                     ; (move m0,x:(r7+$f) / rts), returns here
        rts
zz20:
; KEY OFF -> publish MON_ON[my track] = 0 (no key selected, nothing to show)
        jsr     zz18
        move    #$61,r4             ; --- displaced ; r0 unchanged ---
        move    #>@CTAIL@,r1
        jsr     (r1)
        rts

; shared by zz17/zz20 (see comment at zz17). Deliberately placed AFTER
; scdet's other two rts (zz16's, zz20's) so it becomes the THIRD internal
; rts, matching sc_assemble()'s rts[3] lookup for moncommit's start.
zz18:
        move    x:>$420,a
        asl     #7,a,a
        move    a1,n1
        move    #>$840,r1
        lua     (r1)+n1,r1
        move    #0,b
        move    b,y:(r1)
        rts

; ---- HOOK 3 : dispatcher-level MON commit -- IDENTICAL to patch_sc_dsp3.asm,
; unchanged in every respect. This is "the monitor" the user asked to keep,
; and nothing about removing the compressor's own machinery touches it --
; it runs at the dispatcher's per-track COMMIT step, a completely separate
; splice site from anything in HOOK 2 above, same as step 3.
;
; REGISTER DISCIPLINE (Session 59, hardware-forced): `r0` holds the just-
; replayed `x:$206` and MUST reach the stock `jsr func_00034f` right after us
; UNCHANGED -- unlike r1/n1/r3 (all explicitly overwritten by the three stock
; instructions between this splice and that call: `move #$0,r1` / `move #$1,
; n1` / `move x:>$419,r3`), nothing resets r0 for us, so it is never touched
; again below. Do not reintroduce r2/n2 or touch r0 here without a fresh
; hardware test (see patch_sc_dsp3.asm's own header for the full story).
;
; UNINITIALIZED-SLOT HAZARD: gate on the EXACT sentinel `scdet` publishes for
; ON ($10000, not "nonzero" -- see patch_sc_dsp3.asm's own header for why).
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

; ---- HOOK 4 : second guard on the compressor body's own entry ------------
; NOTES.md Session 73: dynamically confirmed (pcwatch, not assumed) that
; scdet's own redirect to @CTAIL@ does NOT stop every arrival at the real
; body -- P:comp_proc+2 (the body's own first instruction, `move
; x:(r0)+,x0`) is independently reached, with a real, plausible per-track r7
; already loaded, by some OTHER dispatcher call path into this module that
; does not pass through comp_proc+0 (where scdet's own detour lives) at all.
; That second path was not identified (no caller-tracking mechanism available
; via --dsp-pcwatch) -- rather than guess at it further, guard the body's
; own entry directly instead: build_sidechain_diag.py detours P:comp_proc+2
; (ONE word, `jsr zz21` -- fits the short form, no nop needed) to this
; routine, which is safe regardless of which path reaches it, since it only
; needs r7 (the per-track instance pointer, already correct on entry to
; ANY point in this module -- confirmed by the pcwatch dump itself: r7 read
; back as a genuine instance address, not garbage).
zz21:
        move    #>@CTAIL@,r1
        jsr     (r1)
        rts
