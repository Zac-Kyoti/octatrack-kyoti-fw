| SPDX-License-Identifier: MIT
| SPDX-FileCopyrightText: 2026 Zac-Kyoti
| patch_partreapply -- stock bug family: "Part params carry over after a pattern->Part
| change" (Elektronauts "Octatrack OS Bug Reports" / "Playback gets carried over...",
| NOTES.md "Session 49"). A pattern change that links a different Part does not fully
| re-apply that Part's per-track state:
|   #1 a PICKUP machine (not running) on track T, switched via a pattern/Part change to
|      a pattern/Part where T = FLEX, plays the OLD Part's pickup loop instead of the
|      new Part's assigned sample (a STATIC machine on the same switch works correctly --
|      STATIC lives in a different sample arena, forcing an incidental rebind).
|   #2/#3 the recorder page's SRC/RLEN (and the rest of its 12-byte record) from the OLD
|      Part is used even after locking onto the new pattern/Part.
|
| Root cause (static RE, NOTES.md "Session 49", confirmed via tools/emu_partswitch.py
| --repro watching FUN_400972fc + the voice/slot state across a real pattern-driven
| switch): the `sys` task's "select Part P" handler (0x400621a6, the site a real
| pattern->Part change reaches) calls `FUN_400972fc(newPart, track, oldType)` once per
| track. For oldType==4 (PICKUP) and newType!=4, FUN_400972fc takes a fast-path branch
| that does nothing -- no slot rebind, no voice re-trigger. Because PICKUP and FLEX
| share the same sample arena (0x100b14f0+id*1096; STATIC's is a different arena,
| 0x100d5b30+id*1096), the voice's stale SETTINGS pointer keeps reading as "valid" and
| the FLEX track sounds the old pickup loop. Separately, nothing in the pattern-change
| path ever republishes the recorder UI cache (0x80000c94+track*12) from the newly
| applied Part.
|
| Fix -- detour the tail of the "select Part P" handler, right after its existing
| FUN_400972fc x8 loop (which leaves each track's OLD machine type sitting in a local
| buffer at fp@(-9+track), no need to recompute it):
|   1. Recorder memcpy, always, unconditional (nothing else republishes this; safe --
|      recorder settings aren't a continuously-audible parameter): one 96-byte copy
|      (blob + newPart*0x18b2 + 0x8f382) -> 0x80000c94, covering all 8 tracks' 12-byte
|      records (both recorder-page halves) in one shot, since both sides are contiguous
|      per-part blocks.
|   2. Per track, oldType==4 && newType!=4: 0x8000184c |= 1<<track (the voice-kill /
|      re-trigger bit) -- exactly what FUN_400972fc's own notPICKUP->PICKUP arm already
|      does for the reverse transition; nothing does it for this one. This is the one
|      genuinely new piece; narrowly scoped to the exact transition report #1 describes.
|   2c. Per track, same arm: jsr FUN_40001f18(bank, newPart, track) -- THE ACTUAL FIX
|      FOR REPORT #1. The dispatch reads the sample SLOT it passes the resolver from
|      PREIMG_A + track*0x48 byte 0; that byte is seeded from the Part blob only by
|      FUN_40001f18, which stock calls on the way INTO PICKUP and never on the way out,
|      so the PICKUP slot (128+track) survives into the new FLEX machine and the
|      resolver faithfully binds the PICKUP arena entry. Stock's own notPICKUP->PICKUP
|      arm does kill-bit AND this re-seed together (0x400973b4-0x400973e0); Session 49
|      copied the kill bit and omitted the re-seed. Measured, NOTES.md "Session 81".
|   2b. Per track, same arm, when the voice is still set up as PICKUP (voice+0x14==4):
|      jsr FUN_40006820(track) -- stock's own "reset voice + release/transfer the PICKUP
|      ownership singleton" helper. Nothing in stock releases 0x400d7c4c when a track
|      leaves PICKUP (measured, NOTES.md "Session 81"); this completes the symmetry with
|      FUN_40097204's PICKUP arm. NOTE: this is a fix for a separately-measured state
|      leak, NOT for report #1's good->good->bug latch -- the leak is identical at both
|      arrivals, so do not test it against that repro and conclude anything.
|   3. Once: retrigger the crossfader scene morph (move.l #-1,0x400c0c44 ; jsr
|      FUN_4003f1b4) so the new Part's scenes apply now instead of waiting for the next
|      fader touch.
|   4. Only if the transport is stopped (0x800065b8==0): jsr FUN_40009094(bank,newPart)
|      -- Elektron's own full per-track Part-apply (manual PART select / RELOAD PART /
|      bank load / project load all call it). The frame-builder's own per-track lazy
|      catch-up (FUN_4000c8a4) already re-stages machine params + scene data while
|      PLAYING (deliberately left untouched here, to avoid racing whatever jump-avoidance
|      property its timing has); while STOPPED that catch-up never runs at all, so this
|      is the only place machine params / scene buffer / the 0x80001832 marker get
|      refreshed for a stopped-then-switched pattern.
|
| Calling conventions (re-derived fresh from real call sites, NOTES.md "don't trust a
| hand-counted read"):
|   FUN_40020898(dst,src,len)  -- generic memcpy, 3 long stack args, dst closest to jsr
|   FUN_40009094(bank,part)    -- 2 long stack args (each a zero-extended byte), bank
|                                 closest to jsr: push part, push bank, jsr, pop 8
|   FUN_4003f1b4()             -- no arguments
|   FUN_40001f18(bank,part,track) -- 3 long stack args, bank closest to jsr; convention
|                                 copied verbatim from stock's own call at 0x400973c8:
|                                 push track, push part, push bank, jsr, pop 12
|
| Detour (6 B @ 0x40062216, "jsr" kind -- displaced instruction IS itself a jsr, so the
| cave replays it verbatim then rts, resuming at 0x4006221c via the return address the
| site's own jsr already pushes):
|   jsr 0x400326a0  ->  jsr cave

    .equ  BLOB_PTR,    0x46c82456        | pointer variable holding the Part blob base
    .equ  PART_STRIDE, 0x18b2
    .equ  MACH_OFF,    0x8eda2           | PARTS_OFF(0x8ed80) + machine-type-array offset(0x22)
    .equ  REC_OFF,     0x8f382           | recorder record array offset within a Part
    .equ  REC_CACHE,   0x80000c94        | recorder UI cache, 8 tracks x 12 B, contiguous
    .equ  NEWPART_MIR, 0x100b14cf        | mirror of the just-applied Part index (byte)
    .equ  BANK_CUR,    0x80000002        | current bank (byte)
    .equ  KILLBIT,     0x8000184c        | per-track voice-kill/re-trigger bitmap (byte)
    .equ  MORPH_GUARD, 0x400c0c44        | crossfader-morph dedup guard (long); -1 = "stale, re-run"
    .equ  TRANSPORT,   0x800065b8        | sequencer running flag (long); 0 = stopped
    .equ  BANK_MIR,     0x100b14ce        | mirror of the applied BANK index (byte); the
                                          | byte before NEWPART_MIR -- this is the pair
                                          | stock's own FUN_400972fc call site reads
    .equ  FUN_PREIMG_SEED, 0x40001f18     | stock: seed per-track engine pre-image from a Part
    .equ  VOICE_BASE,   0x800049d8        | per-track voice struct base
    .equ  VOICE_STRIDE, 0xA8
    .equ  FUN_PICKUPRESET, 0x40006820     | stock: reset voice + release/transfer PICKUP ownership
    .equ  FUN_MEMCPY,    0x40020898
    .equ  FUN_PARTAPPLY, 0x40009094
    .equ  FUN_MORPH,     0x4003f1b4
    .equ  CONT,        0x400326a0        | displaced instruction's target -- replayed verbatim

    .text
    .global cave
cave:
    lea     -60(%sp),%sp
    movem.l %d0-%d7/%a0-%a6,(%sp)

    | ---- 1: recorder memcpy, always, one 96 B copy (8 tracks x 12 B, contiguous) ----
    clr.l   %d0
    move.b  NEWPART_MIR,%d0
    move.l  #PART_STRIDE,%d1
    muls.l  %d1,%d0
    add.l   BLOB_PTR,%d0
    add.l   #REC_OFF,%d0
    move.l  #96,-(%sp)
    move.l  %d0,-(%sp)
    pea     REC_CACHE
    jsr     FUN_MEMCPY
    lea     12(%sp),%sp

    | ---- 2: per track, oldType==4 && newType!=4 -> kill bit ----
    moveq   #0,%d2                       | track = 0
.Lkill_loop:
    move.b  -9(%fp,%d2.l),%d3            | d3 = oldType[track] (buffered by the loop above)
    extb.l  %d3
    cmpi.l  #4,%d3
    bne.w   .Lkill_next                  | oldType != PICKUP -> no transition of interest

    clr.l   %d0
    move.b  NEWPART_MIR,%d0
    move.l  #PART_STRIDE,%d1
    muls.l  %d1,%d0
    add.l   BLOB_PTR,%d0
    add.l   #MACH_OFF,%d0
    add.l   %d2,%d0
    movea.l %d0,%a0
    move.b  (%a0),%d0                    | d0 = newType[track]
    extb.l  %d0
    cmpi.l  #4,%d0
    beq.w   .Lkill_next                  | newType == PICKUP too -> not this transition

    moveq   #1,%d0
    lsl.l   %d2,%d0                      | d0 = 1<<track
    move.b  KILLBIT,%d1
    or.l    %d1,%d0
    move.b  %d0,KILLBIT

    | ---- 2c: re-seed the per-track pre-image from the NEW Part (Session 81) ----
    | THE ACTUAL FIX FOR REPORT #1. The voice dispatch reads the sample SLOT it
    | hands the resolver from PREIMG_A + track*0x48 byte 0 (measured: a1 at the
    | resolver entry == 0x8000082f + track*0x48 for tracks 1/3/4/5, and byte 0
    | there == the arg2 those same calls passed, 4/4 exact). That byte is seeded
    | from the Part blob by FUN_40001f18(bank, part, track) at 0x400020fa
    | (`move.b (a0),(a1,d1.l)`) -- and across a full round trip it is written
    | EXACTLY ONCE, on the transition INTO PICKUP, never on the way out.
    | Result, measured on stock: T1's slot reads 0x80 (the PICKUP slot 128+T)
    | while the new Part says FLEX slot 2, so the resolver faithfully binds
    | FLEX_ARENA + 128*1096 = 0x100d38f0 -- the PICKUP entry under a FLEX
    | machine. That is report #1, and the one-way latch too: pass 1 is clean
    | because the field is still 0, the return to PICKUP sets it to 0x80
    | correctly, and nothing ever sets it back.
    | Stock's OWN notPICKUP->PICKUP arm in FUN_400972fc does kill-bit AND this
    | re-seed together (0x400973b4-0x400973e0). Session 49's fix replicated the
    | kill bit and omitted the re-seed; this adds the missing half, same call,
    | same argument order (push track, part, bank -- bank closest to the jsr).
    clr.l   %d0
    move.b  %d2,%d0
    move.l  %d0,-(%sp)                   | track
    clr.l   %d0
    move.b  NEWPART_MIR,%d0
    move.l  %d0,-(%sp)                   | part
    clr.l   %d0
    move.b  BANK_MIR,%d0
    move.l  %d0,-(%sp)                   | bank
    jsr     FUN_PREIMG_SEED              | 0x40001f18(bank, part, track)
    lea     12(%sp),%sp

    | ---- 2b: release the PICKUP ownership singleton (Session 81) ----
    | PICKUP is one GLOBAL capture buffer with a single owner track
    | (0x400d7c4c, -1 = unclaimed), not a per-track arena slot. FUN_40097204
    | claims it whenever a track's machine byte becomes 4, but its else branch
    | (0x40097276) clears ONLY the skip-flag bit -- nothing releases ownership
    | when a track leaves PICKUP. Measured on stock (emu_partswitch.py --repeat
    | --own-poke): across a full P1->P5->P1->P5 round trip, 224 writes to the
    | skip flag and ZERO to the owner / enable mask / cfg word; owner stays the
    | departed track and voice+0x14 stays 4 (PICKUP) while the Part says FLEX.
    | Complete the symmetry using Elektron's own routine: stock's PICKUP arm
    | calls FUN_40006820(track) when the voice is NOT yet set up as PICKUP
    | (voice+0x14 != 4); the mirror is to call it when the voice is STILL set up
    | as PICKUP but the machine no longer is. FUN_40006820 resets the voice and
    | calls FUN_4000672C, which rebuilds the enable mask from the live machine
    | bytes and either releases the singleton (owner = -1, clr cfg) or transfers
    | it to another still-PICKUP track -- release-or-transfer, correctly.
    | Gated on voice+0x14 == 4 so it is a no-op when nothing is stale.
    move.l  #VOICE_STRIDE,%d0
    move.l  %d2,%d1
    muls.l  %d0,%d1
    movea.l #VOICE_BASE,%a0
    adda.l  %d1,%a0
    move.b  20(%a0),%d0                  | voice[track]+0x14 (the voice's own machine byte)
    extb.l  %d0
    cmpi.l  #4,%d0
    bne.b   .Lkill_next                  | voice isn't a PICKUP voice -> nothing to release
    move.l  %d2,-(%sp)
    jsr     FUN_PICKUPRESET              | 0x40006820(track) -- saves/restores d2, a2
    addq.l  #4,%sp

.Lkill_next:
    addq.l  #1,%d2
    cmpi.l  #8,%d2
    bne.w   .Lkill_loop

    | ---- 3: once -- retrigger the crossfader scene morph ----
    moveq   #-1,%d0
    move.l  %d0,MORPH_GUARD
    jsr     FUN_MORPH

    | ---- 4: only if the transport is stopped -- Elektron's own full Part apply ----
    tst.l   TRANSPORT
    bne.b   .Ldone                       | running -> leave the frame-builder's own lazy catch-up alone

    clr.l   %d0
    move.b  NEWPART_MIR,%d0
    move.l  %d0,-(%sp)                   | part
    clr.l   %d0
    move.b  BANK_CUR,%d0
    move.l  %d0,-(%sp)                   | bank
    jsr     FUN_PARTAPPLY
    lea     8(%sp),%sp

.Ldone:
    movem.l (%sp),%d0-%d7/%a0-%a6
    lea     60(%sp),%sp
    jsr     CONT                         | replay the displaced instruction verbatim
    rts                                  | resume at 0x4006221c via the site's own return address
