| SPDX-License-Identifier: MIT
| SPDX-FileCopyrightText: 2026 Zac-Kyoti
|
| MUTEMODE_NEW -- a from-scratch redesign of the MUTE MODE audio-track mute
| behaviour, built directly on freshly-disassembled AND dynamically-verified
| stock choke points (not on any earlier mute-mode patch in this repo).
|
| REVISION 2 -- corrects revision 1 after a failed hardware flash. Revision 1
| shipped with muting having NO audible effect at all: it disabled stock's own
| (real, working) post-FX mute cut and replaced it with a per-frame write to
| 0x46c7ff42, a memory location later PROVEN (both statically -- a second,
| unrelated consumer indexes it as a 128-entry lookup table, inconsistent with
| "8 tracks stride 4" -- and dynamically, via a differential Unicorn trace
| showing it holds a constant 0xFFFFFFFF sentinel regardless of whether a
| trig is armed) to be disconnected from audio entirely. That hook is REMOVED.
|
| What replaces it is built on evidence, not another static guess:
|
|   - A live differential DMA trace (muted vs unmuted, real project, real
|     trig, real transport) found the ACTUAL byte stock's mute changes: the
|     word written by `FUN_40004db8` at instruction 0x40004e8c
|     (`move.w %d2,(%a0)+`) -- exactly the function+site this repo's own
|     knowledge base already named as the per-frame mute gate. 2,400 real
|     eDMA transfers to the DSP host port confirmed it; nothing else ever
|     differed. This is hook 3 below, now dynamically confirmed rather than
|     just disassembled.
|   - octabam's own hardware-tested DSP research (refs/octabam) establishes
|     that the ColdFire renders each track's audio (including timestretch)
|     and ships it to the DSP fresh every frame; the DSP's own per-track path
|     is FX1 -> FX2 -> a summing mixdown (P:0x2bf) with no gain stage of its
|     own before that. Directly measured with octabam's `dsp_host` against
|     THIS project's own stock payload (out/dsp/stock_mem_A.mem, built by
|     dsp_modmap.py --dumpmem): a real stock reverb (SPRING REV, id 0x15) fed
|     a burst and then pure silence kept producing non-zero output for the
|     entire rest of a 12,800-sample run (11,198 non-zero samples) -- i.e.
|     the DSP's reverb tail rings on its own once its input actually goes
|     silent, with no separate "let the FX ring" lever needed anywhere.
|   - The per-track STOP command (flags 0xf010 to FUN_40005178) was checked
|     the same way, not assumed: mark a track's voice active, deliver the
|     mailbox message under the REAL RTOS/frame scheduling (not an isolated
|     call -- FUN_40005178 only enqueues it, a later frame-interrupt consumer
|     applies it), and diff the whole per-track voice struct. Exactly one
|     byte changes, unprompted by anything else: +0x01 goes 0x00 -> 0xff.
|     That is a real, measured "voice stopped" effect, not a guess.
|
| Put together: for OTFX-T, neutralising hook 3 (so the post-FX word is no
| longer force-zeroed) lets whatever is really in that word -- silence from a
| stopped voice, plus a genuinely still-decaying FX tail -- reach the output
| exactly as computed. No DSP-side patch, no separate "dry gain" hook, is
| needed for this mode.
|
|   1) 0x40004dc6 -- inside the stock per-frame MUTE GATE (FUN_40004db8),
|      where it loads the mute/solo/cue bitfield (0x80000008) before using it
|      to zero the post-FX per-track word. Neutralising just the MUTE byte
|      (bits 8-15) here, for OTFX-T only, stops stock's hard cut from also
|      erasing the FX tail every single frame while held muted. SOLO (bits
|      0-7) and CUE (bits 16-23) are untouched -- only the MUTE key's own
|      consequence is redefined, and only in OTFX-T.
|
|   2) 0x4000d36e -- inside the per-track per-frame filler (the stock
|      function at 0x4000d0a0), a site that runs unconditionally every frame
|      for every one of the 8 tracks (dynamically confirmed: hit every frame,
|      independent of whether a trig is armed). Used ONLY as a reliable,
|      once-per-frame, per-track edge detector: the first frame OTFX-T sees a
|      track's mute bit newly set, it fires the real STOP command (0xf010,
|      the same flags value stock's own trig_to_voice uses for its own STOP
|      case) inside the same interrupt-disable critical section stock uses
|      for that call. No amp/gain value is touched here any more.
|
|   3) 0x4000d350 -- a few instructions earlier IN THE SAME per-frame filler
|      loop as hook 2, right before it calls FUN_40005ff0 (the "arm caller"
|      that actually starts a new voice for a real trig). Found by chasing
|      the real trig-dispatch chain all the way through, cross-checked
|      against octabam's own external research on this exact firmware
|      (refs/octabam/docs/firmware/RTOS_FORK.md sections 10.4-10.8), which
|      independently hit the same dead end on revision 1's target
|      (`FUN_400977cc`: 0 calls under a real trig, matching what this repo
|      found too) and traced the real path: the step handler's per-track
|      flag word (0x46c7a6c0, matching this repo's own decompile of
|      0x4009d1e8) is tested here as `flags & 0xd0`; when non-zero, D1=flags
|      and D3=track are pushed and FUN_40005ff0 is called -- literally the
|      same call this repo's own much earlier decompile of this function
|      already showed (`if ((flags & 0xd0) != 0) FUN_40005ff0();`), whose
|      significance wasn't recognised until the trace converged on it from
|      the other direction. DT-T suppresses exactly this call, for exactly
|      the muted track, on exactly the frame it would otherwise fire --
|      nothing else in the loop (the currently-sounding voice, hook 1/2,
|      any other track) is touched.
|
| REVISION 3 -- adds a live PERSONALIZE menu entry, replacing build-time mode
| selection. The PERSONALIZE screen is three parallel 16-entry arrays (label /
| getter / setter pointers) at 0x400b2a34/0x400b2a74/0x400b2ac0; the MKI/MKII
| boot probe (0x46c8d18c) feeds a `moveq #15,d1` at 0x40068fb2 that becomes the
| visible row count (15 on MKI, 16 on MKII) -- MKI simply never renders or
| dispatches to slot 15. That slot is real, populated code: "LED BRIGHTNESS"
| (LOW/MID/MAX), backed by 0x800000d0 (live) / 0x100fff60 (battery shadow,
| already within stock's existing restore range -- unlike the old 0x100fff6c
| address, no restore-range patch is needed here). Since MKI has no LED to
| brighten, this slot is provably dead weight on the only hardware this
| project targets. Two small patches repurpose it:
|
|   4) 0x40068fb3 -- one byte, 0x0f -> 0x10: the row-count immediate. MKI now
|      renders/dispatches 16 rows instead of 15 (MKII would see 17, harmless
|      since MKII is out of scope and never built for).
|   5) 0x400b2a70 / 0x400b2ab0 / 0x400b2afc -- slot 15's label/getter/setter
|      pointers, overwritten to point at this cave's own MUTE MODE label,
|      getter and setter, reusing 0x800000d0/0x100fff60 for storage (mode
|      0-3, wrapped with a bitmask since 4 is a power of 2 -- no need to
|      replicate LED BRIGHTNESS's asymmetric 3-state clamp logic). The setter
|      calling convention (delta, direction) and getter (0 args, return a
|      display-string pointer in D0) are copied from LED BRIGHTNESS's own
|      code, byte-identical in shape.
|
| Mode value now lives in 0x800000d0 (read fresh every time by hooks 1-3) --
| there is no more build-time mode selection or baked-in mute_mode byte.
|
|   OT      : all three hooks no-op -- byte-for-byte stock.
|   DT-T    : hook 3 only. A muted track's pending "arm a new voice" event is
|             dropped for as long as it's held muted; whatever is already
|             sounding is never touched (hooks 1/2 stay no-ops in this mode),
|             so it keeps ringing under its own envelope/FX exactly as before.
|   OTFX    : NOT YET IMPLEMENTED IN THIS REVISION -- behaves exactly like OT.
|             Its spec (dry cuts instantly, voice position keeps advancing
|             silently underneath, unmute resumes where it now is) needs a
|             lever that silences output WITHOUT the STOP semantics below
|             (STOP genuinely ends the voice -- position does not survive
|             it). No such lever has been found yet.
|   OTFX-T  : hook 1 + hook 2, both dynamically verified as described above.
|             On the mute-down edge, STOP genuinely ends the voice (dry
|             silence, instant); hook 1 lets the still-decaying FX output
|             already in the per-track word reach the mix instead of being
|             erased every frame; nothing plays again until the next real
|             trig.
|
| Assemble like the other stubs: m68k-elf-as -mcpu=5407 ; ld -Ttext=<cave> ;
| objcopy -O binary. Detour sites and exact replaced bytes are asserted by
| build_mutemode_new.py against the pure stock MAIN OS section.

    .equ  MODE_OT,      0
    .equ  MODE_DTT,     1
    .equ  MODE_OTFX,    2
    .equ  MODE_OTFXT,   3

    .equ  MUTE_MASK,    0x8000000a     | mute bitfield byte, bit t = track t muted
    .equ  VOICE_MBOX,   0x40005178     | voice command mailbox writer (track,flags,extra)
    .equ  STOP_FLAGS,   0xf010         | stock's own per-track STOP command word

    .equ  CONT_PERFRAME, 0x40004dcc    | perframe_mute_gate, right after the detoured load
    .equ  CONT_AMPGATE,  0x4000d374    | per-frame filler, right after the detoured pair
    .equ  ARM_CALLER,    0x40005ff0    | FUN_40005ff0, the real "arm a new voice" call
    .equ  CONT_ARM_YES,  0x4000d356    | per-frame filler: stock's own push-args+jsr+cleanup (untouched)
    .equ  CONT_ARM_NO,   0x4000d35e    | per-frame filler: where both the skip and the call path rejoin

    .equ  MUTE_MODE_RAM,    0x800000d0 | live mode value (0-3), the repurposed LED BRIGHTNESS word
    .equ  MUTE_MODE_SHADOW, 0x100fff60 | its battery-backed shadow, already in stock's restore range

    .text
    .global cave_perframe
    .global cave_ampgate
    .global cave_armgate
    .global mute_prev
    .global mute_menu_label
    .global mute_menu_getter
    .global mute_menu_setter

| ---------------------------------------------------------------------------
| Hook 1 -- neutralise stock's post-FX MUTE bit, OTFX-T only.
| Detour site 0x40004dc6, 6 B: `move.l 0x80000008,%d5`.
| ---------------------------------------------------------------------------
cave_perframe:
    move.l  0x80000008,%d5
    move.l  MUTE_MODE_RAM,%d0
    cmp.l   #MODE_OTFXT,%d0
    bne.s   .Lpf_done                  | any mode but OTFX-T -> stock d5, unchanged
    and.l   #0xffff00ff,%d5            | clear only the mute byte (bits 8-15)
.Lpf_done:
    jmp     CONT_PERFRAME

| ---------------------------------------------------------------------------
| Hook 2 -- STOP-on-mute-edge, OTFX-T only. Detour site 0x4000d36e, 6 B:
| `move.l %d0,(%a2)+` followed by `movea.l 0xa0(%sp),%a1`. D3 = track (0..7),
| live across the whole loop; D0/D1 dead after the write; A1/A2/D2/D3 must
| come out exactly as stock left them -- this cave no longer alters the
| amp/gain value at all, only observes D3 to edge-detect and fire STOP.
| ---------------------------------------------------------------------------
cave_ampgate:
    move.l  %d0,(%a2)+                 | replay the detoured write, untouched
    movea.l 0xa0(%sp),%a1              | replay the detoured movea (needed by the caller)
    move.l  MUTE_MODE_RAM,%d1
    cmp.l   #MODE_OTFXT,%d1
    bne.s   .Lag_exit                  | OT / DT-T / OTFX: this hook is a no-op
    move.l  %d3,%d0
    jsr     mute_is_muted              | -> d1 nonzero if track d3 is muted
    lea     mute_prev,%a0
    tst.b   %d1
    bne.s   .Lag_muted
    clr.b   (%a0,%d3.l)                | not muted: clear this track's edge flag
    bra.s   .Lag_exit
.Lag_muted:
    tst.b   (%a0,%d3.l)
    bne.s   .Lag_exit                  | STOP already fired for this mute hold
    moveq   #1,%d0
    move.b  %d0,(%a0,%d3.l)
    move.l  %d2,-(%sp)                 | D2 is live across this hook -- save it
    move.w  %sr,%d2
    move.w  #0x2700,%sr                | stock's own critical section for this call
    pea     1
    move.l  #STOP_FLAGS,-(%sp)
    move.l  %d3,-(%sp)
    jsr     VOICE_MBOX
    lea     0xc(%sp),%sp
    move.w  %d2,%sr
    move.l  (%sp)+,%d2                 | restore D2
.Lag_exit:
    jmp     CONT_AMPGATE

| ---------------------------------------------------------------------------
| Hook 3 -- DT-T only: drop a pending "arm a new voice" event for a muted
| track. Detour site 0x4000d350, 6 B: `lea.l 0x10(%sp),%sp` followed by
| `beq.b 0x4000d35e`. D0 = the already-computed `flags & 0xd0` test result
| (stock's own ANDI, untouched -- we only replay the LEA and re-implement the
| BEQ this detour swallowed). D1 = this track's pending flags word, D3 =
| track (0..7); both must survive untouched for CONT_ARM_YES's own code
| (unmodified stock, right after this cave) to push as its own arguments.
| ---------------------------------------------------------------------------
cave_armgate:
    lea.l   0x10(%sp),%sp              | replay the detoured stack cleanup
    tst.l   %d0                        | replay the detoured BEQ's own test
    beq.s   .Lar_skip                  | flags & 0xd0 == 0: no new trig this frame, stock skips too
    move.l  MUTE_MODE_RAM,%d0
    cmp.l   #MODE_DTT,%d0
    bne.s   .Lar_arm                   | not DT-T: arm normally, exactly like stock
    move.l  %d1,-(%sp)                 | DT-T: save the flags word around the mute check
    move.l  %d3,%d0
    jsr     mute_is_muted              | -> d1 nonzero if track d3 is muted
    move.l  %d1,%d0                    | d0 = muted flag
    move.l  (%sp)+,%d1                 | restore the flags word
    tst.l   %d0
    bne.s   .Lar_skip                  | muted: drop this trig's arm event entirely
.Lar_arm:
    jmp     CONT_ARM_YES               | stock's own push-args+jsr(ARM_CALLER)+cleanup, unmodified
.Lar_skip:
    jmp     CONT_ARM_NO

| ---------------------------------------------------------------------------
| in: d0 = track (0..7). out: d1 = nonzero if MUTE_MASK has that track's bit
| set, else 0. Clobbers d0, d1 only.
| ---------------------------------------------------------------------------
mute_is_muted:
    moveq   #1,%d1
    lsl.l   %d0,%d1                    | d1 = 1<<track (ColdFire only shifts .l by register count)
    clr.l   %d0
    move.b  MUTE_MASK,%d0              | d0 = zero-extended mute mask byte
    and.l   %d0,%d1                    | d1 &= mask (ColdFire and/or/eor: .l size only)
    rts

mute_prev:
    .space  8                          | per-track "STOP already fired this hold" (OTFX-T)

| ---------------------------------------------------------------------------
| PERSONALIZE row 15 (the repurposed LED BRIGHTNESS slot): label, getter and
| setter. Calling convention copied from stock's own LED BRIGHTNESS code at
| this same slot (0x40068c80 / 0x4006907c): getter takes no arguments and
| returns a display-string pointer in D0; setter takes (delta, direction) as
| two stack longwords -- direction is unused here (mod-4 wraps identically
| both ways, unlike LED BRIGHTNESS's asymmetric 3-state clamp).
| ---------------------------------------------------------------------------
mute_menu_label:
    .asciz  "MUTE MODE"

    .align  2
mute_menu_str_ot:
    .asciz  "OT"
mute_menu_str_dtt:
    .asciz  "DT-T"
mute_menu_str_otfx:
    .asciz  "OTFX"
mute_menu_str_otfxt:
    .asciz  "OTFX-T"

    .align  2
mute_menu_strs:
    .long   mute_menu_str_ot
    .long   mute_menu_str_dtt
    .long   mute_menu_str_otfx
    .long   mute_menu_str_otfxt

mute_menu_getter:
    move.l  MUTE_MODE_RAM,%d0
    and.l   #3,%d0                     | defensive clamp (in case of a stale/foreign value)
    move.l  %d0,%d1
    asl.l   #2,%d1
    lea     mute_menu_strs,%a0
    move.l  (%a0,%d1.l),%d0
    rts

mute_menu_setter:
    move.l  4(%sp),%d0                 | delta (+1 / -1), no local frame ahead of it
    move.l  MUTE_MODE_RAM,%d1
    add.l   %d0,%d1
    and.l   #3,%d1                     | wrap mod 4 (power of 2 -- correct both directions)
    move.l  %d1,MUTE_MODE_RAM
    move.l  %d1,MUTE_MODE_SHADOW
    rts
