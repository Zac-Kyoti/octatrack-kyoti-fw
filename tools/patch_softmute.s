| SPDX-License-Identifier: MIT
| SPDX-FileCopyrightText: 2026 Zac-Kyoti
| patch_softmute V7 -- audio-track mute (and, V7, SOLO silencing) behave like a single STOP:
| the sample audio cuts (fast clean fade), the track's FX inserts ring their delay/reverb
| tails out, and a silenced track's sequencer trigs make no sound.
|
| Session 9 (V1-V6): the mute case.  Session 11 (V7): the SOLO case, same technique.
| *** 20 Sep 2026 (part 18 addendum 5): the user RETRACTS Session 11's solo hardware
| confirmation -- solo was never properly tested. On hardware SOLO currently ignores
| MUTE MODE entirely and always gives an OT-style hard cut with no FX tails. The solo
| handling below (p1_solo) is therefore UNVERIFIED on hardware, not working-as-shipped.
|
| Session 12 (--defsym DT_MODE=1): a third MUTE MODE, "DT".  DT mute is a pure *sequencer*
| mute -- exactly like a Digitakt trig mute: the voice that is already sounding keeps playing
| under its OWN amp envelope (fades, sustains, or loops forever, whatever the AMP page says),
| its FX ring, and only NEW trigs are suppressed while the track is silenced.  Mechanism:
| the same D5-bit clearing as OT+FX (so FUN_40004db8 keeps every frame level word -> the
| voice + FX still reach the mix untouched) and the same `mt_trig` new-trig drop, but WITHOUT
| the FUN_40008f84 note-off / DAT_8000184a hold that OT+FX uses to fade the dry signal.
| GATE (0x800000dc) == 2 selects it.  DT_MODE is compile-gated so a plain build is unchanged.
|
| Mechanism (confirmed on hardware, MKI): FUN_40004dbc (entry FUN_40004db8) is the per-frame
| DSP-frame builder.  It branches on the SOLO flag 0x80000037:
|   - not solo:  per track, if _DAT_80000008 bit 8+t (muted) -> `clr.w` the frame level word.
|   - solo:      per track, if _DAT_80000008 bit t (0..7) set (SOLOED) -> keep; else the level
|                words get AND-ed with 0 (d1, "any track soloed?") -> silenced.  A non-soloed
|                track that is ALSO muted -> `clr.l` instead.
| Either way the silencing is a post-FX cut that also kills the FX return.
|
| _DAT_80000008 layout:  bits 0..7 = per-track SOLO   bits 8..15 = MUTE   bits 16..23 = CUE.
|
| Session 56 (NOT YET HARDWARE-VALIDATED, DSP-level A/B still pending): a FOURTH hook,
| `mt_ctr` @ 0x4000f834 -- see its own header comment below. `mt_trig`/`mt_rebind` were
| both dynamically PROVEN (ot_emu --watch-pc, real BOTLI retrig) to fire exactly as
| designed, on the exact retrig that still leaks audio -- neither gates DSP restart.
| `mt_ctr` gates the ONE remaining unconditional per-trig write this session could find
| that hook 3's own function (FUN_4000f450) makes past its own detour site: a bump of the
| SAME per-track trig counter hook 2 was built around, from a completely different,
| ungated call path (every repeat trig of an already-bound voice -- T1's exact case).
|
| Four hooks, one cave:
|
| part 18 addendum 10: every hook below used to require SOLO_FLAG (0x80000037) to be set
| before it would consider the solo mask. Stock does NOT work that way -- its own not-solo
| branch (0x40004e3a..) builds D1 = (D5.low8 == 0) ? -1 : 0 and ANDs every non-soloed
| track's level word with it, so ONE solo bit silences the rest whether or not the flag is
| set. The flag test has been removed everywhere; "silenced" now means, exactly as stock
| means it: muted, OR (something is soloed AND this track is not).
|
|  1. `pre`   @ 0x40004dc6 (the displaced `move.l 0x80000008,D5`).  With MUTE MODE == OT+FX,
|     compute the "silenced" audio-track set for this frame:
|         not solo   -> silenced = mute mask (bits 8..15 -> 0..7)
|         solo + >=1 track soloed -> silenced = every non-soloed audio track
|         solo + none soloed      -> silenced = 0  (stock: nothing is cut yet)
|     Then:
|       - keep the frame level words for the silenced tracks by clearing the bits FUN_40004dbc
|         tests in D5 (not solo: clear the mute bits; solo: clear bits 0..15 so every track is
|         kept and the "any soloed?" AND-mask D1 becomes -1) -> FX inserts still reach the mix.
|       - every frame: DAT_8000184a |= silenced   (hold the note-off; the DSP runs the release)
|       - 0->1 edge vs the patch-RAM shadow: FUN_40008f84(t) once per newly-silenced track.
|     MUTE MODE == OT clears the shadow and bails -> byte-for-byte stock.
|
|  2. `mt_trig` @ 0x40006844 (the real per-trig voice starter -- NOT FUN_40005178/
|     trig_to_voice, an unrelated code path proven dead-for-this-purpose by dynamic
|     tracing; see the hook's own header comment below for the full trail).  For a
|     silenced audio track, returns before the active-clear / trig-counter bump /
|     FUN_4000672c call that actually restarts the sample -> no 1-frame attack blip.
|     Isolation-tested AND dynamically proven against real playback in the CPU-only
|     emulator: 100% "silenced" branch taken for a muted track, FUN_4000672c called
|     ZERO times. Flashed anyway: HW showed NO CHANGE (blip and DT both unaffected,
|     both STATIC and FLEX). The CPU-only emulator cannot see the DSP at all -- see
|     hook 3 below for the working hypothesis and caveat.
|
|  3. `mt_rebind` @ 0x4000f4dc (the arena-pointer rebind that runs on EVERY trig,
|     unconditionally, one level up the call chain from mt_trig -- see its own header
|     comment below).  Working hypothesis, NOT emulator-provable: the DSP may watch
|     THIS write, not anything mt_trig gates, as its own independent "(re)bind and
|     play" signal. For a silenced audio track, skips both writes so the voice
|     struct's arena pointers stay unchanged.
|
| _DAT_80000008 itself is never written, so the MUTE/SOLO LEDs and pattern-stored state work.
|
| Assemble:  m68k-elf-as -mcpu=5407 [--defsym ALWAYS_ON=1] ; ld -Ttext=<at> ; objcopy -O binary

    .equ GATE,        0x800000dc     | MUTE MODE word (0 = OT/stock, 1 = OT+FX).  Ignored when ALWAYS_ON.
    .equ MUTE_STATE,  0x80000008     | bits 0..7 SOLO   bits 8..15 MUTE   bits 16..23 CUE
    .equ SOLO_BYTE,   0x8000000b     | MUTE_STATE's SOLO byte (bits 0..7), one per track --
                                         | big-endian, so the low byte of the long at
                                         | 0x80000008.  A single `tst.b` on it answers "is
                                         | anything soloed?" in the same two instructions the
                                         | old SOLO_FLAG test used, which keeps the per-frame
                                         | instruction count unchanged (part 18 addendum 10:
                                         | adding even ~3 instructions per track per frame
                                         | measurably perturbed the render -- 0.994
                                         | correlation, same energy -- in a loop this KB
                                         | already flags as timing-sensitive).
    .equ SOLO_FLAG,   0x80000037     | byte, non-zero while SOLO mode is engaged
    .equ REL_STATE,   0x8000184a     | byte: voice t in RELEASE when bit t set
    .equ PROBE_LO,    0x800000d4     | OTFX_PROBE only: free, battery-restored PERSONALIZE
    .equ PROBE_HI,    0x800000d5     | bytes, poked by the harness to bisect the block
    .equ SHADOW,      0x80006c66     | patch RAM: last frame's "silenced" set (8 bits)
    .equ F_NOTEOFF,   0x40008f84     | FUN_40008f84(t) -- per-track note-off
    .equ BACK,        0x40004dcc     | FUN_40004dbc, after the displaced `move.l 0x80000008,D5`

    .text

| ============================ hook 1: FUN_40004dbc =============================
    .global pre
pre:
    move.l  MUTE_STATE,%d5              | displaced: `move.l 0x80000008,D5`
    lea     (-0x10,%sp),%sp
    movem.l %d0-%d3,(%sp)               | 4 longs == the 0x10 reserved

    .ifndef ALWAYS_ON
    move.l  GATE,%d0
    cmpi.l  #1,%d0                      | MUTE MODE == OT+FX ?
    beq     p1_active
    .ifdef DT_MODE
    cmpi.l  #2,%d0                      | MUTE MODE == DT (2) or OTFX (3) ?
    bcc     p1_active                   | `bcc` (GATE >= 2), not a second `beq` plus a third
                                         | compare: MEASURED, this costs OT, OT+FX and DT-T
                                         | exactly ZERO extra instructions, while an appended
                                         | `cmpi #3 / beq` here (two per frame) was on its own
                                         | enough to break OT's bit-identity.
    .endif
    clr.b   SHADOW                      | OT (or unknown): stock; keep the shadow clean for later
    bra     p1_done
p1_active:
    .endif

| ---- silenced set -> D2 (bits 0..7) ----
    tst.b   SOLO_FLAG
    bne     p1_solo

    | SOLO_FLAG == 0 -- but stock STILL solo-silences on this branch, which this project
    | never knew: the not-solo branch (0x40004e3a..) builds D1 = (D5.low8 == 0) ? -1 : 0 at
    | 0x40004e64 and ANDs every NON-soloed track's level word with it at 0x40004e8a. So a
    | single solo bit, with SOLO_FLAG never set, silences every other track instantly,
    | post-FX (no FX tails), identically in every MUTE MODE.
    |
    | *** part 18 addendum 10: THIS is the SOLO bug the user reported, and the reason
    | addendum 8's fix (which only touched the SOLO_FLAG branch) did nothing on hardware.
    | Reproduced in the DSP port by setting ONE solo bit and no flag: 0.0147 at the event
    | then digital silence, vs a normal mute's smooth multi-second reverb decay. ***
    move.l  %d5,%d2
    lsr.l   #8,%d2
    andi.l  #0xff,%d2                   | silenced = mute mask
    move.l  %d5,%d0
    andi.l  #0xff,%d0                   | soloed mask (stock reads the whole low byte)
    beq     p1_ns_clear                 | nothing soloed -> stock's own D1 is already -1 and
                                         | the clear below is a no-op on bits 0..7, so this
                                         | path stays BYTE-IDENTICAL to before for a plain
                                         | mute.  That is the safety property for the modes
                                         | the user has already confirmed working.
    eori.l  #0xff,%d0                   | silenced-by-solo = ~soloed & 0xff
    or.l    %d0,%d2                     | silenced = muted OR not-soloed
p1_ns_clear:
    | keep EVERY track's frame level words: clear D5 bits 0..15 (mute AND solo).  Clearing
    | 8..15 is exactly what the old `D5 &= ~(silenced << 8)` did; clearing 0..7 is the new
    | part.  The CUE bits (16..23) are deliberately left alone -- stock's own cue-send word
    | at 0x40004e6e..78 keys off them, and cueing is not ours to change.
    andi.l  #0xffff0000,%d5
    bra     p1_edge

p1_solo:
    | Solo engaged.  BOTH of stock's solo-branch silencing paths are post-FX HARD cuts that
    | also kill the FX return (re-derived from the binary, part 18 addendum 5):
    |     not soloed AND muted -> `clr.l` both words
    |     not soloed           -> words AND D1, where D1 = (D5.low8 == 0) ? -1 : 0
    | so the ONLY way a silenced track can follow MUTE MODE is for neither to run. That means
    | clearing D5's low 16 bits UNCONDITIONALLY here.
    |
    | *** part 18 addendum 8: this is the SOLO bug the user reported on hardware ("soloing in
    | all modes produces the OT type cut, quick cut, no fx tails"). The previous version
    | branched to p1_zero when the soloed mask was 0 and left D5 UNTOUCHED on that path -- so
    | with solo engaged and nothing soloed, stock's `clr.l` still hard-cut every MUTED track,
    | in every MUTE MODE. Reproduced exactly in the DSP-rendering port: muted + SOLO_FLAG
    | rendered 0.0186 then digital silence within 20 ms, against a normal mute's smooth
    | 0.0504 -> 0.0119 decay over 3 s on the same reverb-carrying track. ***
    move.l  %d5,%d2
    andi.l  #0xff,%d2                   | soloed mask (stock reads the whole low byte, bit 7
                                         | included -- mirror it exactly rather than guessing
                                         | about FUN_4007c428's bit-7 aggregate)
    beq     p1_solo_none
    eori.l  #0xff,%d2                   | silenced = ~soloed & 0xff  (the 8 audio tracks)
    bra     p1_solo_fold
p1_solo_none:
    moveq   #0,%d2                      | solo engaged but nothing soloed -> nothing silenced
                                         | BY SOLO.  Muted tracks are still silenced, below.
p1_solo_fold:
    | Fold the MUTE mask in: a muted track must follow MUTE MODE (fade / FX tails / DT ride)
    | whether or not solo happens to be engaged, instead of stock's `clr.l`.
    move.l  %d5,%d0
    lsr.l   #8,%d0
    andi.l  #0xff,%d0
    or.l    %d0,%d2                     | silenced = solo-silenced OR muted
    | keep EVERY track's frame level words: clear D5 bits 0..15, ALWAYS on this path
    |  -> every track: solo bit clear + mute bit clear -> the "& D1" keep path
    |  -> D1 = (D5.b == 0) ? -1 : 0  becomes -1 -> words pass through unchanged
    andi.l  #0xffff0000,%d5
    bra     p1_edge

p1_zero:
    moveq   #0,%d2

p1_edge:
    .ifdef DT_MODE
| ---- DT: the D5 mute/solo bits are already cleared above (voice + FX keep flowing to the
|      mix untouched); the voice rides its own amp envelope.  No note-off, no REL_STATE. ----
    move.l  GATE,%d0
    cmpi.l  #2,%d0
    bcs     p1_edge_ot                  | GATE < 2 (OT+FX) -> the note-off path.  `bcs` in
                                         | place of the original `bne` is free: same count,
                                         | same taken/not-taken outcome for GATE 1 and GATE 2.
    bhi     p1_otfx                     | GATE > 2 (OTFX) -> the dry cut.
| ---- GATE == 2 (DT-T) falls through to here.  ⚠ THIS TAIL IS LOAD-BEARING: without it DT-T
|      falls straight into p1_otfx and is SILENCED by the dry cut.  That bug was in the v5/v6
|      builds of this session and was caught only by measuring DT-T's post-mute LEVEL against
|      the flashed build (median 30.6 dB quieter, up to 48 dB).  "GATE 2 is not bit-identical"
|      did NOT catch it -- an innocent explanation (the one extra instruction) was already to
|      hand, and it also explains v4's DT-T divergence, which this session first wrote off as
|      alignment sensitivity.  Measure the BEHAVIOUR, not just the equality.
    clr.b   SHADOW                      | DT-T: no note-off state to carry
    bra     p1_done
                                         | ⚠ THIS IS THE ONE INSTRUCTION THAT IS NOT FREE.
                                         | DT-T executes it (not taken) once per frame, and
                                         | one instruction per frame is enough to move this
                                         | build's render off bit-identical -- measured three
                                         | ways (see NOTES.md part 18 addendum 12).  Telling
                                         | four modes apart needs one more test than telling
                                         | three apart, and every arrangement of that test
                                         | lands its cost on one of the three shipped modes.
                                         | DT-T's own BEHAVIOUR is unchanged (per-trig RMS
                                         | matches the shipped build to within a few percent,
                                         | whole-run RMS to 0.03%); it is the sample-exact
                                         | equality that is lost.  Which mode pays is a
                                         | one-line change here -- it is the user's call.
                                         | GATE 2 (DT) and GATE 3 (OTFX) both fall through to
                                         | the no-note-off path: DT because the voice must ride
                                         | its own amp envelope, OTFX because the voice must keep
                                         | playing untouched (the playhead has to stay where the
                                         | pattern puts it) while hook 16 zeroes the dry instead.
                                         | `bcs` rather than `bne` keeps the instruction count
                                         | identical for GATE 1 and GATE 2.

| ---- OTFX (GATE 3): the DRY HARD CUT ------------------------------------------------
| OTFX is DT's frame handling (level words left open so the inserts keep ringing, no
| note-off, no REL_STATE) plus this: every frame, zero a silenced track's dry L/R gains.
| Hooks 2/3/9/10/15 all PASS for GATE 3, so trigs fire and voices restart exactly as on
| stock -- measured, the live playhead reaches stock's own 0x31e1 rather than the 0x14be1
| the trig-masking modes reach -- and unmuting therefore picks up where the pattern would
| have been.  The track is silent because its dry gain is zero, not because the sequencer
| was stopped.
|
| WHERE THE DRY IS.  The per-track DSP parameter block is 0x80000110 + sel*512 + track*64;
| its +2/+4 are the dry L/R gains (established on HARDWARE in Session 58 -- see hook 8's
| header: with only +2 zeroed the leak is dry, one channel only, and panning BAL into the
| zeroed channel silences the track).  Measured this session with --watch-mem: the level
| chain rewrites +2 (0x4000ced4) and +4 (0x4000cb4e/0x4000cc20/0x4000ced0) EVERY frame for
| both halves, so the cut must be re-applied every frame -- and must NOT be keyed on
| REL_STATE, which is exactly the race that sank hooks 8/11/13 and which would leak one
| frame of full-level dry on every trig in the one mode where trigs never stop.
|
| ⚠ WHY IT LIVES HERE, in hook 1's cave, and not at its natural site.  The obvious place is
| the head of stock's own per-track release loop (0x4000d0b4, a clean 6-byte fit).  That was
| built and MEASURED, and it fails this project's own bit-identity rule: a detour there with
| a PURE NO-OP body -- replay the two displaced instructions, jump back, zero logic -- still
| perturbs the render in every mode (max|diff| 1032338 at GATE 0, 1347105 at GATE 2, against
| a build proven bit-identical to itself).  The detour itself is the cost, so no amount of
| tuning inside that cave can recover it.  Riding hook 1's EXISTING per-frame detour costs
| the other modes nothing at all except the single not-taken `bhi` above, which DT-T pays.
|
| %d0-%d3 are ours (hook 1 saved them on entry); %d5 is the function's own displaced
| MUTE_STATE and is untouched; %a0 is the caller's and is pushed/popped, on this path only.
| Both ping-pong halves are zeroed (+0/+0x200) so this needs no knowledge of `sel`.
p1_otfx:
| OTFX (GATE 3) = DT-T's frame handling -- the level words are already left open by the
| shared path above, so the inserts keep reaching the mix and ring their tails -- plus this:
| every frame, zero a silenced track's dry L/R gains.  No note-off, no REL_STATE, and none
| of the trig-masking hooks (2/3/9/10/15 all PASS for GATE 3), so trigs fire and voices
| restart exactly as on stock.  MEASURED: the live playhead reaches stock's own 0x31e1
| rather than the 0x14be1 the trig-masking modes reach, which is precisely "playback picks
| up where it would have been had we never muted".  The track is silent because its dry gain
| is zero, not because the sequencer was stopped.
|
| WHERE THE DRY IS: the per-track DSP parameter block is 0x80000110 + sel*512 + track*64,
| and its +2/+4 are the dry L/R gains (established on HARDWARE in Session 58 -- see hook 8's
| header).  Measured this session with --watch-mem: the level chain rewrites +2 (0x4000ced4)
| and +4 (0x4000cb4e/0x4000cc20/0x4000ced0) EVERY frame for both halves, so the cut must be
| re-applied every frame, and must NOT be keyed on REL_STATE -- that race is what sank hooks
| 8/11/13, and in the one mode where trigs never stop it would leak a frame of full-level dry
| on every trig.  Both ping-pong halves are zeroed, so this needs no knowledge of `sel`.
|
| %d2 (the silenced set) and %d5 are already computed by the shared path; %d0-%d3 are hook
| 1's own saved registers; %a0 belongs to the caller and is pushed/popped on this path only.
| WHICH WORDS, BISECTED WITH RENDERS -- and CORRECTED after a hardware report.
|
| The first version of this cut zeroed bytes 2..15, on the strength of an audio bisection
| alone: every range containing +6 or +10 silenced the track and let the tail ring out, and
| +2/+4 were "known" to be the dry L/R gains from hook 8's hardware result.  IT SHIPPED AND
| IT WAS WRONG.  The user flashed it and reported OTFX behaving exactly like OTFX-T, and the
| test that had never been run -- an actual UNMUTE -- reproduced it at once:
|
|   mute at frame 5532, UNMUTE at 9500 (between trigs; the next trig is at 10335)
|                             silent while muted    audio at the unmute, +0/+40/+80 ms
|     OT (stock, the target)        yes             0.0633  0.0653  0.0654
|     cut 2..6   (the dry pair)     yes             0.0000  0.0000  0.0000   <-- FREEZES it
|     cut 6..8   (+6 alone)         yes             0.0621  0.0653  0.0654   <-- correct
|     cut 10..12 (+10 alone)        yes             0.0621  0.0653  0.0654   <-- correct
|     cut 2..15  (what shipped)     yes             0.0000  0.0000  0.0000   <-- FREEZES it
|
| So +2/+4 do NOT merely scale the dry: zeroing them stops the voice ADVANCING, and playback
| cannot resume mid-sample afterwards -- which is precisely the property OTFX exists for.
| +6 and +10 silence the voice upstream of the insert while leaving it running, so the tail
| rings out AND the unmute picks up where the pattern would have been.  Both are cut, for
| symmetry: each is independently sufficient here, but this project has been bitten before by
| a stereo pair where stock zeroed one side and clamped the other (hook 8), and a centred
| test project cannot tell an L/R pair from a redundant one.
|
| ⚠ The lesson, at cost: an audio bisection answered "what silences the track" and I read it
| as "what cuts the dry".  The defining property of this mode was never measured until the
| user's hardware said otherwise -- the emulator evidence for it was a ColdFire-side playhead
| counter, which kept advancing while the DSP-side voice did not.  Measure the PROPERTY, not
| a proxy for it.
|
    clr.b   SHADOW                      | like DT-T: no note-off state to carry
    tst.l   %d2
    beq     p1_done
    .ifdef OTFX_PROBE
| ⚠ DIAGNOSTIC BUILD ONLY (--defsym OTFX_PROBE=1).  Instead of the two fixed dry words, zero
| the byte range [PROBE_LO, PROBE_HI) of every silenced track's 64-byte block, in BOTH
| ping-pong halves, with the range read fresh every frame from two free PERSONALIZE bytes.
| That makes the block bisectable with RENDERS instead of rebuilds -- which is the cheap way
| to find the pre-insert gain / FX send that the +2/+4 dry cut does not reach (the ~-28 dB
| per-trig re-excitation of the reverb).  Never ship this.
    move.l  %a0,-(%sp)
    move.l  %a1,-(%sp)
    lea     0x80000110,%a0              | ping-pong half 0, track 0
    lea     0x80000310,%a1              | ping-pong half 1, track 0
    moveq   #0,%d3
p1_oc_loop:
    btst    %d3,%d2
    beq     p1_oc_next
    moveq   #0,%d0
    move.b  PROBE_LO,%d0
p1_oc_word:
    clr.w   (0,%a0,%d0.l)
    clr.w   (0,%a1,%d0.l)
    addq.l  #2,%d0
    moveq   #0,%d1
    move.b  PROBE_HI,%d1
    cmp.l   %d1,%d0
    bcs     p1_oc_word
p1_oc_next:
    lea     (64,%a0),%a0
    lea     (64,%a1),%a1
    addq.l  #1,%d3
    cmpi.l  #8,%d3
    bne     p1_oc_loop
    movea.l (%sp)+,%a1
    movea.l (%sp)+,%a0
    bra     p1_done
    .else
    move.l  %a0,-(%sp)
    move.l  %a1,-(%sp)
    lea     0x80000110,%a0              | ping-pong half 0, track 0
    lea     0x80000310,%a1              | ping-pong half 1, track 0 -- zeroing BOTH halves is
                                         | why this needs no knowledge of `sel`
    moveq   #0,%d3
p1_oc_loop:
    btst    %d3,%d2
    beq     p1_oc_next
    clr.w   (6,%a0)                     | half 0
    clr.w   (10,%a0)
    clr.w   (6,%a1)                     | half 1
    clr.w   (10,%a1)
p1_oc_next:
    lea     (64,%a0),%a0
    lea     (64,%a1),%a1
    addq.l  #1,%d3
    cmpi.l  #8,%d3
    bne     p1_oc_loop
    movea.l (%sp)+,%a1
    movea.l (%sp)+,%a0
    bra     p1_done
    .endif

p1_edge_ot:
    .endif
| ---- shadow edge (always update the shadow) ----
    moveq   #0,%d1
    move.b  SHADOW,%d1
    move.b  %d2,SHADOW
    not.l   %d1
    and.l   %d2,%d1                     | D1 = newly-silenced (0->1 edge)

| ---- maintain REL_STATE |= silenced ----
    tst.l   %d2
    beq     p1_done
    moveq   #0,%d0
    move.b  REL_STATE,%d0
    or.l    %d2,%d0
    move.b  %d0,REL_STATE

| ---- note-off the newly-silenced tracks, once ----
    tst.l   %d1
    beq     p1_done
    moveq   #0,%d3
p1_loop:
    btst    %d3,%d1
    beq     p1_next
    move.l  %d3,-(%sp)
    jsr     F_NOTEOFF
    addq.l  #4,%sp
p1_next:
    addq.l  #1,%d3
    moveq   #8,%d0
    cmp.l   %d3,%d0
    bne     p1_loop

p1_done:
    movem.l (%sp),%d0-%d3
    lea     (0x10,%sp),%sp
    jmp     BACK

| ============================ hook 2: FUN_40006844 (the real per-trig voice starter) ==========
| Session ?? part 1 (HW-reported: DT did nothing at all; OT+FX's trig blip, believed fixed, was
| back): hook 2 used to detour FUN_40005178, on the theory (from an old, out-of-context Ghidra
| decompile) that `trig_to_voice` -> FUN_40005178 was the sequencer's per-trig voice-start path.
| WRONG, proven by driving the real firmware in the full-firmware emulator (refs/octabam): 79
| real trigs fired across 6s of playback and FUN_40005178 was entered ZERO times; neither of the
| two "voice command mailbox" addresses its own body writes was ever touched. That whole
| mechanism is unrelated to ordinary sequenced trigs -- the old hook there was harmless dead
| code from this scenario's point of view, which is exactly why reflashing it changed nothing.
|
| Session ?? part 2 -- the REAL path, found by tracing the actual trig flag write
| (`FW_LIVE_NIBBLE` 0x46104d15) back through real execution, not by re-reading decompiles:
| a real trig reaches `FUN_40006820(track)` (an 8-track fan-out: track<8 falls straight through
| to the real work below; track==8 recurses over 0..7) which falls into the genuine per-track
| body at **FUN_40006844**. That function: raises the CPU's IPL (`movew sr,d2` / `movew
| #0x2700,sr`), clears the voice struct's `active` byte (`VOICE_BASE+track*0xA8`), bumps a
| per-track trig counter (`VOICE_BASE+track*0xA8+0x90` -- confirmed dynamically: this exact
| location increments 1,2,3,4,... on every real trig), then calls FUN_4000672c (which restarts
| the sample's amp/settings state -- the actual "make sound" step) before restoring the saved
| SR and returning. Nowhere in this chain is MUTE_STATE ever tested. This is confirmed the real
| dispatch by TWO independent dynamic traces landing on the same code (a PC-trace burst right
| after a real trig, and a direct memory-write watch on the voice struct's trig counter).
|
| Fix: detour FUN_40006844's own entry -- its first two instructions, `movew sr,d2` (2 B) +
| `movew #0x2700,sr` (4 B), are exactly 6 B, a coincidental perfect fit for our `jmp abs.l`
| detour, same convention as every other hook in this project. For a silenced audio track,
| `rts` immediately -- BEFORE the active-clear, the counter bump, or the FUN_4000672c call that
| actually restarts the sample -- so there is nothing left to produce even a one-frame blip.
| For everything else (not muted, not an audio track, MUTE MODE == OT, or any solo case that
| doesn't apply), replay the two displaced instructions and resume normal execution. `%d1`
| (the track number, live across this whole function) is never touched by this hook; `%d0` is
| free to clobber (the original code reloads it immediately after); `%d3` is saved/restored
| around the check purely out of caution since its liveness here isn't otherwise established.
|
| Session ??-ter (caught by dynamic full-firmware validation, NOT flashed): FUN_40006844 is
| reached from FUN_40006820's OWN body via a plain conditional branch (`bccs`), not a fresh
| call -- so FUN_40006820's prologue (`movel a2,-(sp) ; movel d2,-(sp)`) is STILL live on the
| stack at this point, underneath the real return address, and its epilogue
| (`movel sp@+,d2 ; moveal sp@+,a2 ; rts`) is what finally unwinds it. An early `rts` that
| only pops our own scratch push leaves those 2 extra longs on the stack, so `rts` jumps to
| garbage instead of the real caller -- crashed the emulator instantly under real playback
| (`unhandled exception 4` / illegal instruction) even though the isolated unit test passed
| (it entered mt_trig directly, with no simulated FUN_40006820 stack frame beneath it, so it
| never exercised this). `mt_silenced` must pop the SAME 2 longs the real epilogue would.
    .equ MT_BACK,     0x4000684a        | FUN_40006844, after the displaced `movew sr,d2` / `movew #0x2700,sr`
    .global mt_trig
mt_trig:
    move.l  %d3,-(%sp)

    .ifndef ALWAYS_ON
    move.l  GATE,%d0
    .ifdef DT_MODE
    subq.l  #1,%d0                      | mode 1 -> 0, mode 2 -> 1
    cmpi.l  #1,%d0
    bhi     mt_pass                     | MUTE MODE not in { OT+FX, DT }
    .else
    cmpi.l  #1,%d0
    bne     mt_pass
    .endif
    .endif

| ---- drop iff this track (d1, 0-7 -- FUN_40006820's own fan-out guarantees this) is silenced ----
    move.l  %d1,%d0
    addi.l  #8,%d0
    move.l  MUTE_STATE,%d3
    btst    %d0,%d3                     | muted (bit 8+track) ?
    bne     mt_silenced
    tst.b   SOLO_BYTE                   | anything soloed at all ?
    beq     mt_pass
    move.l  %d3,%d0
    andi.l  #0xff,%d0
    beq     mt_pass                     | nothing soloed -> let it through
    btst    %d1,%d3                     | this track soloed (bit track) ?
    bne     mt_pass                     | soloed -> let it through
| fallthrough: solo active + this track not soloed -> silence it
mt_silenced:
    move.l  (%sp)+,%d3                  | restore our own scratch
    move.l  (%sp)+,%d2                  | restore FUN_40006820's saved D2 (its loop counter)
    movea.l (%sp)+,%a2                  | restore FUN_40006820's saved A2 (its self-address)
    rts                                 | NOW the real return address is on top -- drop this
                                         | trig entirely: no active-clear, no counter bump,
                                         | no FUN_4000672c call -- nothing to blip

mt_pass:
    move.l  (%sp)+,%d3
    | ---- displaced prologue of FUN_40006844 ----
    movew   %sr,%d2
    movew   #0x2700,%sr
    jmp     MT_BACK

| ============================ hook 3: 0x4000f4dc (the arena-pointer rebind) ============
| Session ??-quater: mt_trig, isolation-tested AND dynamically proven (real playback,
| direct instrumentation) to take the silenced branch 100% of the time and to reduce
| FUN_4000672c's call count for a muted track to exactly zero, was flashed and STILL
| made no audible difference -- blip unchanged, DT still silent, with BOTH STATIC and
| FLEX tested. This ColdFire-only emulator has no DSP model at all, so everything
| mt_trig fixed is real and CPU-side-true, but invisible to whatever actually gates
| DSP playback. Working hypothesis: the DSP watches this write, not FUN_40006844's own
| CPU-side machinery.
|
| Every real trig unconditionally rewrites the voice struct's arena-entry pointers here
| (`+4`/`+8`, `VOICE_BASE + track*0xA8`) to point at the FLEX/STATIC arena slot this
| track's machine currently resolves to -- no MUTE_STATE test anywhere in the caller
| (`0x4000f454`-ish). If the DSP treats THIS pointer write as its own independent
| "(re)bind and play" edge -- plausible, since it is the only DSP-visible state that
| changes on every trig regardless of what FUN_40006844/FUN_4000672c do -- then leaving
| it unconditional would explain a real trig producing sound no matter what mt_trig
| does purely on the CPU side.
|
| This hook is deliberately narrow: rather than bail out of `0x4000f454`'s own large,
| multi-register prologue (`lea sp@(-60),sp` + `moveml d2-d7/a2-fp,sp@` -- a much bigger,
| riskier frame than FUN_40006844's simple 2-push case that already bit us once), it
| detours only the two write instructions themselves (`movel a5,a2@(4)` /
| `movel a4,a2@(8)`, 8 B total -- room for a 6 B `jmp` + 2 B spare). For a silenced
| track, skip BOTH writes -- the voice struct's arena pointers simply keep whatever they
| already had (0/stale if never yet unmuted, which is the correct "no sound" state
| anyway) -- and resume normal execution. `%a5`/`%a4` (the freshly computed arena
| addresses) are UNCHANGED either way, so the rest of this function's own "does this
| need a fresh FUN_40006820 bind" decision (which reads `%a5@`, a register, not the
| memory this hook gates) is completely unaffected -- mt_trig's own protection there
| stays fully intact regardless of what this hook does.
|
| The track number is read from `(0x40,%sp)` -- the SAME stack argument the original
| code already used for this exact purpose a few instructions earlier (confirmed: the
| stack pointer is untouched by anything between that read and this site, so the slot
| is still valid). `%d0`/`%d1` are freely clobberable here (neither is read by the
| original code again before being freshly redefined, on either the silenced-skip path
| or the resumed-original path).
|
| Caveat, stated plainly: unlike `mt_trig`, this hook's actual effect on real audio
| cannot be verified in this CPU-only emulator at all -- there is no DSP to observe. It
| is a well-reasoned next guess grounded in what IS provably true (this write is the
| one DSP-relevant state change mt_trig does not gate), not a decisively proven fix.
    .equ MR_BACK,   0x4000f4e4        | FUN_4000f454-ish, right after the 2 displaced writes
    .global mt_rebind
mt_rebind:
    .ifndef ALWAYS_ON
    move.l  GATE,%d0
    .ifdef DT_MODE
    subq.l  #1,%d0
    cmpi.l  #1,%d0
    bhi     mr_pass
    .else
    cmpi.l  #1,%d0
    bne     mr_pass
    .endif
    .endif

    move.l  (0x40,%sp),%d0               | track (same stack slot the caller already used)
    addi.l  #8,%d0
    move.l  MUTE_STATE,%d1
    btst    %d0,%d1                      | muted (bit 8+track) ?
    bne     mr_silence
    tst.b   SOLO_BYTE                   | anything soloed at all ?
    beq     mr_pass
    move.l  %d1,%d0
    andi.l  #0xff,%d0
    beq     mr_pass                      | nothing soloed -> let it through
    move.l  (0x40,%sp),%d0
    btst    %d0,%d1                      | this track soloed (bit track) ?
    bne     mr_pass                      | soloed -> let it through
| fallthrough: solo active + this track not soloed -> silence it
mr_silence:
    jmp     MR_BACK                      | skip BOTH arena-pointer writes for a silenced track

mr_pass:
    move.l  %a5,(4,%a2)                  | displaced instr 1
    move.l  %a4,(8,%a2)                  | displaced instr 2
    jmp     MR_BACK

| ---------------- hooks 4-7: TRIED, MEASURED, RULED OUT (Session 56 / 57) ---------------
| Removed from this file to keep the cave small (they also pushed the PERSONALIZE arrays
| out of their usual home and made cross-build comparisons noisy).  Full reasoning, the
| measurements, and the exact detour bytes for each are in NOTES.md, Sessions 56-57:
|
|   mt_ctr  0x4000f834  gate the reuse-path per-track trig counter  -> made the blip LOUDER
|   mt_pos  0x4000f790  gate the six START/END position writes      -> completely inert
|   mt_ptr  0x4000f820  gate the play-pointer writes                -> completely inert
|   fxcut   0x40004e9e  cut the frame builder's per-track word C    -> wrong producer, inert
|   (plus `--defsym ALWAYS_NOTEOFF=1` in hook 1: note-off every frame rather than on the
|    mute edge -> inert on the blip AND a regression on the ordinary mute)
|
| All five aimed at stopping the retriggered VOICE.  The voice was never the problem --
| see hook 8.
|
| ============================ hook 13: 0x4000d0c2 (REL_STATE RACE + the unmuted-envelope
| ==== regression, both closed -- SHADOW is now the ONLY signal, GATE/REL_STATE are not) ===
| Session 58 continued yet again, part 8: first version of this hook only handled the case
| "REL_STATE wrongly says not-silenced but SHADOW says muted" (the original race), by
| falling into `relcut` (hook 8, below) UNCHANGED whenever REL_STATE's own bit was set.
| Session 58 continued yet again, part 10: FLASHED, and the user reported ordinary,
| completely UNMUTED playback in OT+FX/DT mode had shortened envelopes -- "amp hold
| reduced to trig length". Root cause, found by testing `relcut` ALONE (no hook 13 at all,
| the pre-existing hardware-good baseline) against a track with real content, nothing
| muted, GATE toggled 0 vs 1: **`relcut` zeros the second level word (+4) for ANY track
| whose REL_STATE bit is set and GATE != 0 -- it never checks whether THAT SPECIFIC track
| is actually muted.** REL_STATE ("voice t in RELEASE") is a stock, per-voice indicator
| that goes high for ordinary natural decay, muted or not; `relcut`'s own Session-58 header
| comment even says the fix is meant for "ANY silenced track" but the code only ever
| checked the GLOBAL GATE, not per-track mute state. Confirmed directly
| (`tools/diag_relcut_unmuted.py` against `out/mainos_mutemode_dt_BASELINE.bin`, hook 13
| not even present): 8267 of 8268 writes to +4 were VALUE 0, starting 2 frames after a
| single natural trig, with MUTE_STATE at 0 for the entire run. **This predates hook 13
| entirely** -- every build since Session 58 has had it; it was simply never tested with
| nothing muted before.
|
| This is a SECOND, independent bug from the original race, and the RIGHT fix folds both
| into one: make `SHADOW` (`pre`'s own independently-maintained, per-frame, per-track mute
| set -- NEVER read by `relcut`'s old logic at all) the ONLY thing that decides whether a
| track's dry signal gets force-muted. `REL_STATE` still matters, but ONLY for reproducing
| STOCK's own pre-existing natural-release clamp for a track that is genuinely NOT muted --
| exactly what un-modified stock already does, byte for byte. This also means the GLOBAL
| GATE check disappears entirely: `pre` (hook 1) already clears `SHADOW` to 0 every single
| frame whenever GATE is not OT+FX/DT ("OT (or unknown): stock; keep the shadow clean for
| later" -- hook 1's own header), so a `SHADOW`-only design AUTOMATICALLY reproduces true
| stock behaviour in GATE=0 with no separate check needed.
|
| Mechanism, read directly off this loop's own disassembly (`m68k-elf-objdump -m
| m68k:cfv4e`):
|
|   4000d0ba:  mvzb 0x8000184a,%d0   | REL_STATE, loaded ONCE per frame
|   4000d0c0:  asrl #1,%d0          | this track's bit -> Carry, OUTSIDE this detour
|   4000d0c2:  bccs 0x4000d0d6      | stock: carry CLEAR -> skip; carry SET -> old relcut
|   4000d0d6:  lea %a0@(64),%a0     | shared tail: next track (+0x40), loop back
|
| New decision tree, entirely SHADOW-driven:
|   SHADOW bit SET (genuinely muted, regardless of REL_STATE) -> force +2/+43/+4 all to 0.
|   SHADOW bit CLEAR (genuinely not muted):
|     REL_STATE bit was CLEAR (not releasing either) -> do nothing, exact stock skip.
|     REL_STATE bit was SET (genuine natural release)  -> replicate STOCK's OWN original
|       behaviour exactly: zero the dry word, CLAMP (not zero) the route word to 6144.
|
| Track index from %a0, as before: `((%a0 - 0x80000110) >> 6) & 7`. `%d3` confirmed free
| (hook 8's and hook 11's own header comments). `%d4` ALSO confirmed free this session:
| scanned forward to 0x4000d124 (`moveb 0x8000184b,%d4`) with zero reads of %d4 anywhere in
| between -- a fresh load before any use, proving no live value crosses this detour in it.
| `scs %d4` captures REL_STATE's own carry bit into %d4 (0xFF/0x00) BEFORE the SHADOW-index
| arithmetic gets a chance to disturb the flags -- `scs`/`scc` read condition codes without
| writing them, so this is safe where a plain conditional branch immediately after would
| not be. Branches on `btst`'s own Z flag immediately, before restoring %d3 (the same
| flag-clobber class of bug relcut's own header comment already documents once: `move.l
| (sp)+,%d3` sets N/Z from the popped value and clears V/C).
|
| `relcut`'s OWN body (hook 8, below) is now DEAD CODE -- no longer reached by anything,
| stock or this hook. Left in place, unreferenced, per this project's own convention for
| superseded-but-documented attempts (see hook 11's `relstate_or`) rather than deleted.
|
| REPLACES hook 8's own standalone stock-side detour, same as the part-8 version: span
| 0x4000d0c2..0x4000d0d6 (20 B), expected-bytes = relcut's stock string with `6412`
| prepended -- see the build script's PATCHES list.
|
| VALIDATED this session (NOTES.md "part 10"): (1) unmuted, GATE=0, byte-identical to
| stock (SHADOW==0 always, untouched); (2) unmuted, GATE=1, a genuinely-not-muted track
| with real content -- the route word is CLAMPED to 6144 on natural release, matching true
| stock, NOT zeroed (the bug this version fixes); (3) muted, multi-retrig, both pings, both
| modes -- the original race stays closed (SHADOW catches the momentary wrong REL_STATE
| answer exactly as the part-8 version did).
    .global relstate_shadow
relstate_shadow:
    scs     %d4                         | %d4.b = 0xff if REL_STATE's bit was SET (carry),
                                         | else 0x00 -- captured before anything else can
                                         | touch the flags
    move.l  %d3,-(%sp)
    move.l  %a0,%d3
    sub.l   #0x80000110,%d3
    lsr.l   #6,%d3
    and.l   #7,%d3
    btst    %d3,SHADOW                  | Z := this track's SHADOW bit is clear (not muted)?
    beq     rs_not_muted                | branch WHILE Z is still live -- see the flag-
                                         | clobber warning above; do not restore %d3 first
    move.l  (%sp)+,%d3
    | SHADOW says genuinely muted -- force full mute regardless of REL_STATE's own bit
    clr.w   (2,%a0)
    clr.b   (43,%a0)
    clr.w   (4,%a0)
    jmp     RC_BACK                     | (jmp, not bra: RC_BACK is the far-away stock
                                         | address, out of any PC-relative branch's range)
rs_not_muted:
    move.l  (%sp)+,%d3
    tst.b   %d4                         | was REL_STATE's own bit actually set?
    bne     rs_release                  | yes -> local label; RC_BACK is too far for `beq`
    jmp     RC_BACK                     | no -> genuinely idle track, exact stock skip
rs_release:
    | genuinely NOT muted, but in natural release -- replicate STOCK's ORIGINAL behaviour:
    | zero the dry word, CLAMP (never zero) the route word -- this is what un-modified
    | stock already does and must keep doing regardless of MUTE MODE.
    clr.w   (2,%a0)
    clr.b   (43,%a0)
    cmp.w   (4,%a0),%d2
    bgt     rs_clamp_done
    move.w  %d2,(4,%a0)
rs_clamp_done:
    jmp     RC_BACK

| ============================ hook 8: 0x4000d0c4 (the ASYMMETRIC L/R MUTE) ==============
| ⚠ DEAD CODE as of Session 58 continued yet again, part 10 -- hook 13 (relstate_shadow)
| above no longer jumps here at all; its own SHADOW-driven logic replicates what this hook
| was trying to do (and fixes the bug this hook's GATE-only check had: it never checked
| whether the SPECIFIC track was actually muted, so it zeroed +4 for ANY track's ordinary
| natural release once MUTE MODE was on at all -- see hook 13's header for the full story
| and NOTES.md "part 10"). Left in place, unreferenced, per this project's convention for
| superseded-but-documented attempts rather than deleted -- do not re-wire this in as-is.
| Session 58 -- corrected by a hardware report.  The stock per-track loop at
| 0x4000d0a4..0x4000d0dc, driven by REL_STATE (0x8000184a -- the byte `pre` maintains):
|
|   4000d0b6:  movew #6144,%d2           | the cap
|   4000d0ba:  mvzb 0x8000184a,%d0       | REL_STATE
|   4000d0c0:  asrl #1,%d0 / bccs        | per track: silenced this frame?
|   4000d0c4:  clrw  %a0@(2)             | YES -> one channel := 0
|   4000d0c8:  clrb  %a0@(43)
|   4000d0cc:  cmpw  %a0@(4),%d2         | the OTHER channel: if 6144 > it, leave it,
|   4000d0d0:  bgts  0x4000d0d6          | otherwise clamp it DOWN TO 6144 -- never to 0
|   4000d0d2:  movew %d2,%a0@(4)
|
| Session 57 read +2/+4 as "dry" and "a second route (the FX-tail feature)", and gated the
| fix on a retrig.  HARDWARE SAYS OTHERWISE, and is unambiguous: with a muted track
| blipping, **only the LEFT channel blips, the right is silent, the blip is DRY (not
| effected) audio, and turning BAL fully right silences the track completely.**
|
| So +2 and +4 are the per-track **L and R gains of the dry signal** -- a stereo pair,
| computed upstream by the pan/balance maths at ~0x4000cf84..0x4000d022.  Stock zeroes ONE
| of them and merely CLAMPS the other to 6144.  That asymmetry IS the bug, and it is why
| panning into the zeroed channel makes the track fall silent.  Nothing here is the FX-tail
| mechanism at all: the tail rings via hook 1's own D5-bit clearing, on a different set of
| words entirely, which is exactly why the user hears the FX ring correctly while the dry
| leaks.
|
| Fix, accordingly, is simpler than Session 57's: zero +4 the same way stock already zeroes
| +2, for ANY silenced track.  No retrig detection, no HARDCUT byte, no dependency on
| mt_rebind firing -- all of which Session 57 needed only because it thought +4 was a
| feature worth preserving.  It is not; it is the other half of the same mute.
|
| Gated on MUTE MODE so stock (OT) behaviour is byte-for-byte untouched: REL_STATE is a
| STOCK byte that stock sets for voices in their natural release, and stock's clamp on
| those is existing shipped behaviour that must not change.
|
| Detours 18 B (0x4000d0c4..0x4000d0d6).  0x4000d0d6 is a branch target (from the `bccs` at
| 0x4000d0c2 and the `bgts` at 0x4000d0d0) but it is the END of the span, so nothing lands
| inside it.  %d0 is the shifted REL_STATE and %d1/%d2/%a0 are the loop's own state, so %d0
| is saved and restored around the GATE read rather than clobbered.
    .equ RC_BACK,   0x4000d0d6        | the loop's own per-track tail
    .global relcut
relcut:
    clr.w   (2,%a0)                     | displaced 1: one channel := 0 (unchanged)
    clr.b   (43,%a0)                    | displaced 2 (unchanged)

    .ifndef ALWAYS_ON
    move.l  %d0,-(%sp)
    move.l  GATE,%d0
    .ifdef DT_MODE
    subq.l  #1,%d0                      | mode 1 -> 0, mode 2 -> 1
    cmpi.l  #1,%d0
    bhi     rc_clamp                    | MUTE MODE not in { OT+FX, DT } -> stock, untouched
    .else
    cmpi.l  #1,%d0
    bne     rc_clamp
    .endif
    move.l  (%sp)+,%d0                  | restore ONLY on the path that keeps going --
                                         | branching FIRST, while CMP's own flags are still
                                         | live.  A same-session draft restored d0 BEFORE the
                                         | branch on the theory that "the flags survive the
                                         | move" -- they do not: MOVE.L sets N/Z from the
                                         | popped value and clears V/C, which silently
                                         | overwrote the CMP result before BHI/BNE ever read
                                         | it.  relcut then took rc_clamp on EVERY track,
                                         | EVERY time, regardless of GATE -- indistinguishable
                                         | from "the fix does nothing" by any audio test, and
                                         | only caught by watching this exact branch with
                                         | --watch-pc and seeing GATE=1 take rc_clamp anyway.
                                         | The PREVIOUSLY FLASHED relcut (the HARDCUT-gated
                                         | one) did NOT have this bug -- it branched right
                                         | after CMPI, correctly -- so this is not why that
                                         | hardware attempt failed; see the header comment.
    .endif

    clr.w   (4,%a0)                     | the OTHER channel := 0 too.  Both halves of the
    jmp     RC_BACK                     | dry are now muted, which is what a mute means.

rc_clamp:
    .ifndef ALWAYS_ON
    move.l  (%sp)+,%d0                  | the branch above jumped straight here, unrestored
    .endif
    cmp.w   (4,%a0),%d2                 | displaced 3 (stock's clamp, replayed exactly)
    bgt     rc_done                     | displaced 4
    move.w  %d2,(4,%a0)                 | displaced 5
rc_done:
    jmp     RC_BACK

| ============================ hook 9: 0x4000d498 (DROP THE TRIG ENTIRELY) ===============
| Session 58, at the user's direction: "these are supposed to be trig mute-style modes --
| concentrate on finding a way to simply mute all trigs encountered after the mute."
| Session 58 continued: hardware confirmed this FIXES DT with no desync found. OT+FX,
| flashed alongside it with only `relcut` (hook 8), STILL blipped on one channel -- the
| exact same symptom as before hook 8, unchanged. Broadened this hook to cover OT+FX too.
|
| Why `relcut` alone isn't enough for OT+FX: hook 8 only reacts to the per-track LEVEL
| WORD, which is control-rate (updated once per sequencer frame) and was independently
| confirmed, frame by frame across the retrig, to read 0/0 the entire time -- so the
| ColdFire-side mixer gain is provably never wrong. But `relcut` does nothing to stop the
| trig from reaching the voice engine, and the voice engine's OWN restart is exactly what
| hooks 2-6 (Session 56) spent a whole session failing to gate from the outside. A DSP-
| side voice can plausibly reach its own default/unity gain for the first few samples of
| a restart, entirely below the granularity this per-frame level word can see or fix --
| which is consistent with DT (which prevents the restart from ever happening at all)
| working cleanly while OT+FX (which only cleans up the CONTROL-RATE word around it)
| still blips. OT+FX's own hook-1 header has said "a silenced track's sequencer trigs
| make no sound" since Session 9 -- this hook is what actually delivers that, for both
| modes, by removing the restart itself rather than reacting to its level word.
|
| Every earlier DT attempt tried to stop the voice AFTER its trig had been dispatched
| (mt_trig at FUN_40006844, mt_rebind inside FUN_4000f450, the whole Session-56 family).
| DT did nothing at all on hardware.  This hook stops the trig being dispatched at all.
|
| ⚠ FIRST ATTEMPT WAS WRONG, and the emulator caught it before the flash: `grep "jsr
| 0x4000f450"` finds exactly ONE direct call, at 0x4000421c, so that looked like the single
| choke point.  Detouring it produced ZERO hits in a real run while FUN_4000f450 itself was
| entered 7 times -- because the live path does not use that direct call at all.  The return
| address on FUN_4000f450's own stack (`--watch-pc 0x4000f450`, first stack word = 0x4000d49e,
| with a0 == 0x4000f450 on entry) gave up the real site: an INDIRECT `jsr %a0@` two bytes
| earlier, at 0x4000d49c.  Lesson worth keeping: a grep for direct calls does not find a
| function-pointer dispatch; ask the callee's own return address instead.
|
| The real dispatch, 0x4000d47a..0x4000d4ce:
|
|   4000d47a:  mvsb %d1,%d4              | d4 = this track's MACHINE TYPE
|   4000d47e:  moveal %a1@(0,%d4:l:4),%a0| a0 = handler_table[machine type]
|   4000d482:  tstl %a0 / beqs           | no handler -> skip
|   4000d490:  movel %d0,%sp@-           | arg 3 (flags)
|   4000d498:  movel %d0,%sp@-           | arg 2            <- detoured from here
|   4000d49a:  movel %d3,%sp@-           | arg 1 == TRACK NUMBER (%d3)
|   4000d49c:  jsr %a0@                  | THE per-trig dispatch
|   4000d49e:  ...                       | %d0 = the handler's return value, used below
|   4000d4ce:  lea %sp@(12),%sp          | the caller pops all three args itself
|
| Hooking the DISPATCH rather than one handler means every machine type is covered, not
| just the FLEX/STATIC one FUN_4000f450 serves -- which is what a trig mute should do.
|
| For a silenced track we simply do not call the handler.  The three arguments are still
| pushed (so the caller's own `lea %sp@(12),%sp` still balances), and %d0 is set to 0 --
| the value the following code ORs into a per-track word at 0x4000d4ae, i.e. "this handler
| did nothing".  %d3 (track) is live afterwards and is never touched; %d0/%d1 are free
| (%d0 is the handler's return value by convention, %d1 is reloaded at 0x4000d49e).
|
| Net effect: a trig on a silenced track is never dispatched -- no voice start, no arena
| bind, no position write.  A voice ALREADY sounding is not touched at all, so it keeps
| ringing under its own amp envelope.  That is exactly a Digitakt trig mute.
|
| The silenced test is `mr_silence`'s, copied verbatim, so this is solo-aware for free.
|
| BOTH OT+FX and DT now (Session 58 continued -- see the broadening note above).  `relcut`
| (hook 8) still does its own job for OT+FX (the already-sounding voice's dry level and
| its clean fade on mute-engage); this hook additionally stops any NEW trig from reaching
| the voice engine at all, in either mode, which is what actually fixed the blip.
|
| ⚠ UNPROVEN RISK, flagged deliberately: if the handler performs bookkeeping that later
| code depends on (a playhead, a slot lifetime, a counter), skipping it could desync that
| state -- most plausibly on UNMUTE, or after many suppressed trigs.  Test that
| specifically.  Confirmed clean for DT on hardware this session; OT+FX not yet re-tested
| with this broadened gate.
    .equ DT_BACK,   0x4000d49e        | right after the dispatch
    .global dt_trig
dt_trig:
    move.l  %d0,-(%sp)                  | displaced 1 (arg 2) -- MUST reach `jsr %a0@` on the
                                         | dt_pass path byte-identical to what stock's own
                                         | `mvzb %a1@,%d0` left it as (just pushed, unchanged).
                                         | Every check below uses %d1/%d2 ONLY -- never %d0 --
                                         | and %d0 is written (to 0) ONLY on the confirmed
                                         | dt_silence path, where the handler never runs at
                                         | all so it cannot matter.
                                         |
                                         | An earlier draft used %d0 as gate-check scratch. It
                                         | passed a clean controlled A/B for the DT-only gate
                                         | (GATE=0 coincidentally left %d0=0, same as if
                                         | untouched) but showed real, sustained divergence in
                                         | T1's OWN raw voice content -- not just an unrelated
                                         | track's timing -- once broadened to also gate
                                         | OT+FX: GATE=0 through the (correctly-branching)
                                         | subq-based comparison left %d0=-1 (0xFFFFFFFF)
                                         | instead of 0. Root cause not fully chased down
                                         | (whether the handler reads %d0 as an implicit
                                         | input, or something else) -- removed the risk
                                         | instead of continuing to hunt for it: %d0 now
                                         | provably never differs from stock on any path that
                                         | reaches the handler.
    move.l  %d3,-(%sp)                  | displaced 2 (arg 1 == track)

    .ifndef ALWAYS_ON
    move.l  GATE,%d1                    | part 18 addendum 12: with OTFX (GATE 3) added,
    subq.l  #1,%d1                      | "nonzero" is no longer "masks trigs" -- OTFX must
    cmpi.l  #1,%d1                      | leave the sequencer completely alone.  This is the
    bhi     dt_pass                     | same { OT+FX, DT } range test hooks 2/3 have always
                                         | used (mode 1 -> 0, mode 2 -> 1, anything else > 1),
                                         | one instruction more than the old `tst.l`.  It runs
                                         | only when a trig is actually dispatched, not per
                                         | frame -- and the bit-identical A/B for GATE 0/1/2 is
                                         | what actually licenses it.
                                         | (old comment, still true of the branch it replaced:)
                                         | GATE only ever holds 0 (OT/stock), 1 (OT+FX) or,
                                         | with DT_MODE, 2 (DT) -- "nonzero" was exactly
                                         | "any active mute mode" either way, so this needed
                                         | no DT_MODE-specific branch at all and costs the
                                         | SAME 3 instructions as the original DT-only
                                         | `move.l GATE,%d0 / cmpi.l #2,%d0 / bne dt_pass`
                                         | check did (one fewer than the subq-based compare
                                         | tried first, which is what actually mattered here
                                         | -- see below).
    .endif

    move.l  %d3,%d2
    addi.l  #8,%d2
    move.l  MUTE_STATE,%d1
    btst    %d2,%d1                     | muted (bit 8+track) ?
    bne     dt_silence
    tst.b   SOLO_BYTE                   | anything soloed at all ?
    beq     dt_pass
    move.l  %d1,%d2
    andi.l  #0xff,%d2
    beq     dt_pass                     | nothing soloed -> let it through
    btst    %d3,%d1                     | this track soloed (bit track) ?
    bne     dt_pass                     | soloed -> let it through
| fallthrough: solo active + this track not soloed -> silence it
dt_silence:
    moveq   #0,%d0                      | what the handler would have returned, doing nothing
    jmp     DT_BACK                     | DROP THE TRIG: the handler never runs

dt_pass:
    jsr     %a0@                        | displaced 3: the normal per-machine-type dispatch
    jmp     DT_BACK

| ============================ hook 10: 0x40006820 (THE FRESH-VOICE-BIND ENTRY) ==========
| Session 58 continued -- hardware report: OT+FX blips once per trig position during the
| FIRST sequencer cycle after muting, then stops; DT blips scale with how short AMP
| RELEASE is (shorter = more blips), also only in the first cycle. Both point at the same
| gap: `dt_trig` (hook 9) gates only ONE of the paths that can start a voice -- the
| "already bound, reuse" dispatch inside FUN_4000f450. FUN_40006820 -- the "voice not yet
| bound, do a FRESH bind and play it" function -- has SEVEN callers in the whole image:
| one INSIDE FUN_4000f450 (0x4000f518, downstream of hook 9's own gate, already covered),
| and SIX completely independent callers elsewhere (0x40043c50, 0x4007eb3e, 0x4008044e,
| 0x4008055c, 0x40093ec0, 0x40096ad4) hook 9 never touches at all. Once a voice goes
| "cold" (its arena slot recycled -- forced quickly by relcut's note-off in OT+FX, or
| naturally by the AMP envelope's own release in DT), the NEXT trig on it needs exactly
| this fresh-bind path, through one of those six other, unguarded callers -- a complete,
| audible voice start, matching the reported symptom exactly: a blip per affected trig,
| until the voice has been "warm" again for a while and every further retrig goes through
| the already-gated reuse path instead.
|
| Rather than chase and gate six separate call sites (fragile -- a seventh could exist
| uncaught), gate the ONE function they all converge on, at its own entry.
|
| FUN_40006820(track: %d1, via %sp@(12)) is its own well-documented 8-track fan-out
| (Session 53): track 0..7 -> real per-track work at 0x40006844 (SR raise, arena-slot
| active-byte clear, `jsr FUN_4000672c` -- THE actual "start the voice" call); track >= 8
| -> recurse over 0..7 by CALLING ITSELF (`jsr %a2@`, %a2 = its own address). That
| recursion means gating single-track calls here is enough by construction: a track>=8
| ("do them all") call is never itself silenced, but each of the 8 recursive calls it
| makes lands back at THIS SAME entry with one track number and gets individually gated.
|
| Detours the first 8 B / 3 instructions (`movel %a2,%sp@- / movel %d2,%sp@- / movel
| %sp@(12),%d1`) -- an exact instruction boundary, room for a 6 B jmp with 2 B spare.
| Replays all three unconditionally (%a2/%d2 pushed, %d1 = track, either way), then for a
| genuinely single-track (%d1 < 8), muted/soloed-out call, skips straight to the shared
| epilogue (0x40006888: pop %d2/%a2, rts) instead of falling into the real per-track work
| -- the same "drop the trig" outcome hook 9 gives the reuse path, now for the fresh-bind
| path too. A track>=8 call, or an unmuted/soloed-in single-track call, falls through to
| `FB_BACK` (0x40006828, stock's own very next instruction, `moveq #7,%d0`) and lets
| STOCK's OWN track<8 test (already right there) decide the rest -- no need to duplicate
| it. The explicit `cmpi.l #8,%d1 / bcc FB_BACK` guard below matters for a different
| reason: without it, a track>=8 call would still reach the MUTE_STATE/SOLO_FLAG test
| with an out-of-range bit position (track+8 up to 16+), which would test a CUE bit
| instead of a MUTE bit and could silence a "do all tracks" call by accident.
|
| %d0 is stock's own scratch here (freshly reloaded via `moveq #7,%d0` immediately after
| our replayed %d1 load on every path that reaches it, before anything else reads it) --
| free to clobber. %d3 is not read by the displaced code or by 0x40006844's own per-track
| work (checked directly in the disassembly) -- also free, and only touched on the
| track<8 path (the track>=8 early-out never reaches it).
    .equ FB_BACK,     0x40006828      | right after the displaced track-number load
    .equ FB_EPILOGUE, 0x40006888      | stock's own shared epilogue: pop %d2/%a2, rts
    .global fresh_bind
fresh_bind:
    move.l  %a2,-(%sp)                  | displaced 1
    move.l  %d2,-(%sp)                  | displaced 2
    move.l  (12,%sp),%d1                | displaced 3 == track number

    cmpi.l  #8,%d1
    bcc     fb_pass                     | track >= 8 ("do them all") -> never silenced here;
                                         | its own recursive per-track calls come back
                                         | through THIS SAME entry and get gated then

    .ifndef ALWAYS_ON
    move.l  GATE,%d0
    subq.l  #1,%d0                      | part 18 addendum 12: act only for { OT+FX, DT }.
    cmpi.l  #1,%d0                      | MUTE MODE == OT (0) -> stock, untouched; OTFX (3)
    bhi     fb_pass                     | likewise -- it never masks a trig.
    .endif

    move.l  %d1,%d0
    addi.l  #8,%d0
    move.l  MUTE_STATE,%d3
    btst    %d0,%d3                     | muted (bit 8+track) ?
    bne     fb_silence
    tst.b   SOLO_BYTE                   | anything soloed at all ?
    beq     fb_pass
    move.l  %d3,%d0
    andi.l  #0xff,%d0
    beq     fb_pass                     | nothing soloed -> normal dispatch
    btst    %d1,%d3                     | this track soloed (bit track) ?
    bne     fb_pass                     | soloed -> normal dispatch
| fallthrough: solo active + this track not soloed -> silence it
fb_silence:
    jmp     FB_EPILOGUE                 | skip the fresh bind + FUN_4000672c entirely

fb_pass:
    jmp     FB_BACK                     | %d0 is reloaded fresh by stock's own very next
                                         | instruction either way, so it does not matter
                                         | here whether this hook has already clobbered it

| ============================ hook 11: 0x4000d0ba (THE REL_STATE RACE, FIXED SAFELY) ====
| Session 58 continued again -- user clarification: "first cycle" means the first full
| pass through the pattern after muting; a second pass is clean; unmute-then-remute makes
| it happen again. Direct measurement (multi-retrig BOTLI test) found `relcut` (hook 8)
| misses 3 of 1999 eligible frames: the level-chain computation (0x4000cb4e/cc20/ced0)
| writes a fresh, unmuted-value L/R gain EVERY frame unconditionally; `relcut`'s own zero-
| override only runs when the release loop's REL_STATE bit test is true for a track. A
| stock function (0x4000bf22, part of some larger per-voice-parameter routine, entered
| only ~29 times per 4000 frames) transiently clears a muted track's REL_STATE bit as
| ordinary "a note is starting" bookkeeping -- for exactly one frame, since `pre` (hook 1)
| re-asserts it (`REL_STATE |= silenced`) on the very next pass.
|
| ⚠ FIRST ATTEMPT (detouring 0x4000bf22 itself, OR-ing the silenced set back in right
| before its own store) was ABANDONED after real, alarming evidence: a controlled A/B
| showed a SEVERE (~1900-2000 block), reproducible divergence in OTHER tracks' raw audio
| content -- unlike every other hook in this file (all showing only a handful of blocks of
| benign cross-track timing drift). Chased it with a no-op-only diagnostic detour at the
| SAME site (pure jmp out and back, zero logic): that alone cost only ~74 blocks, proving
| the SITE itself is not to blame. Adding back either a GATE check (`move.l GATE,%d1`) or
| just a bare `SHADOW` read + OR, with NO gate check at all, BOTH still produced severe
| divergence (the gate-free version was, if anything, WORSE, ruling out "reading GATE
| specifically" as the cause too). Whatever this function actually is, it appears to sit
| somewhere disproportionately timing-sensitive -- a handful of ColdFire cycles here moves
| far more than they should anywhere else this project has hooked. Not safe to keep
| pushing on blind; abandoned rather than guessed further.
|
| SAFER FIX: don't touch the writer at all. `0x4000d0ba` -- the release loop's OWN load of
| REL_STATE, confirmed by direct measurement to run EXACTLY once per frame (2000 hits over
| 2000 frames), not once per track (the 8-track test-and-skip that follows just shifts
| this ONE loaded byte 8 times via the carry flag, re-reading memory only once) -- sits a
| few instructions before `relcut`'s own detour, inside the SAME function `relcut` already
| lives in safely. OR the silenced set in immediately after this single load, before the
| 8-track shift-test loop even begins: whatever 0x4000bf22 (or anything else) did to
| REL_STATE in memory, a muted track's bit can never actually read as 0 for this frame's
| pass, closing the exact same race from the read side instead of the write side.
|
| Detours 6 B (0x4000d0ba..0x4000d0c0), an exact instruction boundary, room for a 6 B jmp
| with zero spare. `%d0` holds the freshly-loaded REL_STATE byte and must reach the shift-
| test loop with only bits ADDED, never removed. `%d3` is free here: relcut's own header
| comment (hook 8) already established it is unused anywhere in this function's per-track
| body, and nothing between this site and relcut's own reads or writes it either.
    .equ RL_BACK,   0x4000d0c0        | right after the displaced load, where the 8-track
                                       | shift-test loop begins
    .global relstate_or
relstate_or:
    mvzb    0x8000184a,%d0            | displaced instruction, replayed
    move.l  %d3,-(%sp)
    moveq   #0,%d3
    move.b  SHADOW,%d3                | this frame's silenced set, from `pre`
    or.l    %d3,%d0                   | force those tracks' bits back to 1 -- ADD only,
                                       | never remove a bit the loaded byte itself carried
    move.l  (%sp)+,%d3
    jmp     RL_BACK

| ==== hook 14: 0x4000b90c (THE PER-STEP LIVE-NIBBLE HAND-OFF TO THE DSP) ===============
| Session 58 continued yet again, part 18 -- the first hook in this thread built on
| RENDERED AUDIO rather than on ColdFire call counts, and the first one aimed at the
| mechanism that actually produces the "echo".
|
| What part 18 measured (see NOTES.md, and tools/emu_echo_dsp.py / echo_blockdiff.py):
| while a track is muted in DT mode NOTHING ever starts a voice -- hooks 9/10 are clean,
| zero `active <- 0xFF` writes post-mute. The audible bursts are the voice that was
| ALREADY sounding when the mute engaged (which DT mode deliberately lets ride its own
| amp envelope) being RE-ATTACKED once per trig step. The signal that does it reaches the
| DSP as word 1 of core 1's 672-word parameter block, which mirrors this per-track byte:
|
|     0x4000b906  lea.l 0x46104d15,%a1        | FW_LIVE_NIBBLE, per-track
|     0x4000b90c  movea.l (0x72,%a7),%a3      | <- the track index
|     0x4000b910  move.b (%a2),(%a1,%a3.l)    | <- THE STEP'S VALUE, written unconditionally
|
| Measured: that store fires on every one of the track's own trig steps after the mute,
| completely unaffected by MUTE_STATE, and each firing coincides with an audible burst --
| until the surviving voice's sample runs out and the playback-position engine frees it
| (clr.b at 0x40008ea6), after which further firings make no sound at all. It is on a call
| path hook 9 never sees, which is why 17 parts of gating the dispatch chain never touched
| this.
|
| The gate: for a silenced track, leave the per-track byte EXACTLY as it was, so the DSP
| is simply never told about the new step. Everything else is untouched -- in particular
| the frame level words still reach the mix, so DT's intended behaviour (the already-
| sounding voice keeps playing and fades out under its own AMP envelope, FX ring) is
| preserved by construction; only the re-attack is removed.
|
| The companion site 0x4000b9bc (a read-modify-write that ORs 0x10 into the SAME byte) is
| deliberately NOT gated: the value the DSP block carries is the low nibble this store
| writes (measured 0x0c0c / 0x0707 / 0x0808 in the block against 0x1c / 0x17 / 0x18 in
| RAM), so the 0x10 flag is local bookkeeping other firmware may read. If a test shows
| bursts surviving this hook, gate that one too -- do not assume it.
|
| Detours 8 B (0x4000b90c..0x4000b914), two whole instructions, both replayed below.
| %d1/%d2 are provably dead here (each is written before its next read: 0x4000b91a loads
| %d1, 0x4000b92e loads %d2) but are saved and restored anyway -- hook 9's own header
| records what a wrong register assumption cost this project once already.
| ASSEMBLED ONLY WITH --defsym LIVE_NIBBLE=1. The A/B below came out NEGATIVE (the hook
| works, the echo does not change), so it is kept purely as a record and must not cost
| the shipped build a single cave byte -- with it assembled unconditionally,
| patch_softmute grows past patch_mutemode's cave and every downstream address has to
| move. To re-run the experiment: add --defsym LIVE_NIBBLE=1, re-enable the detour in
| build_mutemode_dt.py, and bump patch_mutemode + the three PERSONALIZE arrays by 0x80.
    .ifdef LIVE_NIBBLE
    .equ LN_BACK,   0x4000b914        | right after the displaced load + store
    .global live_nibble
live_nibble:
    movea.l (0x72,%a7),%a3            | displaced 1: the per-track index
    .ifndef ALWAYS_ON
    move.l  %d1,-(%sp)
    move.l  %d2,-(%sp)
    move.l  GATE,%d1
    tst.l   %d1
    beq     ln_store                  | MUTE MODE == OT (or unset) -> byte-for-byte stock
    move.l  MUTE_STATE,%d1
    move.l  %a3,%d2
    addi.l  #8,%d2
    btst    %d2,%d1                   | muted (bit 8+track) ?
    bne     ln_skip
    tst.b   SOLO_BYTE                   | anything soloed at all ?
    beq     ln_store
    move.l  %d1,%d2
    andi.l  #0xff,%d2
    beq     ln_store                  | nothing soloed -> normal
    move.l  %a3,%d2
    btst    %d2,%d1                   | this track soloed ?
    bne     ln_store                  | soloed -> normal
| fallthrough: solo active + this track not soloed -> silenced, same as muted
ln_skip:
    move.l  (%sp)+,%d2
    move.l  (%sp)+,%d1
    jmp     LN_BACK                   | the per-track byte keeps its old value: the DSP is
                                       | never told this step happened
ln_store:
    move.l  (%sp)+,%d2
    move.l  (%sp)+,%d1
    .endif
    move.b  (%a2),(%a1,%a3.l)         | displaced 2
    jmp     LN_BACK
    .endif

| ==== hook 15: 0x40004c72 (THE PER-TRIG FLAG BITS IN THE DSP FRAME WORD) ===============
| Session 58 continued yet again, part 18 addendum 2. Found by following the ONLY
| trig-aligned host-port word left once hook 14 had frozen the live nibble and proved that
| byte innocent (see NOTES.md): word 30 of core 1's 128-word block, i.e. the per-track
| frame word at 0x8000014c + sel*512 + track*64.
|
| Once per trig, three writes inside the per-frame DSP frame loop build that word up:
|
|     0x40004c72  moveq #3,%d0 / and.l %d1,%d0 / beq 0x40004cb0   <- "did a trig happen?"
|     0x40004c7e  bset #7  -> 0x80 | nibble
|     0x40004c8a  or  #0x10 -> 0x90 | nibble
|     0x40004cba  or  #0x40 -> 0xd0 | nibble
|
| Measured, muted, with hook 14 in place: that 0xd0 goes out on EVERY post-mute trig step,
| unchanged. The only part of the word the mute does reach is bit 8 (0x100), which is the
| dispatched handler's own return value OR'd in later at 0x4000d4b0 -- and hook 9 correctly
| makes that 0, so post-mute the word reads 0x00d4 where an unmuted trig reads 0x01dc. The
| flags still say "a trig is happening on this track NOW"; only the "a voice started" bit
| is missing. Working hypothesis this hook tests: that is what re-attacks the voice DT mute
| deliberately leaves sounding.
|
| The gate: for a silenced track take stock's OWN "no trig this frame" exit (0x40004cb0), so
| the word is built exactly as it is on the 13 steps that carry no trig. Nothing else is
| touched -- the frame LEVEL words are still kept, so DT's intended "the sounding voice
| rides its own AMP envelope and its FX ring" behaviour is unaffected by construction.
|
| Registers: %d4 IS the track index here -- the enclosing loop clears it at 0x40004c38,
| `btst %d4,%d2` at 0x40004d08 uses it as one, and the tail does `addq.l #1,%d4` /
| `lea 0x40(%a1),%a1` / `cmp.l %d4,%d0` against 8. %d0 is free: both exits reload it
| (0x40004c78 `move.w (%a1),%d0`, and 0x40004cb0's own path likewise), so no save/restore
| is needed and no flags hazard exists -- the `btst` is read by the very next instruction.
| The gate reads GATE + MUTE_STATE + SOLO_FLAG directly, exactly as hook 9 does -- NOT
| SHADOW. A first draft used SHADOW and was silently inert: `pre` (hook 1) deliberately
| CLEARS SHADOW in DT mode ("so a live DT -> OT+FX switch re-asserts every note-off"), so
| in the one mode this bug lives in, SHADOW is always 0. Caught only by checking that the
| DSP word actually changed -- the audio A/B alone looked like an ordinary negative result.
| %d0 is the ONLY free register here (%d1 is read at 0x40004c80, %d2 at 0x40004cd8, %d3 at
| 0x40004c6c/0x40004cce, %d4 is the track index), hence the `lsr.l #8` trick instead of
| building a 1<<(8+track) mask in a second register.
    .equ TF_BACK,   0x40004c78        | stock's fall-through: build the per-trig flag bits
    .equ TF_SKIP,   0x40004cb0        | stock's own "no trig this frame" continuation
    .global trigflag
trigflag:
    moveq   #3,%d0                    | displaced 1
    and.l   %d1,%d0                   | displaced 2
    beq     tf_skip                   | displaced 3: stock's own branch, unchanged
    .ifndef ALWAYS_ON
    move.l  GATE,%d0
    subq.l  #1,%d0                    | part 18 addendum 12: act only for { OT+FX, DT }.
    cmpi.l  #1,%d0                    | MUTE MODE == OT (or unset) -> byte-for-byte stock;
    bhi     tf_pass                   | OTFX (3) too -- its trigs must reach the DSP normally.
    move.l  MUTE_STATE,%d0
    lsr.l   #8,%d0                    | mute bits 8..15 -> 0..7, so %d4 indexes them directly
    btst    %d4,%d0                   | this track muted ?
    bne     tf_skip
    tst.b   SOLO_BYTE                   | anything soloed at all ?
    beq     tf_pass
    move.l  MUTE_STATE,%d0
    andi.l  #0xff,%d0
    beq     tf_pass                   | nothing soloed -> normal
    btst    %d4,%d0                   | this track soloed ?
    beq     tf_skip                   | not soloed while something is -> silenced
    .endif
tf_pass:
    jmp     TF_BACK
tf_skip:
    jmp     TF_SKIP
