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
    bne.b   .Lkill_next                  | oldType != PICKUP -> no transition of interest

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
    beq.b   .Lkill_next                  | newType == PICKUP too -> not this transition

    moveq   #1,%d0
    lsl.l   %d2,%d0                      | d0 = 1<<track
    move.b  KILLBIT,%d1
    or.l    %d1,%d0
    move.b  %d0,KILLBIT

.Lkill_next:
    addq.l  #1,%d2
    cmpi.l  #8,%d2
    bne.b   .Lkill_loop

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
