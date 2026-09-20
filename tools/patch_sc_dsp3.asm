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
;   @FTAB@   absolute P addr of the 32-word KEY FLT table (a = 1-exp(-2pi fc/fs), Q23)
;   @LPEDGE@ literal Q23 immediate, LP's near-OFF edge-override coefficient
;   @HPEDGE@ literal Q23 immediate, HP's near-OFF edge-override coefficient
;   @KGNA@   literal Q23 immediate, KEY GAIN's block-rate smoothing coefficient
; The tables are appended after the code by build_sidechain3.py; @GTAB@/@FTAB@
; are resolved in a first sizing pass so the `move #>imm` widths never shift.
; @LPEDGE@/@HPEDGE@ are plain literal substitutions (tools/sc_tables.py's
; lp_edge()/hp_edge()), not addresses -- fixed width regardless of pass.
;
; keybus ring (Y): slot(track,gen) = $800 + track*$80 + (gen&3)*$20.
;   gen 0 = the per-frame publish (sctap).  gen 1 = the SC LISTEN stash --
;   scdet writes the *processed* key there, sctail copies it to the dry buffer.
;
; One-pole tracker state, per compressor instance, in the compressor's own r7
; block at r7+$16 -- unused by the stock module (RE: state block r7+$f..$1b;
; disassembly of the real init routine at P:0x1864 confirms it zero-fills
; only $11/$12/$13/$1a/$1b/$f, leaving $14/$16/$17/$18 untouched and
; therefore NOT guaranteed zero -- whatever DSP memory held before this
; track's compressor instance was assigned lands there unchanged). r7+$18 is
; OUR OWN dedicated "have I ever seeded the tracker myself" latch (never
; touched by stock or by any other hook here): do not gate on the stock
; "first-block" bit (r7+$f) instead -- it can legitimately go warm from
; ordinary stock activity before our KEY FLT code has ever run once (e.g.
; KFLT parked at bypass for a while, then turned to LP/HP for the first
; time), which would otherwise seed the tracker from garbage at $16.
; r7+$17 (the old 2-pole SVF's "bp" integrator, Sessions before 76) was
; retired by the one-pole redesign and is reclaimed below as the KEY GAIN
; smoother's own persisted state (see "-- KEY GAIN --"). r7+$14 is a second
; reclaimed word -- a one-shot "the previous block was OFF" flag consumed by
; KEY FLT's HP branch only (see "-- KEY FLT --"); flagged as a free
; candidate slot two sessions ago, used here for exactly the purpose floated
; then.
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
; SIDECHAIN3 ringing bug, take 2 (Session 75, NOTES.md): a mid-block trig
; splits the block into TWO `PROCESS_TABLE[id]` calls to comp_proc (r0=0 for
; the first, r0=split*2 for the second -- Session 74's disassembly of
; P:0x4a7..0x4d7, both payloads), and re-reading the id-lookup code around
; both call sites shows they normally resolve to the SAME `r2` (target
; address) -- meaning `scdet` runs TWICE on a split frame, each time
; redoing the FULL KEY GAIN + KEY FLT + SC LISTEN pipeline the n7 fix now
; makes cover the whole block, with the SVF integrator's state (r7+$16/$17)
; carried over from the first call into the second -- filtering the SAME
; 16 samples twice in immediate succession is a different system than the
; single-pass one Session 64/69 proved has real (non-oscillating) poles,
; and was never analysed. `n6` already holds this call's original `r0`
; (the very first instruction above); test it: nonzero means split*2, i.e.
; this is definitely the SPLIT-BLOCK'S SECOND call, not the frame's only
; one (which always arrives with r0=0) -- skip straight to `zz16`'s own
; exit (still redirects the stock detector to `x:$40`) without touching
; KEY GAIN/KEY FLT/the gen-1 stash or MON_ON/MON_KEY a second time.
;
; WORD BUDGET: this check (4w: move/tst/bne) pushed the cave 1 word over
; SPATIALIZER's 261w donor. Paid for by `r4` (proven free for the whole
; routine -- untouched anywhere between here and the final `move #$61,r4`
; every exit path already does; audited by inspection, not just assumed):
; stash `a` (abs key track, still clean here) into it now, so zz15's own
; publish block below can read it back in 1 word instead of re-deriving it
; from scratch in 4 (net -3w there against this check's +4w = -1 net).
        move    a1,r4
        move    n6,b
        tst     b
        bne     zz16
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
; Session 76 continued yet again (KGN smoothing): applying the raw table
; gain uniformly across the block produced an instantaneous STEP in x:$40
; every time a knob sweep crossed a table-bucket boundary -- inaudible with
; MON off (x:$40 only feeds the DETECTOR there, and the compressor's own
; attack/release ballistics smooth whatever the detector sees before it
; ever reaches the target track's actual audio), but MON's audition path
; (moncommit, HOOK 3) plays x:$40 AS the committed track audio with zero
; smoothing of its own -- every bucket crossing was an audible click while
; riding the knob with MON on. Fix: smooth the APPLIED gain itself with a
; one-pole, coefficient-weighted-feedback tracker -- same principle as KEY
; FLT's tracker below, applied to a scalar coefficient instead of the audio,
; updated once per call (block-rate; the target changes at most once per
; 16-sample block, so per-sample resolution buys nothing here). Persistent
; state: r7+$17, the old 2-pole SVF's retired "bp" integrator slot (free
; since the Session 76 KFLT redesign -- see this file's own header). 0 is
; used as the "never seeded" sentinel -- gain_table()'s entries are all
; strictly positive (even -24 dB is a small positive Q23 value), so a
; genuine table value can never collide with it; a fresh/reassigned
; compressor instance therefore snaps straight to the target on its first
; KEY GAIN block instead of smoothing in from meaningless garbage.
; The old exact-unity (KGAIN==64) bypass skip is gone: table idx 8 (KGAIN
; 64-71, see sc_tables.py gain_table()) already stores a true 1.0
; multiplier, so folding it into the same smoothed path is free -- and
; necessary: a reintroduced skip would let this state go stale across a
; unity-parked gap exactly like KEY FLT's pre-fix OFF gap did.
        move    x:(r6+$e),b           ; (q1) KGAIN|MON word
        asr     #$10,b,b
        move    b1,a                 ; (q3) a = KEY GAIN 0..127
        asr     #$3,a,a               ; a1 = gain table index 0..15
        move    a1,n1
        move    #>@GTAB@,r1
        move    p:(r1+n1),x1          ; x1 = target gain/64 (Q23), this block
        move    x:(r7+$17),b          ; b = applied gain (persisted; 0 = cold)
        tst     b
        bne     zz21
        move    x1,b                  ; cold -> snap straight to target
        bra     zz22
zz21:
        move    b,y1                  ; y1 = applied (preserved across the mpy)
        move    x1,a                  ; a = target
        sub     b,a                   ; a = target - applied = diff
        move    a,y0                  ; y0 = diff (mpy operand slot)
        move    #>@KGNA@,x1           ; x1 = smoothing coefficient
        mpy     x1,y0,b               ; b = coeff * diff
        add     y1,b                  ; b = applied + coeff*diff = updated applied
zz22:
        move    b,x:(r7+$17)          ; persist
        move    b,x1                  ; x1 = smoothed gain, this block's multiply
        move    #$40,r0
        do      #<$20,>zz04
        move    x:(r0),x0
        mpy     x1,x0,a
        asl     #6,a,a                ; * 64
        move    a,x:(r0)+
zz04:

; -- KEY FLT : x:(r6+$d) bits 8-15, 0..127 ; 64 = bypass ; <64 LP ; >64 HP --
; Session 76 continued (third pass): ONE-POLE tracker, not the old 2-pole
; Chamberlin SVF. Single state var (r7+$16, "tracker"), single coefficient
; (x1, Q23 "a"): tracker += a*(in - tracker); LP output = tracker; HP output
; = in - tracker (n0 marks LP vs HP for the per-sample select, same as
; before). r7+$17 (the old "bp" integrator) is no longer used by this cave.
;
; WHY: the previous two attempts at a click-free OFF boundary both failed on
; hardware -- a dry/wet amplitude blend near OFF corrupted the REAL
; compressor's own detector (comb-filtering a signal against a phase-shifted
; copy of itself, read continuously by an envelope follower -> audible ring
; modulation on the TARGET track, not just a click); a wider version of the
; same blend would only have spread that same corruption further, not fixed
; it (NOTES.md, this session). The fix isn't a wider or smoother blend --
; it's a topology whose FEEDBACK is coefficient-weighted. This one-pole
; system's only feedback term is `a*(in-tracker)`: at a=0 the tracker never
; moves (frozen); at a's Q23 ceiling the tracker becomes `in` itself, EVERY
; sample, with NO dependence on its own history -- unlike the old SVF, where
; `hp = in - lp - 2*bp` used `lp`/`bp` UNWEIGHTED, so stale state mattered
; at full strength no matter how small the tuning coefficient got. A single
; real pole also can't resonate (no q parameter needed, no discriminant to
; satisfy, no "q >= 1.688" hardware-forced tuning like the old SVF needed --
; Session 64's ringing bug straightforwardly cannot recur here), AND a
; one-pole coefficient in [0, Q23-ceiling] is unconditionally stable -- no
; upper bound like the old SVF's q=2 hit around ~5-6 kHz when pushed toward
; a bright/transparent LP setting (worked out, not shipped, two sessions
; ago). That headroom is what lets LP's near-OFF step target genuine near-
; unity instead of a compromise value.
;
; THE EDGE OVERRIDE (not a blend -- a coefficient choice, one signal, always):
; FTAB's normal 40-2200 Hz curve (unchanged, same shape as every prior
; session) is shared by both LP (idx 0..31, low->high freq) and HP (idx
; 0..31, low->high freq) -- so FTAB[31] (2200 Hz) is also HP's own deepest
; setting, and FTAB[0] (40 Hz) is also LP's own deepest setting; pushing
; either toward "transparent" in the table itself would detune the OTHER
; mode's tuned end. Instead: idx==31 in the LP branch and idx==0 in the HP
; branch each get a ONE-TIME coefficient override (checked once per call,
; before the loop even starts -- zero per-sample cost) instead of the normal
; FTAB fetch. LP's override is the Q23 ceiling (~unity, as close to a true
; identity tracker as this format allows). HP's is ~8 Hz -- can't reach LP's
; exact-identity limit (a highpass, even at its most transparent, still has
; to track something to subtract; that's what "highpass" means, not a defect
; of this design) but is slow and small enough that any residual error from
; reusing whatever the tracker last held decays gently, not abruptly -- the
; user's own real-hardware anecdote (stock FILTER's BASE control audibly
; reaching transparent in a single raw-value step, 126->127) is the same
; principle: the LAST step near an extreme doesn't need to be gradual if the
; coefficient it lands on is inherently well-behaved.
        move    x:(r6+$d),b           ; (q1)
        asr     #$8,b,b
        move    b1,a                 ; (q3) a1 = (KEY<<8)|KFLT, a0 clean
        and     #>$ff,a              ; a = KEY FLT 0..127
        cmp     #>$40,a
        bne     zz11                   ; not bypass -> continue to LP/HP dispatch
; HP re-entry declick (Session 76 continued yet again -- hardware feedback:
; OFF<->HP still popped after the one-pole redesign fixed everything else).
; Mark that this block was OFF; consumed by the HP branch below, at zz09.
        move    #1,b
        move    b,x:(r7+$14)
        bra     zz10
zz11:
        move    a1,b                  ; b = KEY FLT (b0 clean)
        cmp     #>$40,b
        blt     zz05                   ; KEY FLT < 64 -> LP
;   HP : idx = (KEY FLT - 64) >> 1 (0..31) ; marker n0 = 0
        move    b,a
        sub     #>$40,a
        asr     #$1,a,a
        move    a1,n1
        move    #0,n0
        move    n1,a                   ; (q3) a = idx, clean (re-load from n1)
        tst     a
        bne     zz06                    ; not the edge idx -> normal FTAB fetch
        move    #>@HPEDGE@,x1           ; edge -> ~8 Hz, near-transparent HP
        bra     zz09
zz05:
;   LP : idx = KEY FLT >> 1 (0..31) ; marker n0 != 0
        asr     #$1,b,b
        move    b,n1
        move    #>$10,n0
        move    b1,a                   ; (q3) a = idx, clean
        cmp     #>$1f,a
        bne     zz06                    ; not the edge idx -> normal FTAB fetch
        move    #>@LPEDGE@,x1           ; edge -> Q23 ceiling, ~unity LP
        bra     zz09
zz06:
        move    #>@FTAB@,r1
        move    p:(r1+n1),x1          ; x1 = a coefficient (Q23)
zz09:
;   NOTE: do NOT gate on the stock "first-block" bit (r7+$f) here -- it can go
;   warm from ordinary stock compressor activity before OUR code has ever run
;   a KEY FLT block (e.g. KFLT sits at bypass for a while, then gets turned to
;   LP/HP for the first time). $16 is untouched by stock's own init (0x1864's
;   zero-fill list is $11/$12/$13/$1a/$1b/$f only -- confirmed by
;   disassembly), so reading it on the stock bit's word risks seeding the
;   tracker from garbage. Own the gate: $18 is ALSO untouched by stock and
;   by every other hook here, so use it as OUR single "have I ever seeded the
;   tracker myself" latch, set only below, never by anything else.
;
;   HP re-entry declick: only HP needs a reseed on the block right after OFF
;   -- HP's output is `in - tracker`, so continuity with whatever bypass was
;   just outputting (raw, unfiltered `in`) requires tracker==0 on that first
;   post-OFF sample, NOT the current input sample (seeding to the input
;   sample would give hp[0]=0, a jump TO silence -- worse, not better). LP's
;   output IS the tracker itself, where seeding to the input sample would be
;   the right target -- but LP measured clean on real hardware without any
;   of this (user confirmed, Session 76 continued yet again), so it is
;   deliberately left on the plain warm-continuation path below, untouched.
;   n0 (0=HP / $10=LP, set above) gates this to HP only; r7+$14 is set only
;   in the bypass branch above and consumed (cleared) here, or expired at
;   this routine's own tail below on the next filtered block either mode
;   takes -- so a bypass-then-LP-then-HP sequence can never fire this on a
;   stale flag from an old, already-superseded OFF period.
        move    n0,a                  ; a = 0 (HP) / $10 (LP)
        tst     a
        bne     zz23                   ; LP -> normal warm-continuation path
        move    x:(r7+$14),a          ; HP: was the previous block OFF?
        tst     a
        beq     zz23                   ; no -> normal warm-continuation path
        move    #0,b
        move    b,x:(r7+$14)          ; one-shot, consumed
        move    b,y1                  ; tracker := 0 -> hp[0] = in[0], continuous
        bra     zz08
zz23:
        move    x:(r7+$18),a
        tst     a
        bne     zz07
        move    #0,y1                 ; never seeded -> tracker = 0
        bra     zz08
zz07:
        move    x:(r7+$16),y1        ; warm: tracker
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
        move    a,x0                  ; x0 = in (kept for HP's own output)
        sub     y1,a                   ; a = in - tracker = diff
        move    a,y0                   ; y0 = diff (mpy operand slot)
        mpy     x1,y0,b               ; b = a * diff
        add     y1,b                  ; b = tracker + a*diff = updated tracker
        move    b,y1                  ; y1 = tracker (persists)
        move    x0,a                  ; a = in
        sub     b,a                    ; a = in - tracker = hp (default candidate)
        move    a,x0                   ; x0 = hp (default)
        move    n0,a                 ; marker: 0 = HP (keep x0=hp), != 0 = LP
        tst     a
        beq     zz14
        move    y1,x0                ; LP -> override with tracker
zz14:
        move    x0,x:(r0)+
        move    x0,x:(r0)+
zz13:
zz12:
        move    y1,x:(r7+$16)
        move    #1,a
        move    a,x:(r7+$18)          ; latch: tracker is now genuinely ours
        move    #0,b
        move    b,x:(r7+$14)          ; expire "just bypassed" -- HP consumed it
                                       ; above already if this was that block; LP
                                       ; or any later block clears it here so it
                                       ; can never fire on a stale flag

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
; address pass (r1 -> MON_ON, post-incremented to MON_KEY). Used to
; recompute the redirect track fresh here rather than thread a live
; register across the whole routine -- now threaded anyway via `r4`
; (Session 75, see the word-budget note above `zz16`'s own check): `r4`
; is free for the whole routine except its own final `move #$61,r4`
; (every exit path does that AFTER this point, never before), so reading
; it back here is safe and saves the 3-instruction re-derivation.
        move    r4,a                   ; a = absolute key track 0..7 (kept until the end)
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
; MON off -> publish MON_ON[my track] = 0.  Shared with zz20 via `bsr zz18`
; (zz18 is placed at the END of scdet, after zz20's own rts, specifically so
; the ONE extra internal rts it introduces lands AFTER the rts
; build_sidechain3.py's sc_assemble() counts on to find moncommit's start --
; that index was bumped rts[2]->rts[3] there to match. This used to be
; duplicated inline instead (fear of disturbing that indexing), which cost
; ~9 words per copy for a 1-word `jsr`; reclaimed to make room for the
; moncommit MON_ON exact-match fix below (see moncommit's own header comment).
; `bsr` (PC-relative, 2 words), not `jsr` (Session 76 continued): the SPRING
; REVERB donor's cave_org sits past 0xfff, past dsp_asm's own absolute-jsr
; range -- confirmed by direct test, `bsr` has no such limit since it's a
; displacement, not an absolute address.
        bsr     zz18
zz16:
; SIDECHAIN3 split-detector-offset bug (found this session, investigating a
; real reported artifact -- an alternating loud/quiet pattern between
; consecutive pattern loops, tracking exactly the loop length's own phase
; drift against the 16-sample DSP block grid). This redirect used to set
; r0 := $40 unconditionally, discarding whatever offset the CALLER's own r0
; held on entry -- correct for the frame's only/first call (n6, our saved
; copy of that entry r0, is always 0 there), but WRONG for a mid-block
; split's SECOND call, where n6 = split*2 (the dispatcher's own offset into
; the real audio buffer marking where the newly-triggered voice's segment
; begins -- see the header comment above, "SIDECHAIN3 ringing bug, take 2").
; x:$40 mirrors the WHOLE 16-sample-pair block 1:1 (that same prior fix
; specifically guarantees every pair is valid regardless of split), so the
; correct redirect for BOTH calls is $40+n6, not a bare $40 -- confirmed by
; a direct dsp_host register dump before writing this fix: simulating a
; split second call (incoming r0=$a) left r0=$40 instead of the correct
; $4a, i.e. stock's detector re-read the FIRST part of the block's key
; audio instead of the segment actually following the split. n6 is
; READ-ONLY here, never clobbered by this file -- stock needs it later,
; unmodified, for its own dry-path re-anchor (`move n6,r0`, stage 6).
        move    n6,a                   ; a = split offset (0 on an unsplit/first
                                        ; call -- a no-op there); (r0)+n6 form
                                        ; rejected by dsp_asm -- n6 only pairs
                                        ; with r6 in a `lua`, not r0 (each of
                                        ; r0-r7 has its OWN dedicated n/m pair
                                        ; on this ISA) -- accumulator add
                                        ; instead, same idiom @KADJ@ already
                                        ; uses just above (add/sub then a1 into
                                        ; an address register)
        add     #>$40,a                 ; a = $40 + split offset
        move    a1,r0                   ; detector streams from the processed
                                        ; key, correctly offset for a split's
                                        ; 2nd call
        move    #$61,r4             ; --- displaced ---
        rts
zz20:
; KEY OFF -> publish MON_ON[my track] = 0 (no key selected, nothing to show)
        bsr     zz18
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
