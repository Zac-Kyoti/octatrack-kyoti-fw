| SPDX-License-Identifier: MIT
| SPDX-FileCopyrightText: 2026 Zac-Kyoti
| patch_softmute V7 -- audio-track mute (and, V7, SOLO silencing) behave like a single STOP:
| the sample audio cuts (fast clean fade), the track's FX inserts ring their delay/reverb
| tails out, and a silenced track's sequencer trigs make no sound.
|
| Session 9 (V1-V6): the mute case.  Session 11 (V7): the SOLO case, same technique.
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
    .equ SOLO_FLAG,   0x80000037     | byte, non-zero while SOLO mode is engaged
    .equ REL_STATE,   0x8000184a     | byte: voice t in RELEASE when bit t set
    .equ SHADOW,      0x80006c66     | patch RAM: last frame's "silenced" set (8 bits)
    .equ HARDCUT,     0x8000b000     | patch RAM (Session 57): per-track "this track got a
                                     | REAL TRIG while silenced" set.  Set by mt_rebind's
                                     | mr_silence, consumed by `relcut`, and masked down to
                                     | the currently-silenced set every frame by `pre` (so
                                     | unmuting forgets it and the FX-tail grace returns).
                                     | ⚠ NOT 0x80006c67 (the byte next to SHADOW): stock
                                     | writes a 16-bit 0xc8c over 0x80006c66 from pc
                                     | 0x4009882c, so 0x80006c67 is the LOW HALF of a stock
                                     | field.  Using it made even an UNMUTED run diverge
                                     | (measured).  0x8000b000 was chosen after censusing
                                     | writes AND reads over a full run: zero of either in
                                     | 0x8000b000..0x8000b0ff, unlike 0x80006a00/6b00/6c00/
                                     | 6d00/6e00/7000/7800 which are all actively used.
                                     | Caveat: "no traffic in THIS scenario" is not proof
                                     | it is free under every feature (recorder, arranger,
                                     | MIDI...) -- re-census before trusting it on hardware.
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
    cmpi.l  #2,%d0                      | MUTE MODE == DT ?  (same D5 handling, no note-off)
    beq     p1_active
    .endif
    clr.b   SHADOW                      | OT (or unknown): stock; keep the shadow clean for later
    clr.b   HARDCUT                     | ... and the retrig-while-silenced set with it
    bra     p1_done
p1_active:
    .endif

| ---- silenced set -> D2 (bits 0..7) ----
    tst.b   SOLO_FLAG
    bne     p1_solo

    | not solo: silenced = mute mask
    move.l  %d5,%d2
    lsr.l   #8,%d2
    andi.l  #0xff,%d2
    | keep the muted tracks' frame level words: D5 &= ~(silenced << 8)
    move.l  %d2,%d0
    lsl.l   #8,%d0
    not.l   %d0
    and.l   %d0,%d5
    bra     p1_edge

p1_solo:
    | solo: soloed mask = D5 bits 0..7
    move.l  %d5,%d2
    andi.l  #0xff,%d2
    beq     p1_zero                     | solo engaged but nothing soloed -> nothing silenced
    eori.l  #0xff,%d2                   | silenced = ~soloed & 0xff  (the 8 audio tracks)
    | keep EVERY track's frame level words: clear D5 bits 0..15
    |  -> every track: solo bit clear + mute bit clear -> the "& D1" keep path
    |  -> D1 = (D5.b == 0) ? -1 : 0  becomes -1 -> words pass through unchanged
    andi.l  #0xffff0000,%d5
    bra     p1_edge

p1_zero:
    moveq   #0,%d2

p1_edge:
| ---- HARDCUT &= silenced (Session 57) ----
| A track that is no longer silenced forgets its "retriggered while silenced" flag, so
| the FX-tail grace is available again the next time it IS muted.  Done here, before the
| DT branch, so it is maintained identically in both OT+FX and DT.
    moveq   #0,%d0
    move.b  HARDCUT,%d0
    and.l   %d2,%d0
    move.b  %d0,HARDCUT

    .ifdef DT_MODE
| ---- DT: the D5 mute/solo bits are already cleared above (voice + FX keep flowing to the
|      mix untouched); the voice rides its own amp envelope.  No note-off, no REL_STATE. ----
    move.l  GATE,%d0
    cmpi.l  #2,%d0
    bne     p1_edge_ot
    clr.b   SHADOW                      | so a live DT -> OT+FX switch re-asserts every note-off
    bra     p1_done
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
    tst.b   SOLO_FLAG
    beq     mt_pass                     | not solo, not muted -> let it through
    move.l  %d3,%d0
    andi.l  #0xff,%d0
    beq     mt_pass                     | solo engaged, nothing soloed -> let it through
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
    tst.b   SOLO_FLAG
    beq     mr_pass                      | not solo, not muted -> let it through
    move.l  %d1,%d0
    andi.l  #0xff,%d0
    beq     mr_pass                      | solo engaged, nothing soloed -> let it through
    move.l  (0x40,%sp),%d0
    btst    %d0,%d1                      | this track soloed (bit track) ?
    bne     mr_pass                      | soloed -> let it through
| fallthrough: solo active + this track not soloed -> silence it
mr_silence:
| Session 57: this is the one place already PROVEN (ot_emu --watch-pc, real BOTLI retrig,
| register dump showing a2 = T1's voice struct and d1 = the exact MUTE_STATE bit) to be
| reached exactly when a SILENCED track receives a REAL new trig -- and only then (7 site
| hits across a whole 470-frame run).  Record it: the FX-tail grace belongs to the note
| that was already sounding when the mute engaged, NOT to a new trig, and `fxcut` uses
| this to drop the still-open second level word for such a track.
    move.l  (0x40,%sp),%d0               | track (the same stack slot this hook already uses)
    moveq   #0,%d1
    move.b  HARDCUT,%d1
    bset    %d0,%d1
    move.b  %d1,HARDCUT
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
| ============================ hook 8: 0x4000d0c4 (THE 6144 TAIL-RING CLAMP) =============
| Session 57 -- THE leak, located exactly.  Hooks 2-7 all missed because they assumed the
| retriggered VOICE had to be stopped.  It doesn't: stock already cuts a silenced track's
| dry level to zero.  What it does NOT do is close the track's SECOND route to the mix --
| it merely CAPS it.  The stock loop at 0x4000d0a4..0x4000d0dc, per track, driven by
| REL_STATE (0x8000184a -- the very byte `pre` maintains with `REL_STATE |= silenced`):
|
|   4000d0b6:  movew #6144,%d2           | the cap
|   4000d0ba:  mvzb 0x8000184a,%d0       | REL_STATE
|   4000d0c0:  asrl #1,%d0 / bccs        | per track: in release/silenced?
|   4000d0c4:  clrw  %a0@(2)             | YES -> dry level := 0          <- the mute you hear
|   4000d0c8:  clrb  %a0@(43)
|   4000d0cc:  cmpw  %a0@(4),%d2         | and the second word: if 6144 > it, leave it,
|   4000d0d0:  bgts  0x4000d0d6          | otherwise CLAMP it DOWN TO 6144 -- never to 0
|   4000d0d2:  movew %d2,%a0@(4)
|
| So a silenced track keeps a permanent -14.5 dB route to the mix.  That is the FX-tail
| ring: the dry goes, the tail keeps flowing at a fixed reduced level.  Measured directly
| in the host-port feed (core 1, 0x80000110 + 64*track): with T1 muted, word +2 is 0 and
| word +4 sits at exactly 6144, every frame, from the mute right through the retrig.
| A retrig plays the sample at full level straight into that open 6144 route -> the blip.
|
| This also explains every dead end: mt_pos/mt_ptr/mt_ctr/ALWAYS_NOTEOFF were all trying to
| stop the voice, and `rb` (the per-track chain output) is measured UPSTREAM of this word,
| so none of them could ever have shown a difference here even in principle.
|
| Fix: for a track in the HARDCUT set (one that took a REAL trig while silenced -- recorded
| by mt_rebind's own mr_silence, the site proven to fire exactly then), zero word +4 instead
| of clamping it to 6144.  The tail-ring grace still applies to the note that was sounding
| when the mute engaged; a NEW trig gets no route out at all.  Every other track, and every
| other mode, keeps stock behaviour exactly.
|
| Detours 18 B (0x4000d0c4..0x4000d0d6 -- the clrw/clrb and the whole clamp).  0x4000d0d6 is
| a branch target (from the `bccs` at 0x4000d0c2 and the `bgts` at 0x4000d0d0) but it is the
| END of the span, so nothing lands inside it.  Track index = 8 - %d1 (the loop counts %d1
| 8..1 while %a0 walks 64 bytes per track).  %d0 (the shifted REL_STATE) and %d1/%d2/%a0 are
| all live, so %d0/%d3 are saved and restored rather than clobbered.
    .equ RC_BACK,   0x4000d0d6        | the loop's own per-track tail
    .global relcut
relcut:
    clr.w   (2,%a0)                     | displaced 1: dry level := 0 (unchanged)
    clr.b   (43,%a0)                    | displaced 2 (unchanged)

| FAST PATH FIRST.  This hook sits in a loop that runs once per releasing track EVERY
| frame (~3,760 times in a 470-frame run), unlike hooks 2-6 which sit on the trig path and
| fire a handful of times.  An earlier draft read GATE (a 32-bit absolute load) before
| anything else; that much extra work, that often, measurably perturbed the emulator's
| ColdFire/DSP lockstep and made even an UNMUTED run differ from stock -- with provably
| identical logic (the assembled rc_clamp replays the three displaced instructions exactly).
| So: test HARDCUT first.  It is zero except in the rare window between a retrig-while-
| silenced and the next unmute, so the common path is one byte load and one branch.
    move.l  %d3,-(%sp)
    move.b  HARDCUT,%d3                 | sets Z when nothing is flagged
    beq     rc_clamp                    | common case -> stock behaviour, minimum work

    move.l  %d0,-(%sp)
    .ifndef ALWAYS_ON
    move.l  GATE,%d0
    .ifdef DT_MODE
    subq.l  #1,%d0                      | mode 1 -> 0, mode 2 -> 1
    cmpi.l  #1,%d0
    bhi     rc_clamp2                   | MUTE MODE not in { OT+FX, DT } -> stock
    .else
    cmpi.l  #1,%d0
    bne     rc_clamp2
    .endif
    .endif

    moveq   #8,%d0
    sub.l   %d1,%d0                     | D0 = this track's index (the loop counts D1 8..1)
    btst    %d0,%d3                     | did THIS track take a real trig while silenced ?
    beq     rc_clamp2                   | no -> keep the FX-tail grace exactly as stock

    move.l  (%sp)+,%d0
    move.l  (%sp)+,%d3
    clr.w   (4,%a0)                     | HARD CUT: close the 6144 route completely
    jmp     RC_BACK

rc_clamp2:
    move.l  (%sp)+,%d0

rc_clamp:
    move.l  (%sp)+,%d3
    cmp.w   (4,%a0),%d2                 | displaced 3
    bgt     rc_done                     | displaced 4
    move.w  %d2,(4,%a0)                 | displaced 5
rc_done:
    jmp     RC_BACK
