| SPDX-License-Identifier: MIT
| SPDX-FileCopyrightText: 2026 Zac-Kyoti
| patch_triglock -- Section 13 (NOTES.md): a trigless lock (a step holding p-locks and no
| trig) whose last remaining p-lock is erased stays lit on the 16-step trig row forever.
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
| DETOUR (6 B @ 0x40038a5c): the stock `moveb %d1,%a0@(0x59,%d2:l) ; addl %d4,%d0`. The
| cave replays both before its own `rts`.
|
| Registers there, read straight from the disassembly:
|   a0 = blob + pattern*0x8ed8 + track*0x91a + step*32   (so the `#1` row base is a0+0x59,
|        and TRAC is a0 - d4)
|   d2 = param index      d1 = 0xFF (the sentinel about to be stored)
|   d4 = step*32          d7 = track      a3 = step
|
| NOTE on 0x40038af8, the instruction that looked like the natural hook: its second half
| `addql #1,%d7` is the enclosing loop's INCREMENT, and 0x40038afc is a branch target from
| 0x400388a4 and 0x40038a1a (the skip-this-track paths). A 6-byte detour there swallows it
| and the loop never terminates -- that build hung in the emulator. build_triglock.py now
| refuses any detour whose displaced bytes contain a branch target.
|
| GUARDS, and how they satisfy Session 13
|   - the step must not be owned by any real trig: note/sample TRAC+0x00, the other two
|     trig-type layers +0x08/+0x18, and the three recorder-trig masks +0x20/+0x28/+0x30, so
|     a trigless TRIG that retrigs an LFO, and sample/MIDI/one-shot/recorder/slide trigs,
|     are never touched.
|   - TRAC+0x10's bit must actually be set, i.e. this really is a trigless lock. (With
|     clear_trigs set, stock has already cleared that bit itself, so this no-ops.)
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
| ColdFire (5407) notes: byte-sized register-register ALU ops are unavailable, so mask
| tests zero-extend a byte via MOVE.B and do the logic in .l. MOVEM has no predecrement
| form, so the save/restore adjusts %sp by hand. a4/a5 are never touched.
|
| Assemble like the other stubs: m68k-elf-as -mcpu=5407 ; ld -Ttext=<cave> ; objcopy -O binary

    .equ  PLOCK_OFF,     0x59          | `#1` within TRAC: 64 steps x 32 bytes
    .equ  TYPE_FLAG_OFF, 0x10          | the trig-type layer carrying the trigless-lock bit
    .equ  PAT_STRIDE,    0x8ed8
    .equ  TRK_STRIDE,    0x91a
    .equ  CUR_PATTERN,   0x100b14d0    | the pattern FUN_40038874 itself indexes by
    .equ  MIRROR_BASE,   0x1001615e    | this function's own mirror of that layer
    .equ  BLOB_PTR,      0x46c82456
    .equ  DIRTY_GLOBAL,  0x100f8598
    .equ  DIRTY_IN_BLOB, 0x9b332
    .equ  NOTIFY,        0x40027e00    | stock calls this after each of its own edits here

    .text
    .global cave
cave:
    lea     %sp@(-48),%sp
    moveml  %d0-%d7/%a0-%a3,%sp@

    | ---- was this param ACTUALLY locked a moment ago? ----
    | The store at 0x40038a5c is unconditional, so a gesture aimed at a never-locked param
    | reaches here too. If the old value is already the 0xFF sentinel then nothing is being
    | erased -- a FUNC+TRIG placeholder, or an untouched param -- and it must survive.
    clr.l   %d0
    move.b  %a0@(PLOCK_OFF,%d2:l),%d0
    addq.l  #1,%d0
    and.l   #0xff,%d0                 | (old+1)&0xff == 0  <=>  old == 0xFF
    beq     .Lout

    | ---- was it the LAST one? every OTHER byte of #1[step] must already be 0xFF ----
    lea     %a0@(PLOCK_OFF),%a1       | a1 = the row base
    clr.l   %d3                       | d3 = index 0..31
.Lscan:
    move.l  %d3,%d5
    sub.l   %d2,%d5
    beq     .Lnext                    | skip the param this store is erasing
    clr.l   %d5
    move.b  %a1@(0,%d3:l),%d5
    addq.l  #1,%d5
    and.l   #0xff,%d5
    bne     .Lout                     | another param is still locked -- keep the step lit
.Lnext:
    addq.l  #1,%d3
    moveq   #32,%d5
    cmp.l   %d3,%d5
    bne     .Lscan

    | ---- this store empties the row. TRAC = a0 - step*32 ----
    movea.l %a0,%a1
    suba.l  %d4,%a1                   | a1 = TRAC (d4 still holds step*32 here)

    | ---- mask addressing: byte = 7-(step>>3), bit = 1<<(step&7) ----
    move.l  %a3,%d5                   | step
    move.l  %d5,%d6
    lsr.l   #3,%d6
    moveq   #7,%d3
    sub.l   %d6,%d3                   | d3 = byte index
    and.l   #7,%d5
    moveq   #1,%d6
    lsl.l   %d5,%d6                   | d6 = bit mask
    movea.l %a1,%a2
    adda.l  %d3,%a2                   | a2 = TRAC + byte index

    | ---- refuse if ANY real trig owns this step ----
    clr.l   %d5
    move.b  %a2@(0x00),%d5            | note / sample trig
    and.l   %d6,%d5
    bne     .Lout
    clr.l   %d5
    move.b  %a2@(0x08),%d5            | trig-type layer A
    and.l   %d6,%d5
    bne     .Lout
    clr.l   %d5
    move.b  %a2@(0x18),%d5            | trig-type layer C
    and.l   %d6,%d5
    bne     .Lout
    clr.l   %d5
    move.b  %a2@(0x20),%d5            | recorder trig 1
    and.l   %d6,%d5
    bne     .Lout
    clr.l   %d5
    move.b  %a2@(0x28),%d5            | recorder trig 2
    and.l   %d6,%d5
    bne     .Lout
    clr.l   %d5
    move.b  %a2@(0x30),%d5            | recorder trig 3
    and.l   %d6,%d5
    bne     .Lout

    | ---- and it must really BE a trigless lock ----
    clr.l   %d5
    move.b  %a2@(TYPE_FLAG_OFF),%d5
    and.l   %d6,%d5
    beq     .Lout

    | ---- clear it (bit known set, so EOR is an exact clear) ----
    clr.l   %d5
    move.b  %a2@(TYPE_FLAG_OFF),%d5
    eor.l   %d6,%d5
    move.b  %d5,%a2@(TYPE_FLAG_OFF)

    | ---- and this function's own mirror of that layer:
    | ---- MIRROR_BASE + pattern*0x8ed8 + track*0x91a + byte index ----
    clr.l   %d5
    move.b  CUR_PATTERN,%d5
    move.l  #PAT_STRIDE,%d0
    muls.l  %d0,%d5
    move.l  %d7,%d0
    move.l  #TRK_STRIDE,%d1
    muls.l  %d1,%d0
    add.l   %d0,%d5
    add.l   #MIRROR_BASE,%d5
    movea.l %d5,%a2
    adda.l  %d3,%a2
    clr.l   %d5
    move.b  %a2@,%d5
    and.l   %d6,%d5
    beq     .Ldirty                   | mirror already clear
    clr.l   %d5
    move.b  %a2@,%d5
    eor.l   %d6,%d5
    move.b  %d5,%a2@

    | ---- the dirty flags stock sets after every one of its own edits here ----
.Ldirty:
    movea.l BLOB_PTR,%a2
    adda.l  #DIRTY_IN_BLOB,%a2        | 0x9b332 exceeds ColdFire's 16-bit displacement
    moveq   #1,%d5
    move.l  %d5,%a2@
    movea.l #DIRTY_GLOBAL,%a2
    move.l  %d5,%a2@
    jsr     NOTIFY

.Lout:
    moveml  %sp@,%d0-%d7/%a0-%a3
    lea     %sp@(48),%sp
    move.b  %d1,%a0@(PLOCK_OFF,%d2:l) | the displaced stock instructions, verbatim
    add.l   %d4,%d0
    rts
