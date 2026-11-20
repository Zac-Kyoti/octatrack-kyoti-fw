| SPDX-License-Identifier: MIT
| SPDX-FileCopyrightText: 2026 Zac Kyoti
| patch_triglock -- Section 13 (NOTES.md): a trigless lock (a step holding p-locks and no
| trig) whose last remaining p-lock is erased stays lit on the 16-step trig row forever.
| AUDIO tracks since Session 78; MIDI tracks since 2026-11-20 (the MIDI section below).
|
| HOW THE TARGET WAS FOUND (Session 78). Three earlier builds hooked functions in the
| 0x40041xxx/0x40042xxx p-lock cluster and did nothing on hardware, because that cluster is
| not on the gesture's path at all. A diagnostic firmware (tools/patch_triglock_diag.s)
| logging into the bank blob -- which a project save serialises to the card, so the trace
| exports back to the desk -- settled it by measurement. From ARTLTEST8:
|
|   opcode 1  TRAC+0x10 steps0-7  0x00 -> 0x40   and  #1[6][0] 0xff -> 0x40   (create)
|   opcode 8  #1[6][0] 0x40 -> 0xff  and  #1[6][2] 0x00 -> 0xff   (erase, flag untouched)
|
| with NONE of opcodes 64/65/66/70/74 occurring. Opcode 8's case (0x40061ed4), on the LIVE
| branch (0x460d172a != 0), calls FUN_40041af4 -- which sits immediately BEFORE
| FUN_40041bc4 and has no `linkw`, so every function-boundary scan had missed it -- which
| tail-calls FUN_40038668 (MIDI) / FUN_40038874 (AUDIO).
|
| FUN_40038874(trackmask, clear_trigs, param_mask), per track in the mask:
|     step = FUN_4009b2b0(track)        ; = [0x800064e0 + track] & 0x3f
|     if clear_trigs: clear TRAC +0x00/+0x08/+0x10/+0x18 at step (+ mirrors)
|     if param_mask:
|       for p in 0..31 where param_mask & (1<<p):
|           #1[step][p] = 0xFF          ; 0x40038a5c -- THE ERASE STORE
|       if clear_trigs == 0 && param_mask != 0xffffffff:
|           scan #1[step][0..31]; if any byte != 0xFF -> keep the bitmap bit
|       clear the bitmap bit            ; 0x40038af2, committed at 0x40038af8
|
| So stock already decides "this step's p-lock row is empty" -- it just applies that only
| to the per-step stored-p-lock bitmap 0x46c7d48c and never to the trig-type-layer flag
| TRAC+0x10, which is what keeps the LED lit. That asymmetry is the whole bug.
|
| WHY THE DETOUR IS ON THE STORE AND NOT ON THAT DECISION
|
| An earlier version hooked 0x40038af2, stock's own "the row is empty" conclusion. It
| worked -- hardware-confirmed: multi-pass intact, last erase clears the step -- but it
| could not tell apart two states that look identical there (TRAC+0x10 set, #1[step] all
| 0xFF):
|     (a) the user just erased the step's last remaining p-lock            -> delete
|     (b) the step is an EMPTY trigless lock placed deliberately with       -> keep
|         FUNC+TRIG, and the gesture erased a param that was never locked
| and so it deleted (b) too. FUNC+TRIG placeholders are a first-class workflow, and
| because LIVE REC erases "as the playhead passes" the user need not even be targeting that
| step: holding [NO] and sweeping one knob across a pattern was enough to silently remove
| every placeholder the playhead crossed, with no audible tell (the step was already
| silent) and no undo.
|
| Hooking the erase STORE instead makes the two distinguishable, because the pre-erase
| value is still in memory one instruction before it is overwritten:
|
|     fire only if   the old value of #1[step][param] != 0xFF    (a param really was
|                                                                 locked here a moment ago)
|       and if       every OTHER byte of #1[step] is already 0xFF (it was the last one)
|
| Case (b) fails the first test on every param, always: a FUNC+TRIG placeholder has no
| non-0xFF byte anywhere in its row, so nothing the gesture touches was ever locked. No
| shared state, no flag carried between loop iterations, nothing to leak across calls.
|
| DETOURS (6 B each), one per worker; both replay what they displace before their own `rts`:
|   0x40038a5c (AUDIO, FUN_40038874)  `moveb %d1,%a0@(0x59,%d2:l) ; addl %d4,%d0`  -> cave
|   0x400387b8 (MIDI,  FUN_40038668)  `moveb %d1,%a0@(0x4900)     ; addl %d4,%d0`  -> cave_midi
| Each entry turns its worker's registers into the same four values and calls one shared
| core (`tl_core`), so the rule exists once:
|   a1 = the step's lock row (32 bytes, one per param; the old value is still there)
|   a2 = the track's mask block (layer k at a2 + 8*k, 64 bits each)
|   d2 = the param being erased       d4 = step*32 (both workers keep it there)
|   d7 = which layers k are REAL TRIGS that veto (bit k)
|
| AUDIO registers at 0x40038a5c, read straight from the disassembly:
|   a0 = blob + pattern*0x8ed8 + track*0x91a + step*32   (so the `#1` row base is a0+0x59,
|        and TRAC is a0 - d4)
|   d2 = param index      d1 = 0xFF (the sentinel about to be stored)
|   d4 = step*32          d7 = track      a3 = step
|
| ---- MIDI tracks (2026-11-20; KY18C / KY18BC RC1 on the unit: the step stayed lit) ----
| FUN_40041af4 (opcode 8's LIVE branch) tail-calls FUN_40038668 instead of FUN_40038874 when
| 0x80000012 != 0 (the MIDI side), with the same (trackmask, clear_trigs, param_mask). It is
| the same worker shape on the MIDI block, and it has the same missing clear:
|     step = FUN_4009b2b0(track + 8)
|     if clear_trigs: clear MTRA +0x00/+0x08 (+ mirrors 0x1001aa1e/26)   <- not +0x10 either
|     for p where param_mask & (1<<p):
|         row[p] = 0xFF        ; 0x400387b8 -- THE ERASE STORE
|         mirror row[p] = 0xFF ; 0x400387c8 (0x1001aa4e + ...)
|     row empty -> clear the track's bit in 0x46c7d2e4[step]   (the MIDI per-step lock bitmap)
| MTRA = blob + pattern*0x8ed8 + 0x48d0 + track*0x8b0; the lock row is MTRA+0x30+32*step
| (blob+0x4900+...), one byte per param, 0xFF = not locked. Registers at 0x400387b8:
|   a0 = blob + pattern*0x8ed8 + track*0x8b0 + step*32 + PARAM   (the param is already added;
|        the store is `0x4900(a0)`)
|   d1 = 0xFF   d2 = param   d3 = track*0x8b0   d4 = step*32   d6 = step   d7 = track
|   d0 = pattern*0x8ed8 before the displaced `add.l %d4,%d0` (0x400387be uses it, with d1)
| No branch lands in 0x400387ba..0x400387bd (the loop's only branches are 0x40038794 ->
| 0x400387e4 and 0x400387ea -> 0x4003878c); the builder's assert_no_branch_into covers it.
|
| The MIDI mask layers, from the [FUNC]+trig toggle 0x40040f90, the trig-row painter and the
| pattern initialiser FUN_4009abdc:
|   +0x00 note trig        +0x08 trigless trig     +0x10 TRIGLESS LOCK (the toggle cycles
|   note -> +0x08 -> +0x10 -> +0x08, writing mirrors 0x1001aa1e / aa26 / aa2e)
|   +0x18 swing (FUN_4009abdc fills it 0xAA..: every second step by default -- audio's +0x40)
|   +0x20 slide (filled 0x00 -- audio's +0x48; the 0x40027xxx page loaders pair them so)
| The trig row is painted from exactly the first three: FUN_40034bd4's MIDI branch
| (0x40034d2a..) reads the page's 16-bit word of +0x00 (red), else +0x08 (green), else +0x10
| (green, dim) -- the emulator logged its read of MTRA+0x16 at 0x40034d92 -- so clearing
| +0x10 is what darkens the step. VETO on MIDI: +0x00, +0x08 and +0x20 (slide, a trig type
| the author listed). Swing is NOT a veto: it is a step attribute set on every second step by
| default, so vetoing it would keep half the trigless locks lit; it fires nothing by itself
| (the MIDI step handler 0x4009d062.. ORs +0x00 / +0x08 / +0x10 only).
|
| THE MIRROR. Both workers keep a copy of the bank's pattern area at 0x1001614e: every
| mirror store is 0x1001614e + (its blob address - blob). Audio: TRAC+0x10 -> 0x1001615e +
| pat*0x8ed8 + track*0x91a (the old cave's MIRROR_BASE); MIDI: +0x00 -> 0x1001aa1e (stock's
| clear 0x400386fc), +0x08 -> 0x1001aa26 (0x4003874e), the row -> 0x1001aa4e (0x400387c2), and
| +0x10 -> 0x1001aa2e: the [FUNC]+trig toggle stores it with MTRA+0x10 (0x40041264 / 0x40041282,
| 0x40041192 / 0x400411b0), as do 0x4003dca6 / 0x4003dcb2 and the lock writers 0x40042500 /
| 0x400426aa. So the core finds the mirror byte as (mask byte) - [BLOB_PTR] + 0x1001614e,
| one rule for both sides (the blob pointer is the one the worker indexed by, a moment ago).
|
| NOTE on 0x40038af8, the instruction that looked like the natural hook: its second half
| `addql #1,%d7` is the enclosing loop's INCREMENT, and 0x40038afc is a branch target from
| 0x400388a4 and 0x40038a1a (the skip-this-track paths). A 6-byte detour there swallows it
| and the loop never terminates -- that build hung in the emulator. build_erase_empty_trigless_locks.py now
| refuses any detour whose displaced bytes contain a branch target.
|
| GUARDS, and how they satisfy Session 13
|   - the step must not be owned by any real trig. AUDIO: note/sample TRAC+0x00, the other
|     two trig-type layers +0x08/+0x18, and the three recorder-trig masks +0x20/+0x28/+0x30, so
|     a trigless TRIG that retrigs an LFO, and sample/MIDI/one-shot/recorder/slide trigs,
|     are never touched. MIDI: +0x00 note, +0x08 trigless trig, +0x20 slide (above).
|   - +0x10's bit must actually be set, i.e. this really is a trigless lock. (AUDIO with
|     clear_trigs set: stock has already cleared that bit itself, so this no-ops. MIDI with
|     clear_trigs set: stock clears +0x00/+0x08 and leaves +0x10, so the last locked param's
|     store clears it -- the trigless lock goes as the audio one does; an EMPTY one is left as
|     stock leaves it, by the old-value rule.)
|   - MULTI-PASS: with PTCH and LEN locked, erasing PTCH finds LEN still non-0xFF, so the
|     row test fails and the step stays lit. Erasing LEN then finds every other byte 0xFF
|     and fires. No counter of our own.
|   - EMPTY PLACEHOLDERS SURVIVE: the old-value test rejects them outright.
|   - Never a global sweep: the cave runs only on an instruction that is itself erasing a
|     p-lock from this exact step.
|
| REMAINING AMBIGUITY (pre-existing in stock, not introduced here): a param whose legal
| range includes 255 stores as 0xFF, which stock itself cannot tell from "not locked". Such
| a lock already reads as absent to stock's own row scan, so the LED is already wrong for
| it today, with or without this patch.
|
| ColdFire (5407) notes: byte-sized register-register ALU ops are unavailable, so a byte is
| widened with MVS/MVZ and the logic done in .l. MOVEM has no predecrement form, so the
| save/restore adjusts %sp by hand. a4/a5 are never touched. Position-independent (bsr.w).
|
| Assemble like the other stubs: m68k-elf-as -mcpu=5407 ; ld -Ttext=<cave> ; objcopy -O binary

    .equ  AUD_ROW,       0x59          | `#1` within TRAC: 64 steps x 32 bytes
    .equ  MID_BLK,       0x48d0        | MTRA within the pattern block
    .equ  MID_ROW,       0x4900        | the MIDI lock rows within the pattern block (MTRA+0x30)
    .equ  TYPE_FLAG_OFF, 0x10          | the trig-type layer carrying the trigless-lock bit
    .equ  AUD_VETO,      0x7b          | layers 0,1,3,4,5,6: +0x00 +0x08 +0x18 +0x20 +0x28 +0x30
    .equ  MID_VETO,      0x13          | layers 0,1,4:       +0x00 +0x08 +0x20
    .equ  MIRROR_DELTA,  0x1001614e    | mirror(X) = X - [BLOB_PTR] + MIRROR_DELTA
    .equ  BLOB_PTR,      0x46c82456
    .equ  DIRTY_GLOBAL,  0x100f8598
    .equ  DIRTY_IN_BLOB, 0x9b332
    .equ  NOTIFY,        0x40027e00    | stock calls this after each of its own edits here

    .text
    .global cave
    .global cave_midi

| ---- AUDIO entry (0x40038a5c): a0 = TRAC + step*32. MUST stay at offset 0: the standalone and
| ---- KYOTI builds, patch_triglock_bp's `jmp CAVE` and the manifest all take the cave base. ----
cave:
    lea     %sp@(-48),%sp
    moveml  %d0-%d7/%a0-%a3,%sp@
    lea     %a0@(AUD_ROW),%a1         | a1 = the row
    movea.l %a0,%a2
    suba.l  %d4,%a2                   | a2 = TRAC (d4 = step*32)
    moveq   #AUD_VETO,%d7
    bsr.w   tl_core
    moveml  %sp@,%d0-%d7/%a0-%a3
    lea     %sp@(48),%sp
    move.b  %d1,%a0@(AUD_ROW,%d2:l)   | the displaced stock instructions, verbatim
    add.l   %d4,%d0
    rts

| ---- MIDI entry (0x400387b8): a0 = blob + pat*0x8ed8 + track*0x8b0 + step*32 + param ----
cave_midi:
    lea     %sp@(-48),%sp
    moveml  %d0-%d7/%a0-%a3,%sp@
    movea.l %a0,%a2
    suba.l  %d2,%a2                   | the step's offset in the pattern block, no param
    lea     %a2@(MID_ROW),%a1         | a1 = the row (MTRA + 0x30 + step*32)
    suba.l  %d4,%a2
    lea     %a2@(MID_BLK),%a2         | a2 = MTRA
    moveq   #MID_VETO,%d7
    bsr.w   tl_core
    moveml  %sp@,%d0-%d7/%a0-%a3
    lea     %sp@(48),%sp
    move.b  %d1,%a0@(MID_ROW)         | the displaced stock instructions, verbatim
    add.l   %d4,%d0
    rts

| ---- the shared rule: a1 = row, a2 = mask block, d2 = param, d4 = step*32, d7 = veto layers ----
tl_core:
    | was this param ACTUALLY locked a moment ago? The store is unconditional, so a gesture
    | aimed at a never-locked param reaches here too. If the old value is already the 0xFF
    | sentinel then nothing is being erased -- a FUNC+TRIG placeholder, or an untouched
    | param -- and it must survive.
    mvs.b   %a1@(0,%d2:l),%d0
    addq.l  #1,%d0                    | old == 0xFF  <=>  -1 + 1 == 0
    beq     .Lout

    | was it the LAST one? every OTHER byte of the row must already be 0xFF
    moveq   #31,%d3
.Lscan:
    cmp.l   %d2,%d3
    beq     .Lnext                    | skip the param this store is erasing
    mvs.b   %a1@(0,%d3:l),%d0
    addq.l  #1,%d0
    bne     .Lout                     | another param is still locked -- keep the step lit
.Lnext:
    subq.l  #1,%d3
    bpl     .Lscan

    | mask addressing: byte = 7-(step>>3), bit = 1<<(step&7)
    move.l  %d4,%d5
    lsr.l   #5,%d5                    | step
    move.l  %d5,%d6
    lsr.l   #3,%d6
    moveq   #7,%d3
    sub.l   %d6,%d3                   | d3 = byte index
    moveq   #7,%d6
    and.l   %d5,%d6
    moveq   #1,%d5
    lsl.l   %d6,%d5                   | d5 = bit mask
    adda.l  %d3,%a2                   | a2 = block + byte index

    | refuse if ANY real trig owns this step: layer k (a2 + 8*k) for every bit k of d7
    movea.l %a2,%a3
.Lveto:
    lsr.l   #1,%d7
    bcc     .Lnoveto
    mvz.b   %a3@,%d6
    and.l   %d5,%d6
    bne     .Lout
.Lnoveto:
    addq.l  #8,%a3
    tst.l   %d7
    bne     .Lveto

    | and it must really BE a trigless lock; clear it (bit known set, so EOR is an exact clear)
    mvz.b   %a2@(TYPE_FLAG_OFF),%d6
    move.l  %d6,%d3
    and.l   %d5,%d3
    beq     .Lout
    eor.l   %d5,%d6
    move.b  %d6,%a2@(TYPE_FLAG_OFF)

    | and the worker's own mirror of that byte: (block + byte) - blob + MIRROR_DELTA
    suba.l  BLOB_PTR,%a2
    adda.l  #MIRROR_DELTA,%a2
    mvz.b   %a2@(TYPE_FLAG_OFF),%d6
    move.l  %d6,%d3
    and.l   %d5,%d3
    beq     .Ldirty                   | mirror already clear
    eor.l   %d5,%d6
    move.b  %d6,%a2@(TYPE_FLAG_OFF)

    | the dirty flags stock sets after every one of its own edits here
.Ldirty:
    movea.l BLOB_PTR,%a2
    adda.l  #DIRTY_IN_BLOB,%a2        | 0x9b332 exceeds ColdFire's 16-bit displacement
    moveq   #1,%d5
    move.l  %d5,%a2@
    move.l  %d5,DIRTY_GLOBAL
    jsr     NOTIFY
.Lout:
    rts
