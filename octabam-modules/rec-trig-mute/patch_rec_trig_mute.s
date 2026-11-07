| REC_TRIG_MUTE -- [TRACK]+[REC] toggles the held tracks' recorder trigs muted / unmuted.
|
| Scope, addresses and every proof: reference/handoffs/REC_TRIG_MUTE_SCOPE.md.
| The trigs stay in the pattern; the step handler simply stops seeing them, so a recording
| already running finishes its RLEN and nothing new starts.  Global across pattern / Part /
| bank changes, volatile (power-up = unmuted).  Each held track flips its own state.  While a
| track key is held, [REC] does not switch GRID REC; without one, [REC] is stock.  MIDI CC RTM_CC: value 0 =
| unmute, 1-127 = mute, received on the track's channel (AUTO channel = active track) and sent
| 1/0 on each held track's channel when the keys are used -- both gated by the project's
| AUDIO CC IN/OUT exactly like stock's CC 52/53.  Track tab: two dots stacked beside a muted
| track's machine letter, on its inner side (right of it on T1-4, left of it on T5-8), one blank
| pixel from the letter, the first level with its top row.  The status icon below is stock.
| [TRACK]+[YES]/[NO] are stock (ARM / DISARM REC TRK).
|
| No cave: the code reuses three stock routines nothing can reach (strict reference scan,
| stock + KYOTI, done by the builder on every build):
|   .main   0x40032bd4  an orphaned encoder value helper
|   .draw   0x4005a0e0  FUN_4005a0e0, the bare text popup (dead in stock)
|   .ccrx   0x4009e7dc  an orphaned arranger-row resolver ("ARR PARSE ERROR")
| The only runtime-written byte, RTM_MASK, lives in the proven-writable classic cave.

    .globl rtm_rec, rtm_trel, rtm_gate, rtm_dots, rtm_mark, rtm_cc

| OCTABAM_UNIT (--defsym; the octabam module octabam-modules/rec-trig-mute): one linked unit
| octabam places itself -- a single section, RTM_MASK inside it, the step-handler hook a plain
| jmp.  Without it this is the standalone / KYOTI layout, byte for byte.
    .ifdef OCTABAM_UNIT
    .macro SECT name
    .text
    .endm
    .else
    .macro SECT name
    .section \name,"ax"
    .endm
    .ifndef RTM_MASK                | the builder passes it: kyoti_place "rtm_mask"
    .equ RTM_MASK,  0x400d7c3a      | bit t = track t's recorder trigs muted (byte, image 0)
    .endif
    .equ RTM_TOAST, RTM_MASK+1      | 1 from our toast until the last track key is released
    .endif
    .equ RTM_CC,    80

    .equ HELD,      0x460fab40      | held track keys, bit t (physical keys, both modes)
    .equ REC_KEY,   0x40048774      | stock [REC] handler: GRID REC toggle, "REC held"
    .equ REC_HELD,  0x460d1726      | "REC held", set by its press, cleared by its release
    .equ NOTIFY,    0x4005a2b8      | FUN_4005a2b8(text, dur) -- key-handler context only
    .equ NOTIFY_CLOSE, 0x40056bec   | closes the toast (none open: returns) -- key handlers only
    .equ TOAST_DUR, 0x3c            | 1.0 s (60 ticks), QUANTIZE_LIVE_REC_TOGGLE's length
    .equ CC_SEND,   0x40033e3c      | FUN_40033e3c(track, cc, value): AUDIO CC OUT enqueue
    .equ CC_CHK,    0x40033970
    .equ CC_IN,     0x80000049      | project AUDIO CC IN
    .equ CC_EXIT,   0x4000f274      | CC handler epilogue
    .equ CC_NEXT,   0x4000f216      | CC 120-127 path
    .equ PLANE,     0x400bf10a
    .equ SETPIX,    0x40011830      | FUN_40011830(plane, x, y, value)
    .equ L_PICKUP,  0x4004014c      | letter renderer: PICKUP's own marks
    .equ L_JOIN,    0x400401c6      | letter renderer: active-tab inversion, then the next track
    .equ M_NEXT,    0x400448c0      | mark painter: the next track
    .equ PART_BASE, 0x46c82456      | -> the bank; + part * 6322 + 585122 + t = track t's machine
    .equ PART_IDX,  0x80000003

| ------------------------------------------------------------------ .main @ 0x40032bd4
| handler(keycode@4, event@8): the base keymaps' [REC] records (T1 0x400bfc3a, T2 0x400c061e,
| press + release fields) name stock's REC handler 0x40048774 -> repointed here.  The
| [TRACK]-held layer has no [REC] record, so with a track key held [REC] still reaches us.
    SECT .main
rtm_rec:
    move.l  HELD,%d1
    beq.s   0f                      | no track key held: stock [REC] (GRID REC toggle)
    tst.l   8(%sp)                  | press, as stock tests it
    bne.s   1f
    tst.b   RTM_TOAST               | release while our toast is up and a track key held:
    beq.s   0f
    clr.l   REC_HELD                | stock's whole release, minus any hook on it -- in KYOTI
    rts                             | QUANTIZE_LIVE_REC_TOGGLE's would close our toast here
0:  jmp     REC_KEY                 | every other event: stock (a release only clears "REC
                                    | held" -- we never set it on our press)
1:  mvz.b   RTM_MASK,%d0            | d0/d1/a0/a1 only: d2-d7 are the caller's
    eor.l   %d1,%d0                 | every held track flips its own state
    move.b  %d0,RTM_MASK
    move.l  %d0,%a0
    and.l   %d1,%d0                 | the held tracks muted now
    cmp.l   %d1,%d0
    beq.s   3f
    tst.l   %d0
    beq.s   2f
    move.l  #S_TOGGLED,%d0          | some muted, some unmuted
    bra.s   4f
2:  move.l  #S_UNMUTED,%d0
    bra.s   4f
3:  move.l  #S_MUTED,%d0
4:  move.l  %d0,4(%sp)              | NOTIFY's text, in our caller's frame
    move.l  %a0,%d0
    bsr.s   rtm_tx
    moveq   #1,%d0
    move.b  %d0,RTM_TOAST           | rtm_trel closes it when the track keys go up
    moveq   #TOAST_DUR,%d0          | tail-call NOTIFY(text, TOAST_DUR)
    move.l  %d0,8(%sp)
    jmp     NOTIFY

| step handler 0x4009d9a4: `jsr rtm_gate ; beq.s 0x4009da16 ; nop` replaces
| `tst.l %d3 ; beq.s 0x4009da16 ; move.l #0x91a,%d2`.  d3 = REC1/2/3 bits of track d7.
rtm_gate:
    move.l  #0x91a,%d2              | the displaced instruction
    moveq   #8,%d0
    cmp.l   %d0,%d7
    bcc.s   1f                      | audio tracks only
    mvz.b   RTM_MASK,%d0
    btst    %d7,%d0
    beq.s   1f
    moveq   #0,%d3                  | muted: this step has no recorder trig
1:  tst.l   %d3                     | rts keeps the CCR for the caller's beq
    .ifdef OCTABAM_UNIT                 | reached by jmp (octabam pads the 10 B with nops)
    bne.s   2f
    jmp     0x4009da16              | no recorder trig on this step
2:  jmp     0x4009d9ae              | muls.l %d7,%d2 and on
    .else
    rts
    .endif

| rtm_tx(d0 = new RTM_MASK, d1 = held mask): CC_SEND(t, RTM_CC, 1 muted / 0 unmuted) for
| every held track
rtm_tx:
    lea     -12(%sp),%sp
    movem.l %d2-%d4,(%sp)
    move.l  %d0,%d3
    move.l  %d1,%d4
    moveq   #0,%d2
1:  btst    %d2,%d4
    beq.s   2f
    moveq   #1,%d0
    btst    %d2,%d3
    bne.s   3f
    moveq   #0,%d0
3:  move.l  %d0,-(%sp)
    pea     RTM_CC
    move.l  %d2,-(%sp)
    jsr     CC_SEND
    lea     12(%sp),%sp
2:  addq.l  #1,%d2
    moveq   #8,%d0
    cmp.l   %d0,%d2
    blt.s   1b
    movem.l (%sp),%d2-%d4
    lea     12(%sp),%sp
    rts

| stock's mark painter 0x40044804 runs after both tab renderers on every UI pass (0x40052238) and,
| per track, sets or clears four pixels in the column beside the letter: x = 6 / 7 (active) on
| T1-4 -- rtm_dots' column -- and x = 127 / 126 on T5-8, at y = a2, a2+2, a2+3, a2+4 (its a2 =
| the letter's bottom row; lit -- a '!' -- when the voice runs with byte +3 set).  That cleared
| our top dot on T1-4 (hardware, 2026-11-07).  `jmp rtm_mark` replaces its per-track end `addq.l
| #1,%d4 ; lea 32(%sp),%sp`; on a muted, non-PICKUP T1-4 tab it writes the column again from
| a2+4 down: background, dot, background, dot, background, so the dots win over a lit '!'.
| d2 = x (6 + active), d3 = what stock wrote; both and a2 are reloaded by the painter's next pass.
rtm_mark:
    addq.l  #1,%d4                  | the displaced instructions
    lea     32(%sp),%sp
    moveq   #4,%d0
    cmp.l   %d4,%d0                 | d4 = t + 1 now: T5-8 untouched
    blt.s   9f
    move.l  %d5,-(%sp)              | the painter's caller's: kept
    moveq   #-1,%d5
    add.l   %d4,%d5                 | d5 = t
    mvz.b   RTM_MASK,%d0
    btst    %d5,%d0
    beq.s   8f
    mvz.b   PART_IDX,%d0            | the letter renderer's machine byte (0x4004009a)
    mulu.w  #6322,%d0
    add.l   PART_BASE,%d0
    add.l   %d5,%d0
    move.l  %d0,%a0
    adda.l  #585122,%a0
    mvs.b   (%a0),%d0
    moveq   #4,%d1
    cmp.l   %d0,%d1                 | PICKUP: no dots, stock's marks stand
    beq.s   8f
    move.l  %d2,%d3
    subq.l  #6,%d3                  | background: 0 on a tab, 1 on the active (filled) one
    move.l  %a2,%d5                 | the last row, a2+0
    addq.l  #5,%a2
1:  subq.l  #1,%a2                  | a2+4 .. a2+0
    move.l  %d3,-(%sp)
    move.l  %a2,-(%sp)
    move.l  %d2,-(%sp)
    pea     PLANE
    jsr     (%a3)                   | the painter's SETPIX (0x40011830); keeps d2-d5, a2-a4
    lea     16(%sp),%sp
    moveq   #1,%d0
    eor.l   %d0,%d3                 | background, dot, background, dot, background
    cmp.l   %a2,%d5
    bne.s   1b
8:  move.l  (%sp)+,%d5
9:  jmp     M_NEXT

| ------------------------------------------------------------------ .draw @ 0x4005a0e0
| letter renderer 0x4003fed8 (audio mode; it redraws every tab's letter cell on every UI poll, so
| the dots are cleared, redrawn and inverted with the letter): `jmp rtm_dots` replaces `moveq #4,%d0
| ; cmpl %a4,%d0 ; bnes L_JOIN`.  d3 = letter x (2 / 123, one pixel inward on the active tab),
| d4 = track, a2 = cell y (the 3x4 letter spans a2+1 .. a2+4, top row a2+4; y counts upward),
| a4 = machine.  d2 is free here (stock's PICKUP path reloads it).  PICKUP keeps its own marks.
    SECT .draw
rtm_dots:
    moveq   #4,%d0
    cmp.l   %a4,%d0
    bne.s   1f
    jmp     L_PICKUP
1:  mvz.b   RTM_MASK,%d0
    btst    %d4,%d0
    beq.s   9f
    moveq   #4,%d2                  | T1-4: x+3 blank, dots at x+4
    moveq   #3,%d0
    cmp.l   %d4,%d0
    bge.s   2f
    moveq   #-2,%d2                 | T5-8: x-1 blank, dots at x-2
2:  add.l   %d3,%d2
    pea     1.w
    pea     4(%a2)                  | level with the letter's top row
    move.l  %d2,-(%sp)
    pea     PLANE
    jsr     SETPIX
    pea     1.w
    pea     2(%a2)                  | one blank row, then the second dot
    move.l  %d2,-(%sp)
    pea     PLANE
    jsr     SETPIX
    lea     32(%sp),%sp
9:  jmp     L_JOIN

| ------------------------------------------------------------------ .ccrx @ 0x4009e7dc
| CC handler 0x4000f210: `jmp rtm_cc` replaces `moveq #119,%d6 ; cmp.l %d1,%d6 ; bge CC_EXIT`
| (the fall-through of every CC stock ignores).  d1 = CC#, a2 = msg (value at +2),
| d7 = channel -> track mask (bit 8 = AUTO), tracks d5 .. a4-1 (set at 0x4000e8fe..e91a).
| Gating and loop are stock's CC 52/53 (0x4000ed90..0x4000ee0c) one for one.
    SECT .ccrx
rtm_cc:
    moveq   #RTM_CC,%d0
    cmp.l   %d1,%d0
    beq.s   1f
    moveq   #119,%d6                | replay the displaced compare
    cmp.l   %d1,%d6
    bge.s   9f
    jmp     CC_NEXT
1:  jsr     CC_CHK
    tst.l   %d0
    beq.s   2f
    btst    #8,%d7
    bne.s   9f
2:  tst.b   CC_IN
    beq.s   9f
    mvz.b   RTM_MASK,%d0
    bra.s   6f
3:  btst    %d5,%d7
    beq.s   5f
    tst.b   2(%a2)
    ble.s   4f
    bset    %d5,%d0
    bra.s   5f
4:  bclr    %d5,%d0
5:  addq.l  #1,%d5
6:  cmp.l   %a4,%d5
    blt.s   3b
    move.b  %d0,RTM_MASK
9:  jmp     CC_EXIT

| track-key release 0x40083e40, at 0x40083e84: `jsr rtm_trel` replaces `and.l %d0,HELD` (d0 =
| ~(1 << t)).  Once no track key is held, our toast closes, as QUANTIZE_LIVE_REC_TOGGLE's closes
| on [REC] release.  Key-handler context, so NOTIFY_CLOSE is legal; d0/d1/a0/a1 are free here
| (the caller reloads d0 next), d2-d4 are callee-saved by NOTIFY_CLOSE.
rtm_trel:
    and.l   %d0,HELD                | the displaced instruction
    bne.s   9f                      | a track key is still held
    tst.b   RTM_TOAST
    beq.s   9f                      | not our toast
    clr.b   RTM_TOAST
    jmp     NOTIFY_CLOSE            | returns at once if it has already timed out
9:  rts

S_MUTED:   .asciz "REC TRIGS MUTED"
S_UNMUTED: .asciz "REC TRIGS UNMUTED"
S_TOGGLED: .asciz "REC TRIGS TOGGLED"

    .ifdef OCTABAM_UNIT                 | in .text, right after the code: the unit lives in DRAM,
RTM_MASK: .byte 0                   | so it is writable; a .data section would sit 8 KB past
RTM_TOAST: .byte 0                  | the code (ld's default) -- Sam, octabam PR #566
    .even
    .endif
