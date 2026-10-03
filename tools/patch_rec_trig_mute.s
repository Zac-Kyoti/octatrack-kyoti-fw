| REC_TRIG_MUTE -- [TRK]+[NO] mutes / [TRK]+[YES] unmutes the held tracks' recorder trigs.
|
| Scope, addresses and every proof: reference/handoffs/REC_TRIG_MUTE_SCOPE.md.
| The trigs stay in the pattern; the step handler simply stops seeing them, so a recording
| already running finishes its RLEN and nothing new starts.  Global across pattern / Part /
| bank changes, volatile (power-up = unmuted).  MIDI CC RTM_CC: value 0 = unmute, 1-127 =
| mute, received on the track's channel (AUTO channel = active track) and sent 1/0 on each
| held track's channel when the keys are used -- both gated by the project's AUDIO CC IN/OUT
| exactly like stock's CC 52/53.  Track-edge status glyph: "..[]" / "..>" on every muted
| track that is not recording.
|
| No cave: the code reuses four stock routines nothing can reach (strict reference scan,
| stock + KYOTI, done by the builder on every build):
|   .keys   0x40083488  stock [TRK]-layer NO/YES handlers (NO keeps its entry, YES is repointed)
|   .draw   0x4005a0e0  FUN_4005a0e0, the bare text popup (dead in stock)
|   .glyph  0x40032bd4  an orphaned encoder value helper
|   .ccrx   0x4009e7dc  an orphaned arranger-row resolver ("ARR PARSE ERROR")
| The only runtime-written byte, RTM_MASK, lives in the proven-writable classic cave.

    .globl rtm_no, rtm_yes, rtm_gate, rtm_glyph, rtm_draw, rtm_cc

    .equ RTM_MASK,  0x400d7c3a      | bit t = track t's recorder trigs muted (byte, image 0)
    .equ RTM_CC,    80

    .equ HELD,      0x460fab40      | held track keys, bit t (physical keys, both modes)
    .equ NOTIFY,    0x4005a2b8      | FUN_4005a2b8(text, dur) -- key-handler context only
    .equ CC_SEND,   0x40033e3c      | FUN_40033e3c(track, cc, value): AUDIO CC OUT enqueue
    .equ CC_CHK,    0x40033970
    .equ CC_IN,     0x80000049      | project AUDIO CC IN
    .equ CC_EXIT,   0x4000f274      | CC handler epilogue
    .equ CC_NEXT,   0x4000f216      | CC 120-127 path
    .equ CACHE,     0x400c0cb8      | the edge renderer's per-track state cache
    .equ PLANE,     0x400bf10a
    .equ MASK7,     0x400c514e      | stock "+>" glyph's 7-column opaque mask
    .equ R_GO,      0x4004c012      | renderer: a4 == 3 ("+>") draw
    .equ R_BLIT,    0x4004c024      | renderer: jsr (a5) + lea 16(sp)
    .equ R_SKIP,    0x4004c02a      | renderer: nothing to draw

| ------------------------------------------------------------------ .keys @ 0x40083488
| handler(keycode@4, event@8), reached through the [TRK]-held layer records: NO (0x400d15fc)
| keeps naming 0x40083488 = rtm_no; the builder repoints YES (0x400d15e2) at rtm_yes.
    .section .keys,"ax"
rtm_no:
    moveq   #1,%d0
    cmp.l   8(%sp),%d0              | press only
    bne.s   9f
    move.l  HELD,%d1
    beq.s   9f
    mvz.b   RTM_MASK,%d0
    or.l    %d1,%d0
    move.b  %d0,RTM_MASK
    moveq   #1,%d0
    bsr.s   rtm_tx
    move.l  #S_MUTED,%d0
toast:                              | tail-call NOTIFY(text, 0x30) in our caller's frame
    move.l  %d0,4(%sp)
    moveq   #0x30,%d0
    move.l  %d0,8(%sp)
    jmp     NOTIFY
9:  rts

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
    rts

rtm_yes:
    moveq   #1,%d0
    cmp.l   8(%sp),%d0
    bne.s   9b
    move.l  HELD,%d1
    beq.s   9b
    mvz.b   RTM_MASK,%d0            | d0/d1/a0/a1 only: d2-d7 are the caller's
    not.l   %d1
    and.l   %d1,%d0
    not.l   %d1                     | held mask again, for rtm_tx
    move.b  %d0,RTM_MASK
    moveq   #0,%d0
    bsr.s   rtm_tx
    move.l  #S_UNMUTED,%d0
    bra.s   toast

| rtm_tx(d0 = value, d1 = held mask): CC_SEND(t, RTM_CC, value) for every held track
rtm_tx:
    lea     -12(%sp),%sp
    movem.l %d2-%d4,(%sp)
    move.l  %d0,%d3
    move.l  %d1,%d4
    moveq   #0,%d2
1:  btst    %d2,%d4
    beq.s   2f
    move.l  %d3,-(%sp)
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

| ------------------------------------------------------------------ .glyph @ 0x40032bd4
| renderer 0x4004bee2: `jsr rtm_glyph` replaces `lea CACHE,%a0`.  d3 = track, a4 = state
| (d2 + 2*d1 + 4*d0; bit 0 = playing, bit 1 = recorder live).  A muted track that is not
| recording -> a4 = 8 | playing, shown as "..[]" / "..>" whether or not it has recorder trigs
| (user, 2026-10-02).  Folding it into a4 lets the stock cache redraw on every toggle.
    .section .glyph,"ax"
rtm_glyph:
    mvz.b   RTM_MASK,%d0
    btst    %d3,%d0
    beq.s   8f
    move.l  %a4,%d0
    btst    #1,%d0                  | recorder live: the true "+" wins until it ends
    bne.s   8f
    moveq   #1,%d1
    and.l   %d1,%d0
    addq.l  #8,%d0
    move.l  %d0,%a4
8:  lea     CACHE,%a0
    rts

    .balign 4
G_DOTSS: .long 0x20000000,0,0x20000000,0,0x70000000,0x70000000,0x70000000 | . . []
G_DOTSP: .long 0x20000000,0,0x20000000,0,0xf8000000,0x70000000,0x20000000 | . . >
S_MUTED:   .asciz "REC TRIGS MUTED"
S_UNMUTED: .asciz "REC TRIGS UNMUTED"

| ------------------------------------------------------------------ .draw @ 0x4005a0e0
| renderer 0x4004c00c: `jmp rtm_draw` replaces `moveq #3,%d0 ; cmpl %a4,%d0 ; bnes R_SKIP`
| a3 = box x, a2 = row offset, a5 = the blit 0x400128a8(desc, plane, x, y)
    .section .draw,"ax"
rtm_draw:
    move.l  %a4,%d0
    moveq   #3,%d1
    cmp.l   %d0,%d1
    bne.s   1f
    jmp     R_GO
1:  lea     D_DOTSS,%a0             | 8: muted, idle    "..[]"
    subq.l  #8,%d0
    beq.s   2f
    lea     D_DOTSP,%a0             | 9: muted, playing "..>"
    subq.l  #1,%d0
    beq.s   2f
    jmp     R_SKIP
2:  pea     49(%a2)
    move.l  %a3,-(%sp)              | 7 wide, at x like stock's "+>"
    pea     PLANE
    move.l  %a0,-(%sp)
    jmp     R_BLIT

    .balign 4
D_DOTSS: .long 7,5,1,G_DOTSS,MASK7
D_DOTSP: .long 7,5,1,G_DOTSP,MASK7

| ------------------------------------------------------------------ .ccrx @ 0x4009e7dc
| CC handler 0x4000f210: `jmp rtm_cc` replaces `moveq #119,%d6 ; cmp.l %d1,%d6 ; bge CC_EXIT`
| (the fall-through of every CC stock ignores).  d1 = CC#, a2 = msg (value at +2),
| d7 = channel -> track mask (bit 8 = AUTO), tracks d5 .. a4-1 (set at 0x4000e8fe..e91a).
| Gating and loop are stock's CC 52/53 (0x4000ed90..0x4000ee0c) one for one.
    .section .ccrx,"ax"
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
