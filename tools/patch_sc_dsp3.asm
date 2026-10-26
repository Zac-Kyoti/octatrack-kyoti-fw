; SPDX-License-Identifier: MIT
; SPDX-FileCopyrightText: 2026 Zac Kyoti
; ===========================================================================
; SIDE-CHAIN COMPRESSOR -- step 3 DSP code.
;
; Superset of tools/patch_sc_dsp.asm (step 2).  Same two detour sites in the
; stock payload (dispatcher FX1 entry -> sctap ; COMPRESSOR proc+0 -> scdet)
; plus a THIRD hook at COMPRESSOR proc-end -> sctail for SC LISTEN.
;
; New page-2 controls the DSP acts on (packing = octabam PARAM_PAGES;
; emu_sc_dsp3.py -params index in parens):
;   KEY      x:(r6+$d) bits 16-23   0..8    OFF / any of T1..T8, flat  (8)
;   KEY FLT  x:(r6+$d) bits  8-15   0..127  64=bypass  <64 LP  >64 HP  (9)
;   KEY GAIN x:(r6+$e) bits 16-23   0..127  64=unity  ~+/-24 dB        (10)
;   SC LISTN x:(r6+$e) bits  8-15   0..1    OFF / ON  (audition key)   (11)
; KEY's range widened 0..4 -> 0..8 in Session 77 (cross-core SIDECHAIN,
; NOTES.md): it now names an absolute track T1..T8 directly, same value on
; both payloads, rather than "one of this track's own 4 same-core siblings"
; -- @KADJ@ (the old per-payload relative-offset token) is retired.
;
; dsp_asm quirks (see patch_sc_dsp.asm header): no directives / constants /
; jmp / jcc -- literals only, labels substituted textually (raw substring, so
; every label here is `zzNN`, all 4 chars, all distinct => none is a prefix of
; another), every routine ends `rts` (the build hand-encodes `jsr <cave>` at
; each site, control returns via rts).  Build tokens, rewritten per payload:
;   the KEY GAIN table's base -- the one 6-hex-digit `fab1e0` literal below
;            (octabam's ptable marker, so it appears nowhere else in this file):
;            absolute P addr of the 16-word KEY GAIN table (gain/64, Q23); the
;            49-word key-filter table follows it in the standalone
;   the key-filter table's base -- the one `fab2e0` literal below (octabam's ptable2
;            marker; the standalone builder writes its own address). It cannot come from
;            the KEY GAIN base: the gain store points r1 at r5+$20 first.
;   @LPEDGE@ literal Q23 immediate, LP's near-OFF edge-override coefficient
;   @HPEDGE@ literal Q23 immediate, HP's near-OFF edge-override coefficient
;   @KGNA@   literal Q23 immediate, KEY GAIN's block-rate smoothing coefficient
; The tables are appended after the code by build_sidechain_compressor.py; both table addresses
; are resolved in a first sizing pass so the `move #>imm` widths never shift.
; @LPEDGE@/@HPEDGE@ are plain literal substitutions (tools/sc_tables.py's
; lp_edge()/hp_edge()), not addresses -- fixed width regardless of pass.
;
; Cross-core tokens (Session 77, NOTES.md has the full design writeup):
;   @COREBASE@   this core's own base track index: 4 (payload A, tracks 5-8)
;                / 0 (payload B, tracks 1-4)
;   @FCOREBASE@  the FOREIGN core's base track index: the other one of the
;                pair above
;   @SBASE@      this core's OWN publish region in the shared window:
;                $33e00 (payload A) / $3be00 (payload B) -- where sctap
;                writes so the FOREIGN core can read.  Session 115 moved it
;                from $30100/$38100: those are 256 words into the stock FX2
;                slot of bank track 3 (T7 / T3), i.e. INSIDE a reverb's delay
;                lines -- every track's audio was being written into DARK/PLATE
;                REVERB's memory on that core (NOTES.md "Session 114 continued
;                (4)").  The new block is the last $200 words of the same
;                16K slot: stock DSP code never writes past slot+$3da2 (DARK
;                REVERB's last line, measured and read from its init; PLATE
;                stops near +$3577, every FX1-capable effect below +$c00, the
;                DELAY runs on the ColdFire), and each payload's own init
;                zeroes its half of the window at boot.
;   @FSBASE@     the FOREIGN core's publish region: the other one of the
;                pair above -- where scdet reads a foreign KEY selection from
;   @GCNT@       this core's own generation counter, one word, in the shared
;                window right before its own @SBASE@ block: $33dff (A) /
;                $3bdff (B). Never read the FOREIGN core's copy of this --
;                each core tracks its OWN belief about "what generation is
;                everyone on right now" and assumes the two agree (XBUS's own
;                rule, inherited along with its caveat: this assumes the two
;                cores are rate-locked, unverified, see NOTES.md)
;   @GSEED@      this core's own "have I ever seeded @GCNT@" sentinel word,
;                right before @GCNT@: $33dfe (A) / $3bdfe (B)
;   @FOREIGN_BR@ "beq zzXX" (payload A) / "bne zzXX" (payload B) -- branches
;                to the foreign-core read path when a track-membership test
;                (`and #>4,acc`, uniform on both payloads) says this KEY
;                selection is NOT on this core's own half
; Shared-window layout: 4 tracks x 4 generations x 32 words = $200 (512)
; words per core, `slot(local_track, gen) = SBASE + local_track*$80 +
; (gen&3)*$20`. No accumulation
; (each publish wholly overwrites its own slot), so unlike XBUS's bus there
; is no clear-vs-write race and no housekeeper election needed -- only the
; write-vs-read race, guarded the same way XBUS's is: four buffers, reader
; always two generations behind the writer.
;
; keybus (Y, this core's private memory; 2026-10-15 layout):
;   slot(track) = $7e00 + track*$40, track = ABSOLUTE 0..7, so $7e00..$7fff:
;     +$00..$1f  gen 0 = the per-frame publish (sctap) -- only this core's
;                own 4 tracks are ever written here
;     +$20..$3f  gen 1 = the SC LISTEN stash -- scdet writes the *processed*
;                key there, indexed by the CONSUMER track (2026-10-19;
;                it was the source track), and moncommit mixes it into the
;                dry buffer
;   MON_ON/MON_FADE[track] = Y:$7df0 + track*2 (+0 / +1), $7df0..$7dff
;   (MON_FADE was MON_KEY until 2026-10-19).
;   Both sit in the tail of the first internal FX2 slot (Y:$4000..$7fff):
;   stock never writes past slot+$3da2 (octabam's stock.SLOT_EXTENT, DARK REV
;   the highest), and the cross-core window already uses the same +$3e00
;   offset in the shared slots (hardware-confirmed since Session 115). Both
;   boot loops zero Y:$4000..$bfff before the first frame. Only long
;   immediates name these addresses, so no instruction changed size.
;   History: Session 115 put the keybus at $800..$9ff and MON at $7f0 (before
;   that $800 + track*$80 hit REPITCH's Y:$a00..). 2026-10-15 moved both here
;   to free Y:$7f0..$9ff for BLACKPYRAMIDS_303's voice ($7a5..$feb).
;
;   THE LAYOUT IS A BUILD CHOICE (2026-10-16): the code names these words only
;   through @KEYB@ (gen 0 base), @KEYB1@ (= @KEYB@ + $20, gen 1) and @MONB@.
;     standalone/KYOTI  $7e00 / $7e20 / $7df0 (above; the FX2 slot tail)
;     octabam/Modwerk   $800  / $820  / $7f0  (Session 115's: $7f0..$9ff)
;   The slot tail is only free where every FX2 effect is stock: MINIVERB,
;   GATE VERB and WAVE (octabam) write their whole 16,384-word FX2 slot (or,
;   GATE VERB, up to +$3EF7), so beside them the tail of T1/T5's slot is not
;   SIDE-CHAIN's. The standalone and KYOTI images carry none of them; octabam
;   and Modwerk keep Y:$7f0..$9ff, which no FX2 slot reaches.
;   This is SAME-CORE-ONLY and unaffected by cross-core KEY (see the design
;   note above scdet's r5 computation); only its addresses moved.
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

; ---- HOOK 1 : publish tap (same-core keybus unchanged from step 2; extended
; Session 77 with a cross-core publish into the shared window) -------------
; Clobber budget for THIS splice (audited, step 2's own header): stock
; reloads a,b,r0,r1,n1,x0 right after each rejoin -- everything added below
; stays strictly within that set, plus r6, which the displaced instruction
; at the end reloads itself, on purpose (this hook runs unconditionally
; for every track every block, the hottest path in this whole file, so an
; unaudited register here has a much bigger blast radius than anything in
; scdet, which only runs for tracks actually using COMPRESSOR).
;
; Cross-core design (NOTES.md "Session 77" has the full reasoning): every
; track sctap ever sees IS one of this core's own 4 tracks (a core's own
; dispatcher only ever dispatches its own tracks), so there is no same/
; foreign branch needed here at all -- every call publishes.  Unlike XBUS's
; accumulator bus, there is nothing to CLEAR (each track's slot is wholly
; overwritten every publish, never summed), so no housekeeper election is
; needed either -- just a per-core generation counter, advanced once per
; block, gated on "this is core-local track 0" (@COREBASE@ itself), which is
; a STRUCTURAL condition (some track always dispatches first; sctap already
; runs for it unconditionally) rather than an elected one.
sctap:
; -- generation counter advance (Session 77), gated on core-local track 0 --
        move    x:>$420,a               ; a1 = track index 0..7
        cmp     #>@COREBASE@,a
        bne     zz30                    ; not this core's local index 0 -> skip
; GSEED holds the exact sentinel $10000 once this core has ever run this
; path before -- same "exact match, not nonzero" idiom as MON_ON (this
; file's own moncommit hazard fix), needed because true cold DSP RAM in a
; region nothing has ever written before is NOT reliably zero (the
; "persistent slot" trap) and a plain nonzero test would very likely read
; boot garbage as "already seeded" and skip the one-time reset to a KNOWN
; value both cores must agree on. HARDWARE-ONLY validation gap: dsp_host /
; dsp_host_xcore zero all DSP RAM at their own "boot", so no emulator run
; can exercise the TRUE cold-boot garbage case -- see NOTES.md.
        move    #>@GSEED@,r1
        move    y:(r1),b               ; b = seed sentinel word
        cmp     #>$10000,b
        beq     zz29                    ; already seeded -> normal advance
        move    #1,b                    ; (q2) stores as $10000, matching the
        move    b,y:(r1)                ; cmp above -- same quirk, same fix
        move    #>@GCNT@,r1
        move    #0,b
        move    b,y:(r1)                ; first-ever block -> generation 0
        bra     zz30
zz29:
        move    #>@GCNT@,r1
        move    y:(r1),b
        add     #>1,b                   ; b = GCNT + 1 (plain arithmetic add,
                                        ; not the quirky short move form -- q2
                                        ; only affects `move #imm,reg`)
        and     #>3,b                   ; wrap 0..3 (masking risk on b)
        move    b1,a                   ; (q3) a = clean wrapped value
        move    a,y:(r1)
zz30:
; -- this track's shared-window slot -> r6 --
; SBASE + (local_index*4 + gen) * $20, local_index = track - @COREBASE@
; r6 is free here: the displaced `move x:>$208,r6` at the end reloads it.
        move    x:>$420,a
        sub     #>@COREBASE@,a          ; a1 = local index 0..3 (plain subtract,
                                        ; not a masking op -- no staleness risk)
        asl     #2,a,a                  ; a1 = local*4
        move    a1,x0                   ; x0 = local*4 (audited-safe scratch)
        move    #>@GCNT@,r1
        move    y:(r1),b
        and     #>3,b                   ; b = gen 0..3 (masking risk on b)
        move    b1,a                   ; (q3) a = gen, clean
        add     x0,a                    ; a = local*4 + gen
        asl     #5,a,a                  ; a = combined * $20
        move    a1,n1
        move    #>@SBASE@,r1
        lua     (r1)+n1,r6              ; r6 -> this track's shared-window slot
; -- this track's keybus slot (gen 0) -> r1 --
        move    x:>$420,a               ; a1 = track index 0..7
        asl     #6,a,a                  ; a1 = index * $40
        move    a1,n1
        move    #>@KEYB@,r1
        lua     (r1)+n1,r1              ; r1 -> keybus slot (gen 0)
; -- one pass over the block: each word to the keybus and to the window --
; (2026-10-15: was two loops, `move x:(r0)+,x0` / `move x0,y:(rN)+` each,
; 4 instructions a word; now 2. The XY move stores a's old word to the
; window and loads the next into a, so the loop reads X:$20 once past the
; block, which is internal X RAM and harmless. sctap already writes an
; accumulator to Y (GCNT above): no new move class in this context.)
        move    #0,r0
        move    x:(r0)+,a               ; a = word 0
        do      #<$20,>zz01
        move    a,y:(r1)+               ; keybus
        move    x:(r0)+,a   a,y:(r6)+   ; window; a = next word
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
        move    x:(r6+$d),b            ; (q1) KEY|KGN word
        asr     #$10,b,b
        move    b1,a                  ; (q3) a = KEY 0..8, a0 clean
; KEY DECLICK (2026-10-19, major version): r7+$2c = the key in use. While MON is audible
; (MON_FADE[my track] != 0) a new KEY waits: the old key keeps running and MON is forced off
; this block (r7+$2d = 1), so MON fades out on the live old key; with MON_FADE at 0 the new
; key is taken and MON fades back in -- a ~12 ms dip through the track's own sound instead of
; a hard swap between two keys. A key in use outside 0..8 (cold memory) is replaced at once.
; scinit sets it to 0. Registers a, b, x0, r1, n1.
        move    x:(r7+$2c),b          ; (q1) b = the key in use
        move    a,x0
        cmp     x0,b
        beq     zz70                  ; unchanged
        tst     b
        blt     zz71
        cmp     #>8,b
        bgt     zz71                  ; not a key: take the new one
        bsr     zz18
        lua     (r1+1),r1
        move    y:(r1),b              ; MON_FADE[my track]
        tst     b
        beq     zz71                  ; MON not audible: take the new key now
        move    x:(r7+$2c),b          ; (q1) keep the old key ...
        move    b,a
        move    #1,b                  ; (q2) $10000: only tested for non-zero
        bra     zz72                  ; ... and force MON off
zz71:
        move    x0,x:(r7+$2c)         ; the new key is in use
zz70:
        clr     b
zz72:
        move    b,x:(r7+$2d)
        tst     a
        beq     zz20                   ; KEY OFF -> self-detect, skip all
        sub     #>1,a                   ; KEY 1..8 -> absolute track 0..7, FLAT --
                                        ; @KADJ@ retired (Session 77): widening KEY
                                        ; to reach any of the 8 tracks removed the
                                        ; old "same-core siblings relative to my
                                        ; own track" indirection entirely, so this
                                        ; one subtract is now identical on both
                                        ; payloads (NOTES.md "Session 77").
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
; KEY GAIN/KEY FLT/the gen-1 stash or MON_ON a second time.
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
; r5 = the gen-1 stash slot base (SC LISTEN) of THIS track, the consumer
; (2026-10-19, MON declick). It used to be the SOURCE track's slot, so two
; COMPRESSORs keying the same track shared one stash; now that the stash is
; also written while MON fades out, each consumer needs its own. A core only
; ever runs its own 4 tracks' scdet, and gen 1 is written by nothing else.
        move    x:>$420,a               ; a = MY track 0..7 (r4 still holds the key)
        asl     #6,a,a
        move    a1,n1
        move    #>@KEYB@,r1
        lua     (r1)+n1,r1
        move    r1,r5                 ; r5 = slot base (SC LISTEN stash)
; -- same-core vs foreign-core source select (Session 77) --
        move    r4,b                   ; b = abs track (fresh reload; a/n1/r1
                                        ; just spent above computing r5)
        and     #>4,b                  ; b = 4 if track's high half is set, else 0
        move    b1,a                  ; (q3) a = clean 4-or-0
        tst     a
        @FOREIGN_BR@                    ; -> zz24 iff this track is on the OTHER
                                        ; core (which half is "foreign" flips
                                        ; between payloads -- see the header's
                                        ; token table)
; -- same-core source: keybus[abs] gen 0 (2026-10-19: no copy any more; the filter loop
;    reads the key from Y itself, through KEY GAIN, and writes X:$40) --
        move    r4,a
        asl     #6,a,a
        move    a1,n1
        move    #>@KEYB@,r1
        lua     (r1)+n1,r1            ; r1 -> keybus[abs] gen 0
        bra     zz25
zz24:
; -- foreign-core copy (Session 77): shared-window relay, 2 generations
; behind this core's own write generation (XBUS's own proven race-safety
; shape -- four buffers, reader always two behind the writer; the "-2" is
; done as "+2" since -2 == +2 mod 4, avoiding a negative immediate).
; @GCNT@ here is THIS core's OWN counter, never the foreign core's word --
; standing in for "what generation the foreign core is almost certainly on
; right now", which only holds if the two cores are truly rate-locked
; (inherited from XBUS unverified, see NOTES.md "Session 77" and
; refs/octabam/docs/effects/XBUS.md's own standing caveat).
        move    r4,a                    ; a = abs track
        sub     #>@FCOREBASE@,a         ; a = foreign-local index 0..3 (plain
                                        ; subtract, no masking risk -- @FOREIGN_BR@
                                        ; already proved this track is on the
                                        ; foreign half, so this is always in range)
        asl     #2,a,a                  ; a = local*4
        move    a1,x1                   ; x1 = local*4 (safe here -- not yet used
                                        ; for anything else in this routine; the
                                        ; KEY FLT coefficient use of x1 starts
                                        ; much later, well past this point)
        move    #>@GCNT@,r1
        move    y:(r1),b
        add     #>2,b                   ; b = GCNT + 2 (== GCNT - 2 mod 4)
        and     #>3,b                   ; b = read_gen 0..3 (masking risk on b)
        move    b1,a                   ; (q3) a = read_gen, clean
        add     x1,a                    ; a = local*4 + read_gen
        asl     #5,a,a                  ; a = combined * $20
        move    a1,n1
        move    #>@FSBASE@,r1
        lua     (r1)+n1,r1              ; r1 -> foreign track's shared-window slot
zz25:
        move    r1,x:(r7+$2b)           ; the key's 32 words in Y, for the filter loop

; -- KEY GAIN : x:(r6+$d) bits 8-15 (slot 9, major version), 0..127 ; 64 = unity --
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
        move    x:(r6+$d),b           ; (q1) KEY|KGN word
        asr     #$8,b,b
        move    b1,a                 ; (q3)
        and     #>$ff,a               ; a = KEY GAIN 0..127
        asr     #$3,a,a               ; a1 = gain table index 0..15
        move    a1,n1
        move    #>$fab1e0,r1
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
        lua     (r5+$20),r1
        move    b,y:(r1)              ; the gain heads the loop's Y scratch (the filter
                                      ; loop applies it: gain/64 x key, then * 64)

; -- KEY FILTERS (2026-10-19, major version; tools/sc_keyfilt.py is the bit-exact model) --
; KBAS x:(r6+$e) bits 16-23 (0 = OFF, 1..127), KWID bits 8-15 (0..126, 127 = OFF): a
; base-width pair (2026-10-21). HP 18 dB/oct = TPT one-pole HP x TPT state-variable HP
; (k 1) at KBAS; LP 12 dB/oct = TPT SVF LP (k sqrt 2) KWID above it (above 20 Hz with KBAS
; OFF: a plain LP); Butterworth, on one grid, 20 Hz * 2^(g/16). OFF is a cutoff out of the
; way (~5 Hz / ~19.6 kHz), so no code path switches as a knob moves (the old KFLT's centre
; pop cannot happen); the settled-OFF bypass below is continuous. The two cannot cross.
; Positions glide per block; coefficients are recomputed only in a block
; where a position moved: G from the 49-word table (interpolated), a1 = 1/D by `div`.
; State, in this instance's r7 block (free while COMPRESSOR runs: r7 canary, emulator +
; hardware, 2026-10-19; another effect in the slot reuses it, hence scinit):
;   r7+$1c s1   $1d/$1e HP ic1/ic2   $1f/$20 LP ic1/ic2
;   $21 g1   $22..$24 HP a1 a2 a3   $25..$27 LP a1 a2 a3
;   $28 Vh  $29 Vl (positions, (g+32)<<15)   $2a @KFMAGIC@ once set up (scinit clears it)
;   $2b the key source's Y address, this block (same-core keybus or the shared window)
;   $2c the key in use, $2d "a KEY change is waiting" (the KEY declick, at scdet's top)
; dsp_asm encodes no backward branch or bsr: every subroutine sits after its callers. It also
; mis-encodes accumulator-to-accumulator `tfr` and `cmp` (tfr a,b -> rnd b, cmp b,a -> maxm
; a,b): those go through `move` (the values are clean 24-bit) or a data register. The
; builders' mnemonic round trip (dsp_asm_util.mnemonic_mismatches) refuses any such swap.
; Registers: a, b, x0, x1, y0, y1, r0, r1, n1, r4 (r4 is reloaded at every scdet exit,
; r0 by the redirect at zz16). r5 (the stash base) is not touched.
        move    #>$fab2e0,r1
        move    x:(r6+$e),b           ; (q1) KBAS|KWID word
        asr     #$10,b,b
        move    b1,a                  ; (q3) a = KBAS 0..127
        tst     a
        beq     zz40
        sub     #>1,a
        move    a1,x0
        move    #>@KFHSTEP@,x1
        mpy     x1,x0,a               ; 2 * (n-1) * HSTEP, in a0
        asl     #$17,a,a              ; a1 = (n-1) * HSTEP
        add     #>$100000,a           ; + V of g 0
        bra     zz41
zz40:
        clr     a                     ; OFF: g -32
zz41:
        move    a,y0                  ; y0 = Vh target
        move    x:(r6+$e),b           ; (q1)
        asr     #$8,b,b
        move    b1,a                  ; (q3)
        and     #>$ff,a               ; a = KWID 0..127
        cmp     #>$7f,a
        beq     zz42
        move    a1,x0
        move    #>@KFWSTEP@,x1
        mpy     x1,x0,a
        asl     #$17,a,a              ; a1 = m * WSTEP
        add     #>@KFWMIN@,a          ; + half an octave: the width
        move    y0,b
        tst     b
        bne     zz43
        move    #>$100000,b           ; KBAS OFF: counted from 20 Hz, a plain LP
zz43:
        add     b,a                   ; Vl = base + width
        cmp     #>$5f8000,a
        ble     zz39
zz42:
        move    #>$5f8000,a           ; OFF, or past the top: g 159
zz39:
        move    a,y1                  ; y1 = Vl target
        lua     (r7+$1c),r4           ; r4 -> the filter block
        move    x:(r4+$e),b           ; (q1)
        cmp     #>@KFMAGIC@,b
        beq     zz44
; first block after scinit (or never set up): zero the sections, positions straight to target
        clr     b
        move    r4,r0
        do      #<5,>zz62
        move    b,x:(r0)+
zz62:
        move    y0,x:(r4+$c)
        move    y1,x:(r4+$d)
        move    #>@KFMAGIC@,b
        move    b,x:(r4+$e)
        bra     zz46
zz44:
        move    #0,r0                 ; r0 = "a position moved"
        move    x:(r4+$c),x0
        tfr     y0,a
        sub     x0,a                  ; a = Vh target - Vh
        bsr     zz52
        cmp     x0,a
        beq     zz45
        move    #1,r0
zz45:
        move    a,x:(r4+$c)
        move    x:(r4+$d),x0
        tfr     y1,a
        sub     x0,a
        bsr     zz52
        cmp     x0,a
        beq     zz49
        move    #1,r0
zz49:
        move    a,x:(r4+$d)
        move    r0,b
        tst     b
        beq     zz47                  ; nothing moved: the coefficients stand
        move    x:(r4+$c),y0
        move    x:(r4+$d),y1
zz46:
; coefficients: HP one-pole g1 and SVF (k 1) from Vh, LP SVF (k sqrt 2) from Vl
        tfr     y0,a
        bsr     zz54                  ; x0 = G16(Vh)
        move    x0,y0
        tfr     y0,b
        add     #>$80000,b            ; 1/16 + G16
        move    b,x0
        tfr     y0,a
        bsr     zz56
        move    a0,x:(r4+5)           ; g1 = G16 / (1/16 + G16)
        move    #>@KFK16H@,x1
        bsr     zz58                  ; x0 = a1, x1 = a2
        move    x0,x:(r4+6)
        move    x1,x:(r4+7)
        move    #>$400000,a
        asl     #1,a,a                ; 1.0
        sub     x0,a
        sub     x1,a                  ; a3 = 1 - a1 - a2 (k 1)
        move    a,x:(r4+8)
        tfr     y1,a
        bsr     zz54                  ; x0 = G16(Vl)
        move    x0,y0
        move    #>@KFK16L@,x1
        bsr     zz58
        move    x0,x:(r4+9)
        move    x1,x:(r4+$a)
        move    #>@KFKHL@,y0
        mpy     x1,y0,b
        asl     #1,b,b                ; k * a2 (k/2 * a2 * 2)
        move    b,y0
        move    #>$400000,a
        asl     #1,a,a
        sub     x0,a
        sub     y0,a                  ; a3 = 1 - a1 - k a2
        move    a,x:(r4+$b)
zz47:
; the filters, per sample, on the mono key: u = (L + R) / 16, out = 8 * LP, both channels.
; 2026-10-19 cycle pass: the 7 coefficients are copied once per block to Y (this track's gen-1
; stash slot, r5+$20: scratch until the MON tail rewrites it), so states (X, r1) and
; coefficients (Y, r4) load in one instruction; no displaced address in the loop. The SVFs
; use z = v3 - v1 - P and h2' = h2 + 2P (P = a2 h1 + a3 v3), which keeps w out of the
; registers; integer for integer the model's arithmetic. Parallel moves take a1, so a value
; with fraction bits in a0 is truncated exactly where the model's >> 23 truncates.
; both knobs at OFF and their positions settled there: bypass (the model's rule, see
; sc_keyfilt.py): out = 8u; HP sections left at 0, the LP's ic2 = the last u, so a knob
; turned away from OFF picks up without a step. Plain ducking (filters OFF) costs about what
; the old KFLT bypass did.
        move    x:(r4+$c),b           ; (q1)
        tst     b
        bne     zz61
        move    x:(r4+$d),b           ; (q1)
        cmp     #>$5f8000,b
        bne     zz61
        lua     (r5+$20),r1
        move    y:(r1),y1             ; y1 = gain/64
        move    x:(r7+$2b),r1         ; the key, in Y
        move    #$40,r0
        do      #<$10,>zz63
        move    y:(r1)+,x0
        mpy     x0,y1,a     y:(r1)+,x0
        asl     #$6,a,a
        mpy     x0,y1,b     a,x0
        asl     #$6,b,b
        tfr     x0,a        b,y0
        add     y0,a
        asr     #$4,a,a
        move    a,x0                  ; x0 = u
        tfr     x0,a
        asl     #$3,a,a
        move    a,x:(r0)+
        move    a,x:(r0)+
zz63:
        clr     b
        move    b,x:(r4)+
        move    b,x:(r4)+
        move    b,x:(r4)+
        move    b,x:(r4)+
        move    x0,x:(r4)             ; l2 = the last u
        bra     zz10
zz61:
        lua     (r4+5),r0
        lua     (r5+$21),r1
        do      #<7,>zz60
        move    x:(r0)+,x0
        move    x0,y:(r1)+
zz60:
        move    r4,r1                 ; X: s1 h1 h2 l1 l2
        lua     (r5+$20),r4           ; Y: gain g1 ha1 ha2 ha3 la1 la2 la3
        move    x:(r7+$2b),r5         ; Y: the key (r5 is the stash base again below)
        move    #>$fffffc,n1          ; -4: back from l2 to s1
        move    #$40,r0
        do      #<$10,>zz48
        move    y:(r4)+,y1                  ; y1 = gain/64
        move    y:(r5)+,x0                  ; x0 = L
        mpy     x0,y1,a     y:(r5)+,x0      ; a = gain/64 L ; x0 = R
        asl     #$6,a,a
        mpy     x0,y1,b     a,x0            ; b = gain/64 R ; x0 = gain L (saturated)
        asl     #$6,b,b
        tfr     x0,a        b,y0            ; y0 = gain R (saturated)
        add     y0,a        y:(r4)+,y1      ; a = L + R ; y1 = g1
        move    x:(r1),b                    ; b = s1
        asr     #$4,a,a
        sub     b,a         a,x0            ; x0 = u ; a1 = d = u - s1
        move    a,y0
        mpy     y1,y0,a                     ; a1 = v = d g1
        add     a,b         a,y0            ; b1 = lp1 = s1 + v ; y0 = v
        add     y0,b        b,x1            ; b1 = s1' = lp1 + v ; x1 = lp1
        tfr     x0,a        b,x:(r1)+       ; a = u ; s1'
        sub     x1,a                        ; a = w (this dsp_asm takes no ALU op with an XY move)
        move    x:(r1)+,x1  y:(r4)+,y0      ; x1 = h1 ; y0 = ha1
        move    x:(r1)-,b   y:(r4)+,y1      ; b = h2 ; y1 = ha2
        sub     b,a                         ; a = v3
        mpy     x1,y0,b     a,x0            ; b = ha1 h1 ; x0 = v3
        mac     x0,y1,b     y:(r4)+,y0      ; b1 = v1 ; y0 = ha3
        mpy     y1,x1,a     b,y1            ; a = ha2 h1 ; y1 = v1
        mac     y0,x0,a                     ; a1 = P
        tfr     y1,b        a,y0            ; b = v1 ; y0 = P
        asl     b
        sub     x1,b                        ; b = h1' = 2 v1 - h1
        tfr     x0,a        b,x:(r1)+       ; a = v3 ; h1'
        sub     y1,a        x:(r1),b        ; a = v3 - v1 ; b = h2
        sub     y0,a                        ; a = z = v3 - v1 - P (the HP)
        add     y0,b
        add     y0,b                        ; b = h2' = h2 + 2P
        move    b,x:(r1)+   y:(r4)+,y0      ; h2' ; y0 = la1
        move    x:(r1)+,x1  y:(r4)+,y1      ; x1 = l1 ; y1 = la2
        move    x:(r1)-,b                   ; b = l2
        sub     b,a                         ; a = v3
        mpy     x1,y0,b     a,x0
        mac     x0,y1,b     y:(r4)+,y0      ; b1 = v1 ; y0 = la3
        mpy     y1,x1,a     b,y1            ; y1 = v1
        mac     y0,x0,a                     ; a1 = P
        tfr     y1,b        a,y0            ; y0 = P
        asl     b
        sub     x1,b                        ; b = l1'
        move    b,x:(r1)+                   ; l1'
        move    x:(r1),b                    ; b = l2
        add     y0,b                        ; b = v2 = l2 + P, the LP output
        add     y0,b        b,x0            ; b = l2' = l2 + 2P ; x0 = v2
        tfr     x0,a        b,x:(r1)+n1     ; a = v2 ; l2' ; r1 back to s1
        asl     #$3,a,a
        move    a,x:(r0)+                   ; saturated
        move    a,x:(r0)+
        lua     (r4-8),r4
zz48:
        lua     (r4-$20),r5           ; r5 = the stash base again, for the MON tail
        bra     zz10
; glide: a = target - V, x0 = V -> a = the new V (clean). Snap within @KFSNAP@.
zz52:
        move    a,b
        abs     b
        cmp     #>@KFSNAP@,b
        blt     zz53
        move    a,x1
        move    #>@KFGA@,y0
        mpy     x1,y0,a
zz53:
        add     x0,a
        move    a,x1
        tfr     x1,a
        rts
; G16 at position a (clean), r1 = the table: x0 = GT[j] + frac (GT[j+1] - GT[j])
zz54:
        move    a,b
        asr     #$11,a,a
        move    a1,n1                 ; j
        and     #>$1ffff,b
        asl     #6,b,b
        move    b,x1                  ; frac
        lua     (r1)+n1,r0
        move    p:(r0)+,x0
        move    p:(r0),a
        sub     x0,a
        move    a,y0
        mpy     x1,y0,a
        add     x0,a
        move    a,x0
        rts
; SVF a1, a2 from G16 (y0), k/16 (x1): x0 = a1 = (1/256)/(D/256), x1 = a2 = G a1
zz58:
        mpy     y0,y0,a
        mac     x1,y0,a
        add     #>$8000,a
        move    a,x0                  ; D/256
        move    #>$8000,a
        bsr     zz56
        move    a0,x0                 ; a1
        mpy     y0,x0,a
        asl     #4,a,a
        move    a,x1                  ; a2
        rts
; a0 = floor(a * 2^23 / x0), 0 < a < x0
zz56:
        andi    #$fe,ccr
        do      #<$18,>zz57
        div     x0,a
zz57:
        rts

zz10:
; -- SC LISTEN : if on, stash the processed key -> keybus[my track] gen 1, and
;    publish MON_ON[track] so the dispatcher-level `moncommit`
;    hook (spliced at the per-track COMMIT step, well after this WHOLE module
;    -- including its own undocumented envelope/gain math -- has returned)
;    can independently redo the substitution outside any shared execution
;    context with the compressor's own code. MON_ON/MON_FADE live at
;    Y:$7df0 + track*2 (+0/+1), below the keybus (layout and its evidence at
;    the top of this file); sctap/scdet's gen-0/gen-1 writes never reach it.
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
;
;    MON declick (2026-10-19): MON_ON[my track] is now a per-block ARM that
;    moncommit consumes (reads, then clears) every block, and the word after
;    it, MON_FADE[my track], is moncommit's fade position (0..16 blocks; it
;    used to be MON_KEY -- the stash is indexed by this track now, see r5).
;    While MON is off the stash is still written as long as MON_FADE is not 0,
;    so the fade-out has a live key to fade from. Registers: a, b, x0, r0, r1,
;    n1 only (the proven set above); r5 is reset by stock (`move r4,r5`).
        bsr     zz18                   ; r1 -> MON_ON[my track]
        move    x:(r7+$2d),b          ; (q1) a KEY change waiting: MON off this block
        tst     b
        bne     zz17
        move    x:(r6+$c),b           ; (q1) RMS|MON word
        asr     #$8,b,b
        move    b1,a                 ; (q3)
        and     #>$1,a                 ; MON: 2 = OFF, 3 = ON (sc_norm turns anything
        tst     a                      ; else into 2 before the frame reaches the DSP)
        beq     zz17
        move    #1,b                   ; (q2) stores $10000, moncommit's exact match
        move    b,y:(r1)               ; MON_ON = armed for this block
        bra     zz27
zz17:
        move    #0,b
        move    b,y:(r1)+              ; MON_ON = 0 ; r1 -> MON_FADE[my track]
        move    y:(r1),a
        tst     a
        beq     zz16                   ; not fading out: no stash needed
zz27:
        move    r5,r1
        move    #$20,n1
        lua     (r1)+n1,r1
        move    #$40,r0
        do      #<$20,>zz15
        move    x:(r0)+,x0
        move    x0,y:(r1)+
zz15:
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
                                        ; instead, same idiom the cross-core
                                        ; addressing above already uses
                                        ; (add/sub then a1 into an address
                                        ; register)
        add     #>$40,a                 ; a = $40 + split offset
        move    a1,r0                   ; detector streams from the processed
                                        ; key, correctly offset for a split's
                                        ; 2nd call
        move    #$61,r4             ; --- displaced ---
        rts
zz20:
; KEY OFF -> publish MON_ON[my track] = 0 (no key selected, nothing to show).
; moncommit then fades out from the last stash (at most 16 blocks of it).
        move    #$61,r4             ; --- displaced ; r0 unchanged ---
        bsr     zz18
        move    #0,b
        move    b,y:(r1)
        rts

; r1 -> MON_ON[my track]; uses b and n1. Shared by the KEY declick, the MON tail and zz20
; (2026-10-19 word pass). `bsr` (PC-relative), not `jsr`: the cave sits past dsp_asm's
; short-jsr range; and dsp_asm encodes no backward bsr, so this stays after its callers.
zz18:
        move    x:>$420,b
        asl     #1,b,b
        move    b1,n1
        move    #>@MONB@,r1
        lua     (r1)+n1,r1
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
; commit, every frame -- but MON_ON (then Y:0x800+track*0x80+0x40) is only ever
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
;
; MON DECLICK (2026-10-19): a linear crossfade instead of a hard swap.
; MON_FADE[my track] (the word after MON_ON) counts 0..16 blocks; the mix
; weight g ramps per SAMPLE PAIR, 1/256 per pair, so a full fade is 256 samples
; (16 blocks, ~5.8 ms; 64 samples until 2026-10-24, which left a KEY change with MON
; on a soft click) and continuous across block boundaries:
;   out = dry + g*(key - dry)        dry = X:0.. (this track), key = the stash
; At 0 (dry) and 16 (key) the fast paths below are the old behaviour.
; MON_ON is CONSUMED here (cleared after the read): scdet re-arms it every
; block it runs with MON on, so when scdet stops running -- KEY to OFF, or
; the effect changed away from COMPRESSOR -- the next block fades out. Before
; this, a set MON_ON stayed set and replayed a frozen stash forever.
; MON_FADE outside 0..16 (cold-RAM garbage) reads as 0.
; Registers: a, b, x0, x1, y1, r1, n1, r3. func_00034f, called right after
; the three stock instructions that follow this hook, loads x1, y1 and x0
; itself and writes a and b before reading them (disassembled, both
; payloads: A P:0x55a, B P:0x34f); r1/n1/r3 are reset by those three. r0 is
; never touched. y0, r2 and n2 are NOT used (r2/n2 broke transport, S59).
; mpy x0,y1 is the operand order stock uses there (true signed mpy).
moncommit:
        move    x:>$206,r0           ; --- displaced --- (must survive untouched)
; Exported callable entry for a composed hook. The caller must have replayed
; the displaced x:$206 load first; this body preserves r0 for the stock
; dispatcher and returns after optionally replacing the committed audio.
; It clobbers a, b, x0, x1, y1, r1, n1, r3.
scmonbody:
; The stash pointer is computed once, past the dry exit (2026-10-19 word pass): this hook runs
; for every track every block, and most of them leave there. r3 -> MON_ON/MON_FADE until the
; fade position is written, then the dry pointer.
        move    x:>$420,a             ; a = my track 0..7
        asl     #1,a,a
        move    a1,n1
        move    #>@MONB@,r1
        lua     (r1)+n1,r3            ; r3 -> MON_ON[my track]
        move    y:(r3),b              ; b = MON_ON (exact $10000 = armed this block)
        clr     a
        move    a,y:(r3)+             ; consume ; r3 -> MON_FADE[my track]
        move    y:(r3),a              ; a = fade position
        tst     a
        blt     mc20                  ; garbage -> 0
        cmp     #>$10,a
        ble     mc21
mc20:
        clr     a
mc21:
        cmp     #>$10000,b             ; (q2) exact match vs scdet's ON sentinel,
        beq     mc22                   ; NOT "nonzero" -- see hazard note above.
; -- MON off: fade out, or nothing --
        move    #>$ff8000,x1          ; step -1/256 per pair
        tst     a
        bne     mc24
        move    a,y:(r3)              ; MON_FADE = 0 (also clears any garbage)
        rts                            ; dry: the track's own audio, untouched
mc22:
        move    #>$8000,x1            ; MON on: step +1/256 per pair
mc24:
        move    x:>$420,b
        asl     #6,b,b
        move    b1,n1
        move    #>@KEYB1@,r1
        lua     (r1)+n1,r1            ; r1 -> keybus[my track] gen 1 (the stash)
        move    x1,b
        asr     #$f,b,b               ; b = the step's sign, -1 or +1
        add     a,b                   ; b = the next fade position
        cmp     #>$10,b
        bgt     mc25                  ; MON on and fully in: plain copy, MON_FADE stays 16
        move    b,y:(r3)              ; MON_FADE = one block further out / in
        asl     #$13,a,a              ; a = position * 1/16 (16 -> +1.0, saturated below)
        move    a,y1
        move    #0,r3
        move    y1,a
        add     x1,a
        move    a,y1                  ; g for pair 0 (the move saturates at +1.0)
        do      #<$10,>mc26
        do      #<2,>mc27             ; L, then R (the outer loop's step comes last,
        move    x:(r3),b              ; so the two loops never end on one address; a
        move    y:(r1)+,a             ; `nop` there would cost a cycle a pair)
        sub     b,a
        asr     #1,a,a                ; (key - dry)/2 fits 24 bits
        move    a,x0
        mpy     x0,y1,a
        asl     #1,a,a                ; g*(key - dry)
        add     b,a
        move    a,x:(r3)+
mc27:
        move    y1,a
        add     x1,a
        move    a,y1                  ; g for the next pair
mc26:
        rts
mc25:
        move    #0,r3                  ; reuse r3 (stock resets it right after us anyway)
        do      #<$20,>mc11
        move    y:(r1)+,x0
        move    x0,x:(r3)+
mc11:
        rts

; ---- HOOK 4 : COMPRESSOR init (A P:0x1aa4, B P:0x1864; 2026-10-19, major version) --------
; Stock init's first instruction, `move #>$20c5,x0`, is replaced by a bsr here and replayed
; last. The dispatcher calls init whenever an instance is (re)assigned the effect; the slot's
; previous effect may have used r7+$1c.. (the r7 canary: CHORUS and PLATE do), so the key
; filters start over: $2a is cleared, and scdet's first block zeroes the sections and puts
; the positions straight on target. KEY GAIN's smoother ($17) goes cold too (it snaps).
; Registers: x0 only, which the displaced instruction then sets as stock does.
scinit:
        move    #0,x0
        move    x0,x:(r7+$2a)
        move    x0,x:(r7+$17)
        move    x0,x:(r7+$2c)         ; key in use: OFF
        move    x0,x:(r7+$2d)
        move    #>$20c5,x0           ; --- displaced ---
        rts
