| SPDX-License-Identifier: MIT
| SPDX-FileCopyrightText: 2026 Zac Kyoti
|
| CLYPS (reference/handoffs/CLYPS_SCOPE.md): Clyps mode, the Clyps view (2 x 8 table of the active
| track's sequence in each pattern of a bank) and the Clyps grid (trig LEDs), with the held /
| latched states of scope §1.1. A load copies the source track record into the playing pattern:
| at once when stopped, cued while running (§1.5a). Saved sequences ([FUNC]+[YES] / [FUNC]+[NO],
| §1.6). Originals (§1.5, redefined by the user 2026-10-26): a track's original is what it held when
| its bank was last loaded (power-on, LOAD PROJECT, a reload); Clyps snapshots every bank as it is
| loaded, and the ORIG entry / [PAGE] / [FUNC]+[PAGE] put a track back from that snapshot.
|
| Calling conventions (stock, C): args on the stack, caller pops; d0-d1/a0-a1 scratch,
| d2-d7/a2-a6 preserved. Key handlers are called as handler(code@4, event@8):
| event 1 = press, 2 = hold/repeat, 0 = release.
|
| State lives in this blob (it runs from RAM), never in 0x80006a40+ (CLAUDE.md).

| ---------------------------------------------------------------- stock addresses (scope §3)
    .equ PLAY_BANK,   0x800065bd        | the PLAYED bank (pair with ACT_PAT, RELOAD S92)
    .equ ACT_PAT,     0x800065be
    .equ UI_BANK,     0x80000002        | the bank the SRAM mirror holds
    .equ CUR_TRACK,   0x80000000        | active track 0..7
    .equ MIDI_MODE,   0x80000012        | LONG, != 0 -> MIDI tracks (stock: tst.l / clr.l / move.l;
                                        | a byte read sees its high byte, always 0 -- the CLYP6 bug)
    .equ BLOB,        0x400e21e0
    .equ BANKSTRIDE,  0x9b340
    .equ PATSTRIDE,   0x8ed8
    .equ TRAC_A,      0x91a
    .equ MIDI_BASE,   0x48d0
    .equ TRAC_M,      0x8b0
    .equ SRAM_PAT,    0x1001614e        | SRAM mirror of the UI bank's 16 slabs
    .equ TRAILER,     0x8e50            | slab + 0x8e50: the pattern trailer (beyond d16 range,
    .equ T_MLEN,      0                 | so it is addressed through a register)
    .equ T_MSCALE,    2                 | u16 master length at +0 (-1 = INF)
    .equ T_LEN,       3
    .equ T_SCALE,     4
    .equ T_SMODE,     5                 | 0 = NORMAL
    .equ T_PART,      7                 | the pattern's Part 0..3 (slab + 0x8e57)
| FULL loads (scope §1.7): one track's Part slice, applied for that track only
    .equ PART_OFF,    0x8ed80           | a bank's 4 Parts, after its 16 slabs
    .equ PARTSZ,      0x18b2
    .equ SRAM_PART,   0x100a4ece        | the SRAM mirror's Parts (SRAM_PAT + PART_OFF)
    .equ PEDIT,       0x95048           | bank + : byte, bit p = Part p edited (stock's paste)
    .equ PEDIT_S,     0x100b145e        | ... its SRAM copy
    .equ PSAVED,      0x9b312           | bank + part: != 0 = the Part has a SAVE PART copy
    .equ PSAVECPY,    0x9504a           | bank + part * PARTSZ: the SAVE PART copies
    .equ BDIRTY,      0x9b332           | bank + : long 1 = the bank has changed
    .equ DIRTY2,      0x100f8598        | long 1 (stock's paste sets it with the two above)
    .equ TRK_APPLY,   0x40001f18        | (bank, part, t): one audio track's Part values -> the engine
                                        | (engine state + memcpy only: tick-safe)
    .equ ENG_RESTART, 0x8000184c        | byte, bit t: restart the voice (a new machine, 0x400973b4)
    .equ PICKUP_SET,  0x40097290        | stock's PICKUP setup after a machine change (UI context)
    .equ MENG,        0x46c76dc0        | 8 x 68 B: a MIDI track's page values (32) + setup (36)
    .equ MDES,        0x46c7738c        | 24 x 16 B: the MIDI LFOs' designer waves
    .equ MSLP,        0x46c7750c        | 24 x u16: ... their slopes
    .equ MBANK,       0x8000666e        | byte[8] bank / [8+m] Part the MIDI track's values came from
    .equ MZERO,       0x8000664e        | long[8], cleared by stock's apply
| stock's UI refresh after a Part change (the tail of its Part-reload shortcut, 0x4005e0a8)
    .equ PR_A,        0x4004d948        | (-1)
    .equ PR_B,        0x40032208
    .equ PR_C,        0x4004d640
    .equ PR_D,        0x400486cc
    .equ PR_E,        0x4006dbe8
    .equ PR_F,        0x40077b00
    .equ PR_G,        0x4002f2f8
    .equ HELD_BASE,   0x46c7d8ee        | is_key_held(code) = (0x46c7d8ee + code*24) != 0
    .equ FUNC_HELD,   0x46c7dd26        | code 0x2d
    .equ PTN_HELD,    0x46c7dd3e        | code 0x2e
    .equ BANK_HELD,   0x46c7dd56        | code 0x2f
    .equ PTN_CONSUMED,0x460d173e        | !=0 on [PTN] release -> teardown only, no window
    .equ BANK_SEL,    0x460e73c6        | 2 -> [BANK] release takes the (no-op) dismiss
    .equ WIN_SLOT,    0x460d1e5c        | SHOW_WIN popup handle (SELECT BANK lives here)
    .equ WIN_ONCLOSE, 0x460d1e60
    .equ BANK_TEARDOWN,0x4007b408       | SELECT BANK's onClose: pops its layers
    .equ DISMISS,     0x40056a70        | dismiss the SHOW_WIN popup (runs its onClose)
    .equ BANK_TAP,    0x460e73c2        | [BANK] "tap eligible": set on press (unless latched), hold
    .equ BANK_PICK,   0x460e73b8        | the bank a [BANK] + trig picked (BANK_SEL 1)
    .equ BANK_LATCH,  0x460e73bc        | SELECT BANK latched (a tap's release)
    .equ BANK_LAYER,  0x400cff14        | [BANK]'s keymap layer: the trigs pick a bank, then a pattern
    .equ BANK_LEDL,   0x400cff28        | ... and its LED layer
    .equ SHOW_WIN,    0x40059f8c        | (title, ticks, sticky, onClose): the SELECT window
    .equ BANK_TITLE,  0x400b7302        | "SELECT BANK"
    .equ WIN_STICKY,  0x40031200        | the SHOW_WIN window stays (no countdown)
    .equ PTN_LAYER,   0x400bf0f2        | stock [PTN]'s keymap layer (trigs pick a pattern)
    .equ PTN_LEDL,    0x400bebfe        | ... and its LED layer
    .equ PAT_HASDATA, 0x4009a464        | (pattern, bank) -> != 0: stock lights it green
    .equ PAGE_PAINT,  0x4004d1a8        | stock's LED slot 7: the 4 page LEDs (the step indicator)
| the page LEDs: LED k (0..3) = red die 0x48 + 2k, green = + 1
    .equ ARR_ACT,     0x460d1aec        | arranger running
    .equ POPUP,       0x460e5cd0        | a blocking MLNOTIFY dialog is up
    .equ LAYER_PUSH,  0x40031494
    .equ LAYER_POP,   0x4003146c
    .equ LED_PUSH,    0x4007e760
    .equ LED_POP,     0x4007e81c
    .equ LED_PAINT,   0x4007e998        | (slot) repaint + flush
    .equ LED_TBL,     0x400a74ce        | trig n red die id (long); green = +1
    .equ LED_BRI,     0x400135b0        | (id, 0..15)
    .equ LED_ON,      0x400131a0        | (id)
    .equ LED_OFF,     0x400131c8        | (id)
    .equ WIN_NEW,     0x4005829c        | (w, h, dx, dy, prio, close_cb) -> win or 0
    .equ WIN_DEL,     0x40055db4        | (&handle): destroy, RDRAW, handle = 0
    .equ RECT,        0x40012254        | (surf, x0, y0, x1, y1, mode) 0 clear, -1 xor
    .equ TEXT,        0x40012bd8        | (font, surf, x, y, mode, str)
    .equ FONT,        0x400ba876
    .equ SPRINTF,     0x40013a08
    .equ RDRAW,       0x46c7c72c
    .equ MEMCPY,      0x40020898        | (dst, src, n)
    .equ SEQ_DIRTY,   0x40029b9c        | (t 0..7): dirty flags + refresh, as stock's undo-restore
    .ifndef TRK_BASE
    .equ TRK_BASE,    0x40040250        | stock base TRACK handler (press, release, hold). In an image
    .endif                              | with RELOAD_FROM_PROJECT's detour there, point it at a stub
    .equ FUNC_PRESS,  0x4004e954        | stock [FUNC] press (sets 0x46c7c730)
    .equ FUNC_REL,    0x400568e4        | stock [FUNC] release
    .equ PTN_RESUME,  0x4005a04a        | after `move.l 8(sp),d0 ; moveq #1,d1`
    .equ BANKP_RESUME,0x4007af86        | after `tst.l 0x460e73bc`
    .equ BANKR_RESUME,0x4007b3e8        | after `moveq #2,d0 ; cmp.l 0x460e73c6,d0`
    .equ RUNNING,     0x800065b8        | long: 1 while the transport runs
    .equ PEND_BANK,   0x800065bf
    .equ PEND_PAT,    0x800065c0
    .equ MASTER_STEP, 0x800065b2        | u16: the master step, ++ at each master tick 0
    .equ CHAIN_ACT,   0x80006546        | long != 0: a pattern chain runs (DIRECT JUMP stays out)
    .equ ARR_ACT,     0x460d1aec        | long != 0: the arranger runs (DIRECT JUMP stays out)
    .equ TICK_CTR,    0x800065b6        | byte: master ticks within the step
    .equ SCALE_IX,    0x8000663d        | byte: the live master scale index
    .equ LEN_TBL,     0x400aba50        | long[scale]: ticks per step (2 = 1x = 6)
    .equ QUANT_TBL,   0x400d80dc        | long[17]: CHAIN AFTER lengths in steps, [0] = -1 (off)
    .equ PROJ_QUANT,  0x8000004e        | byte: the project default CHAIN AFTER index
    .equ STEP_ARR,    0x800064d0        | byte[16]: per-track step   (audio 0..7, MIDI 8..15)
    .equ STEPM1_ARR,  0x800064e0        | byte[16]: per-track step - 1 (mod len)
    .equ TICKS_ARR,   0x800064f0        | byte[16]: per-track ticks within the step
    .equ TSCALE_ARR,  0x8000663e        | byte[16]: per-track scale cache
    .equ LAND_RESUME, 0x400a1f78        | after `move.b 0x80006687,%d0` (stock's ble.w follows)
    .equ UIT_RESUME,  0x40062d22        | after `tst.l 0x46c7c72c` (stock's beq.w follows)
    .equ WRAP_RESUME, 0x400a43a6        | after `move.l (a2),d0 ; moveq #1,d2 ; or.l d2,d0`
    .equ PRIO,        0                 | WIN_NEW(prio p) evicts every window with prio >= p (0x4005829c):
                                        | at 0, stock's menus (the Parts menu: 1), SELECT windows (10),
                                        | toasts and the name editor (5) all open over Clyps and leave
                                        | it there (the user, 2026-10-29: Parts over Clyps). Was 3.
    .equ FL_TICKS,    30                | the load confirmation: 30 UI ticks of 1/60 s = 0.5 s (the user,
    .equ FL_HALF,     5                 | 2026-10-30), its phase toggling every 5 ticks: 3 inverted /
                                        | normal cycles (6 Hz)
    .equ TOAST_T,     0x460d1e6c        | stock's toast countdown, read by the UI tick 0x40056c28
    .equ UITICK_RES,  0x40056c2e        | after `move.l 0x460d1e6c,%d0` (stock's beq follows)
    .equ CL_BLINK,    30                | the flash period: stock's trig LED tick (0x400340e4, period 30)
    .equ LED_FLASH,   0x40013784        | (die, n): invert the die for n LED ticks -- stock's p-lock
                                        | flash: its trig tick gives a locked trig's green die 3 ticks
                                        | every period, so the red trig blinks yellow
    .equ CUE_TRK,     0x40083dc4        | stock [CUE] + TRACK: cue toggle
    .equ TRK_SELECT,  0x40083bf8        | (t 0..7): select track t on the side you are on (the TRACK
                                        | release's 0x40083e40 calls it)
    .equ RSETUP_WIN,  0x460d10cc        | the Recording Setup menu's window (0 = closed; opener 0x4002fec4)
    .equ ARM_REC,     0x400834d8        | stock ARM REC TRK (TRACK + [YES]), DISARM REC TRK (+ [NO])
    .equ DISARM_REC,  0x40083488
    .equ SEL_PEND,    0x460fab44        | a TRACK press's "select on release" (0x40083e40 tests + clears it)
    .equ HELD_TRK,    0x460fab40        | held TRACK keys, bit t (stock's TRACK press / release)
    .equ LAYERS_HEAD, 0x460d165c        | the keymap layer chain: base first, then each pushed layer
    .equ TOAST,       0x4005a2b8        | (text, dur): stock's block toast (legal from a key handler)
    .equ TOAST_DUR,   0x30              | stock's standard duration
    .equ SCLK,        0x4610757c        | the audio engine's time accumulator: ~127 M units / s
                                        | (2880 per sample at 44.1 kHz, measured in the emulator)
    .equ TEXT_EDIT,   0x4007e664        | (maxchars, title, buf, layout, done_cb(confirmed)): stock's name
                                        | editor (RENAME PART, project naming: layout 0 = the full one);
                                        | its window is prio 5, so the Clyps view (3) stays under it.
                                        | maxchars = the characters it lets you type: the cursor stops at
                                        | maxchars - 1 (0x4007e57e), and [YES] writes maxchars + 1 bytes
                                        | back (0x4007e3a4; RENAME PART: 6 into 7-byte names)
| names on the card: per bank, <project>/clypsNN.work and clypsNN.strd (NN 01..16), kept in step
| with stock's own bankNN.work / .strd -- written, copied, restored, deleted and exported with them.
| All of it runs in stock's project worker task (0x4008445c, prio 1), where stock does its own bank
| file I/O; every error of ours is swallowed, never stock's result. Facts: research 2026-10-27
| (scope §10.2).
    .equ FOPEN,       0x40016864        | (h, path, mode, buf, bufsize) -> 1 / < 0 (-12 missing)
    .equ FREAD,       0x40016564        | (h, dst, n) -> 1 / 0 EOF / < 0
    .equ FWRITE,      0x400166b8        | (h, src, n) -> 1 / < 0
    .equ FCLOSE,      0x4001677c        | (h) -> 1 / < 0; "w": the file gets exactly what was written
    .equ FCOPY,       0x40016388        | (dst, src, allow_empty) -> 1 / -12 src missing; unlinks dst
    .equ FS_SIZE,     0x46c8241e        | -> size(fd)
    .equ FS_UNLINK,   0x46c82432        | -> unlink(path)
    .equ PROJDIR,     0x40025230        | (0, 0) -> "<set>/<project>" (a static buffer: use at once)
    .equ FBUF,        0x460a8f60        | the worker's 64 KB file buffer (free at our hook points)
    .equ FBUFSZ,      4096
    .equ S_R,         0x400b3289        | "r"
    .equ S_W,         0x400b328b        | "w"
    .equ DEL_ONE,     0x4008ec08        | DELETE PROJECT's own (file), a1 = its context: unlink if present
    .equ EXP_ONE,     0x4009115c        | EXPORT TO SET's own (src, dst, set, name, required, cb)
    .equ NF_SIZE,     8+256*10          | "CLYP", u16 version 1, u16 256, then 256 names of 10 B
    .equ NAME_W,      10                | a sequence name: 9 characters + NUL (9 x 4 - 1 = 35 px: the
                                        | 37 px a slot has after its number)
    .equ BANKS_RESUME,0x400905dc        | the masked bank loader 0x400905d4(ctx, mask, ...) after its
                                        | `lea -328(sp),sp ; movem.l d2-d7/a2-a6,(sp)` (8 B)
    .equ SRAM_RESTORE,0x4000fbb4        | (bank): the SRAM mirror -> RAM (power-on resume: the
                                        | current bank's unsaved edits; one caller 0x40025808)
    .equ BANK_HASDATA,0x4000fd78        | (bank) -> d0 != 0: stock's bank LEDs light it green
    .equ BANKSZ,      0x95048           | one bank's ORIGINALS: its 16 slabs + its 4 working Parts (PART_OFF +
                                        | 4 * PARTSZ; the live bank's SAVE PART copies, flags and names after
                                        | them are never read from a snapshot: 405 KB less, the user 2026-11-04)
    .equ RESET_BANKS, 0x4000fd34        | (flag): every bank to defaults (bank 0 init, copied over 1..15)
    .equ CL_MAGIC,    0x434c5950        | 'CLYP': the DRAM part is loaded (cl_magic)
| sources other than a slot: the bank byte of a cue / provenance code (bank << 8 | pattern)
    .equ SRC_ORIG,    0xfd              | the track's original (the load snapshot) on the playing pattern
    .equ SRC_SAVED,   0xfe              | the track's saved sequence

| ---- the view's geometry (window-local, y = 0 is the bottom row; text occupies y..y+4). Measured
| in the emulator by rendering stock's own compositor output (tools/clyps_render.py).
    .equ WIN_W,       112               | screen columns 8..119: on stock's own border lines
    .equ WIN_H,       64                | (the main playback window's and ATTR's), the user's spec
    .equ WIN_DX,      -1                | x = (128 - 112) / 2 + 1 - 1 = 8
    .equ FONT_S,      0x400ba876        | the interface font: 3 px glyphs, 1 px apart, 5 rows
    .equ FONT_WTAB,   0x400c246a        | ... its width table, one byte per character code
    .equ DIGIT_W,     4                 | digit advance
    .equ ROW_PITCH,   6                 | 5 px text + 1 px between rows (2 px tried and dropped by the
                                        | user, 2026-10-27)
    .equ HDR_Y,       57                | header: lit band 55..63 (63 = the border), text 57..61:
                                        | two lit rows above and below the inverted text
    .equ BODY_TOP,    54                | the rows' field: y 1..54 (border at 0, band from 55)
    .equ ROW0_Y,      46                | row r text at 46 - 6r: the 47-row block 4..50, centred in
                                        | 1..54 (4 rows above, 3 below: the field is odd by one); a bar /
                                        | box (text +- 1) stays inside the field (cl_bary clips anyway)
| The cells (the user, 2026-10-27), x from the frame (0) to the right: 2 px, the "edited" x (3..5),
| 2 px, the bar / box edge (8), 1 px, the slot number (column 1 has only single digits: x 10), 3 px,
| the label (16, up to 35 px: a 9-character name), 1 px, the edge (52); 2 px, column 2's x (55..57),
| 2 px, its edge (60), 1 px, its numbers (62..68), 3 px, its label (72), 1 px, its edge (108), 2 px,
| the frame (111). Per column (cl_colx): the 2-digit number field's x, the bar / box edges, the x's x.
    .equ EMP_DX,      12                | "---" (11 px) centred in the 35 px label: places 4..6
    .equ SUM_GAP,     2                 | the number field (2 x DIGIT_W) + 2 = the label at col + 10
    .equ BOX_R,       109               | a dark header box's right column (text ends at 107)
    .equ LOADP_A,     21                | "LOAD: " advance (20 px + 1)

| Two sections, linked together (tools/build_clyps.py): `.text` = the ROM part in the classic cave
| (the sequencer-tick code -- phase D, the wrap body -- and the cue state it touches: ISR code
| stays out of DRAM, build_kyoti.py's policy); `.dram` = everything else (the UI task's handlers,
| the view, the grid, the keymap / LED layers), linked at the arena reserve and carried by the
| boot loader (tools/dram/). The buffers (CL_BSS_SIZE) follow `.dram`'s end, uninitialised.
| Calls between the two are absolute (jsr / lea abs.l): a pc-relative branch across them fails
| the link (R_68K_PC16 overflow), so nothing slips through.
| CLYPS_ALLDRAM (KYOTI, scope §1.10): the ROM part goes to `.dram` too -- KYOTI's caves are full, and
| DRAM is in place before any hook can run (the loader runs from the boot site 0x4000050c, before
| the tasks, the UI and the sequencer start; DIRECT JUMP's phase-D hook ran from DRAM on the
| unit in OBKYOTI6-12, caves.md §5).
    .macro ROMSEC
    .ifdef CLYPS_ALLDRAM
    .section .dram,"ax"
    .else
    .text
    .endif
    .endm
    .macro FWDCHK                       | a menu over Clyps: this key is the base keymap's (cl_under)
    jsr     cl_under
    tst.l   %d0
    bne.w   cl_fwdbase
    .endm
    .global cl_ptn, cl_bankp, cl_bankr, cl_land, cl_uitail, cl_wrap, cl_projload, cl_rstall
    .global cl_yes, cl_no
    .global cl_hwrite, cl_hstorep, cl_hstoreb, cl_hrestp, cl_hrestb, cl_hdel, cl_hexp
    .section .dram,"ax"

| ================================================================ detours
| [PTN] key handler 0x4005a044 (press, release, hold). Replaces 6 B:
|   move.l 8(sp),%d0 ; moveq #1,%d1
| A press with [BANK] held enters Clyps; everything else is stock's (inside Clyps only the chord's
| own [PTN] reaches here: PTN_CONSUMED makes its release a teardown).
cl_ptn:
    move.l  8(%sp),%d0
    bne.b   cp_nrel
    clr.b   cl_chordout                 | a key of the chord that opened Clyps is let go
cp_nrel:
    cmpi.l  #1,%d0
    bne.b   cp_stock
    tst.l   BANK_HELD                   | [BANK] held: [PTN] completes the chord
    beq.b   cp_stock
    tst.b   cl_open
    bne.b   cp_stock
    jsr     cl_gate
    tst.l   %d0
    beq.b   cp_stock
    pea     1                           | 1 = [BANK] came first: undo its press
    jsr     cl_enter
    addq.l  #4,%sp
    rts                                 | stock's press never runs
cp_stock:
    move.l  8(%sp),%d0
    moveq   #1,%d1
    jmp     PTN_RESUME

| [BANK] press handler 0x4007af80. Replaces 6 B: tst.l 0x460e73bc
| With [PTN] held: enter Clyps. Otherwise stock's press WITHOUT its window: SELECT BANK opens on the
| release of a plain tap (the user, 2026-10-29; RELOAD_FROM_PROJECT's inversion, patch_reload3.s
| rl3_bank_show / rl3_bank_rel), so a chord begun with [BANK] flashes no window.
cl_bankp:
    tst.l   PTN_HELD
    beq.b   cb_def
    tst.b   cl_open
    bne.b   cb_def
    jsr     cl_gate
    tst.l   %d0
    beq.b   cb_def
    clr.l   -(%sp)                      | 0 = [PTN] came first: nothing to undo
    jsr     cl_enter
    addq.l  #4,%sp
    rts                                 | no SELECT BANK, no [BANK] layers
cb_def:
    moveq   #1,%d0
    move.b  %d0,cl_bkdef
    bra.w   cl_bkdefer

| [BANK] release handler 0x4007b3e0. Replaces 8 B: moveq #2,d0 ; cmp.l 0x460e73c6,d0. A release
| of a deferred press (cl_bankp) finishes it (cl_bkrel); otherwise stock's.
cl_bankr:
    clr.b   cl_chordout                 | a key of the chord that opened Clyps is let go
    tst.b   cl_bkdef
    beq.b   cl_bankr_stock
    clr.b   cl_bkdef
    moveq   #0,%d1                      | no arrows paged (outside Clyps)
    bra.w   cl_bkrel
cl_bankr_stock:
    moveq   #2,%d0
    cmp.l   BANK_SEL,%d0
    jmp     BANKR_RESUME

| cl_bkdefer: stock's [BANK] press (0x4007af80 and its tail 0x4007af30) without SHOW_WIN: the overlay
| that makes the trigs pick a bank IS pushed. SHOW_WIN would first have dismissed whatever SELECT
| window is up (its onClose pops its layers): done here.
cl_bkdefer:
    tst.l   BANK_LATCH
    seq     %d0
    andi.l  #1,%d0
    move.l  %d0,BANK_TAP                | a second tap on a latched SELECT BANK closes it
    jsr     DISMISS
    clr.l   BANK_SEL
    clr.l   BANK_PICK
    clr.l   BANK_LATCH
    pea     BANK_LAYER
    jsr     LAYER_PUSH
    pea     BANK_LEDL
    jsr     LED_PUSH
    clr.l   (%sp)
    jsr     LED_PAINT
    addq.l  #8,%sp
    rts

| cl_bkrel (d1 = 1: the arrows paged during the hold): finish a deferred [BANK] gesture. Something
| picked on the grid -> stock's own release; paged -> just the overlay off; a plain tap -> SELECT
| BANK now, latched as stock's release latches it; the tap that closes a latched one -> overlay off.
cl_bkrel:
    tst.l   BANK_SEL
    bne.w   cl_bankr_stock
    tst.l   %d1
    bne.b   br_tear
    tst.l   BANK_TAP
    beq.b   br_tear
    pea     BANK_TEARDOWN
    clr.l   -(%sp)
    pea     0xf0
    pea     BANK_TITLE
    jsr     SHOW_WIN
    lea     16(%sp),%sp
    moveq   #1,%d0
    move.l  %d0,BANK_LATCH
    jmp     WIN_STICKY
br_tear:
    jmp     BANK_TEARDOWN

| ================================================================ entering / leaving
| d0 = 1 when Clyps may open now
cl_gate:
    moveq   #0,%d0
    tst.l   ARR_ACT
    bne.b   cg_no
    tst.l   POPUP
    bne.b   cg_no
    moveq   #1,%d0
cg_no:
    rts

| cl_enter(bankfirst). Clyps opens on the bank of the pattern you are on (its slot highlighted),
| with the select box on that slot.
cl_enter:
    tst.l   4(%sp)
    beq.b   ce_noundo
    move.l  WIN_SLOT,%d0
    beq.b   ce_tear
    move.l  WIN_ONCLOSE,%d0
    cmpi.l  #BANK_TEARDOWN,%d0
    bne.b   ce_tear
    jsr     DISMISS                     | closes SELECT BANK; its onClose pops the layers
    bra.b   ce_noundo
ce_tear:
    jsr     BANK_TEARDOWN               | no window: pop the layers it pushed directly
ce_noundo:
    moveq   #2,%d0
    move.l  %d0,BANK_SEL                | [BANK] release -> dismiss (nothing up: no-op)
    moveq   #1,%d0
    move.l  %d0,PTN_CONSUMED            | [PTN] release -> teardown only
    clr.b   cl_bkarm                    | BANK_SEL 2 is ours now, not a pick
    clr.b   cl_bkdef                    | the chord's [BANK]: its release is stock's (BANK_SEL 2)
    moveq   #1,%d0
    move.b  %d0,cl_chordout             | opened by the chord: chord + SCALE closes Clyps
    clr.b   cl_ptfwd
    clr.b   cl_bkfwd
    jsr     cl_boxhome                  | the box on the active track's sequence (the user, 2026-11-04)
    pea     cl_close                    | close_cb: eviction lands in the same teardown
    pea     PRIO
    clr.l   -(%sp)                      | dy
    pea     WIN_DX
    pea     WIN_H
    pea     WIN_W
    jsr     WIN_NEW
    lea     24(%sp),%sp
    move.l  %d0,cl_win
    beq.b   ce_fail                     | all 5 window slots busy: stay out of Clyps
    moveq   #1,%d0
    move.b  %d0,cl_open
    clr.b   cl_flash
    clr.w   cl_grp                      | no group (scope §1.9)
    clr.b   cl_cuh
    jsr     cl_gupd
    jsr     cl_flstop
    pea     cl_layer
    jsr     LAYER_PUSH
    pea     cl_led
    jsr     LED_PUSH
    addq.l  #8,%sp
    jsr     cl_refresh
ce_fail:
    rts

| the one teardown: [NO] AND the window's close_cb (eviction). Nothing else closes Clyps (the
| user, 2026-10-27). Idempotent; stock never clears a slot's close_cb, so it may be called again.
cl_close:
    tst.b   cl_open
    beq.b   cc_out
    clr.b   cl_open
    clr.w   cl_grp                      | the group ends with Clyps: the tab and the LED colours
    jsr     cl_gupd                     | go back to the active track
    jsr     cl_flstop
    tst.l   cl_win
    beq.b   cc_nowin
    pea     cl_win
    jsr     WIN_DEL                     | destroys, RDRAW = 1, cl_win = 0
    addq.l  #4,%sp
cc_nowin:
    pea     cl_layer
    jsr     LAYER_POP
    pea     cl_led
    jsr     LED_POP
    clr.l   (%sp)
    jsr     LED_PAINT                   | slot 0 back to whatever is underneath
    moveq   #7,%d0
    move.l  %d0,(%sp)
    jsr     LED_PAINT                   | and the page LEDs (stock's step indicator)
    addq.l  #8,%sp
    moveq   #1,%d0
    move.l  %d0,RDRAW
cc_out:
    rts

| ================================================================ keymap handlers
| The highlight (inverted bar) = the pattern you are on, in its bank; it moves only when the pattern
| changes. The select box (1 px frame) = what a [YES] loads: (cl_sbank, cl_cur), cl_cur 16 = ORIG.
| [BANK] held: the arrows page the shown bank instead (the slot selector rests).

| bank paging: d0 = +1 / -1. A [BANK] pressed in Clyps that pages opens no SELECT BANK on release.
cl_page:
    moveq   #1,%d1
    move.b  %d1,cl_bkused
    move.l  %d0,-(%sp)
    jsr     cl_flstop
    move.l  (%sp)+,%d0
    moveq   #0,%d1
    move.b  cl_bank,%d1
    add.l   %d0,%d1
    andi.l  #15,%d1
    move.b  %d1,cl_bank
    bra.w   cl_refresh

| UP 0x33 / DOWN 0x20: the box through 1..16 -> ORIG -> 1, wrapping, auto-repeat (hold events).
| A move made in another bank than the box's brings the box into the shown bank (same slot).
| [BANK] held: UP = previous bank, DOWN = next bank.
cl_k_ud:
    FWDCHK
    tst.l   8(%sp)
    beq.b   ku_out
    clr.b   cl_flash
    tst.l   BANK_HELD
    beq.b   ku_sel
    moveq   #1,%d0
    move.l  4(%sp),%d1
    cmpi.l  #0x33,%d1
    bne.w   cl_page
    moveq   #-1,%d0
    bra.w   cl_page
ku_sel:
    moveq   #16,%d0                     | 16 slots (no ORIG entry since 2026-11-02: your own slot is it)
    movea.l %d0,%a1                     | a1 = entries in the cycle
    moveq   #0,%d0
    move.b  cl_cur,%d0
    move.l  4(%sp),%d1
    cmpi.l  #0x33,%d1
    bne.b   ku_down
    tst.l   %d0                         | UP = previous
    bne.b   ku_prev
    move.l  %a1,%d0
ku_prev:
    subq.l  #1,%d0
    bra.b   ku_set
ku_down:
    addq.l  #1,%d0
    cmpa.l  %d0,%a1
    bne.b   ku_set
    moveq   #0,%d0
ku_set:
    move.b  %d0,cl_cur
    jsr     cl_flstop
    move.b  cl_bank,%d0
    move.b  %d0,cl_sbank
    jsr     cl_draw
    clr.l   -(%sp)
    jsr     LED_PAINT                   | the yellow box LED follows
    addq.l  #4,%sp
ku_out:
    rts

| LEFT 0x34 / RIGHT 0x21: the box to the same row of the other column (1 <-> 9 ... 8 <-> 16);
| nothing on ORIG. [BANK] held: LEFT = previous bank, RIGHT = next bank.
cl_k_lr:
    FWDCHK
    move.l  8(%sp),%d0
    cmpi.l  #1,%d0
    bne.b   kl_out
    clr.b   cl_flash
    tst.l   BANK_HELD
    beq.b   kl_sel
    moveq   #1,%d0
    move.l  4(%sp),%d1
    cmpi.l  #0x34,%d1
    bne.w   cl_page
    moveq   #-1,%d0
    bra.w   cl_page
kl_sel:
    moveq   #0,%d0
    move.b  cl_cur,%d0
    eori.l  #8,%d0
    move.b  %d0,cl_cur
    jsr     cl_flstop
    move.b  cl_bank,%d0
    move.b  %d0,cl_sbank
    jsr     cl_draw
    clr.l   -(%sp)
    jsr     LED_PAINT
    addq.l  #4,%sp
kl_out:
    rts

| TRIG 1-16 (codes 0x00..0x0f): the box to that slot of the shown bank, and load it (cued while
| running). [BANK] held: nothing yet (stock's bank select inside Clyps is the next step).
cl_k_trig:
    FWDCHK
    move.l  8(%sp),%d0
    cmpi.l  #1,%d0
    bne.w   kt_out
    clr.b   cl_flash
    tst.l   BANK_HELD                   | [BANK] held alone (from the chord that opened Clyps):
    beq.b   kt_go                       | nothing; with [PTN] too: the pattern reload
    tst.l   PTN_HELD
    beq.b   kt_out
    clr.l   -(%sp)                      | (no track)
    move.l  8(%sp),%d0
    andi.l  #15,%d0
    move.l  %d0,-(%sp)                  | pattern N of the playing bank, from the card
    pea     RQ_PTN
    jsr     cl_rlreq
    lea     12(%sp),%sp
    tst.b   cl_chordout                 | the chord opened Clyps: close it (begun inside: stay)
    beq.b   kt_out
    clr.b   cl_chordout
    bra.w   cl_close
kt_go:
    move.l  4(%sp),%d0
    andi.l  #15,%d0
    move.b  %d0,cl_cur
    move.b  cl_bank,%d1
    move.b  %d1,cl_sbank
    jsr     cl_onorig                   | your own pattern's slot: its original back (as [YES] there)
    tst.l   %d0
    bne.w   ky_orig
    move.l  4(%sp),%d0
    andi.l  #15,%d0
    move.l  %d0,-(%sp)
    jsr     cl_load
    addq.l  #4,%sp
    jsr     cl_flstart                  | the load confirmation
    bra.w   cl_refresh
kt_out:
    rts

| [YES]: load the box's entry (a slot of its bank, or ORIG: restore); Clyps stays. The [PTN]+[BANK]
| chord held -> nothing: DIRECT JUMP must not toggle there (the user, 2026-10-25). [PTN]+[YES]
| ([PTN] held, [BANK] not) -> DIRECT JUMP's toggle in an image that has it (--defsym DJ_TOGGLE=
| its entry), nothing here; never a load. [FUNC]+[YES] -> save (§1.6).
cl_k_yes:
    FWDCHK
    move.l  8(%sp),%d0
    cmpi.l  #1,%d0
    bne.b   ky_out                      | [FUNC]+[YES]: the same, FULL (cl_load / ky_orig read cl_fn)
    clr.b   cl_flash
    tst.l   PTN_HELD
    beq.b   ky_noptn
    tst.l   BANK_HELD
    bne.w   kp_pat                      | the chord: ORIG PTN+PART, as chord + [PAGE] (the user,
                                        | 2026-10-30; closes Clyps when the chord opened it)
.ifdef DJ_TOGGLE
    jmp     DJ_TOGGLE                   | [PTN]+[YES]: DIRECT JUMP on / off (a tail call: our
.endif                                  | (keycode, event) are its arguments, in place)
    rts
ky_noptn:
    jsr     cl_onorig                   | your own pattern's slot = the original
    tst.l   %d0
    bne.b   ky_orig
    moveq   #0,%d0
    move.b  cl_cur,%d0
    move.l  %d0,-(%sp)
    jsr     cl_load
    addq.l  #4,%sp
    jsr     cl_flstart
    bra.w   cl_refresh
ky_orig:
    moveq   #0,%d0
    tst.b   cl_fn
    beq.b   ky_os
    move.l  #0x10000,%d0                | ORIG SEQ/MCH/FX
ky_os:
    jsr     cl_restore
    jsr     cl_flhdr                    | the ORIG box flashes
    bra.w   cl_refresh
ky_out:
    rts

| [NO]: close Clyps (the only key that does). [FUNC]+[NO]: nothing (temp reload lives outside).
| With a group (scope §1.9): dismiss the group instead; Clyps stays.
cl_k_no:
    move.l  8(%sp),%d0
    cmpi.l  #1,%d0
    bne.b   kn_out
    clr.b   cl_flash
    tst.b   cl_fn
    bne.b   kn_out
    tst.w   cl_grp
    beq.w   cl_close
    clr.w   cl_grp
    jsr     cl_flstop
    jsr     cl_gupd
    bra.w   cl_draw
kn_out:
    rts

| [CUE] 0x2a in Clyps (scope §1.9): not stock's cue. While it is held the group can change ([CUE] +
| TRACK, cl_k_cuet: our sub-map cl_csub, chained after stock's 0x400bf2a0, wins) and the header
| reads MULTI; the tab and the active LED colours show the members only. Press and release.
cl_k_cue:
    FWDCHK
    clr.b   cl_flash
    move.l  8(%sp),%d0
    cmpi.l  #1,%d0
    seq     %d0
    move.b  %d0,cl_cuh
    jsr     cl_gupd
    bra.w   cl_draw

| [CUE] held + TRACK n: track n (MIDI n + 8 on the MIDI side) in / out of the group. Press only.
| The view follows the group (the user, 2026-11-04): an added track is selected; after a removal,
| the newest remaining member on the side you are on, else the track you were on before the group
| began (same side only), else no change. Never switches sides: the screen and the device's side
| must agree. cl_gord = the members in add order (cl_gn entries, newest last).
cl_k_cuet:
    jsr     cl_under                    | a menu over Clyps: stock's [CUE] + TRACK (its sub-map 0x400bf2a0)
    tst.l   %d0
    beq.b   kcu_ours
    jmp     CUE_TRK
kcu_ours:
    move.l  8(%sp),%d0
    cmpi.l  #1,%d0
    bne.b   kcu_out
    clr.b   cl_flash
    jsr     cl_flstop
    move.l  4(%sp),%d0
    andi.l  #7,%d0
    tst.l   MIDI_MODE
    beq.b   kcu_t
    addq.l  #8,%d0
kcu_t:
    move.l  %d2,-(%sp)
    move.l  %d0,%d2                     | d2 = t
    jsr     cl_gdrop                    | t out of the add order (in again below when added)
    moveq   #0,%d1
    move.w  cl_grp,%d1
    bne.b   kcu_tg
    clr.b   cl_gn                       | the group begins: a fresh order, and where you were
    jsr     cl_trk
    move.b  %d0,cl_gpre
kcu_tg:
    bchg    %d2,%d1
    move.w  %d1,cl_grp
    btst    %d2,%d1
    beq.b   kcu_v                       | removed
    moveq   #0,%d0
    move.b  cl_gn,%d0
    lea     cl_gord,%a0
    move.b  %d2,(%a0,%d0.l)
    addq.l  #1,%d0
    move.b  %d0,cl_gn
kcu_v:
    jsr     cl_gview
    move.l  (%sp)+,%d2
    jsr     cl_gupd
    bra.w   cl_refresh                  | the view may have moved
kcu_out:
cl_k_nop:
    rts

| cl_gdrop: track d2 out of cl_gord. Keeps d2. Uses d0, d1, a0, a1.
cl_gdrop:
    lea     cl_gord,%a0
    movea.l %a0,%a1                     | write pointer
    moveq   #0,%d0                      | read index
gd_l:
    cmp.b   cl_gn,%d0
    bcc.b   gd_end
    move.b  (%a0,%d0.l),%d1
    cmp.b   %d1,%d2
    beq.b   gd_skip
    move.b  %d1,(%a1)+
gd_skip:
    addq.l  #1,%d0
    bra.b   gd_l
gd_end:
    move.l  %a1,%d0
    sub.l   %a0,%d0
    move.b  %d0,cl_gn
    rts

| cl_gview: select the group's view track -- the newest member (cl_gord, from the end) on the side
| you are on, else cl_gpre if it is on this side, else nothing. Selects only on a change, through
| stock's TRK_SELECT. Keeps d2-d7. Uses d0, d1, a0, a1.
cl_gview:
    move.l  %d3,-(%sp)
    moveq   #0,%d1
    tst.l   MIDI_MODE
    beq.b   gv_s
    moveq   #8,%d1                      | d1 = this side's bit 3
gv_s:
    moveq   #0,%d0
    move.b  cl_gn,%d0
    lea     cl_gord,%a0
gv_l:
    subq.l  #1,%d0
    bmi.b   gv_pre
    moveq   #0,%d3
    move.b  (%a0,%d0.l),%d3
    eor.l   %d1,%d3
    btst    #3,%d3
    bne.b   gv_l                        | the other side's member: skip it
    eor.l   %d1,%d3                     | d3 = the track
    bra.b   gv_try
gv_pre:
    moveq   #0,%d3
    move.b  cl_gpre,%d3
    move.l  %d3,%d0
    eor.l   %d1,%d0
    btst    #3,%d0
    bne.b   gv_out                      | it was on the other side: stay
gv_try:
    jsr     cl_trk
    cmp.l   %d3,%d0
    beq.b   gv_out
    andi.l  #7,%d3
    move.l  %d3,-(%sp)
    jsr     TRK_SELECT
    addq.l  #4,%sp
gv_out:
    move.l  (%sp)+,%d3
    rts

| cl_gmask = 0 without a group, else 0x10000 | the members (bit t, MIDI 8..15): the painters' test
| (cl_act4 / cl_act5). A group = [CUE] held or members picked, while Clyps is open. Then the track
| LEDs are repainted; the sidebar follows on stock's next 0x40052200 pass. Uses d0, d1, a0, a1.
cl_gupd:
    moveq   #0,%d0
    tst.b   cl_open
    beq.b   gu_set
    move.w  cl_grp,%d0
    tst.b   cl_cuh
    bne.b   gu_m
    tst.l   %d0
    beq.b   gu_set
gu_m:
    ori.l   #0x10000,%d0
gu_set:
    move.l  %d0,cl_gmask
    pea     6
    jsr     LED_PAINT
    addq.l  #4,%sp
    moveq   #1,%d0
    move.l  %d0,RDRAW
    rts

| d0 != 0: the header shows the group (MULTI; not while the [PTN]+[BANK] chord is held: its
| ORIG PTN+PART is the whole pattern's). Uses d0.
| cl_under -> d0 != 0 while the Recording Setup menu is open over Clyps (its window 0x460d10cc; its
| opener 0x4002fec4 pushes a layer listing only [NO], [FUNC], [MIDI], the scene keys and the encoder
| pushes). The keys it does not list fall through to our layer; in stock they reach the base keymap,
| so FWDCHK sends them there (cl_fwdbase): the menu works as on stock and Clyps underneath is left
| alone (the user, 2026-11-02). Not "any layer above ours": a held key's sub-map (TRACK, [FUNC], [CUE])
| is linked into the same chain above us. Uses d0.
cl_under:
    move.l  RSETUP_WIN,%d0
    rts

| cl_fwdbase(code, event): the base keymap's record for `code` (the first layer of the chain), its
| press / release / hold handler by the event, as a tail call; none: nothing. Uses d0, d1, a0, a1.
cl_fwdbase:
    movea.l LAYERS_HEAD,%a0
    movea.l 4(%a0),%a0                  | its key records (26 B each, ended by 0xff)
fb_l:
    moveq   #0,%d0
    move.b  (%a0),%d0
    cmpi.l  #0xff,%d0
    beq.b   fb_none
    cmp.l   4(%sp),%d0
    beq.b   fb_hit
    lea     26(%a0),%a0
    bra.b   fb_l
fb_hit:
    move.l  8(%sp),%d0
    cmpi.l  #1,%d0
    beq.b   fb_p
    tst.l   %d0
    beq.b   fb_r
    move.l  10(%a0),%d1                 | a hold
    bra.b   fb_go
fb_p:
    move.l  2(%a0),%d1
    bra.b   fb_go
fb_r:
    move.l  6(%a0),%d1
fb_go:
    tst.l   %d1
    beq.b   fb_none
    movea.l %d1,%a1
    jmp     (%a1)
fb_none:
    rts

cl_ismulti:
    jsr     cl_hstate
    btst    #1,%d0
    bne.b   im_no
    move.l  cl_gmask,%d0
    rts
im_no:
    moveq   #0,%d0
    rts

| d0 != 0: the select box is on the playing pattern's own slot and it has an original -- that slot is
| the ORIG entry (the user, 2026-11-02: no 17th slot; loading your own slot was a no-op anyway).
| Uses d0, d1, a0, a1.
cl_onorig:
    move.b  cl_sbank,%d0
    cmp.b   PLAY_BANK,%d0
    bne.b   oo_no
    move.b  cl_cur,%d0
    cmp.b   ACT_PAT,%d0
    bne.b   oo_no
    jmp     cl_origok
oo_no:
    moveq   #0,%d0
    rts

| cl_textw (a0 = string) -> d0 = its width in the interface font (widths 0x400c246a, 1 px apart).
| Uses d0, d1, a0, a1.
cl_textw:
    moveq   #0,%d0
    lea     FONT_WTAB,%a1
tw_l:
    moveq   #0,%d1
    move.b  (%a0)+,%d1
    beq.b   tw_e
    move.b  (%a1,%d1.l),%d1
    addq.l  #1,%d1
    add.l   %d1,%d0
    bra.b   tw_l
tw_e:
    tst.l   %d0
    beq.b   tw_o
    subq.l  #1,%d0
tw_o:
    rts

| [PAGE] (SCALE) 0x1b (the user, 2026-10-29): like the ORIG entry -- this track's original
| sequence (ORIG SEQ); [FUNC]+[PAGE] = with its machine / FX (ORIG SEQ/MCH/FX; a MIDI track always).
| With the [PTN]+[BANK] chord held: ORIG PTN/PART, the pattern and its Part as loaded; if that chord
| opened Clyps (begun outside), Clyps then closes; begun inside, it stays.
cl_k_page:
    FWDCHK
    move.l  8(%sp),%d0
    cmpi.l  #1,%d0
    bne.w   kn_out
    clr.b   cl_flash
    jsr     cl_hstate
    btst    #1,%d0
    bne.b   kp_pat
    moveq   #0,%d0
    tst.b   cl_fn
    beq.b   kp_one
    move.l  #0x10000,%d0
kp_one:
    jsr     cl_restore
    jsr     cl_onorig
    tst.l   %d0
    beq.w   cl_refresh                  | the box elsewhere: nothing to flash
    jsr     cl_flhdr
    bra.w   cl_refresh
kp_pat:
    jsr     cl_restorepat
    tst.b   cl_chordout
    beq.b   kp_in
    clr.b   cl_chordout
    bra.w   cl_close
kp_in:
    jsr     cl_flhdr                    | begun inside: the ORIG PTN+PART box flashes (the user)
    bra.w   cl_refresh

| d0: bit 0 = [BANK] held without [PTN] (the arrows page: "BANK A" boxed), bit 1 = the [PTN]+[BANK]
| chord held (ORIG PTN/PART). Uses d0.
cl_hstate:
    moveq   #0,%d0
    tst.l   BANK_HELD
    beq.b   hs_out
    moveq   #1,%d0
    tst.l   PTN_HELD
    beq.b   hs_out
    moveq   #2,%d0
hs_out:
    rts

| TRACK 1-8 (0x10..0x17): every event goes through stock's own base handler, as the base keymap
| does (press marks the key held in 0x460fab40 and handles double taps; the RELEASE selects the
| track and clears the held mark). After the release the view and the grid follow.
cl_k_track:
    FWDCHK
    clr.b   cl_flash
    jsr     cl_flstop
|   a card reload (scope §1.8, the user 2026-10-30): [PTN] alone held = the sequence, [BANK] alone
|   held = the sequence + its machine / FX (the track's Part slice); both held: nothing. The press
|   is the reload (not forwarded: no track change, as RELOAD_FROM_PROJECT); the release goes on.
    move.l  8(%sp),%d0
    cmpi.l  #1,%d0
    bne.b   ktr_fwd
    tst.l   PTN_HELD
    beq.b   ktr_b
    tst.l   BANK_HELD
    bne.b   ktr_fwd
    moveq   #1,%d0
    move.l  %d0,PTN_CONSUMED            | no SELECT PATTERN on [PTN]'s release (1, not stock's -1:
    moveq   #RQ_TRKSEQ,%d1              | -1 closes Clyps as a pattern pick)
    bra.b   ktr_req
ktr_b:
    tst.l   BANK_HELD
    beq.b   ktr_fwd
    moveq   #1,%d0
    move.b  %d0,cl_bkused               | no SELECT BANK on [BANK]'s release
    moveq   #RQ_TRKFULL,%d1
ktr_req:
    move.l  4(%sp),%d0
    andi.l  #7,%d0
    tst.l   MIDI_MODE
    beq.b   ktr_t
    addq.l  #8,%d0
ktr_t:
    move.l  %d0,-(%sp)                  | t
    moveq   #0,%d0
    move.b  ACT_PAT,%d0
    move.l  %d0,-(%sp)                  | the playing pattern
    move.l  %d1,-(%sp)
    jsr     cl_rlreq
    lea     12(%sp),%sp
    rts
ktr_fwd:
    move.l  8(%sp),-(%sp)
    move.l  8(%sp),-(%sp)
    jsr     TRK_BASE
    addq.l  #8,%sp
    tst.l   8(%sp)
    beq.w   cl_refresh                  | release: the track has changed
    rts

| [PTN] / [BANK] pressed while Clyps is open (keys pressed AFTER our layer went up reach these
| records, and their hold / release come back here, even after Clyps has closed). Scope §1.0
| step 2: both behave as in stock.
|  * [PTN]: stock's own handler for every event: its press pushes the pattern-pick layer, a tap
|    opens SELECT PATTERN on release. A pattern picked that way is a real pattern change and closes
|    Clyps (cl_uitail).
|  * [BANK]: stock's press without SELECT BANK (the overlay that makes the trigs pick a bank IS
|    pushed). Held, the arrows page the shown bank instead (the header boxes "BANK A"). The release
|    of a plain tap opens SELECT BANK (RELOAD_FROM_PROJECT's inversion). A bank picked on the grid
|    stays pending, as in stock; the pattern picked after it is a real change and closes Clyps.
|  * the chord's second key ([PTN] with [BANK] held, or the reverse): swallowed.
|  * [FUNC]+[BANK]: name the box's sequence; [FUNC]+[PTN]: nothing.
cl_k_chord:
    FWDCHK
    move.l  8(%sp),%d0
    move.l  4(%sp),%d1
    cmpi.l  #0x2f,%d1
    beq.b   kc_bank
|   [PTN]
    cmpi.l  #1,%d0
    bne.b   kc_pfwd
    clr.b   cl_ptfwd
    tst.b   cl_fn
    bne.w   kc_out
    tst.l   BANK_HELD
    beq.b   kc_pgo
    moveq   #1,%d1                      | the chord (again): no SELECT BANK on [BANK]'s release, and
    move.b  %d1,cl_bkused               | never the bank view while both are held (the user,
    tst.b   cl_bkfwd                    | 2026-10-30): a [BANK] pressed in Clyps took its overlay
    beq.b   kc_pch                      | down now
    clr.b   cl_bkfwd
    jsr     BANK_TEARDOWN               | its keymap + LED layers off (and a repaint)
kc_pch:
    clr.l   -(%sp)
    jsr     LED_PAINT                   | the pattern view (cl_paint, the chord held)
    addq.l  #4,%sp
    rts
kc_pgo:
    moveq   #1,%d1
    move.b  %d1,cl_ptfwd
kc_pfwd:
    tst.b   cl_ptfwd
    beq.w   kc_out
    tst.l   %d0
    bne.w   cp_stock
    clr.b   cl_ptfwd                    | the release ends the gesture
    bra.w   cp_stock                    | stock's [PTN] handler; (code, event) still at 4 / 8(sp)
|   [BANK]
kc_bank:
    cmpi.l  #1,%d0
    beq.b   kc_bpress
    tst.l   %d0
    bne.b   kc_bhold
    tst.b   cl_ptpop                    | released with [PTN] still held: its overlay back
    beq.b   kc_brl0
    clr.b   cl_ptpop
    tst.l   PTN_HELD
    beq.b   kc_brl0
    tst.b   cl_ptfwd
    beq.b   kc_brl0
    pea     PTN_LAYER
    jsr     LAYER_PUSH
    pea     PTN_LEDL
    jsr     LED_PUSH
    addq.l  #8,%sp
kc_brl0:
    tst.b   cl_bkfwd
    beq.w   kc_out
    bra.w   kc_brel
kc_bhold:
    tst.b   cl_bkfwd
    beq.w   kc_out
    moveq   #1,%d0                      | hold: tap-eligible again (stock's hold 0x4007af24)
    move.l  %d0,BANK_TAP
    rts
kc_bpress:
    clr.b   cl_bkfwd
    tst.b   cl_fn
    bne.w   cl_rename                   | [FUNC]+[BANK] (EDIT): name the box's sequence
    tst.l   PTN_HELD
    beq.b   kc_bgo
    moveq   #1,%d1                      | the chord (again): no SELECT PATTERN on [PTN]'s release;
    move.l  %d1,PTN_CONSUMED            | a [PTN] pressed in Clyps: stock's pattern-pick overlay and
    tst.b   cl_ptfwd                    | its LEDs off while both are held (the trigs and the LEDs
    beq.b   kc_bch                      | are Clyps' then); back on [BANK]'s release if [PTN] is
    pea     PTN_LAYER                   | still held. Stock's own teardown at [PTN]'s release pops
    jsr     LAYER_POP                   | them again: the pops search the lists, a missing layer is
    pea     PTN_LEDL                    | a no-op (0x4003146c / 0x4007e81c)
    jsr     LED_POP
    addq.l  #8,%sp
    moveq   #1,%d1
    move.b  %d1,cl_ptpop
kc_bch:
    clr.l   -(%sp)
    jsr     LED_PAINT
    addq.l  #4,%sp
    rts
kc_bgo:
    moveq   #1,%d0
    move.b  %d0,cl_bkfwd
    move.b  %d0,cl_bkarm
    clr.b   cl_bkused
    bra.w   cl_bkdefer
kc_out:
    rts
kc_brel:
    clr.b   cl_bkfwd
    moveq   #0,%d1
    move.b  cl_bkused,%d1               | the arrows paged the view: no SELECT BANK
    bra.w   cl_bkrel

| [FUNC]+[BANK] in Clyps: stock's name editor (as project naming) on the sequence under the select
| box (nothing on ORIG). It edits a scratch copy; its [YES] stores it (cl_named), its [NO] keeps the
| old name; either way the Clyps view is under it again.
cl_rename:
    tst.b   cl_namesok
    beq.b   rn_out
    moveq   #0,%d0
    move.b  cl_cur,%d0
    move.l  %d0,%d1
    moveq   #0,%d0
    move.b  cl_sbank,%d0
    jsr     cl_nidx                     | d0 = the name's index (bank, pattern, active track)
    move.l  %d0,cl_nedit
    jsr     cl_nptr                     | a0 = its name
    lea     cl_nbuf,%a1
    moveq   #NAME_W,%d0
rn_cp:
    move.b  (%a0)+,(%a1)+
    subq.l  #1,%d0
    bne.b   rn_cp
    clr.b   cl_nbuf+NAME_W-1
    pea     cl_named
    clr.l   -(%sp)                      | layout 0: the full editor, as project naming
    pea     cl_nbuf
    pea     cl_s_rename
    pea     NAME_W-1                    | 9 characters: input stops there, and the copy back
    jsr     TEXT_EDIT                   | (10 bytes) fills cl_nbuf exactly
    lea     20(%sp),%sp
rn_out:
    rts

| the editor's done_cb(confirmed): [YES] stores the name; the view and grid redraw (Clyps stays)
cl_named:
    tst.l   4(%sp)
    beq.b   nd_draw
    move.l  cl_nedit,%d0
    jsr     cl_nptr
    lea     cl_nbuf,%a1
    moveq   #NAME_W,%d0
nd_cp:
    move.b  (%a1)+,(%a0)+
    subq.l  #1,%d0
    bne.b   nd_cp
    clr.b   -1(%a0)
nd_draw:
    tst.b   cl_open
    beq.b   nd_out
    jsr     cl_refresh
nd_out:
    rts

| [FUNC]: redraws (the FULL label arrives with FULL loads)
cl_k_func:
    move.l  8(%sp),%d0
    beq.b   kf_rel
    cmpi.l  #1,%d0
    bne.b   kf_out                      | hold events: nothing (stock's record has no hold handler)
    move.l  %d0,-(%sp)
    move.l  8(%sp),-(%sp)
    jsr     FUNC_PRESS                  | stock's own press (its state 0x46c7c730)
    addq.l  #8,%sp
    moveq   #1,%d0
    bra.b   kf_set
kf_rel:
    clr.l   -(%sp)
    move.l  8(%sp),-(%sp)
    jsr     FUNC_REL                    | stock's own release
    addq.l  #8,%sp
    moveq   #0,%d0
kf_set:
    move.b  %d0,cl_fn
    bra.w   cl_draw
kf_out:
    rts

| ================================================================ the load confirmation
| (the user, 2026-10-29) after a load, the select box flashes as an inverted bar (text inverted too)
| for 0.5 s (cl_draw: cl_fph); the ORIG header box likewise. An arrow, bank paging, a TRACK key or
| closing stops it at once; a new pick restarts it on the new slot.
cl_flhdr:                               | the header's label flashes (ORIG / ORIG PTN+PART)
    moveq   #1,%d0
    move.b  %d0,cl_ftgt
    bra.b   cl_fls
cl_flstart:                             | the select box flashes
    clr.b   cl_ftgt
cl_fls:
    moveq   #FL_TICKS,%d0
    move.b  %d0,cl_flk
    moveq   #FL_HALF,%d0
    move.b  %d0,cl_fcnt
    moveq   #1,%d0
    move.b  %d0,cl_fph
    rts
cl_flstop:
    clr.b   cl_flk
    clr.b   cl_fph
    rts
| cl_flashtick: one UI tick (cl_uitick, UI task, every 1/60 s while cl_flk != 0)
cl_flashtick:
    tst.b   cl_open
    bne.b   ft_go
    bra.b   cl_flstop
ft_go:
    moveq   #0,%d0
    move.b  cl_flk,%d0
    subq.l  #1,%d0
    move.b  %d0,cl_flk
    beq.b   ft_end
    moveq   #0,%d0
    move.b  cl_fcnt,%d0
    subq.l  #1,%d0
    move.b  %d0,cl_fcnt
    bne.b   ft_out
    moveq   #FL_HALF,%d0
    move.b  %d0,cl_fcnt
    moveq   #0,%d0
    move.b  cl_fph,%d0
    eori.l  #1,%d0
    move.b  %d0,cl_fph
    jmp     cl_draw
ft_end:
    clr.b   cl_fph
    jmp     cl_draw
ft_out:
    rts

| ================================================================ helpers
| d0 = active track 0..15 (MIDI tracks 8..15)
cl_trk:
    moveq   #0,%d0
    move.b  CUR_TRACK,%d0
    andi.l  #7,%d0
    tst.l   MIDI_MODE
    beq.b   ct_out
    addq.l  #8,%d0
ct_out:
    rts

    ROMSEC
| cl_slab(bank, pat) -> a0
cl_slab:
    move.l  4(%sp),%d0
    move.l  #BANKSTRIDE,%d1
    muls.l  %d1,%d0
    movea.l #BLOB,%a0
    adda.l  %d0,%a0
    move.l  8(%sp),%d0
    move.l  #PATSTRIDE,%d1
    muls.l  %d1,%d0
    adda.l  %d0,%a0
    rts

| cl_toff(t) -> d0 = record offset in the slab, d1 = record length
cl_toff:
    move.l  4(%sp),%d0
    cmpi.l  #8,%d0
    bcc.b   to_midi
    move.l  #TRAC_A,%d1
    muls.l  %d1,%d0
    rts
to_midi:
    subq.l  #8,%d0
    move.l  #TRAC_M,%d1
    muls.l  %d1,%d0
    addi.l  #MIDI_BASE,%d0
    rts

    .section .dram,"ax"
| d0 = (bank << 8) | pattern of the sequence playing on the active track: its Clyps source
| while the load still belongs to the playing pattern, otherwise the playing pattern itself
| cl_srccode -> d0 = (bank << 8) | slot of the active track's sequence: where its playing sequence was
| loaded from (cl_playing); its original, saved sequence or a card reload -> the playing pattern's own
| slot. Uses d0, d1, a0.
cl_srccode:
    jsr     cl_playing
    move.l  %d0,%d1
    lsr.l   #8,%d1
    cmpi.l  #16,%d1
    bcs.b   sc2_out
    moveq   #0,%d0                      | ORIG / SAVED: the pattern's own slot
    move.b  PLAY_BANK,%d0
    lsl.l   #8,%d0
    move.b  ACT_PAT,%d0
sc2_out:
    rts

| cl_boxhome: the select box (and the shown bank) on the active track's sequence (cl_srccode). Opening
| Clyps and every change of the viewed track; moving it within a view is free (the user, 2026-11-04).
| Uses d0, d1, a0.
cl_boxhome:
    jsr     cl_srccode
    move.b  %d0,%d1
    andi.l  #15,%d1
    move.b  %d1,cl_cur
    lsr.l   #8,%d0
    move.b  %d0,cl_sbank
    move.b  %d0,cl_bank
    rts

cl_playing:
    jsr     cl_trk
| cl_playt (d0 = track): the same for any track
cl_playt:
    move.l  %d2,-(%sp)
    add.l   %d0,%d0
    move.l  %d0,%d1                     | d1 = 2 * track
    moveq   #0,%d0
    move.b  PLAY_BANK,%d0
    lsl.l   #8,%d0
    move.b  ACT_PAT,%d0                 | d0 = the playing pattern
    lea     cl_home,%a0
    moveq   #0,%d2
    move.b  (%a0,%d1.l),%d2
    lsl.l   #8,%d2
    move.b  1(%a0,%d1.l),%d2
    cmp.l   %d0,%d2
    bne.b   cy_out
    lea     cl_src,%a0
    moveq   #0,%d0
    move.b  (%a0,%d1.l),%d0
    lsl.l   #8,%d0
    move.b  1(%a0,%d1.l),%d0
cy_out:
    move.l  (%sp)+,%d2
    rts

| cl_classify(rec, midi) -> d0 = 0 empty, 1 half (data, no sample/note trigs), 2 full
cl_classify:
    movea.l 4(%sp),%a0
    move.l  (%a0),%d0                   | +0x00 note / sample trigs
    or.l    4(%a0),%d0
    bne.b   cf_full
    tst.l   8(%sp)
    bne.b   cf_midi
    lea     8(%a0),%a1                  | audio: +0x08..+0x37 trigless layers + recorder trigs
    moveq   #12,%d1
cf_lay:
    tst.l   (%a1)+
    bne.b   cf_half
    subq.l  #1,%d1
    bne.b   cf_lay
    lea     0x59(%a0),%a1               | locks: 64 x 32 B, 0xff = none (byte-aligned)
    bra.b   cf_locks
cf_midi:
    move.l  8(%a0),%d0                  | MIDI: +0x08 trigless layer
    or.l    12(%a0),%d0
    bne.b   cf_half
    lea     0x30(%a0),%a1
cf_locks:
    move.l  #0x800,%d1
cf_lk:
    moveq   #0,%d0
    move.b  (%a1)+,%d0
    cmpi.l  #0xff,%d0
    bne.b   cf_half
    subq.l  #1,%d1
    bne.b   cf_lk
    moveq   #0,%d0
    rts
cf_half:
    moveq   #1,%d0
    rts
cf_full:
    moveq   #2,%d0
    rts

| rebuild the 16 classes for (cl_bank, active track), then redraw the view and the grid
cl_refresh:
    lea     -16(%sp),%sp
    movem.l %d2-%d4/%a2,(%sp)
    jsr     cl_trk                      | another track than at the last refresh (TRACK, [MIDI], a group's
    cmp.b   cl_lastt,%d0                | view): the box goes to ITS sequence (the user, 2026-11-04 -- each
    beq.b   crf_same                    | track's box is where its playing sequence came from)
    jsr     cl_boxhome
crf_same:
    moveq   #0,%d0                      | the one cursor choke point: 16 slots
    move.b  cl_cur,%d0
    andi.l  #15,%d0
    move.b  %d0,cl_cur
crf_cur:
    jsr     cl_trk
    move.l  %d0,%d3                     | d3 = track
    move.b  %d0,cl_lastt
    move.l  %d3,-(%sp)
    jsr     cl_toff
    addq.l  #4,%sp
    move.l  %d0,%d4                     | d4 = record offset
    moveq   #0,%d2                      | d2 = pattern
crf_lp:
    move.l  %d2,-(%sp)
    moveq   #0,%d0
    move.b  cl_bank,%d0
    move.l  %d0,-(%sp)
    jsr     cl_slab
    addq.l  #8,%sp
    adda.l  %d4,%a0
    moveq   #0,%d0
    cmpi.l  #8,%d3
    scc     %d0                         | MIDI flag
    move.l  %d0,-(%sp)
    move.l  %a0,-(%sp)
    jsr     cl_classify
    addq.l  #8,%sp
    lea     cl_cls,%a0
    move.b  %d0,(%a0,%d2.l)
    addq.l  #1,%d2
    cmpi.l  #16,%d2
    bne.b   crf_lp
    movem.l (%sp),%d2-%d4/%a2
    lea     16(%sp),%sp
    jsr     cl_draw
    clr.l   -(%sp)
    jsr     LED_PAINT
    addq.l  #4,%sp
    rts

| ================================================================ loads
| cl_load(n): the box bank's pattern n onto the active track of the playing pattern; with a group,
| onto every member, each its own track of that pattern (scope §1.9)
cl_load:
    moveq   #0,%d0
    move.b  cl_sbank,%d0
    lsl.l   #8,%d0
    or.l    4(%sp),%d0                  | bank<<8 | pattern
    tst.b   cl_fn
    beq.b   cl_each
    ori.l   #0x10000,%d0                | [FUNC] held: FULL
|   fall through
| cl_each (d0 = code): cl_cueload(t, code, cued) on the active track, or on every member of the
| group (cl_gmask; none while [CUE] is held with no member picked). Keeps d2-d7/a2-a6.
cl_each:
    lea     -12(%sp),%sp
    movem.l %d2-%d4,(%sp)
    move.l  %d0,%d3                     | d3 = code
    jsr     cl_bbeg
    jsr     cl_targets
    move.l  %d0,%d4                     | d4 = the tracks
    moveq   #0,%d2
ea_l:
    btst    %d2,%d4
    beq.b   ea_n
    clr.l   -(%sp)                      | cued
    move.l  %d3,-(%sp)
    move.l  %d2,-(%sp)
    jsr     cl_cueload
    lea     12(%sp),%sp
ea_n:
    addq.l  #1,%d2
    cmpi.l  #16,%d2
    bne.b   ea_l
    jsr     cl_bend
    movem.l (%sp),%d2-%d4
    lea     12(%sp),%sp
    rts

| d0 = the tracks a load / restore acts on, bit t (MIDI 8..15): the group's members, or the active
| track. Uses d0, d1.
cl_targets:
    move.l  cl_gmask,%d0
    bne.b   tg_out
    jsr     cl_trk
    moveq   #1,%d1
    lsl.l   %d0,%d1
    move.l  %d1,%d0
tg_out:
    andi.l  #0xffff,%d0
    rts

| cl_cueload(t, code, now): source `code` (bank<<8 | pattern, SRC_SAVED<<8, SRC_ORIG<<8; + 0x10000 =
| FULL, with its machine / FX: audio only, a MIDI load always is) onto track t of the playing pattern. Stopped: at once. Running: cued (scope §1.5a), the sequencer tick lands
| it (cl_land / cl_wrap); now != 0 arms it at once: it lands at the track's next window start,
| phase-continuous ([FUNC]+[NO], O3).
cl_cueload:
    lea     -20(%sp),%sp
    movem.l %d2-%d5/%a2,(%sp)
    move.l  24(%sp),%d3                 | d3 = track
    move.l  28(%sp),%d2                 | d2 = code
    move.l  32(%sp),%d4                 | d4 = now
    move.l  %d2,%d5
    swap    %d5
    andi.l  #1,%d5                      | d5 = FULL (the MIDI side too since 2026-10-30: the user
                                        | wants SEQ vs FULL there as on the audio side)
    andi.l  #0xffff,%d2
    tst.l   RUNNING
    bne.b   lo_cue
    move.l  %d5,-(%sp)
    move.l  %d2,%d0
    andi.l  #0xff,%d0
    move.l  %d0,-(%sp)
    move.l  %d2,%d0
    lsr.l   #8,%d0
    move.l  %d0,-(%sp)
    move.l  %d3,-(%sp)
    jsr     cl_apply                    | at once
    lea     16(%sp),%sp
    tst.b   cl_bat
    beq.b   lo_post
    moveq   #1,%d0                      | a batch: its UI side once, at cl_bend
    lsl.l   %d3,%d0
    or.l    %d0,cl_batm
    bra.b   lo_out
lo_post:
    move.l  %d3,-(%sp)
    jsr     cl_post_ui
    addq.l  #4,%sp
    bra.b   lo_out
lo_cue:
    lea     cl_cue,%a2
|   re-picking the slot that already plays (its source, or the pattern's own slot) cancels the cue --
|   only while the track plays it unedited; an ALL load is always re-applied (its slice may differ).
|   (2026-11-02: a second temp reload after an edit was cancelled this way: toast, no data.)
    move.l  %d3,%d0
    jsr     cl_playt                    | d0 = playing
    cmp.l   %d2,%d0
    bne.b   lo_set
    tst.l   %d5
    bne.b   lo_set
    jsr     cl_asplays                  | d3 = track, d2 = code -> d0 = 0: the record equals the source
    tst.l   %d0
    beq.b   lo_cancel
lo_set:
    move.l  %d3,%d1
    add.l   %d1,%d1
    move.w  %d2,(%a2,%d1.l)             | cue[t] = code
    moveq   #0,%d0
    move.b  PLAY_BANK,%d0
    lsl.l   #8,%d0
    move.b  ACT_PAT,%d0
    lea     cl_cueh,%a0
    move.w  %d0,(%a0,%d1.l)             | the pattern it is aimed at
    lea     cl_cuef,%a0
    move.b  %d5,(%a0,%d3.l)
    lea     cl_arm,%a0
    move.b  %d4,(%a0,%d3.l)             | 0 = wait for the gate; 1 = armed already
    jsr     cl_count
    bra.b   lo_out
lo_cancel:
    move.l  %d3,%d1
    add.l   %d1,%d1
    moveq   #-1,%d0
    move.w  %d0,(%a2,%d1.l)
    lea     cl_arm,%a0
    clr.b   (%a0,%d3.l)
    jsr     cl_count
lo_out:
    movem.l (%sp),%d2-%d5/%a2
    lea     20(%sp),%sp
    rts

| cl_asplays (d3 = track, d2 = code bank<<8 | pattern / SRC_*<<8) -> d0 = 0 when the playing pattern's
| record of the track equals that source's record (cl_same: length / scale bytes aside), 1 otherwise or
| without a source. Uses d0, d1, a0, a1.
cl_asplays:
    moveq   #0,%d0
    move.b  %d2,%d0
    move.l  %d0,-(%sp)                  | spat
    move.l  %d2,%d0
    lsr.l   #8,%d0
    andi.l  #0xff,%d0
    move.l  %d0,-(%sp)                  | sbank
    move.l  %d3,-(%sp)
    jsr     cl_srcrec
    lea     12(%sp),%sp
    move.l  %a0,%d0
    beq.b   ap_ne
    move.l  %a0,-(%sp)                  | the source record
    moveq   #0,%d0
    move.b  ACT_PAT,%d0
    move.l  %d0,-(%sp)
    move.b  PLAY_BANK,%d0
    move.l  %d0,-(%sp)
    jsr     cl_slab
    addq.l  #8,%sp
    move.l  %a0,-(%sp)
    move.l  %d3,-(%sp)
    jsr     cl_toff
    addq.l  #4,%sp
    movea.l (%sp)+,%a0
    adda.l  %d0,%a0                     | a0 = the playing record
    movea.l (%sp)+,%a1
    move.l  %d3,%d0
    jmp     cl_same
ap_ne:
    moveq   #1,%d0
    rts

| cl_diff (d0 = track) -> d0 = 1 when the playing pattern's record of the track differs from its
| original (the load snapshot); 0 when equal or when there is no snapshot. Keeps d2-d7/a2-a6.
cl_diff:
    lea     -8(%sp),%sp
    movem.l %d2-%d3,(%sp)
    move.l  %d0,%d2
    jsr     cl_origok
    tst.l   %d0
    beq.b   df_out
    move.l  %d2,-(%sp)
    jsr     cl_toff
    addq.l  #4,%sp
    move.l  %d0,%d3                     | d3 = record offset
    move.l  %d1,-(%sp)                  | its length
    moveq   #0,%d0
    move.b  PLAY_BANK,%d0
    moveq   #0,%d1
    move.b  ACT_PAT,%d1
    jsr     cl_snapslab
    adda.l  %d3,%a0
    move.l  %a0,-(%sp)                  | the original record
    moveq   #0,%d0
    move.b  ACT_PAT,%d0
    move.l  %d0,-(%sp)
    move.b  PLAY_BANK,%d0
    move.l  %d0,-(%sp)
    jsr     cl_slab
    addq.l  #8,%sp
    adda.l  %d3,%a0                     | a0 = the playing record
    movea.l (%sp)+,%a1
    move.l  (%sp)+,%d0
    jsr     cl_cmpw
df_out:
    movem.l (%sp),%d2-%d3
    lea     8(%sp),%sp
    rts

| cl_restore (d0 = 0x10000: with its machine / FX, ORIG SEQ/MCH/FX): the active track's original
| back (cued like any load). Sequence only (and every MIDI restore): nothing if the sequence is
| original. With machine / FX: always (its Part slice may differ). With a group: every member its
| own original, by the same rule (scope §1.9, the user's choice).
cl_restore:
    lea     -12(%sp),%sp
    movem.l %d2-%d4,(%sp)
    move.l  %d0,%d3                     | d3 = 0 / 0x10000
    jsr     cl_bbeg
    jsr     cl_targets
    move.l  %d0,%d4
    moveq   #0,%d2
rs_l:
    btst    %d2,%d4
    beq.b   rs_n
    tst.l   %d3
    bne.b   rs_go
    move.l  %d2,%d0
    jsr     cl_diff
    tst.l   %d0
    beq.b   rs_n
rs_go:
    move.l  %d3,%d0
    ori.l   #SRC_ORIG<<8,%d0
    clr.l   -(%sp)
    move.l  %d0,-(%sp)
    move.l  %d2,-(%sp)
    jsr     cl_cueload
    lea     12(%sp),%sp
rs_n:
    addq.l  #1,%d2
    cmpi.l  #16,%d2
    bne.b   rs_l
    jsr     cl_bend
    movem.l (%sp),%d2-%d4
    lea     12(%sp),%sp
    rts

| cl_restorepat: ORIG PTN/PART (the user, 2026-10-29): the pattern you are on and its Part as
| loaded. Every track (all 16, whether changed or not) gets its original sequence AND its Part slice,
| cued like a load (one landing); the first of those landings also copies the Part bytes no track's
| slice holds (cl_slR, cl_pwhole), so the whole Part is as loaded; the pattern's own length / scale /
| mode come back with the last track (cl_back). Nothing without a snapshot.
cl_restorepat:
    jsr     cl_origok
    tst.l   %d0
    beq.w   rp_out
|   playing (the user, 2026-11-04): the pattern as loaded comes back AS A PATTERN CHANGE to itself --
|   DIRECT JUMP on: its jump (the next landing point, every track re-landed, its hand-off); off: stock's
|   switch (the CHAIN AFTER point / the pattern end, every track from its start, the Part applied by the
|   engine, START SILENT, the conditional counters reset). cl_self is the request: cl_sw6 / cl_scommit
|   (stock) or dj_selfvec (DIRECT JUMP) land it, cl_selfcopy puts the originals back at that point.
|   Stopped: at once, as before.
    tst.l   RUNNING
    beq.b   rp_now
    moveq   #1,%d0
    move.b  %d0,cl_self
.ifdef DJ_SELFVEC
    lea     cl_djvec,%a0
    move.l  %a0,DJ_SELFVEC
.endif
    rts
rp_now:
    moveq   #1,%d0
    move.b  %d0,cl_pwhole
    move.l  %d2,-(%sp)
    jsr     cl_bbeg
    moveq   #0,%d2
rp_l:
    clr.l   -(%sp)
    pea     0x10000+(SRC_ORIG<<8)
    move.l  %d2,-(%sp)
    jsr     cl_cueload
    lea     12(%sp),%sp
    addq.l  #1,%d2
    cmpi.l  #16,%d2
    bne.b   rp_l
    jsr     cl_bend
    move.l  (%sp)+,%d2
rp_out:
    rts

| cl_savet(t): what track t plays now -> its saved sequence (the temp save), with its resolved length
| / scale written into the copy's own bytes (a NORMAL pattern's are the pattern's)
cl_savet:
    lea     -12(%sp),%sp
    movem.l %d2-%d3/%a2,(%sp)
    move.l  16(%sp),%d2                 | d2 = track
    move.l  %d2,-(%sp)
    jsr     cl_toff
    addq.l  #4,%sp
    move.l  %d0,%d3                     | d3 = record offset (d1 = length)
    move.l  %d1,-(%sp)
    moveq   #0,%d0
    move.b  ACT_PAT,%d0
    move.l  %d0,-(%sp)
    move.b  PLAY_BANK,%d0
    move.l  %d0,-(%sp)
    jsr     cl_slab
    addq.l  #8,%sp
    movea.l %a0,%a2                     | a2 = the playing slab
    move.l  %a2,%d0
    add.l   %d3,%d0
    move.l  %d0,-(%sp)                  | src
    move.l  %d2,%d0
    move.l  #TRAC_A,%d1
    muls.l  %d1,%d0
    addi.l  #SAVED_BASE,%d0
    move.l  %d0,-(%sp)                  | dst = saved[t]
    jsr     MEMCPY
    move.l  (%sp),%a1                   | a1 = saved[t]
    lea     12(%sp),%sp
    movea.l %a2,%a0
    adda.l  #TRAILER,%a0
    tst.b   T_SMODE(%a0)
    bne.b   sv_valid                    | PER TRACK: the record's own bytes are its length / scale
    moveq   #0x50,%d0
    cmpi.l  #8,%d2
    bcs.b   sv_off
    moveq   #0x28,%d0
sv_off:
    adda.l  %d0,%a1
    move.b  T_LEN(%a0),%d0
    move.b  %d0,(%a1)
    move.b  T_SCALE(%a0),%d0
    move.b  %d0,1(%a1)
sv_valid:
    moveq   #0,%d0                      | the Part it plays with (a FULL reload brings its slice)
    move.b  PLAY_BANK,%d0
    moveq   #0,%d1
    move.b  ACT_PAT,%d1
    movea.l #BLOB,%a1
    jsr     cl_partin
    move.l  %d2,%d0
    move.l  #PARTSZ,%d1
    muls.l  %d1,%d0
    addi.l  #SAVEPART,%d0
    pea     PARTSZ
    move.l  %a0,-(%sp)
    move.l  %d0,-(%sp)
    jsr     MEMCPY
    lea     12(%sp),%sp
    lea     cl_svalid,%a0
    moveq   #1,%d0
    move.b  %d0,(%a0,%d2.l)
    tst.b   cl_namesok                  | and its name
    beq.b   sv_out
    moveq   #0,%d0
    move.b  PLAY_BANK,%d0
    lsl.l   #4,%d0
    moveq   #0,%d1
    move.b  ACT_PAT,%d1
    add.l   %d1,%d0
    lsl.l   #4,%d0
    add.l   %d2,%d0
    jsr     cl_nptr
    move.l  %d2,%d0
    moveq   #NAME_W,%d1
    muls.l  %d1,%d0
    movea.l #SNAMES,%a1
    adda.l  %d0,%a1
    moveq   #NAME_W,%d0
sv_nl:
    move.b  (%a0)+,(%a1)+
    subq.l  #1,%d0
    bne.b   sv_nl
sv_out:
    movem.l (%sp),%d2-%d3/%a2
    lea     12(%sp),%sp
    rts

| ================================================================ temp save / reload
| The user, 2026-11-02: TRACK held + [YES] = temp save, TRACK held + [NO] = temp reload, outside and
| inside Clyps. The TRACK-held sub-map 0x400d164a (both base keymaps' TRACK records use it; Clyps' TRACK
| records carry none, so it chains there too) has its [YES] / [NO] records' press + release fields,
| stock's ARM / DISARM REC TRK 0x400834d8 / 0x40083488, pointed here (build_clyps.py SUBMAP). Stock's
| ARM / DISARM still run while the Recording Setup menu is open (its window 0x460d10cc), and only then.
| Every held track (0x460fab40, bit t; the MIDI tracks while they are showing); one toast, "TEMP TRK
| SAVED" / "TEMP TRK RELOADED" (the user, 2026-11-02: no track numbers). A reload is FULL: the sequence and
| the track's Part slice as saved, landing at the track's next step (in step) while playing.
cl_tsy:
    moveq   #0,%d1
    bra.b   cl_tsyn
cl_tsn:
    moveq   #1,%d1
cl_tsyn:
    tst.l   RSETUP_WIN
    beq.b   ty_ours
    tst.l   %d1                         | Recording Setup open: stock's own, untouched
    bne.b   ty_dis
    jmp     ARM_REC
ty_dis:
    jmp     DISARM_REC
ty_ours:
    move.l  8(%sp),%d0
    cmpi.l  #1,%d0
    bne.w   ty_out                      | the release: nothing
    clr.l   SEL_PEND                    | the TRACK keys' release then selects no track (the user, 2026-11-02)
    lea     -16(%sp),%sp
    movem.l %d2-%d5,(%sp)
    move.l  %d1,%d4                     | d4 = 0 save, 1 reload
    move.l  HELD_TRK,%d3
    andi.l  #0xff,%d3                   | d3 = the held tracks
    move.l  %d3,%d0
    moveq   #0,%d1
    jsr     cl_popc                     | d1 = how many
    tst.l   %d1
    beq.w   ty_done
    jsr     cl_bbeg
    moveq   #0,%d2
    moveq   #0,%d5                      | d5 = how many were done
ty_l:
    btst    %d2,%d3
    beq.b   ty_n
    move.l  %d2,%d0
    tst.l   MIDI_MODE
    beq.b   ty_t
    addq.l  #8,%d0
ty_t:
    jsr     cl_tsone                    | d0 = track, d4 = kind -> d0 = 1 if done
    add.l   %d0,%d5
ty_n:
    addq.l  #1,%d2
    cmpi.l  #8,%d2
    bne.b   ty_l
    jsr     cl_bend
    pea     TOAST_DUR                   | one toast, whatever the tracks (the user, 2026-11-02)
    pea     cl_s_ttsv                   | "TEMP TRK SAVED" (81 px)
    tst.l   %d4
    beq.b   ty_toast
    move.l  #cl_s_ttrl,(%sp)            | "TEMP TRK RELOADED" (99 px)
    tst.l   %d5
    bne.b   ty_toast
    move.l  #cl_s_savef2,(%sp)          | nothing saved for any held track: "SAVE FIRST!"
ty_toast:
    jsr     TOAST
    addq.l  #8,%sp
ty_view:
    tst.b   cl_open                     | inside Clyps: the view follows (SAVED TRK, the grid)
    beq.b   ty_done
    jsr     cl_refresh
ty_done:
    movem.l (%sp),%d2-%d5
    lea     16(%sp),%sp
ty_out:
    rts

| cl_tsone (d0 = track 0..15, d4 = 0 save / 1 reload): that track's temp save or reload (no toast).
| d0 = 1 if something was saved / reloaded. Keeps d2-d7 / a2-a6.
cl_tsone:
    move.l  %d2,-(%sp)
    move.l  %d0,%d2                     | d2 = track 0..15
ts_a:
    tst.l   %d4
    bne.b   ts_no
    move.l  %d2,-(%sp)                  | save
    jsr     cl_savet
    addq.l  #4,%sp
    bra.b   ts_done
ts_no:
    lea     cl_svalid,%a0               | reload
    tst.b   (%a0,%d2.l)
    beq.b   ts_none
    pea     1                           | armed at once: its next step, in step
    pea     0x10000+(SRC_SAVED<<8)      | FULL: the sound as saved -- sequence, machine, FX, pages,
                                        | scene locks, designer (the user, 2026-10-29)
    move.l  %d2,-(%sp)
    jsr     cl_cueload
    lea     12(%sp),%sp
ts_done:
    moveq   #1,%d0
    move.l  (%sp)+,%d2
    rts
ts_none:
    moveq   #0,%d0
    move.l  (%sp)+,%d2
    rts
    rts

| The masked bank loader 0x400905d4(ctx, mask, ...) (storage task): bit n of mask = bank n is read
| from the card. Every LOAD PROJECT goes through it (measured, emulator: mask 0xffff on a first
| load from 0x400853d8, 0xfffe on the power-on / reload resume from 0x40084d60, whose current bank
| comes back from the SRAM mirror instead: cl_sramrest). Entry: the banks being read lose their
| snapshot, and eight banks or more = a project load: the saved sequences, the provenance and every
| cue go (scope §1.6). The return goes through cl_ldexit, which snapshots every bank just read: the
| new originals. Then the loader's first two instructions, replayed.
cl_projload:
    move.l  8(%sp),%d0
    andi.l  #0xffff,%d0                 | d0 = the bank mask
    move.w  %d0,cl_ldmask
    moveq   #0,%d1
    move.w  cl_snapok,%d1
    not.l   %d0
    and.l   %d0,%d1
    move.w  %d1,cl_snapok               | no originals for these banks until the load is done
    moveq   #0,%d0
    move.w  cl_ldmask,%d0
    moveq   #0,%d1                      | d1 = banks in it
pl_cnt:
    tst.l   %d0
    beq.b   pl_counted
    move.l  %d0,%a0
    subq.l  #1,%d0
    move.l  %a0,-(%sp)
    and.l   (%sp)+,%d0                  | clear the lowest set bit
    addq.l  #1,%d1
    bra.b   pl_cnt
pl_counted:
    cmpi.l  #8,%d1
    bcs.w   pl_go
    movea.l #NAMES,%a0                  | a project load: the names go (they live in memory only, for
    move.l  #(4096*NAME_W+16*NAME_W)/4,%d0 | now) -- every sequence's and every saved one's
pl_n:
    clr.l   (%a0)+
    subq.l  #1,%d0
    bne.b   pl_n
    moveq   #1,%d0
    move.b  %d0,cl_namesok
    lea     cl_svalid,%a0               | ... and no saved sequence survives
    clr.l   (%a0)+
    clr.l   (%a0)+
    clr.l   (%a0)+
    clr.l   (%a0)+
    lea     cl_home,%a0
    moveq   #-1,%d1
    moveq   #8,%d0
pl_h:
    move.l  %d1,(%a0)+
    subq.l  #1,%d0
    bne.b   pl_h
    clr.b   cl_flash
    moveq   #0,%d0
    move.b  cl_nproj,%d0
    addq.l  #1,%d0
    move.b  %d0,cl_nproj
    jsr     cl_dropall
pl_go:
    move.l  (%sp),cl_ldret              | the loader returns through cl_ldexit
    move.l  #cl_ldexit,(%sp)
    lea     -328(%sp),%sp               | displaced
    movem.l %d2-%d7/%a2-%a6,(%sp)
    jmp     BANKS_RESUME

| the masked loader's return: snapshot every bank it read, then back to its caller (d0 kept)
cl_ldexit:
    lea     -12(%sp),%sp
    movem.l %d0/%d2-%d3,(%sp)
.ifndef NOFILES
    jsr     cl_nload_all                | the names from the card first (they are part of the original)
.endif
    moveq   #0,%d2                      | d2 = bank
    moveq   #0,%d3
    move.w  cl_ldmask,%d3
le_l:
    btst    %d2,%d3
    beq.b   le_n
    move.l  %d2,-(%sp)
    jsr     cl_snapbank
    addq.l  #4,%sp
le_n:
    addq.l  #1,%d2
    cmpi.l  #16,%d2
    bne.b   le_l
    jsr     cl_presave                  | the temp saves = the originals (the user, 2026-11-02)
    movem.l (%sp),%d0/%d2-%d3
    lea     12(%sp),%sp
    move.l  cl_ldret,-(%sp)
    rts

| 0x40025808 `jsr 0x4000fbb4` (the power-on resume: the current bank's unsaved edits, SRAM -> RAM)
| -> here: the same call, then that bank's snapshot (whatever wrote the bank last, its snapshot is
| taken last)
cl_sramrest:
    move.l  4(%sp),-(%sp)
    jsr     SRAM_RESTORE
    addq.l  #4,%sp
    move.l  4(%sp),-(%sp)
    jsr     cl_snapbank
    addq.l  #4,%sp
    jmp     cl_presave                  | the temp saves = the originals (the user, 2026-11-02)

| cl_snapmask(mask): those banks -> their snapshots (SAVE BANK); the temp saves too when the playing bank
| is one of them
cl_snapmask:
    lea     -8(%sp),%sp
    movem.l %d2-%d3,(%sp)
    move.l  12(%sp),%d3
    moveq   #0,%d2
sm_l:
    btst    %d2,%d3
    beq.b   sm_n
    move.l  %d2,-(%sp)
    jsr     cl_snapbank
    addq.l  #4,%sp
sm_n:
    addq.l  #1,%d2
    cmpi.l  #16,%d2
    bne.b   sm_l
    moveq   #0,%d0
    move.b  PLAY_BANK,%d0
    btst    %d0,%d3
    beq.b   sm_out
    jsr     cl_presave
sm_out:
    movem.l (%sp),%d2-%d3
    lea     8(%sp),%sp
    rts

| cl_snapall: every bank -> its snapshot, then the temp saves (cl_presave)
cl_snapall:
    move.l  %d2,-(%sp)
    moveq   #0,%d2
sa_l:
    move.l  %d2,-(%sp)
    jsr     cl_snapbank
    addq.l  #4,%sp
    addq.l  #1,%d2
    cmpi.l  #16,%d2
    bne.b   sa_l
    move.l  (%sp)+,%d2
|   fall through: the temp saves follow the originals
| cl_presave: every track's temp save := what it plays now (its record + the Part), i.e. its original
| at the points the originals are taken -- power-on, a project load / reload, SAVE PROJECT, every bank
| reset (the user, 2026-11-02: a temp reload works even before any temp save). Data only (no UI).
cl_presave:
    move.l  %d2,-(%sp)
    moveq   #0,%d2
ps_l:
    move.l  %d2,-(%sp)
    jsr     cl_savet
    addq.l  #4,%sp
    addq.l  #1,%d2
    cmpi.l  #16,%d2
    bne.b   ps_l
    move.l  (%sp)+,%d2
    rts

| cl_snapbank(bank): the bank as it is now -> its snapshot (the originals); mark it valid
cl_snapbank:
    pea     BANKSZ                      | its slabs + working Parts (BANKSZ < the live BANKSTRIDE)
    move.l  8(%sp),%d0
    move.l  #BANKSTRIDE,%d1
    muls.l  %d1,%d0
    movea.l #BLOB,%a0
    pea     (%a0,%d0.l)                 | src: the live bank
    move.l  12(%sp),%d0
    move.l  #BANKSZ,%d1
    muls.l  %d1,%d0
    movea.l #SNAPB,%a0
    pea     (%a0,%d0.l)                 | dst: its snapshot
    jsr     MEMCPY
    lea     12(%sp),%sp
    tst.b   cl_namesok                  | the bank's names as loaded, too (ORIG restores them)
    beq.b   sb_ok
    move.l  4(%sp),%d0
    move.l  #256*NAME_W,%d1
    muls.l  %d1,%d0
    pea     256*NAME_W
    movea.l #NAMES,%a0
    pea     (%a0,%d0.l)
    movea.l #NAMESNAP,%a0
    pea     (%a0,%d0.l)
    jsr     MEMCPY
    lea     12(%sp),%sp
sb_ok:
    move.l  4(%sp),%d1
    moveq   #0,%d0
    move.w  cl_snapok,%d0
    bset    %d1,%d0
    move.w  %d0,cl_snapok
    rts

    ROMSEC
| cl_apply(t, sbank, spat, full) -> d0 = 1 copied, 0 not (the playing pattern's own slot, or no saved
| sequence / original to put back). The record, its length/scale (scope §4.6) and the provenance. Writes RAM only (slab + our state): safe in
| the sequencer tick. sbank = SRC_SAVED / SRC_ORIG: the saved sequence / the original of t.
cl_apply:
    lea     -40(%sp),%sp
    movem.l %d2-%d7/%a2-%a5,(%sp)
    move.l  44(%sp),%d6                 | d6 = track 0..15
    move.l  48(%sp),%d2                 | d2 = source bank (or SRC_*)
    move.l  52(%sp),%d7                 | d7 = source pattern
    move.l  %d6,-(%sp)
    jsr     cl_toff
    addq.l  #4,%sp
    move.l  %d0,%d4                     | d4 = record offset
    move.l  %d1,%d5                     | d5 = record length
    moveq   #0,%d0
    move.b  ACT_PAT,%d0
    move.l  %d0,-(%sp)
    move.b  PLAY_BANK,%d0
    move.l  %d0,-(%sp)
    jsr     cl_slab
    addq.l  #8,%sp
    movea.l %a0,%a2                     | a2 = destination slab
    cmpi.l  #16,%d2
    bcc.b   ap_src                      | a saved sequence / an original: never the own slot
    move.l  %d7,-(%sp)
    move.l  %d2,-(%sp)
    jsr     cl_slab
    addq.l  #8,%sp
    cmpa.l  %a2,%a0
    beq.w   ap_own                      | the playing pattern's own slot: nothing to copy
ap_src:
    move.l  %d7,-(%sp)
    move.l  %d2,-(%sp)
    move.l  %d6,-(%sp)
    jsr     cl_srcrec
    lea     12(%sp),%sp
    move.l  %a0,%d3
    beq.w   ap_none
    movea.l %a0,%a3                     | a3 = the source record
    movea.l %d0,%a4                     | a4 = its length
    movea.l %d1,%a5                     | a5 = its scale
ap_copy:
    move.l  %d5,-(%sp)
    move.l  %a3,-(%sp)
    move.l  %a2,%d0
    add.l   %d4,%d0
    move.l  %d0,-(%sp)
    jsr     MEMCPY
    lea     12(%sp),%sp
    jsr     cl_nload                    | the name comes with the sequence
    tst.l   56(%sp)
    beq.b   ap_seq
    jsr     cl_fullone                  | FULL: its machine / FX too
ap_seq:
|   length / scale: the source's, resolved. Track len/scale bytes: audio +0x50/+0x51, MIDI +0x28/+0x29.
    moveq   #0x50,%d3
    cmpi.l  #8,%d6
    bcs.b   ap_lsoff
    moveq   #0x28,%d3
ap_lsoff:
    add.l   %d4,%d3                     | d3 = offset of this record's len byte
    lea     (%a2,%d3.l),%a0             | a0 -> the destination record's len byte
    cmpi.l  #SRC_ORIG,%d2
    bne.b   ap_wlen
    movea.l %a2,%a1                     | putting an original back onto a NORMAL pattern: its own
    adda.l  #TRAILER,%a1                | bytes stand (the slab comes back byte for byte)
    tst.b   T_SMODE(%a1)
    beq.b   ap_back
ap_wlen:
    move.l  %a4,%d0
    move.b  %d0,(%a0)
    move.l  %a5,%d0
    move.b  %d0,1(%a0)
    cmpi.l  #SRC_ORIG,%d2
    bne.b   ap_dst
ap_back:
    jsr     cl_back                     | put back: with every track original again, the pattern's
    move.l  %d6,%d0                     | length / scale / mode too; provenance off
    add.l   %d0,%d0
    lea     cl_home,%a0
    moveq   #-1,%d1
    move.b  %d1,(%a0,%d0.l)
    moveq   #1,%d0
    bra.b   ap_out
ap_dst:
    movea.l %a2,%a1
    adda.l  #TRAILER,%a1                | a1 -> the destination trailer
    tst.b   T_SMODE(%a1)
    bne.b   ap_prov                     | PER TRACK destination: done
    move.b  (%a0),%d0
    cmp.b   T_LEN(%a1),%d0
    bne.b   ap_conv
    move.b  1(%a0),%d0
    cmp.b   T_SCALE(%a1),%d0
    beq.b   ap_prov                     | NORMAL, same len/scale: nothing to convert
ap_conv:
    jsr     cl_convert                  | a2 = slab, d3 = len-byte offset (kept)
ap_prov:
|   provenance: this track now plays (sbank, spat) on the playing pattern
    move.l  %d6,%d0
    add.l   %d0,%d0
    lea     cl_src,%a0
    move.b  %d2,(%a0,%d0.l)
    move.b  %d7,1(%a0,%d0.l)
    lea     cl_home,%a0
    move.b  PLAY_BANK,%d1
    move.b  %d1,(%a0,%d0.l)
    move.b  ACT_PAT,%d1
    move.b  %d1,1(%a0,%d0.l)
    moveq   #1,%d0
    bra.b   ap_out
ap_own:
    move.l  %d6,%d0                     | back to its own: provenance off
    add.l   %d0,%d0
    lea     cl_home,%a0
    moveq   #-1,%d1
    move.b  %d1,(%a0,%d0.l)
ap_none:
    moveq   #0,%d0
ap_out:
    movem.l (%sp),%d2-%d7/%a2-%a5
    lea     40(%sp),%sp
    rts

| cl_nload (d6 = t, d2 = sbank or SRC_*, d7 = spat): the source's name -> the playing pattern's
| name of t (a slot's, the saved sequence's, or the one it had when loaded). Keeps d2-d7/a2-a6.
cl_nload:
    tst.b   cl_namesok
    beq.b   nl_out
    moveq   #0,%d0                      | the destination
    move.b  PLAY_BANK,%d0
    lsl.l   #4,%d0
    moveq   #0,%d1
    move.b  ACT_PAT,%d1
    add.l   %d1,%d0
    lsl.l   #4,%d0
    add.l   %d6,%d0
    moveq   #NAME_W,%d1
    muls.l  %d1,%d0
    movea.l #NAMES,%a1
    adda.l  %d0,%a1                     | a1 = the destination name
    cmpi.l  #SRC_SAVED,%d2
    beq.b   nl_saved
    cmpi.l  #SRC_ORIG,%d2
    beq.b   nl_orig
    move.l  %d2,%d0                     | a slot
    lsl.l   #4,%d0
    add.l   %d7,%d0
    lsl.l   #4,%d0
    add.l   %d6,%d0
    moveq   #NAME_W,%d1
    muls.l  %d1,%d0
    movea.l #NAMES,%a0
    adda.l  %d0,%a0
    bra.b   nl_cp
nl_saved:
    move.l  %d6,%d0
    moveq   #NAME_W,%d1
    muls.l  %d1,%d0
    movea.l #SNAMES,%a0
    adda.l  %d0,%a0
    bra.b   nl_cp
nl_orig:
    move.l  %a1,%d0                     | the same index in the names as loaded
    subi.l  #NAMES,%d0
    movea.l #NAMESNAP,%a0
    adda.l  %d0,%a0
nl_cp:
    cmpa.l  %a0,%a1
    beq.b   nl_out                      | its own slot
    moveq   #NAME_W,%d0
nl_l:
    move.b  (%a0)+,(%a1)+
    subq.l  #1,%d0
    bne.b   nl_l
nl_out:
    rts


| ================================================================ FULL loads (scope §1.7)
| A FULL load carries the track's Part slice with its sequence: what stock's TRACK COPY / PASTE
| carries (machine, FX, levels, every page), plus its 16 scene-lock rows, per-scene bytes and LFO
| designer. It is written into the Part of the playing pattern and published for that one track
| (audio: stock's TRK_APPLY; MIDI: cl_mapply), at the landing tick like the sequence. The UI tail
| then owes the SRAM mirror, the edited flags, the PICKUP setup and the page redraw (cl_postpart).
| Audio: [FUNC] + trig / [FUNC]+[YES]. MIDI: every load (the user, 2026-10-28).

| cl_partin (a1 = BLOB or SNAPB, d0 = bank, d1 = pattern) -> a0 = the pattern's Part in that
| image, d0 = its index 0..3. Uses d0-d1/a0-a1.
cl_partin:
    move.l  %d2,-(%sp)
    move.l  #BANKSTRIDE,%d2
    cmpa.l  #SNAPB,%a1
    bne.b   pi_live
    move.l  #BANKSZ,%d2                 | the snapshot's banks are shorter (BANKSZ)
pi_live:
    muls.l  %d0,%d2
    adda.l  %d2,%a1                     | a1 = the bank
    move.l  #PATSTRIDE,%d2
    muls.l  %d1,%d2
    movea.l %a1,%a0
    adda.l  %d2,%a0
    adda.l  #TRAILER,%a0
    moveq   #0,%d0
    move.b  T_PART(%a0),%d0
    andi.l  #3,%d0
    move.l  #PARTSZ,%d2
    muls.l  %d0,%d2
    adda.l  #PART_OFF,%a1
    lea     (%a1,%d2.l),%a0
    move.l  (%sp)+,%d2
    rts

| cl_slice(t, dst Part, src Part): track t's slice (cl_slA / cl_slM: off, stride, size, count,
| step; ends with 0xffff). Uses d0-d1/a0-a1.
| cl_slrest(t, dst, src): the Part bytes no track's slice holds (cl_slR; t unused). Same frame.
cl_slrest:
    lea     -20(%sp),%sp
    movem.l %d2-%d5/%a2,(%sp)
    moveq   #0,%d2
    lea     cl_slR,%a2
    bra.b   sc_seg
cl_slice:
    lea     -20(%sp),%sp
    movem.l %d2-%d5/%a2,(%sp)
    move.l  24(%sp),%d2
    lea     cl_slA,%a2
    cmpi.l  #8,%d2
    bcs.b   sc_seg
    subq.l  #8,%d2
    lea     cl_slM,%a2
sc_seg:
    moveq   #0,%d0
    move.w  (%a2)+,%d0                  | offset
    cmpi.l  #0xffff,%d0
    beq.b   sc_out
    moveq   #0,%d1
    move.w  (%a2)+,%d1                  | stride
    muls.l  %d2,%d1
    add.l   %d1,%d0                     | d0 = offset + stride * t
    moveq   #0,%d3
    move.w  (%a2)+,%d3                  | size
    moveq   #0,%d4
    move.w  (%a2)+,%d4                  | count
    moveq   #0,%d1
    move.w  (%a2)+,%d1                  | step
sc_rep:
    movea.l 28(%sp),%a0
    adda.l  %d0,%a0
    movea.l 32(%sp),%a1
    adda.l  %d0,%a1
    move.l  %d3,%d5
sc_b:
    move.b  (%a1)+,(%a0)+
    subq.l  #1,%d5
    bne.b   sc_b
    add.l   %d1,%d0
    subq.l  #1,%d4
    bne.b   sc_rep
    bra.b   sc_seg
sc_out:
    movem.l (%sp),%d2-%d5/%a2
    lea     20(%sp),%sp
    rts

| cl_fullone (d6 = t, d2 = sbank or SRC_*, d7 = spat): the source's slice of t -> the playing
| pattern's Part, published for t. Sources: a slot's Part; SRC_ORIG: the playing pattern's Part as
| loaded (the snapshot); SRC_SAVED: the Part saved with t's saved sequence. Keeps d2-d7/a2-a6.
cl_fullone:
    lea     -12(%sp),%sp
    movem.l %d4/%a2-%a3,(%sp)
    cmpi.l  #SRC_SAVED,%d2
    beq.b   fo_saved
    cmpi.l  #SRC_ORIG,%d2
    beq.b   fo_orig
    move.l  %d2,%d0
    move.l  %d7,%d1
    movea.l #BLOB,%a1
    bsr.w   cl_partin
    bra.b   fo_src
fo_saved:
    lea     cl_svalid,%a0
    tst.b   (%a0,%d6.l)
    beq.w   fo_out
    move.l  %d6,%d0
    move.l  #PARTSZ,%d1
    muls.l  %d1,%d0
    movea.l #SAVEPART,%a0
    adda.l  %d0,%a0
    bra.b   fo_src
fo_orig:
    jsr     cl_origok
    tst.l   %d0
    beq.w   fo_out
    moveq   #0,%d0
    move.b  PLAY_BANK,%d0
    moveq   #0,%d1
    move.b  ACT_PAT,%d1
    movea.l #SNAPB,%a1
    bsr.w   cl_partin
fo_src:
    movea.l %a0,%a3                     | a3 = the source Part
    moveq   #0,%d0
    move.b  PLAY_BANK,%d0
    moveq   #0,%d1
    move.b  ACT_PAT,%d1
    movea.l #BLOB,%a1
    bsr.w   cl_partin
    movea.l %a0,%a2                     | a2 = the playing pattern's Part
    move.l  %d0,%d4                     | d4 = its index
|   audio: a new machine restarts the voice (as stock's machine edit, 0x400973b4) and owes the
|   PICKUP setup (UI tail)
    cmpi.l  #8,%d6
    bcc.b   fo_copy
    move.b  0x22(%a2,%d6.l),%d0
    cmp.b   0x22(%a3,%d6.l),%d0
    beq.b   fo_copy
    moveq   #1,%d0
    lsl.l   %d6,%d0
    move.b  ENG_RESTART,%d1
    or.l    %d1,%d0
    move.b  %d0,ENG_RESTART
    lea     cl_postm,%a0
    moveq   #1,%d0
    move.b  %d0,(%a0,%d6.l)
fo_copy:
    move.l  %a3,-(%sp)
    move.l  %a2,-(%sp)
    move.l  %d6,-(%sp)
    bsr.w   cl_slice
    cmpi.l  #SRC_ORIG,%d2               | ORIG PTN/PART: the first landing brings the rest of the
    bne.b   fo_norest                   | Part too (cl_restorepat)
    tst.b   cl_pwhole
    beq.b   fo_norest
    clr.b   cl_pwhole
    moveq   #1,%d0
    move.b  %d0,cl_wpart                | the UI side owes the whole Part's mirror
    bsr.w   cl_slrest
fo_norest:
    lea     12(%sp),%sp
    move.l  %d6,%d0                     | publish it: this track only
    cmpi.l  #8,%d0
    bcs.b   fo_t
    subq.l  #8,%d0
fo_t:
    move.l  %d0,-(%sp)                  | t / m
    move.l  %d4,-(%sp)                  | part
    moveq   #0,%d0
    move.b  PLAY_BANK,%d0
    move.l  %d0,-(%sp)
    cmpi.l  #8,%d6
    bcc.b   fo_m
    jsr     TRK_APPLY
    bra.b   fo_pub
fo_m:
    bsr.w   cl_mapply
fo_pub:
    lea     12(%sp),%sp
    lea     cl_postf,%a0
    moveq   #1,%d0
    move.b  %d0,(%a0,%d6.l)             | the UI side owes its part (cl_postpart)
fo_out:
    movem.l (%sp),%d4/%a2-%a3
    lea     12(%sp),%sp
    rts

| cl_mapply(bank, part, m): one MIDI track's Part values -> the engine: stock's whole-Part apply
| 0x40009094 does this for every m (0x400094b0..0x400095e0), RAM writes only.
cl_mapply:
    lea     -20(%sp),%sp
    movem.l %d2-%d4/%a2-%a3,(%sp)
    move.l  24(%sp),%d0                 | bank
    move.l  28(%sp),%d1                 | part
    move.l  32(%sp),%d2                 | m
    move.l  #BANKSTRIDE,%d3
    muls.l  %d0,%d3
    movea.l #BLOB+PART_OFF,%a2
    adda.l  %d3,%a2
    move.l  #PARTSZ,%d3
    muls.l  %d1,%d3
    adda.l  %d3,%a2                     | a2 = the Part
    moveq   #68,%d3
    muls.l  %d2,%d3
    movea.l #MENG,%a0
    adda.l  %d3,%a0                     | a0 = the engine's record m
    move.l  %d2,%d3
    lsl.l   #5,%d3
    movea.l %a2,%a1
    adda.l  #0x3e2,%a1
    adda.l  %d3,%a1                     | page values, 32 B
    moveq   #32,%d4
cm_p:
    move.b  (%a1)+,(%a0)+
    subq.l  #1,%d4
    bne.b   cm_p
    moveq   #36,%d3
    muls.l  %d2,%d3
    movea.l %a2,%a1
    adda.l  #0x4e2,%a1
    adda.l  %d3,%a1                     | setup, 36 B
    movea.l %a1,%a3
    adda.l  #9,%a3                      | a3 = its 3 LFO waves
    moveq   #36,%d4
cm_s:
    move.b  (%a1)+,(%a0)+
    subq.l  #1,%d4
    bne.b   cm_s
    moveq   #0,%d4                      | each LFO on a designer wave (> 10): its 16 B and slope
cm_d:
    move.b  (%a3,%d4.l),%d0
    extb.l  %d0
    moveq   #10,%d1
    cmp.l   %d1,%d0
    ble.b   cm_dn
    subi.l  #11,%d0                     | d0 = the designer it uses
    movea.l %a2,%a1
    adda.l  #0x1792,%a1
    move.l  %d0,%d1
    lsl.l   #4,%d1
    adda.l  %d1,%a1
    move.l  %d2,%d1                     | d1 = 3m + i
    add.l   %d1,%d1
    add.l   %d2,%d1
    add.l   %d4,%d1
    movea.l #MDES,%a0
    move.l  %d1,%d3
    lsl.l   #4,%d3
    adda.l  %d3,%a0
    moveq   #16,%d3
cm_w:
    move.b  (%a1)+,(%a0)+
    subq.l  #1,%d3
    bne.b   cm_w
    movea.l %a2,%a1
    adda.l  #0x1812,%a1
    add.l   %d0,%d0
    adda.l  %d0,%a1
    movea.l #MSLP,%a0
    add.l   %d1,%d1
    adda.l  %d1,%a0
    move.w  (%a1),(%a0)
cm_dn:
    addq.l  #1,%d4
    cmpi.l  #3,%d4
    bne.b   cm_d
    movea.l #MBANK,%a0
    move.l  24(%sp),%d0
    move.b  %d0,(%a0,%d2.l)
    move.l  28(%sp),%d0
    move.b  %d0,8(%a0,%d2.l)
    move.l  %d2,%d0
    lsl.l   #2,%d0
    movea.l #MZERO,%a0
    clr.l   (%a0,%d0.l)
    movem.l (%sp),%d2-%d4/%a2-%a3
    lea     20(%sp),%sp
    rts

| the slices (scope §1.7): off, stride, size, count, step
cl_slA:
    .short 0x000, 1, 1, 1, 0            | FX1
    .short 0x008, 1, 1, 1, 0            | FX2
    .short 0x012, 2, 2, 1, 0            | levels
    .short 0x022, 1, 1, 1, 0            | machine
    .short 0x02a, 30, 30, 1, 0          | machine page 1 (all 5 machines)
    .short 0x1da, 30, 30, 1, 0          | machine page 2
    .short 0x11a, 24, 24, 1, 0          | AMP / LFO / FX1 / FX2 page 1
    .short 0x2f2, 30, 30, 1, 0          | LFO, AMP / FX page 2, MULT / TRIG
    .short 0x2ca, 5, 5, 1, 0            | slot record
    .short 0x602, 12, 12, 1, 0          | recorder setup
    .short 0x662, 32, 32, 16, 0x100     | 16 scene-lock rows
    .short 0x1662, 1, 1, 16, 10         | per-scene bytes
    .short 0x1702, 16, 16, 1, 0         | LFO designer
    .short 0x1782, 2, 2, 1, 0           | ... its slope
    .short 0xffff
cl_slM:
    .short 0x3e2, 32, 32, 1, 0          | page values
    .short 0x4e2, 36, 36, 1, 0          | setup: channel, bank, program, ...
    .short 0x1792, 16, 16, 1, 0         | LFO designer
    .short 0x1812, 2, 2, 1, 0           | ... its slope
    .short 0xffff
cl_slR:                                 | the rest of a Part (in no track's slice; measured)
    .short 0x010, 0, 2, 1, 0
    .short 0x166a, 0, 2, 16, 10         | per-scene bytes 8..9
    .short 0x1822, 0, 144, 1, 0         | the Part's tail
    .short 0xffff
    .align 2

| cl_srcrec(t, sbank, spat) -> a0 = the source record (0 = none), d0 = its resolved length, d1 =
| its resolved scale. sbank 0..15: a slot (a NORMAL pattern's length / scale are the pattern's);
| SRC_SAVED: saved[t] (resolved when saved); SRC_ORIG: t's record in the playing pattern's load
| snapshot (resolved through that snapshot's trailer). Uses d0-d1/a0-a1 only.
cl_srcrec:
    move.l  8(%sp),%d0
    cmpi.l  #SRC_SAVED,%d0
    beq.b   sr_saved
    cmpi.l  #SRC_ORIG,%d0
    beq.b   sr_orig
    move.l  4(%sp),-(%sp)
    jsr     cl_toff
    addq.l  #4,%sp
    move.l  %d0,-(%sp)                  | the record offset
    move.l  16(%sp),-(%sp)              | spat
    move.l  16(%sp),-(%sp)              | sbank
    jsr     cl_slab
    addq.l  #8,%sp
    movea.l %a0,%a1
    adda.l  #TRAILER,%a1                | a1 -> the source trailer
    adda.l  (%sp)+,%a0                  | a0 -> the source record
    tst.b   T_SMODE(%a1)
    bne.b   sr_rec                      | PER TRACK: the record's own bytes
    moveq   #0,%d0
    move.b  T_LEN(%a1),%d0
    moveq   #0,%d1
    move.b  T_SCALE(%a1),%d1
    rts
sr_saved:
    move.l  4(%sp),%d0
    lea     cl_svalid,%a0
    tst.b   (%a0,%d0.l)
    beq.b   sr_none
    move.l  #TRAC_A,%d1
    muls.l  %d1,%d0
    movea.l #SAVED_BASE,%a0
    adda.l  %d0,%a0
    bra.b   sr_rec
sr_orig:
    jsr     cl_origok
    tst.l   %d0
    beq.b   sr_none
    move.l  4(%sp),-(%sp)
    jsr     cl_toff
    addq.l  #4,%sp
    move.l  %d0,-(%sp)                  | the record offset
    moveq   #0,%d0
    move.b  PLAY_BANK,%d0
    moveq   #0,%d1
    move.b  ACT_PAT,%d1
    jsr     cl_snapslab                 | a0 = the playing pattern's slab, as loaded
    movea.l %a0,%a1
    adda.l  #TRAILER,%a1
    adda.l  (%sp)+,%a0                  | a0 = the original record
    tst.b   T_SMODE(%a1)
    bne.b   sr_rec                      | PER TRACK when loaded: the record's own bytes
    moveq   #0,%d0                      | NORMAL when loaded: the pattern's length / scale
    move.b  T_LEN(%a1),%d0
    moveq   #0,%d1
    move.b  T_SCALE(%a1),%d1
    rts
sr_none:
    suba.l  %a0,%a0
    rts
sr_rec:                                 | a0 = a record whose own bytes count; t at 4(sp)
    move.l  4(%sp),%d1
    moveq   #0x50,%d0
    cmpi.l  #8,%d1
    bcs.b   sr_ra
    moveq   #0x28,%d0
sr_ra:
    movea.l %a0,%a1
    adda.l  %d0,%a1
    moveq   #0,%d0
    move.b  (%a1),%d0
    moveq   #0,%d1
    move.b  1(%a1),%d1
    rts

| d0 = 1 when the playing bank has its load snapshot (the originals). Uses d0-d1.
cl_origok:
    moveq   #0,%d1
    move.b  PLAY_BANK,%d1
    moveq   #0,%d0
    move.w  cl_snapok,%d0
    btst    %d1,%d0
    beq.b   ok_no
    moveq   #1,%d0
    rts
ok_no:
    moveq   #0,%d0
    rts

| cl_snapslab (d0 = bank, d1 = pattern) -> a0 = that pattern's slab in the load snapshot. d0-d1/a0.
cl_snapslab:
    move.l  %d1,-(%sp)
    move.l  #BANKSZ,%d1
    muls.l  %d1,%d0
    movea.l #SNAPB,%a0
    adda.l  %d0,%a0
    move.l  (%sp)+,%d0
    move.l  #PATSTRIDE,%d1
    muls.l  %d1,%d0
    adda.l  %d0,%a0
    rts

| cl_cmpw (a0, a1, d0 = an even byte count) -> d0 = 0 equal, 1 not; a0/a1 advance. Uses d1.
cl_cmpw:
    lsr.l   #1,%d0
    beq.b   cw_eq
cw_l:
    move.w  (%a0)+,%d1
    cmp.w   (%a1)+,%d1
    bne.b   cw_ne
    subq.l  #1,%d0
    bne.b   cw_l
cw_eq:
    moveq   #0,%d0
    rts
cw_ne:
    moveq   #1,%d0
    rts

| cl_back (a2 = the playing slab): an original has been put back. When every track of the pattern
| equals its original again (its length / scale bytes aside: a conversion rewrote them), the
| pattern's own length / scale / mode (+0x50..+0x55) and every track's length / scale come back
| from the snapshot too: a NORMAL -> PER TRACK conversion is undone, the slab is as loaded.
cl_back:
    lea     -20(%sp),%sp
    movem.l %d2-%d5/%a3,(%sp)
    moveq   #0,%d0
    move.b  PLAY_BANK,%d0
    moveq   #0,%d1
    move.b  ACT_PAT,%d1
    jsr     cl_snapslab
    movea.l %a0,%a3                     | a3 = the snapshot slab
    moveq   #0,%d2                      | d2 = track
bk_l:
    move.l  %d2,-(%sp)
    jsr     cl_toff
    addq.l  #4,%sp
    move.l  %d0,%d3                     | d3 = record offset
    move.l  %d1,%d4                     | d4 = record length
    moveq   #0x50,%d5
    cmpi.l  #8,%d2
    bcs.b   bk_a
    moveq   #0x28,%d5                   | d5 = the len byte's offset in the record
bk_a:
    lea     (%a2,%d3.l),%a0
    lea     (%a3,%d3.l),%a1
    move.l  %d5,%d0
    jsr     cl_cmpw                     | up to the length / scale bytes
    tst.l   %d0
    bne.w   bk_out
    addq.l  #2,%a0
    addq.l  #2,%a1
    move.l  %d4,%d0
    sub.l   %d5,%d0
    subq.l  #2,%d0
    jsr     cl_cmpw                     | after them
    tst.l   %d0
    bne.w   bk_out
    addq.l  #1,%d2
    cmpi.l  #16,%d2
    bne.b   bk_l
    movea.l %a2,%a0                     | every track original: the rest comes back
    adda.l  #TRAILER,%a0
    movea.l %a3,%a1
    adda.l  #TRAILER,%a1
    moveq   #6,%d0
bk_tr:
    move.b  (%a1)+,(%a0)+
    subq.l  #1,%d0
    bne.b   bk_tr
    moveq   #0,%d0
bk_pa:
    move.l  #TRAC_A,%d1
    muls.l  %d0,%d1
    lea     0x50(%a3,%d1.l),%a1
    lea     0x50(%a2,%d1.l),%a0
    move.b  (%a1)+,(%a0)+
    move.b  (%a1)+,(%a0)+
    addq.l  #1,%d0
    cmpi.l  #8,%d0
    bne.b   bk_pa
    moveq   #0,%d0
bk_pm:
    move.l  #TRAC_M,%d1
    muls.l  %d0,%d1
    addi.l  #MIDI_BASE+0x28,%d1
    lea     (%a3,%d1.l),%a1
    lea     (%a2,%d1.l),%a0
    move.b  (%a1)+,(%a0)+
    move.b  (%a1)+,(%a0)+
    addq.l  #1,%d0
    cmpi.l  #8,%d0
    bne.b   bk_pm
bk_out:
    movem.l (%sp),%d2-%d5/%a3
    lea     20(%sp),%sp
    rts

    .section .dram,"ax"
| cl_post_ui(t): what a load owes the UI side (never from the tick) -- cl_postmask(1 << t).
cl_post_ui:
    moveq   #1,%d0
    move.l  4(%sp),%d1
    lsl.l   %d1,%d0
    move.l  %d0,-(%sp)
    bsr.w   cl_postmask
    addq.l  #4,%sp
    rts

| ================================================================ ORIG PTN+PART as a pattern change
| cl_sreq -> d0 != 0: a self-switch is pending (cl_self) and the cue is the playing pattern itself (a
| real cue or a stop cancels it at the commit). Uses d0.
cl_sreq:
    moveq   #0,%d0
    tst.b   cl_self
    beq.b   sq_out
    move.b  PEND_PAT,%d0
    cmp.b   ACT_PAT,%d0
    bne.b   sq_no
    move.b  PEND_BANK,%d0
    cmp.b   PLAY_BANK,%d0
    bne.b   sq_no
    moveq   #1,%d0
    rts
sq_no:
    moveq   #0,%d0
sq_out:
    rts

| cl_stockown -> d0 != 0: stock's switch lands the request, not DIRECT JUMP's (DJ off, or a chain / the
| arranger running: DJ stays out then). Uses d0.
cl_stockown:
.ifdef DJ_MODE
    tst.l   DJ_MODE
    beq.b   so_yes
    tst.l   CHAIN_ACT
    bne.b   so_yes
    tst.l   ARR_ACT
    bne.b   so_yes
    moveq   #0,%d0
    rts
so_yes:
.endif
    moveq   #1,%d0
    rts

| cl_sw6: stock's per-master-step switch gate (0x400a4352, `mvz.w 0x800065b2,%d2`, jsr; d6 = PEND !=
| ACT was just computed): a pending self-switch that stock owns counts as a real one (d6 = 1), so the
| CHAIN AFTER rule / the pattern end lands it and the d6 hand-off runs. Keeps all but d2 / d6.
cl_sw6:
    tst.b   cl_self
    beq.b   s6_out
    move.l  %d0,-(%sp)
    jsr     cl_stockown
    tst.l   %d0
    beq.b   s6_r
    moveq   #1,%d6
s6_r:
    move.l  (%sp)+,%d0
s6_out:
    mvz.w   MASTER_STEP,%d2             | displaced
    rts

| cl_scommit: stock's commit (0x400a44a0, `lea 0x800065be,%a0`, jsr), before ACT <- PEND and every read of
| the pattern / its Part: the originals back for a self-switch stock owns; any other cue drops it.
cl_scommit:
    tst.b   cl_self
    beq.b   scm_out
    lea     -60(%sp),%sp
    movem.l %d0-%d7/%a0-%a6,(%sp)
    jsr     cl_stockown
    tst.l   %d0
    beq.b   scm_done                     | DIRECT JUMP's: it lands it
    jsr     cl_sreq
    tst.l   %d0
    beq.b   scm_clr
    jsr     cl_selfcopy
scm_clr:
    clr.b   cl_self
scm_done:
    movem.l (%sp),%d0-%d7/%a0-%a6
    lea     60(%sp),%sp
scm_out:
    lea     ACT_PAT,%a0                 | displaced
    rts

.ifdef DJ_SELFVEC
| DIRECT JUMP's self-jump vector (dj_selfvec): [0] request?, [1] the originals' slab, [2] put them back
| (its landing tick, before its parameters and hand-off read them). Keep d2-d7 / a2-a6.
cl_djvec:   .long cl_sreq, cl_sblob, cl_sput
cl_sblob:
    moveq   #0,%d0
    move.b  PLAY_BANK,%d0
    moveq   #0,%d1
    move.b  ACT_PAT,%d1
    jsr     cl_snapslab
    move.l  %a0,%d0
    rts
cl_sput:
    jsr     cl_sreq
    tst.l   %d0
    beq.b   su_clr
    jsr     cl_selfcopy
su_clr:
    clr.b   cl_self
    rts
.endif

| cl_selfcopy: the playing pattern and its Part as loaded, back in place (sequencer tick context): the
| slab (its runtime tail +0x8e5c.. kept), the Part it links to; a changed machine restarts its voice;
| the UI side owes the whole slab and Part (cl_postmask). Keeps d2-d7 / a2-a6.
cl_selfcopy:
    lea     -24(%sp),%sp
    movem.l %d2-%d4/%a2-%a4,(%sp)
    moveq   #0,%d0
    move.b  PLAY_BANK,%d0
    moveq   #0,%d1
    move.b  ACT_PAT,%d1
    jsr     cl_snapslab
    movea.l %a0,%a3                     | a3 = the slab as loaded
    moveq   #0,%d0
    move.b  ACT_PAT,%d0
    move.l  %d0,-(%sp)
    move.b  PLAY_BANK,%d0
    move.l  %d0,-(%sp)
    jsr     cl_slab
    addq.l  #8,%sp
    pea     0x8e5c
    move.l  %a3,-(%sp)
    move.l  %a0,-(%sp)
    jsr     MEMCPY
    lea     12(%sp),%sp
    moveq   #0,%d0
    move.b  PLAY_BANK,%d0
    moveq   #0,%d1
    move.b  ACT_PAT,%d1
    movea.l #SNAPB,%a1
    jsr     cl_partin
    movea.l %a0,%a4                     | a4 = its Part as loaded
    moveq   #0,%d0
    move.b  PLAY_BANK,%d0
    moveq   #0,%d1
    move.b  ACT_PAT,%d1
    movea.l #BLOB,%a1
    jsr     cl_partin
    movea.l %a0,%a2                     | a2 = the live Part (the restored link)
    moveq   #0,%d2
sl_m:
    move.b  0x22(%a2,%d2.l),%d0
    cmp.b   0x22(%a4,%d2.l),%d0
    beq.b   sl_mn
    moveq   #1,%d0                      | a new machine: restart the voice, PICKUP setup owed
    lsl.l   %d2,%d0
    move.b  ENG_RESTART,%d1
    or.l    %d1,%d0
    move.b  %d0,ENG_RESTART
    lea     cl_postm,%a0
    moveq   #1,%d0
    move.b  %d0,(%a0,%d2.l)
sl_mn:
    addq.l  #1,%d2
    cmpi.l  #8,%d2
    bne.b   sl_m
    pea     PARTSZ
    move.l  %a4,-(%sp)
    move.l  %a2,-(%sp)
    jsr     MEMCPY
    lea     12(%sp),%sp
    lea     cl_postf,%a0                | the UI side: every track, the whole slab and Part
    moveq   #15,%d0
    moveq   #1,%d1
sl_f:
    move.b  %d1,(%a0,%d0.l)
    subq.l  #1,%d0
    bpl.b   sl_f
    moveq   #1,%d0
    move.b  %d0,cl_wslab
    move.b  %d0,cl_wpart
    move.l  %d0,RDRAW
    moveq   #-1,%d0
    move.w  %d0,cl_post
    movem.l (%sp),%d2-%d4/%a2-%a4
    lea     24(%sp),%sp
    rts

| cl_bbeg / cl_bend: a batch of loads (a group, ORIG, ORIG PTN+PART, a temp chord on several tracks):
| the immediate (stopped) loads inside it note their tracks (cl_batm) and cl_bend serves them in one
| cl_postmask -- not one 36 KB mirror pass a track. Not nested. cl_bend keeps d2-d7/a2-a6.
cl_bbeg:
    moveq   #1,%d0
    move.b  %d0,cl_bat
    clr.l   cl_batm
    rts
cl_bend:
    clr.b   cl_bat
    move.l  cl_batm,%d0
    beq.b   be_out
    clr.l   cl_batm
    move.l  %d0,-(%sp)
    jsr     cl_postmask
    addq.l  #4,%sp
be_out:
    rts

| cl_postmask(mask: bit t, MIDI 8..15): what the loads of those tracks owe the UI side, each shared
| piece ONCE (the user, 2026-11-04: an ORIG PTN+PART landing did all of it 16 times -- with DIRECT
| JUMP on it lands inside the 0.5 s flash and the flash crawled), and no more than changed: the SRAM
| mirror (the UI bank only; battery NVRAM on the external bus) gets those tracks' records and the
| pattern trailer (2.2-2.3 KB + 136 B a track, not the 36 KB slab), the whole slab only after a NORMAL
| -> PER TRACK conversion (cl_wslab: it rewrites every record's length / scale); stock's dirty flags +
| refresh (the undo-restore's own 0x40029b9c) once per audio index (it does t and t + 8); the Part's
| share once (cl_postpart).
cl_postmask:
    lea     -16(%sp),%sp
    movem.l %d2-%d4/%a2,(%sp)
    move.l  20(%sp),%d4                 | d4 = the mask
    move.b  PLAY_BANK,%d0
    cmp.b   UI_BANK,%d0
    bne.w   pu_dirty
    moveq   #0,%d0
    move.b  ACT_PAT,%d0
    move.l  %d0,-(%sp)
    move.b  PLAY_BANK,%d0
    move.l  %d0,-(%sp)
    jsr     cl_slab
    addq.l  #8,%sp
    movea.l %a0,%a2                     | a2 = the live slab
    moveq   #0,%d0
    move.b  ACT_PAT,%d0
    move.l  #PATSTRIDE,%d1
    muls.l  %d1,%d0
    addi.l  #SRAM_PAT,%d0
    move.l  %d0,%d3                     | d3 = its mirror
    tst.b   cl_wslab
    beq.b   pu_recs
    pea     PATSTRIDE
    move.l  %a2,-(%sp)
    move.l  %d3,-(%sp)
    jsr     MEMCPY
    lea     12(%sp),%sp
    bra.b   pu_dirty
pu_recs:
    moveq   #0,%d2
pu_rl:
    btst    %d2,%d4
    beq.b   pu_rn
    move.l  %d2,-(%sp)
    jsr     cl_toff                     | d0 = the record's offset, d1 = its length
    addq.l  #4,%sp
    move.l  %d1,-(%sp)
    move.l  %a2,%d1
    add.l   %d0,%d1
    move.l  %d1,-(%sp)
    add.l   %d3,%d0
    move.l  %d0,-(%sp)
    jsr     MEMCPY
    lea     12(%sp),%sp
pu_rn:
    addq.l  #1,%d2
    cmpi.l  #16,%d2
    bne.b   pu_rl
    pea     PATSTRIDE-TRAILER           | the trailer: length / scale / mode / Part link
    move.l  %a2,%d0
    addi.l  #TRAILER,%d0
    move.l  %d0,-(%sp)
    move.l  %d3,%d0
    addi.l  #TRAILER,%d0
    move.l  %d0,-(%sp)
    jsr     MEMCPY
    lea     12(%sp),%sp
pu_dirty:
    clr.b   cl_wslab
    moveq   #0,%d2
pu_l:
    move.l  %d4,%d0
    move.l  %d0,%d1
    lsr.l   #8,%d1
    or.l    %d1,%d0
    btst    %d2,%d0
    beq.b   pu_n
    move.l  %d2,-(%sp)
    jsr     SEQ_DIRTY
    addq.l  #4,%sp
pu_n:
    addq.l  #1,%d2
    cmpi.l  #8,%d2
    bne.b   pu_l
    move.l  %d4,-(%sp)
    jsr     cl_postpart
    addq.l  #4,%sp
    movem.l (%sp),%d2-%d4/%a2
    lea     16(%sp),%sp
    rts

| cl_pmark (d3 = Part index, a2 = that Part, of the playing bank): stock's Part-edited mark follows
| "differs from its SAVE PART copy" (bank +0x9504a + part * PARTSZ, valid when +0x9b312 + part != 0, the
| test stock's PART RELOAD makes); the Part's SRAM copy when the playing bank is the UI's -- d4 in = the
| tracks whose slice changed (only those slices are copied), 0 = the whole Part; the bank marked changed.
| -> d4 = 1: the playing bank is the UI's. Data only (UI task or the card worker). Keeps d2, d3, a2.
cl_pmark:
    move.l  %d5,-(%sp)
|   d5 = 1: the Part now equals its SAVE PART copy (the user, 2026-10-30: then it is not edited,
|   as after stock's own PART RELOAD, 0x4004ab46): the "saved" flag set (bank +0x9b312 + part, the
|   test stock's PART RELOAD makes) and the bytes equal (bank +0x9504a + part * PARTSZ)
    moveq   #0,%d5
    moveq   #0,%d0
    move.b  PLAY_BANK,%d0
    move.l  #BANKSTRIDE,%d1
    muls.l  %d1,%d0
    movea.l #BLOB,%a1
    adda.l  %d0,%a1
    movea.l %a1,%a0
    adda.l  #PSAVED,%a0
    tst.b   (%a0,%d3.l)
    beq.b   pm_neq
    move.l  #PARTSZ,%d0
    muls.l  %d3,%d0
    adda.l  #PSAVECPY,%a1
    adda.l  %d0,%a1                     | a1 = the SAVE PART copy
    movea.l %a2,%a0
    move.l  #PARTSZ,%d0
    jsr     cl_cmpw
    tst.l   %d0
    bne.b   pm_neq
    moveq   #1,%d5
pm_neq:
    move.l  %d4,%d1                     | d1 = the slices that changed (0: the whole Part)
    moveq   #0,%d4                      | d4 = 1: the UI bank
    move.b  PLAY_BANK,%d0
    cmp.b   UI_BANK,%d0
    bne.b   pm_flags
    moveq   #1,%d4
    move.l  #PARTSZ,%d0
    muls.l  %d3,%d0
    addi.l  #SRAM_PART,%d0              | d0 = its mirror
    tst.l   %d1
    bne.b   pm_slm
    pea     PARTSZ
    move.l  %a2,-(%sp)
    move.l  %d0,-(%sp)
    jsr     MEMCPY
    lea     12(%sp),%sp
    bra.b   pm_mk
pm_slm:                                 | only those tracks' slices (cl_slice: 0.2-1 KB each, not 6.3 KB)
    lea     -12(%sp),%sp
    movem.l %d6-%d7/%a3,(%sp)
    move.l  %d1,%d6
    movea.l %d0,%a3
    moveq   #0,%d7
pm_sl:
    btst    %d7,%d6
    beq.b   pm_sn
    move.l  %a2,-(%sp)                  | src: the live Part
    move.l  %a3,-(%sp)                  | dst: its mirror
    move.l  %d7,-(%sp)
    jsr     cl_slice
    lea     12(%sp),%sp
pm_sn:
    addq.l  #1,%d7
    cmpi.l  #16,%d7
    bne.b   pm_sl
    movem.l (%sp),%d6-%d7/%a3
    lea     12(%sp),%sp
pm_mk:
    bset    %d3,PEDIT_S
    tst.l   %d5
    beq.b   pm_flags
    bclr    %d3,PEDIT_S
pm_flags:
    moveq   #0,%d0
    move.b  PLAY_BANK,%d0
    move.l  #BANKSTRIDE,%d1
    muls.l  %d1,%d0
    movea.l #BLOB,%a0
    adda.l  %d0,%a0
    movea.l %a0,%a1
    adda.l  #PEDIT,%a0
    bset    %d3,(%a0)                   | a byte: bset, never or.l (the REPITCH lesson, S119)
    tst.l   %d5
    beq.b   pm_fl2
    bclr    %d3,(%a0)                   | equal to the SAVE PART copy: not edited
pm_fl2:
    adda.l  #BDIRTY,%a1
    moveq   #1,%d0
    move.l  %d0,(%a1)
    move.l  %d0,DIRTY2
    move.l  (%sp)+,%d5
    rts

| cl_postpart(t): what a FULL landing of t owes the UI side, as stock's TRACK PASTE does it
| (0x4002b554..0x4002b59a): the Part in the SRAM mirror (the UI bank only), the Part-edited and
| bank-changed flags, then -- for a new audio machine -- stock's PICKUP setup, and the page redraw
| of stock's Part reload (0x4005e0a8). Nothing if no FULL landing is owed.
cl_postpart:
    lea     -20(%sp),%sp
    movem.l %d2-%d5/%a2,(%sp)
    move.l  24(%sp),%d5                 | d5 = the mask
    moveq   #0,%d4                      | d4 = the tracks of it owing their Part's share (cl_postf)
    moveq   #0,%d2                      | d2 = 1: ... and an audio one changed machine (cl_postm)
    moveq   #0,%d3
    lea     cl_postf,%a0
    lea     cl_postm,%a1
pq_l:
    btst    %d3,%d5
    beq.b   pq_n
    tst.b   (%a0,%d3.l)
    beq.b   pq_n
    clr.b   (%a0,%d3.l)
    bset    %d3,%d4                     | d4 = the tracks whose slice changed
    cmpi.l  #8,%d3
    bcc.b   pq_n
    tst.b   (%a1,%d3.l)
    beq.b   pq_n
    moveq   #1,%d2
pq_n:
    addq.l  #1,%d3
    cmpi.l  #16,%d3
    bne.b   pq_l
    tst.l   %d4
    beq.w   pp_out2
    moveq   #0,%d0
    move.b  PLAY_BANK,%d0
    moveq   #0,%d1
    move.b  ACT_PAT,%d1
    movea.l #BLOB,%a1
    jsr     cl_partin
    movea.l %a0,%a2                     | a2 = the Part
    move.l  %d0,%d3                     | d3 = its index
    tst.b   cl_wpart
    beq.b   pq_sl
    clr.b   cl_wpart
    moveq   #0,%d4                      | the rest of the Part changed too: the whole Part
pq_sl:
    jsr     cl_pmark                    | its mirror (d4: those slices) and stock's edited mark; d4 = 1: the UI bank
    tst.l   %d4
    beq.b   pp_out2                     | another bank than the UI's: nothing on screen to redraw
    tst.l   %d2
    beq.b   pp_ref
    lea     cl_postm,%a0                | the mask's audio tracks: their machine change is served
    moveq   #0,%d0
pq_m:
    btst    %d0,%d5
    beq.b   pq_mn
    clr.b   (%a0,%d0.l)
pq_mn:
    addq.l  #1,%d0
    cmpi.l  #8,%d0
    bne.b   pq_m
    jsr     PICKUP_SET                  | a new machine: stock's PICKUP setup (it reads the UI bank), once
pp_ref:
    moveq   #1,%d0
    move.l  %d0,RDRAW
    pea     -1
    jsr     PR_A
    jsr     PR_B
    jsr     PR_C
    jsr     PR_D
    jsr     PR_E
    jsr     PR_F
    jsr     PR_G
    addq.l  #4,%sp
pp_out2:
    movem.l (%sp),%d2-%d5/%a2
    lea     20(%sp),%sp
pp_out:
    rts

    ROMSEC
| ================================================================ the landing (sequencer tick)
| Measured rule (scope §3.4), stated in what each hook sees:
|  * MASTER WRAP (or a stock pattern change): stock's wrap body, entry 0x400a43a0 in phase G
|    (cl_wrap). A stock change landing there drops every cue (O8); a plain wrap lands every cue,
|    copy only -- the wrap body re-homes every track right after (the A1/A2 oracle).
|  * CHAIN AFTER point mid-pattern: phase D, 0x400a1f72 (cl_land, replaces `move.b 0x80006687,%d0`,
|    6 B; stock's ble.w follows on those flags, so the replay comes LAST). Phase G of the previous
|    tick has already advanced the master: TICK_CTR == 0 means this is the first tick of master
|    step s = MASTER_STEP; CHAIN AFTER N > 0 and s % N == 0 arms every cue. An armed track lands on the
|    first tick that is a window start for its old AND new rate, phase-continuous:
|    t0 = (MASTER_STEP - 1) * tps_M + TICK_CTR,  STEP = (t0 / tps + 1) mod len,  TICKS = t0 mod tps
|    (the A4..A8 oracles: t0 66 -> step 23 at 2x, t0 114 -> step 20).
cl_land:
.ifdef DJ_LAND
|   KYOTI (scope §1.10): this site is shared with DIRECT JUMP, whose hook dj_land (`jsr`, the same
|   6 B) runs first. It keeps every register and replays the displaced move itself; ours replays
|   it again at la_out (the same byte: Clyps never writes 0x80006687).
    jsr     DJ_LAND
.endif
    tst.b   cl_nq
    beq.w   la_out                      | nothing cued: one byte test per tick
    tst.l   RUNNING
    beq.w   la_out
|   mid-function in stock's tick handler: every register may be live -- save them all
    lea     -60(%sp),%sp
    movem.l %d0-%d7/%a0-%a6,(%sp)
.ifdef DJ_STATE
|   DIRECT JUMP lands on this tick (dj_land just committed: state LANDING): stock re-lands the
|   whole sequencer right after us, so every pending cue is dropped (scope §1.10, O8's rule)
    move.b  DJ_STATE,%d0
    cmpi.b  #2,%d0                      | DJ's ST_LANDING
    bne.b   la_nodj
    jsr     cl_dropall
    bra.w   la_done
la_nodj:
.endif
|   tps_M and t0
    moveq   #0,%d0
    move.b  SCALE_IX,%d0
    jsr     cl_tps
    move.l  %d0,%d5                     | d5 = tps_M
    moveq   #0,%d3
    move.w  MASTER_STEP,%d3             | d3 = s
    moveq   #0,%d1
    move.b  TICK_CTR,%d1
    move.l  %d3,%d0
    subq.l  #1,%d0
    muls.l  %d5,%d0
    add.l   %d1,%d0
    move.l  %d0,%d7                     | d7 = t0
    tst.l   %d1
    bne.w   la_tracks                   | not the first tick of a master step
    tst.l   %d3
    beq.w   la_tracks
|   the playing pattern's CHAIN AFTER
    moveq   #0,%d0
    move.b  ACT_PAT,%d0
    move.l  %d0,-(%sp)
    move.b  PLAY_BANK,%d0
    move.l  %d0,-(%sp)
    jsr     cl_slab
    addq.l  #8,%sp
    adda.l  #TRAILER,%a0
    move.b  6(%a0),%d0                  | +0x8e56: CHAIN AFTER index (signed), < 0 = project default
    extb.l  %d0
    bpl.b   la_q
    moveq   #0,%d0
    move.b  PROJ_QUANT,%d0
la_q:
    cmpi.l  #16,%d0
    bhi.w   la_tracks
    lea     QUANT_TBL,%a1
    move.l  (%a1,%d0.l*4),%d1           | N
.ifdef DJ_MODE
|   DIRECT JUMP on (scope §1.5a / §1.10): a load lands at the next master step, phase-continuous in
|   the playing pattern's master cycle (= DJ's clock-locked position once DJ landed that pattern)
    tst.l   DJ_MODE
    beq.b   la_qn
    moveq   #1,%d1
la_qn:
    tst.l   %d1                         | the flags of N again for the ble below
.endif
    ble.w   la_tracks                   | CHAIN AFTER at its default: only the master wrap lands (cl_wrap)
    move.l  %d3,%d0
    remu.l  %d1,%d2:%d0                 | d2 = s mod N
    tst.l   %d2
    bne.w   la_tracks
|   a stock change cued for this same point lands it at the wrap body: leave that to cl_wrap
    move.b  PEND_PAT,%d0
    cmp.b   ACT_PAT,%d0
    bne.w   la_tracks
    move.b  PEND_BANK,%d0
    cmp.b   PLAY_BANK,%d0
    bne.w   la_tracks
|   arm every cue
    lea     cl_cue,%a0
    lea     cl_arm,%a1
    moveq   #0,%d0
la_arml:
    move.w  (%a0)+,%d1
    cmpi.w  #-1,%d1
    beq.b   la_armn
    moveq   #1,%d1
    move.b  %d1,(%a1,%d0.l)
la_armn:
    addq.l  #1,%d0
    cmpi.l  #16,%d0
    bne.b   la_arml

| every armed track whose old and new rates both start a window at t0
la_tracks:
    moveq   #0,%d6                      | d6 = track
la_tl:
    lea     cl_arm,%a0
    tst.b   (%a0,%d6.l)
    beq.w   la_tn
|   the cue must still aim at the playing pattern
    move.l  %d6,%d0
    add.l   %d0,%d0
    lea     cl_cueh,%a0
    move.w  (%a0,%d0.l),%d1
    moveq   #0,%d2
    move.b  PLAY_BANK,%d2
    lsl.l   #8,%d2
    move.b  ACT_PAT,%d2
    cmp.w   %d2,%d1
    beq.b   la_aimed
    jsr     cl_dropone                  | d6 = track
    bra.w   la_tn
la_aimed:
|   old rate
    lea     TSCALE_ARR,%a0
    moveq   #0,%d0
    move.b  (%a0,%d6.l),%d0
    jsr     cl_tps                      | d0 -> ticks per step
    move.l  %d7,%d1
    remu.l  %d0,%d2:%d1
    tst.l   %d2
    bne.w   la_tn                       | old window not at its start: wait
|   new rate: the source record's (after the copy's NORMAL/PER TRACK rule -- peek it first)
    move.l  %d6,%d0
    add.l   %d0,%d0
    lea     cl_cue,%a0
    moveq   #0,%d1
    move.w  (%a0,%d0.l),%d1
    move.l  %d1,%d0
    andi.l  #0xff,%d0
    move.l  %d0,-(%sp)                  | spat
    lsr.l   #8,%d1
    move.l  %d1,-(%sp)                  | sbank
    move.l  %d6,-(%sp)
    jsr     cl_newrate                  | d0 = new tps, d1 = new len, d2 = new scale index
    lea     12(%sp),%sp
    tst.l   %d0
    bne.b   la_rate
    jsr     cl_dropone                  | nothing to land any more
    bra.w   la_tn
la_rate:
    move.l  %d0,%a3                     | a3 = tps_new
    move.l  %d1,%a4                     | a4 = len_new
    move.l  %d2,%a5                     | a5 = scale_new
    move.l  %d7,%d1
    remu.l  %d0,%d2:%d1
    tst.l   %d2
    bne.w   la_tn                       | new window not at its start: wait
    jsr     cl_landone                  | d6 = track: copy + clear the cue
|   phase-continuous counters
    move.l  %d7,%d0
    move.l  %a3,%d1
    divu.l  %d1,%d0                     | t0 / tps
    addq.l  #1,%d0
    move.l  %a4,%d1
    remu.l  %d1,%d2:%d0                 | d2 = STEP
    lea     STEP_ARR,%a0
    move.b  %d2,(%a0,%d6.l)
    add.l   %d1,%d2
    subq.l  #1,%d2
    remu.l  %d1,%d0:%d2                 | d0 = (STEP + len - 1) mod len
    lea     STEPM1_ARR,%a0
    move.b  %d0,(%a0,%d6.l)
    move.l  %d7,%d0
    move.l  %a3,%d1
    remu.l  %d1,%d2:%d0
    lea     TICKS_ARR,%a0
    move.b  %d2,(%a0,%d6.l)             | 0 at a window start
    move.l  %a5,%d0
    lea     TSCALE_ARR,%a0
    move.b  %d0,(%a0,%d6.l)
la_tn:
    addq.l  #1,%d6
    cmpi.l  #16,%d6
    bne.w   la_tl
la_done:
    movem.l (%sp),%d0-%d7/%a0-%a6
    lea     60(%sp),%sp
la_out:
    move.b  0x80006687,%d0              | displaced; stock's ble.w follows on these flags
    jmp     LAND_RESUME

| Phase G, the wrap body's entry 0x400a43a0 (replaces `move.l (a2),d0 ; moveq #1,d2 ;
| or.l d2,d0`, 6 B). Reached at a master wrap and when a stock pattern change lands.
cl_wrap:
    tst.b   cl_nq
    beq.w   wr_out
    lea     -60(%sp),%sp
    movem.l %d0-%d7/%a0-%a6,(%sp)
    move.b  PEND_PAT,%d0
    cmp.b   ACT_PAT,%d0
    bne.b   wr_drop
    move.b  PEND_BANK,%d0
    cmp.b   PLAY_BANK,%d0
    bne.b   wr_drop
    jsr     cl_sreq                     | ORIG PTN+PART's switch to itself lands here: a pattern change,
    tst.l   %d0                         | which drops every cue (as O8)
    beq.b   wr_pl
    jsr     cl_stockown
    tst.l   %d0
    bne.b   wr_drop
wr_pl:
    moveq   #0,%d6                      | a plain wrap: every cue lands, copy only
wr_l:
    move.l  %d6,%d0
    add.l   %d0,%d0
    lea     cl_cue,%a0
    move.w  (%a0,%d0.l),%d1
    cmpi.w  #-1,%d1
    beq.b   wr_n
    lea     cl_cueh,%a0
    move.w  (%a0,%d0.l),%d1
    moveq   #0,%d2
    move.b  PLAY_BANK,%d2
    lsl.l   #8,%d2
    move.b  ACT_PAT,%d2
    cmp.w   %d2,%d1
    beq.b   wr_land
    jsr     cl_dropone                  | aimed at a pattern no longer playing
    bra.b   wr_n
wr_land:
    jsr     cl_landone
wr_n:
    addq.l  #1,%d6
    cmpi.l  #16,%d6
    bne.b   wr_l
    bra.b   wr_done
wr_drop:
    jsr     cl_dropall                  | the pattern is changing: the cues' destination goes
wr_done:
    movem.l (%sp),%d0-%d7/%a0-%a6
    lea     60(%sp),%sp
wr_out:
    move.l  (%a2),%d0                   | displaced
    moveq   #1,%d2
    or.l    %d2,%d0
    jmp     WRAP_RESUME

| d0 = scale index -> d0 = ticks per step (out-of-range scale reads as 1x, as DIRECT JUMP does)
cl_tps:
    cmpi.l  #6,%d0
    bls.b   tp_ok
    moveq   #2,%d0
tp_ok:
    lea     LEN_TBL,%a0
    move.l  (%a0,%d0.l*4),%d0
    rts

| cl_newrate(t, sbank, spat) -> d0 = tps, d1 = len, d2 = scale index the track will have after
| cl_apply (the source's resolved length / scale, cl_srcrec); d0 = 0: there is no source (no saved
| sequence / original any more).
cl_newrate:
    move.l  12(%sp),-(%sp)              | spat
    move.l  12(%sp),-(%sp)              | sbank
    move.l  12(%sp),-(%sp)              | t
    jsr     cl_srcrec
    lea     12(%sp),%sp
    move.l  %a0,%d2
    beq.b   nr_none
    move.l  %d1,%d2                     | scale
    move.l  %d0,%d1                     | len
    move.l  %d1,-(%sp)
    move.l  %d2,%d0
    jsr     cl_tps
    move.l  (%sp)+,%d1
    tst.l   %d1
    bne.b   nr_out
    moveq   #16,%d1                     | never divide by a zero length
nr_out:
    rts
nr_none:
    moveq   #0,%d0
    rts

| cl_landone (d6 = track): copy the cue onto the playing pattern, clear it, owe the UI follow-up
cl_landone:
    lea     cl_cuef,%a0
    moveq   #0,%d0
    move.b  (%a0,%d6.l),%d0
    move.l  %d0,-(%sp)                  | full
    move.l  %d6,%d0
    add.l   %d0,%d0
    lea     cl_cue,%a0
    moveq   #0,%d1
    move.w  (%a0,%d0.l),%d1
    move.l  %d1,%d0
    andi.l  #0xff,%d0
    move.l  %d0,-(%sp)
    lsr.l   #8,%d1
    move.l  %d1,-(%sp)
    move.l  %d6,-(%sp)
    jsr     cl_apply
    lea     16(%sp),%sp
    jsr     cl_dropone
    move.w  cl_post,%d0
    moveq   #1,%d1
    lsl.l   %d6,%d1
    or.l    %d1,%d0
    move.w  %d0,cl_post                 | the UI side writes the SRAM mirror + dirty flags
    rts

| cl_dropone (d6 = track): forget its cue
cl_dropone:
    move.l  %d6,%d0
    add.l   %d0,%d0
    lea     cl_cue,%a0
    moveq   #-1,%d1
    move.w  %d1,(%a0,%d0.l)
    lea     cl_arm,%a0
    clr.b   (%a0,%d6.l)
    bra.w   cl_count

cl_dropall:
    lea     cl_cue,%a0
    moveq   #-1,%d1
    moveq   #16,%d0
da_l:
    move.w  %d1,(%a0)+
    subq.l  #1,%d0
    bne.b   da_l
    lea     cl_arm,%a0
    moveq   #16,%d0
da_l2:
    clr.b   (%a0)+
    subq.l  #1,%d0
    bne.b   da_l2
| cl_nq = number of cues pending (the tick's one-byte fast path)
cl_count:                               | uses d0, d1, a0, a1 only
    lea     cl_cue,%a0
    lea     cl_cue+32,%a1
    moveq   #0,%d0
cn_l:
    move.w  (%a0)+,%d1
    cmpi.w  #-1,%d1
    beq.b   cn_n
    addq.l  #1,%d0
cn_n:
    cmpa.l  %a1,%a0
    bne.b   cn_l
    move.b  %d0,cl_nq
    rts

    .section .dram,"ax"
| ================================================================ the UI tail
| The UI task's message loop, common tail 0x40062d1c (replaces `tst.l 0x46c7c72c`, 6 B; stock's
| beq.w follows on those flags). Runs after every UI message. Does what a landing owes the UI.
cl_uitail:
    tst.l   RUNNING
    bne.b   ut_run
    clr.b   cl_self                     | stopped before it landed: ORIG PTN+PART's request goes
ut_run:
    tst.b   cl_open
    beq.w   ut_post
|   a pattern picked the stock way inside Clyps (scope §1.0 step 2) closes it: [PTN] + trig / a
|   trig on SELECT PATTERN (0x40056b2c sets PTN_CONSUMED -1; Clyps' entry leaves it 1, stock's press
|   0), or the pattern after a [BANK] + trig bank pick (BANK_SEL 2, armed by cl_k_chord's [BANK]
|   press; Clyps' entry writes 2 itself and disarms)
    moveq   #-1,%d0
    cmp.l   PTN_CONSUMED,%d0
    beq.b   ut_pick
    tst.b   cl_bkarm
    beq.b   ut_box
    moveq   #2,%d0
    cmp.l   BANK_SEL,%d0
    bne.b   ut_box
ut_pick:
    clr.b   cl_bkarm
    jsr     cl_close
    bra.b   ut_post
ut_box:
    jsr     cl_hstate                   | [BANK] / [PTN] held flags change after their handlers: the
    cmp.b   cl_hdrst,%d0                | header (BANK box, ORIG PTN/PART) and page LED follow here
    beq.b   ut_pat
    jsr     cl_draw
ut_pat:
    jsr     cl_trk                      | the active track changed under Clyps -- the [MIDI] key
    cmp.b   cl_lastt,%d0                | (audio <-> MIDI side) is not ours: the view and grid follow
    bne.b   ut_refr
    moveq   #0,%d0                      | the pattern you are on changed: the highlight follows
    move.b  PLAY_BANK,%d0
    lsl.l   #8,%d0
    move.b  ACT_PAT,%d0
    cmp.w   cl_lastp,%d0
    beq.b   ut_post
    move.w  %d0,cl_lastp
ut_refr:
    jsr     cl_refresh
ut_post:
    move.w  cl_post,%d0
    beq.b   ut_out
    clr.w   cl_post
    move.l  %d0,-(%sp)                  | every track that landed, each shared piece once
    jsr     cl_postmask
    addq.l  #4,%sp
    tst.b   cl_open
    beq.b   ut_out
    jsr     cl_refresh                  | a landing: the slot labels and the grid follow
ut_out:
    tst.l   RDRAW                       | displaced; stock's beq.w follows on these flags
    jmp     UIT_RESUME

    ROMSEC
| NORMAL -> PER TRACK, preserving every other track (scope §4.6). a2 = slab; d3 = this record's
| len-byte offset (its own len/scale are already written and are kept).
cl_convert:
    lea     -24(%sp),%sp
    movem.l %d2-%d5/%a2-%a3,(%sp)
    moveq   #1,%d0
    move.b  %d0,cl_wslab                | every record's length / scale: the mirror owes the whole slab
    movea.l %a2,%a3
    adda.l  #TRAILER,%a3                | a3 -> trailer
    move.b  (%a2,%d3.l),%d4             | this track's own len / scale, kept
    move.b  1(%a2,%d3.l),%d5
    moveq   #0,%d0
    move.b  T_LEN(%a3),%d0
    move.w  %d0,T_MLEN(%a3)             | master length = the pattern length (u16)
    move.b  T_SCALE(%a3),%d1
    move.b  %d1,T_MSCALE(%a3)           | master scale = the pattern scale
    moveq   #0,%d2                      | every audio track
cv_a:
    move.l  %d2,%d1
    move.l  #TRAC_A,%d0
    muls.l  %d0,%d1
    move.b  T_LEN(%a3),%d0
    move.b  %d0,0x50(%a2,%d1.l)
    move.b  T_SCALE(%a3),%d0
    move.b  %d0,0x51(%a2,%d1.l)
    addq.l  #1,%d2
    moveq   #8,%d0
    cmp.l   %d2,%d0
    bne.b   cv_a
    moveq   #0,%d2                      | every MIDI track
cv_m:
    move.l  %d2,%d1
    move.l  #TRAC_M,%d0
    muls.l  %d0,%d1
    addi.l  #MIDI_BASE,%d1
    move.b  T_LEN(%a3),%d0
    move.b  %d0,0x28(%a2,%d1.l)
    move.b  T_SCALE(%a3),%d0
    move.b  %d0,0x29(%a2,%d1.l)
    addq.l  #1,%d2
    moveq   #8,%d0
    cmp.l   %d2,%d0
    bne.b   cv_m
    move.b  %d4,(%a2,%d3.l)             | this track's own length and scale back
    move.b  %d5,1(%a2,%d3.l)
    moveq   #1,%d0
    move.b  %d0,T_SMODE(%a3)            | PER TRACK
    movem.l (%sp),%d2-%d5/%a2-%a3
    lea     24(%sp),%sp
    rts

| The four `jsr 0x4000fd34` sites (every bank to defaults: a new project, the start of a load) ->
| here. The reset may be the last thing to write the banks (measured in the emulator: a reload
| whose loader pass came BEFORE the reset), so the originals are retaken after it: whatever wrote
| the banks last defines them. In ROM because 0x4001fb1e may run before the boot loader has put
| the DRAM part in place: the snapshot is only taken once cl_magic says it is there.
| the LED layer's tick (stock calls it every CL_BLINK ticks from 0x4007e940, inside FUN_40052200 --
| the context of the QLREC crash: LED bits only, CLAUDE.md; ROM, as tick-path code): the active track's cued slot, if it is shown and is not the pattern you are on,
| alternates yellow / off
cl_blink:
|   (the user, 2026-11-04) every period: the active track's sequence (cl_srccode: red, cl_paint) gets its
|   green die for 3 LED ticks (LED_FLASH, stock's own call) -- a red / yellow flash, as stock's p-locked
|   trig; its cued sequence (yellow) goes off for half the period -- flashing yellow. With the [PTN]+[BANK]
|   chord held (the pattern view), the cued pattern flashes the same way. The four page LEDs do the
|   3-tick flash when cl_ppaint left them "flash" (cl_pled 3).
    move.l  %d2,-(%sp)
    tst.l   PTN_HELD
    beq.b   bl_box
    tst.l   BANK_HELD
    beq.b   bl_box
    tst.l   RUNNING                     | the pattern view: the cued pattern of the playing bank
    beq.w   bl_page
    move.b  PEND_BANK,%d0
    cmp.b   PLAY_BANK,%d0
    bne.w   bl_page
    moveq   #0,%d1
    move.b  PEND_PAT,%d1
    move.b  ACT_PAT,%d0
    cmp.b   %d1,%d0
    beq.w   bl_page
    andi.l  #15,%d1
    bsr.b   bl_yel
    bra.w   bl_page
bl_box:
    moveq   #0,%d0                      | the active track's cue
    move.b  CUR_TRACK,%d0
    andi.l  #7,%d0
    tst.l   MIDI_MODE
    beq.b   bl_trk
    addq.l  #8,%d0
bl_trk:
    add.l   %d0,%d0
    lea     cl_cue,%a0
    moveq   #0,%d1
    move.w  (%a0,%d0.l),%d1
    move.l  %d1,%d0
    lsr.l   #8,%d0
    cmp.b   cl_bank,%d0
    bne.b   bl_src                      | none (0xffff) / in another bank
    move.l  %d1,%d2                     | (the code, kept to skip its slot below)
    andi.l  #15,%d1
    bsr.b   bl_yel
    bra.b   bl_src2
bl_src:
    moveq   #-1,%d2
bl_src2:
    jsr     cl_srccode
    cmp.l   %d2,%d0
    beq.b   bl_page                     | cued again (a FULL re-load): flashing yellow only
    move.l  %d0,%d1
    lsr.l   #8,%d1
    cmp.b   cl_bank,%d1
    bne.b   bl_page                     | in another bank
    andi.l  #15,%d0
    lea     LED_TBL,%a0
    move.l  (%a0,%d0.l*4),%d2
    addq.l  #1,%d2                      | its green die
    bsr.b   bl_led
    bra.b   bl_page
bl_yel:                                 | d1 = a slot: both its dies off for half the period. Keeps d2.
    lea     LED_TBL,%a0
    move.l  (%a0,%d1.l*4),%d0
    move.l  %d0,-(%sp)                  | (the red die, kept for the green one)
    pea     CL_BLINK/2
    move.l  %d0,-(%sp)
    jsr     LED_FLASH
    addq.l  #8,%sp
    move.l  (%sp)+,%d0
    addq.l  #1,%d0
    pea     CL_BLINK/2
    move.l  %d0,-(%sp)
    jsr     LED_FLASH
    addq.l  #8,%sp
    rts
bl_page:
    moveq   #0,%d0
    move.b  cl_pled,%d0
    cmpi.l  #3,%d0
    bne.b   bl_out
    moveq   #0x49,%d2                   | the four page LEDs' green dies
bl_pk:
    bsr.b   bl_led
    addq.l  #2,%d2
    cmpi.l  #0x51,%d2
    bne.b   bl_pk
bl_out:
    move.l  (%sp)+,%d2
    rts
bl_led:                                 | d2 = a green die: on for 3 ticks
    pea     3
    move.l  %d2,-(%sp)
    jsr     LED_FLASH
    addq.l  #8,%sp
    rts

| the UI task's 1/60 s tick (0x40056c28, the toast countdown, called once per tick message from
| task 0x40056c40; replaces `move.l 0x460d1e6c,%d0`, 6 B: stock's beq follows on its flags) drives
| the load confirmation flash (cl_flashtick). ROM: the tick runs from boot, before the DRAM part is
| in place; cl_magic says when it is (as cl_rstall).
    .global cl_uitick
cl_uitick:
    move.l  cl_magic,%d0
    cmpi.l  #CL_MAGIC,%d0
    bne.b   uk_out
    tst.b   cl_flk
    beq.b   uk_out
    jsr     cl_flashtick
uk_out:
    move.l  TOAST_T,%d0                 | displaced; stock's beq follows on these flags
    jmp     UITICK_RES

| The active-track test of stock's track sidebars -- the tab's upper half, the machine glyph
| (0x4003fed8, its track in d4), and its lower half, the play-status glyph (0x4004bd48: d4 on the MIDI
| side, d3 on the audio side; CLYPT missed these two: half tabs on hardware), the status mark beside
| the glyph (0x40044804, audio, d4; CLYPV missed it: a stray "!") -- and of the track LED painter
| (0x40083eb0, LED slot 6, its track in d5: the active colours), nine sites of
| `mvzb 0x80000000,%d0` -> jsr here (scope §1.9). With a Clyps group (cl_gmask: [CUE] held, or
| members picked) d0 = the track itself when it is a member, -1 otherwise, so every member gets the
| tab and the colours and the active track only if it is one. Else stock's byte. Keeps all but d0.
| ROM: both painters run before the DRAM part exists (cl_magic).
cl_act3:
    move.l  %d3,%d0
    bra.b   ca_go
cl_act4:
    move.l  %d4,%d0
    bra.b   ca_go
cl_act5:
    move.l  %d5,%d0
ca_go:
    move.l  %d1,-(%sp)
    move.l  cl_magic,%d1
    cmpi.l  #CL_MAGIC,%d1
    bne.b   ca_stock
    move.l  cl_gmask,%d1
    beq.b   ca_stock
    tst.l   MIDI_MODE
    beq.b   ca_side
    lsr.l   #8,%d1                      | the MIDI side: members 8..15
ca_side:
    btst    %d0,%d1
    bne.b   ca_out                      | a member: its own index
    moveq   #-1,%d0
    bra.b   ca_out
ca_stock:
    moveq   #0,%d0
    move.b  CUR_TRACK,%d0
ca_out:
    move.l  (%sp)+,%d1
    rts

cl_rstall:
    move.l  4(%sp),-(%sp)
    jsr     RESET_BANKS
    addq.l  #4,%sp
    move.l  cl_magic,%d0
    cmpi.l  #CL_MAGIC,%d0
    bne.b   rs_skip
    jmp     cl_snapall                  | returns to our caller
rs_skip:
    rts

    .section .dram,"ax"
| ================================================================ the Clyps view
| text(x, y, str) in the small font onto the window surface (a4); keeps d2-d7/a2-a6
cl_text:
    move.l  12(%sp),-(%sp)              | str
    pea     -1                          | mode
    move.l  16(%sp),-(%sp)              | y
    move.l  16(%sp),-(%sp)              | x
    move.l  %a4,-(%sp)
    pea     FONT_S
    jsr     TEXT
    lea     24(%sp),%sp
    rts

| xor(x0, y0, x1, y1) on the window surface (a4)
cl_xor:
    pea     -1
    move.l  20(%sp),-(%sp)              | y1
    move.l  20(%sp),-(%sp)              | x1
    move.l  20(%sp),-(%sp)              | y0
    move.l  20(%sp),-(%sp)              | x0
    move.l  %a4,-(%sp)
    jsr     RECT
    lea     24(%sp),%sp
    rts

| set(x0, y0, x1, y1) on the window surface (a4): the same as cl_xor, mode 1 (set: stock's
| 0x40012254 ORs for mode bit 0, XORs for mode < 0, clears otherwise)
cl_set:
    pea     1
    move.l  20(%sp),-(%sp)              | y1
    move.l  20(%sp),-(%sp)              | x1
    move.l  20(%sp),-(%sp)              | y0
    move.l  20(%sp),-(%sp)              | x0
    move.l  %a4,-(%sp)
    jsr     RECT
    lea     24(%sp),%sp
    rts

| cl_cell (d2 = slot) -> a3 = its column's cl_colx entry, d3 = its 2-digit number field's x, d4 = its
| text row y. Uses d0.
cl_cell:
    lea     cl_colx,%a3
    cmpi.l  #8,%d2
    bcs.b   cc_c
    addq.l  #8,%a3
cc_c:
    moveq   #0,%d3
    move.w  (%a3),%d3
    move.l  %d2,%d4
    andi.l  #7,%d4
    moveq   #ROW_PITCH,%d0
    muls.l  %d0,%d4
    moveq   #ROW0_Y,%d0
    sub.l   %d4,%d0
    move.l  %d0,%d4
    rts

| cl_bary (d4 = text y) -> d0 = the bar's y0 (y - 1), d1 = its y1 (y + 5), clipped to 1..BODY_TOP
cl_bary:
    move.l  %d4,%d0
    subq.l  #1,%d0
    bgt.b   by_lo
    moveq   #1,%d0
by_lo:
    move.l  %d4,%d1
    addq.l  #5,%d1
    cmpi.l  #BODY_TOP,%d1
    ble.b   by_hi
    moveq   #BODY_TOP,%d1
by_hi:
    rts

| the select box's horizontal edge at y = d4 + d0, x d5..d6; its vertical edge at x = d0, y d4..d4+4
cd_hline:
    add.l   %d4,%d0
    move.l  %d0,-(%sp)
    move.l  %d6,-(%sp)
    move.l  %d0,-(%sp)
    move.l  %d5,-(%sp)
    bsr.w   cl_set
    lea     16(%sp),%sp
    rts

cd_vline:
    move.l  %d4,%d1
    addq.l  #4,%d1
    move.l  %d1,-(%sp)
    move.l  %d0,-(%sp)
    move.l  %d4,-(%sp)
    move.l  %d0,-(%sp)
    bsr.w   cl_set
    lea     16(%sp),%sp
    rts

cl_draw:
    tst.b   cl_open
    beq.w   cd_out
    lea     -36(%sp),%sp
    movem.l %d2-%d7/%a2-%a4,(%sp)
    movea.l cl_win,%a4
    lea     0x24(%a4),%a4               | a4 = the window's surface
|   clear, then a 1 px border (xor on a cleared surface = set)
    clr.l   -(%sp)
    pea     WIN_H-1
    pea     WIN_W-1
    clr.l   -(%sp)
    clr.l   -(%sp)
    move.l  %a4,-(%sp)
    jsr     RECT
    lea     24(%sp),%sp
    pea     WIN_H-1                     | top
    pea     WIN_W-1
    pea     WIN_H-1
    clr.l   -(%sp)
    bsr.w   cl_xor
    lea     16(%sp),%sp
    clr.l   -(%sp)                      | bottom
    pea     WIN_W-1
    clr.l   -(%sp)
    clr.l   -(%sp)
    bsr.w   cl_xor
    lea     16(%sp),%sp
    pea     WIN_H-2                     | left
    clr.l   -(%sp)
    pea     1
    clr.l   -(%sp)
    bsr.w   cl_xor
    lea     16(%sp),%sp
    pea     WIN_H-2                     | right
    pea     WIN_W-1
    pea     1
    pea     WIN_W-1
    bsr.w   cl_xor
    lea     16(%sp),%sp
|   header (the user, 2026-11-02 / 11-04): "T6 LOAD: <label> BNK A" -- the track at x 3, then "LOAD: " and the
|   label in a dark box, "BNK A" right-aligned to x 107 (boxed while [BANK] alone is held); a group or the
|   [PTN]+[BANK] chord: "MULTI LD: <label> BNK A".
|   Labels: TRK SEQ / TRK FULL ([FUNC]), the MIDI side the same; the box on your own pattern's slot (it has an
|   original): ORIG TRK SEQ / ORIG TRK FULL; a group: TRK SEQS / TRKS FULL / ORIG SEQS / ORIGS FULL; the
|   [PTN]+[BANK] chord held: ORIG PTN+PART. Each label's [FUNC] form is the next string (cl_s_* pairs).
|   Widths at runtime (cl_textw); the longest label's box ends at x 86, "BNK A"'s box starts at 88.
    jsr     cl_hstate
    move.b  %d0,cl_hdrst
    move.l  %d0,%d7                     | d7 = header state (free until the cells)
    jsr     cl_trk
    move.l  %d0,%d6                     | d6 >= 8: the MIDI side
    btst    #1,%d7
    beq.b   cd_r1
    lea     cl_s_origp,%a2
    bra.b   cd_rl
cd_r1:
    jsr     cl_onorig
    move.l  %d0,%d4                     | d4 = the box is on the original (your own pattern's slot)
    jsr     cl_ismulti
    tst.l   %d0
    beq.b   cd_r1s
    lea     cl_s_gseq,%a2
    tst.l   %d4
    beq.b   cd_rf
    lea     cl_s_gorig,%a2
    bra.b   cd_rf
cd_r1s:
    lea     cl_s_seqb,%a2
    tst.l   %d4
    beq.b   cd_rf
    lea     cl_s_origs,%a2
cd_rf:
    tst.b   cl_fn
    beq.b   cd_rl
cd_rskip:                               | [FUNC]: the FULL form, the next string
    tst.b   (%a2)+
    bne.b   cd_rskip
cd_rl:
    movea.l %a2,%a0
    jsr     cl_textw
    move.l  %d0,%d5                     | d5 = the label's width
|   a group, or the [PTN]+[BANK] chord held (ORIG PTN+PRT acts on every track): "MULTI LD:" at x 3 and the
|   label 2 dark columns after it (the user, 2026-11-04) -- "MULTI LD: ORIG PTN+PRT"'s box ends at x 86
    btst    #1,%d7
    bne.b   cd_mh
    jsr     cl_ismulti
    tst.l   %d0
    beq.b   cd_one
cd_mh:
    pea     cl_s_multi
    pea     HDR_Y
    pea     3
    bsr.w   cl_text
    lea     12(%sp),%sp
    lea     cl_s_multi,%a0
    jsr     cl_textw
    move.l  %d0,%d3
    addq.l  #7,%d3                      | d3 = the label's x: 3 + the width + 4 (as after "LOAD:")
    bra.b   cd_lab
cd_one:
|   one track: "T6 " / "M6 " at x 3, then "LOAD:"
    move.l  %d6,%d0
    moveq   #'T',%d1
    cmpi.l  #8,%d0
    bcs.b   cd_ta
    moveq   #'M',%d1
    subq.l  #8,%d0
cd_ta:
    addq.l  #1,%d0
    move.l  %d0,-(%sp)
    move.l  %d1,-(%sp)
    pea     cl_fmt_hdrt                 | "%c%d "
    pea     cl_buf
    jsr     SPRINTF
    lea     16(%sp),%sp
    pea     cl_buf
    pea     HDR_Y
    pea     3
    bsr.w   cl_text
    lea     12(%sp),%sp
    lea     cl_buf,%a0
    jsr     cl_textw
    move.l  %d0,%d3
    addq.l  #4,%d3                      | d3 = "LOAD: "'s x (3 + the width + 1)
    pea     cl_s_load
    pea     HDR_Y
    move.l  %d3,-(%sp)
    bsr.w   cl_text
    lea     12(%sp),%sp
    addi.l  #LOADP_A,%d3                | d3 = the label's x
cd_lab:
    move.l  %a2,-(%sp)
    pea     HDR_Y
    move.l  %d3,-(%sp)
    bsr.w   cl_text
    lea     12(%sp),%sp
|   right: "BNK A", ending at x 107
    moveq   #0,%d2
    move.b  cl_bank,%d2
    addi.l  #'A',%d2
    move.l  %d2,-(%sp)
    pea     cl_fmt_hdrb                 | "BNK %c"
    pea     cl_buf
    jsr     SPRINTF
    lea     12(%sp),%sp
    lea     cl_buf,%a0
    jsr     cl_textw
    moveq   #108,%d2
    sub.l   %d0,%d2                     | d2 = its x
    pea     cl_buf
    pea     HDR_Y
    move.l  %d2,-(%sp)
    bsr.w   cl_text
    lea     12(%sp),%sp
cd_band:
    pea     WIN_H-2                     | the band, inverted with its text
    pea     WIN_W-2
    pea     HDR_Y-2
    pea     1
    bsr.w   cl_xor
    lea     16(%sp),%sp
    tst.b   cl_ftgt                     | a header flash (ORIG after a restore; ORIG PTN+PART after the
    beq.b   cd_hb                       | chord + [PAGE] / [YES], begun inside): the label's box off in
    tst.b   cl_fph                      | alternate phases
    bne.b   cd_nob
cd_hb:
    pea     WIN_H-2                     | the label: a dark box, lit letters, one lit row below
    move.l  %d3,%d0                     | (the band's) and one above (the border); 2 dark columns
    add.l   %d5,%d0                     | each side of the text
    addq.l  #1,%d0
    move.l  %d0,-(%sp)
    pea     HDR_Y-1
    move.l  %d3,%d0
    subq.l  #2,%d0
    move.l  %d0,-(%sp)
    bsr.w   cl_xor
    lea     16(%sp),%sp
cd_nob:
    btst    #0,%d7
    beq.b   cd_nobk
    pea     WIN_H-2                     | [BANK] alone held: "BNK A" in a dark box
    pea     BOX_R
    pea     HDR_Y-1
    subq.l  #2,%d2
    move.l  %d2,-(%sp)
    bsr.w   cl_xor
    lea     16(%sp),%sp
cd_nobk:
|   round the two top corners (a card): clear (0,63) (1,63) (0,62) and their mirror images
    lea     cl_corners,%a2
    moveq   #6,%d2
cd_corner:
    clr.l   -(%sp)                      | mode 0 = clear
    move.w  (%a2)+,%d0
    ext.l   %d0
    move.w  (%a2)+,%d1
    ext.l   %d1
    move.l  %d1,-(%sp)                  | y1 = y
    move.l  %d0,-(%sp)                  | x1 = x
    move.l  %d1,-(%sp)                  | y0
    move.l  %d0,-(%sp)                  | x0
    move.l  %a4,-(%sp)
    jsr     RECT
    lea     24(%sp),%sp
    subq.l  #1,%d2
    bne.b   cd_corner
|   the 16 cells (bars XORed with their text; the select box after them, cd_box)
    jsr     cl_trk
    move.l  %d0,-(%sp)
    jsr     cl_toff
    addq.l  #4,%sp
    move.l  %d0,%d7                     | d7 = record offset
    moveq   #0,%d2                      | d2 = slot 0..15
cd_cell:
    bsr.w   cl_cell                     | a3 = the column's entry, d3 = its number field, d4 = y
|   the slot number, right-aligned by position (a space is narrower than a digit)
    move.l  %d2,%d0
    addq.l  #1,%d0
    move.l  %d0,-(%sp)
    pea     cl_fmt_num
    pea     cl_buf
    jsr     SPRINTF
    lea     12(%sp),%sp
    move.l  %d3,%d0
    cmpi.l  #9,%d2
    bcc.b   cd_two
    addq.l  #DIGIT_W,%d0                | one digit: start one digit in
cd_two:
    pea     cl_buf
    move.l  %d4,-(%sp)
    move.l  %d0,-(%sp)
    bsr.w   cl_text
    lea     12(%sp),%sp
|   the "edited" mark: this sequence differs from its original (the user, 2026-10-27)
    moveq   #0,%d0
    move.b  cl_bank,%d0
    move.l  %d2,%d1
    jsr     cl_edited
    tst.l   %d0
    beq.w   cd_noed
    lea     cl_xpix,%a2                 | five (dx, dy) pixels
    moveq   #5,%d5
cd_edp:
    moveq   #0,%d6
    move.w  6(%a3),%d6                  | the x's x
    move.b  (%a2)+,%d0
    extb.l  %d0
    add.l   %d0,%d6                     | x
    move.b  (%a2)+,%d0
    extb.l  %d0
    add.l   %d4,%d0                     | y
    move.l  %d0,-(%sp)
    move.l  %d6,-(%sp)
    move.l  %d0,-(%sp)
    move.l  %d6,-(%sp)
    bsr.w   cl_xor
    lea     16(%sp),%sp
    subq.l  #1,%d5
    bne.b   cd_edp
cd_noed:
|   a named sequence shows its name; else the summary: "A01 15 TR" / "LOCKS" / "---"; on the
|   highlighted slot (the pattern you are on), while the track plays a sequence Clyps put there
|   unedited: its source, "B14 06 TR" / "SAVED SEQ"
    tst.b   cl_namesok
    beq.b   cd_noname
    moveq   #0,%d0
    move.b  cl_bank,%d0
    move.l  %d2,%d1
    jsr     cl_nidx
    jsr     cl_nptr
    tst.b   (%a0)
    bne.w   cd_sum                      | the name
cd_noname:
    move.b  cl_bank,%d0
    cmp.b   PLAY_BANK,%d0
    bne.b   cd_plain
    moveq   #0,%d0
    move.b  ACT_PAT,%d0
    cmp.l   %d2,%d0
    bne.b   cd_plain
    jsr     cl_srclbl
    move.l  %a0,%d0
    bne.b   cd_sum
cd_plain:
    lea     cl_cls,%a0
    moveq   #0,%d0
    move.b  (%a0,%d2.l),%d0
    beq.b   cd_empty
    subq.l  #1,%d0
    beq.b   cd_half
    move.l  %d2,-(%sp)
    moveq   #0,%d0
    move.b  cl_bank,%d0
    move.l  %d0,-(%sp)
    jsr     cl_slab
    addq.l  #8,%sp
    adda.l  %d7,%a0
    moveq   #0,%d1
    move.l  4(%a0),-(%sp)
    move.l  (%a0),%d0
    bsr.w   cl_popc
    move.l  (%sp)+,%d0
    bsr.w   cl_popc
    move.l  %d1,-(%sp)                  | trigs
    move.l  %d2,%d0
    addq.l  #1,%d0
    move.l  %d0,-(%sp)                  | the slot's pattern 1..16
    moveq   #0,%d0
    move.b  cl_bank,%d0
    addi.l  #'A',%d0
    move.l  %d0,-(%sp)                  | its bank
    pea     cl_fmt_trg
    pea     cl_buf
    jsr     SPRINTF
    lea     20(%sp),%sp
    lea     cl_buf,%a0
    bra.b   cd_sum
cd_half:
    lea     cl_s_lck,%a0
    bra.b   cd_sum
cd_empty:
    lea     cl_s_emp,%a0
cd_sum:
    move.l  %a0,-(%sp)
    move.l  %d4,-(%sp)
    move.l  %d3,%d0
    addi.l  #2*DIGIT_W+SUM_GAP,%d0
    lea     cl_s_emp,%a1
    cmpa.l  %a1,%a0
    bne.b   cd_sx
    addi.l  #EMP_DX,%d0                 | an empty slot: "---" centred in the 9 places (4..6)
cd_sx:
    move.l  %d0,-(%sp)
    bsr.w   cl_text
    lea     12(%sp),%sp
|   the cell's rectangle: x d5..d6, y d4-1 .. d4+5 (one row above and below the text)
    moveq   #0,%d5
    move.w  2(%a3),%d5
    moveq   #0,%d6
    move.w  4(%a3),%d6
|   the highlight: an inverted bar over the pattern you are on (only in its bank)
    move.b  cl_bank,%d0
    cmp.b   PLAY_BANK,%d0
    bne.b   cd_next
    moveq   #0,%d0
    move.b  ACT_PAT,%d0
    cmp.l   %d2,%d0
    bne.b   cd_next
    bsr.w   cl_bary                     | d0 = y0, d1 = y1, clipped to the field 1..54
    move.l  %d1,-(%sp)                  | y1
    move.l  %d6,-(%sp)                  | x1
    move.l  %d0,-(%sp)                  | y0
    move.l  %d5,-(%sp)                  | x0
    bsr.w   cl_xor
    lea     16(%sp),%sp
cd_next:
    addq.l  #1,%d2
    cmpi.l  #16,%d2
    bne.w   cd_cell
|   the select box: a full 1 px frame, SET after every bar -- a box in the row next to the highlight
|   shares a pixel row with its bar, where an XOR would cancel (the user: "it's a full box").
|   Only in the box's bank, not over the highlight (the bar alone shows it there). Not while the
|   [PTN]+[BANK] chord is held (the user, 2026-10-30): it comes back where it was on its release.
    move.b  cl_hdrst,%d0
    btst    #1,%d0
    bne.w   cd_boxed
    move.b  cl_bank,%d0
    cmp.b   cl_sbank,%d0
    bne.w   cd_boxed
    moveq   #0,%d2
    move.b  cl_cur,%d2
    cmp.b   PLAY_BANK,%d0
    bne.b   cd_sbx
    moveq   #0,%d0
    move.b  ACT_PAT,%d0
    cmp.l   %d2,%d0
    bne.b   cd_sbx
    tst.b   cl_ftgt                     | the box on your pattern (the highlight): a load confirmation
    bne.w   cd_boxed                    | flashes the bar itself -- un-inverted in alternate phases
    tst.b   cl_fph                      | (the user, 2026-10-30)
    beq.w   cd_boxed
    bsr.w   cl_cell
    moveq   #0,%d5
    move.w  2(%a3),%d5
    moveq   #0,%d6
    move.w  4(%a3),%d6
    bsr.w   cl_bary
    move.l  %d1,-(%sp)
    move.l  %d6,-(%sp)
    move.l  %d0,-(%sp)
    move.l  %d5,-(%sp)
    bsr.w   cl_xor
    lea     16(%sp),%sp
    bra.w   cd_boxed
cd_sbx:
    bsr.w   cl_cell
    moveq   #0,%d5
    move.w  2(%a3),%d5
    moveq   #0,%d6
    move.w  4(%a3),%d6
    tst.b   cl_ftgt                     | a header flash (ORIG / PTN+PART): the box as usual
    bne.b   cd_sout
    tst.b   cl_fph
    beq.b   cd_sout
    bsr.w   cl_bary                     | the load confirmation: the cell inverted, as the highlight
    move.l  %d1,-(%sp)
    move.l  %d6,-(%sp)
    move.l  %d0,-(%sp)
    move.l  %d5,-(%sp)
    bsr.w   cl_xor
    lea     16(%sp),%sp
    bra.w   cd_boxed
cd_sout:
    move.l  %d4,%d0                     | top (y + 5) -- not on the top row, where the band stands
    addq.l  #5,%d0                      | for it -- and bottom (y - 1), not on the bottom row (frame)
    cmpi.l  #BODY_TOP,%d0
    bgt.b   cd_notop
    moveq   #5,%d0
    bsr.w   cd_hline
cd_notop:
    move.l  %d4,%d0
    subq.l  #1,%d0
    ble.b   cd_nobot
    moveq   #-1,%d0
    bsr.w   cd_hline
cd_nobot:
    move.l  %d5,%d0                     | left and right, y .. y + 4
    bsr.w   cd_vline
    move.l  %d6,%d0
    bsr.w   cd_vline
cd_boxed:
    moveq   #1,%d0
    move.l  %d0,RDRAW
    pea     7
    jsr     LED_PAINT                   | the page LEDs (cl_ppaint) follow the view
    clr.l   (%sp)
    jsr     LED_PAINT                   | and the grid (the chord's pattern view comes and goes)
    addq.l  #4,%sp
    movem.l (%sp),%d2-%d7/%a2-%a4
    lea     36(%sp),%sp
cd_out:
    rts

| cl_nidx (d0 = bank, d1 = pattern) -> d0 = the name index of (bank, pattern, the active track).
| Keeps d2-d7/a2-a6.
cl_nidx:
    lsl.l   #4,%d0
    add.l   %d1,%d0
    lsl.l   #4,%d0
    move.l  %d0,-(%sp)
    jsr     cl_trk
    add.l   (%sp)+,%d0
    rts

| cl_nptr (d0 = a name index) -> a0 = that name (NAME_W bytes, NUL-terminated; "" = none). d0-d1/a0.
cl_nptr:
    moveq   #NAME_W,%d1
    muls.l  %d1,%d0
    movea.l #NAMES,%a0
    adda.l  %d0,%a0
    rts

| cl_edited (d0 = bank, d1 = pattern) -> d0 = 1 when the active track's sequence there differs from
| its original (the load snapshot): the record (its length / scale bytes aside), or its EFFECTIVE
| length / scale (the record's own in PER TRACK, the pattern's in NORMAL -- so a NORMAL -> PER
| TRACK conversion does not mark the untouched tracks). 0 = original, or no snapshot. Keeps
| d2-d7/a2-a6.
cl_edited:
    lea     -28(%sp),%sp
    movem.l %d2-%d6/%a2-%a3,(%sp)
    move.l  %d0,%d2                     | d2 = bank
    move.l  %d1,%d3                     | d3 = pattern
    moveq   #0,%d0
    move.w  cl_snapok,%d0
    btst    %d2,%d0
    beq.b   ed_no
    jsr     cl_trk
    move.l  %d0,%d4                     | d4 = track
    move.l  %d4,-(%sp)
    jsr     cl_toff
    addq.l  #4,%sp
    move.l  %d0,%d5                     | d5 = record offset
    move.l  %d3,-(%sp)
    move.l  %d2,-(%sp)
    jsr     cl_slab
    addq.l  #8,%sp
    movea.l %a0,%a2                     | a2 = the slab now
    move.l  %d2,%d0
    move.l  %d3,%d1
    jsr     cl_snapslab
    movea.l %a0,%a3                     | a3 = the slab as loaded
    lea     (%a2,%d5.l),%a0
    lea     (%a3,%d5.l),%a1
    move.l  %d4,%d0
    jsr     cl_same
    tst.l   %d0
    bne.b   ed_yes
    movea.l %a2,%a0
    bsr.b   cl_efflen
    move.l  %d0,%d6
    movea.l %a3,%a0
    bsr.b   cl_efflen
    cmp.l   %d6,%d0
    bne.b   ed_yes
ed_no:
    moveq   #0,%d0
    bra.b   ed_out
ed_yes:
    moveq   #1,%d0
ed_out:
    movem.l (%sp),%d2-%d6/%a2-%a3
    lea     28(%sp),%sp
    rts

| cl_efflen (a0 = a slab, d5 = the record's offset, d4 = its track) -> d0 = length << 8 | scale as
| it plays: the record's own in PER TRACK, the pattern's in NORMAL. Uses d0-d1/a1.
cl_efflen:
    movea.l %a0,%a1
    adda.l  #TRAILER,%a1
    tst.b   T_SMODE(%a1)
    bne.b   ef_rec
    moveq   #0,%d0
    move.b  T_LEN(%a1),%d0
    lsl.l   #8,%d0
    move.b  T_SCALE(%a1),%d0
    rts
ef_rec:
    moveq   #0x50,%d1
    cmpi.l  #8,%d4
    bcs.b   ef_a
    moveq   #0x28,%d1
ef_a:
    add.l   %d5,%d1
    moveq   #0,%d0
    move.b  (%a0,%d1.l),%d0
    lsl.l   #8,%d0
    move.b  1(%a0,%d1.l),%d0
    rts

| cl_srclbl -> a0 = the label for the highlighted slot when the active track plays a sequence
| Clyps put on this pattern and it is unedited (length / scale bytes aside): "A14 6 TRG",
| "A14 LOCKS", "A14 ---" (in cl_buf) or "SAVED"; else a0 = 0. Keeps d2-d7/a2-a6.
cl_srclbl:
    lea     -20(%sp),%sp
    movem.l %d2-%d5/%a2,(%sp)
    jsr     cl_trk
    move.l  %d0,%d2                     | d2 = track
    jsr     cl_playt
    move.l  %d0,%d3                     | d3 = what plays: bank << 8 | pattern
    moveq   #0,%d0
    move.b  PLAY_BANK,%d0
    lsl.l   #8,%d0
    move.b  ACT_PAT,%d0
    cmp.l   %d3,%d0
    beq.w   sl_none                     | its own sequence
    move.l  %d2,-(%sp)
    jsr     cl_toff
    addq.l  #4,%sp
    move.l  %d0,%d4                     | d4 = record offset
    moveq   #0,%d0
    move.b  ACT_PAT,%d0
    move.l  %d0,-(%sp)
    move.b  PLAY_BANK,%d0
    move.l  %d0,-(%sp)
    jsr     cl_slab
    addq.l  #8,%sp
    adda.l  %d4,%a0
    movea.l %a0,%a2                     | a2 = the playing record
    move.l  %d3,%d5
    lsr.l   #8,%d5                      | d5 = source bank (or SRC_SAVED)
    cmpi.l  #SRC_SAVED,%d5
    beq.w   sl_saved
    cmpi.l  #16,%d5
    bcc.w   sl_none
    move.l  %d3,%d0
    andi.l  #0xff,%d0
    move.l  %d0,-(%sp)
    move.l  %d5,-(%sp)
    jsr     cl_slab
    addq.l  #8,%sp
    adda.l  %d4,%a0
    movea.l %a0,%a1                     | a1 = the source record
    movea.l %a2,%a0
    move.l  %d2,%d0
    jsr     cl_same
    tst.l   %d0
    bne.w   sl_none                     | edited since: the plain summary
    moveq   #0,%d0
    cmpi.l  #8,%d2
    scc     %d0
    move.l  %d0,-(%sp)
    move.l  %a2,-(%sp)
    jsr     cl_classify
    addq.l  #8,%sp
    move.l  %d3,%d1
    andi.l  #0xff,%d1
    addq.l  #1,%d1                      | slot number
    addi.l  #'A',%d5                    | bank letter
    subq.l  #1,%d0
    beq.b   sl_lck
    bcs.b   sl_emp
    moveq   #0,%d1
    move.l  4(%a2),-(%sp)
    move.l  (%a2),%d0
    bsr.w   cl_popc
    move.l  (%sp)+,%d0
    bsr.w   cl_popc
    move.l  %d1,-(%sp)                  | trig count
    move.l  %d3,%d1
    andi.l  #0xff,%d1
    addq.l  #1,%d1
    move.l  %d1,-(%sp)
    move.l  %d5,-(%sp)
    pea     cl_fmt_srct
    bra.b   sl_fmt
sl_lck:
    clr.l   -(%sp)
    move.l  %d1,-(%sp)
    move.l  %d5,-(%sp)
    pea     cl_fmt_srcl
    bra.b   sl_fmt
sl_emp:
    clr.l   -(%sp)
    move.l  %d1,-(%sp)
    move.l  %d5,-(%sp)
    pea     cl_fmt_srce
sl_fmt:
    pea     cl_buf
    jsr     SPRINTF
    lea     20(%sp),%sp
    lea     cl_buf,%a0
    bra.b   sl_out
sl_saved:
    move.l  %d2,%d0
    move.l  #TRAC_A,%d1
    muls.l  %d1,%d0
    movea.l #SAVED_BASE,%a1
    adda.l  %d0,%a1                     | a1 = the saved sequence
    movea.l %a2,%a0
    move.l  %d2,%d0
    jsr     cl_same
    tst.l   %d0
    bne.b   sl_none
    lea     cl_s_saved,%a0
    bra.b   sl_out
sl_none:
    suba.l  %a0,%a0
sl_out:
    movem.l (%sp),%d2-%d5/%a2
    lea     20(%sp),%sp
    rts

| cl_same (a0, a1 = two records of track d0) -> d0 = 0 when equal, their length / scale bytes
| aside (a load writes the resolved ones). Uses d1/a0/a1; keeps d2-d7/a2-a6.
cl_same:
    lea     -8(%sp),%sp
    movem.l %d2-%d3,(%sp)
    move.l  #TRAC_A,%d3                 | d3 = record length
    moveq   #0x50,%d2                   | d2 = the length byte's offset
    cmpi.l  #8,%d0
    bcs.b   cs_a
    move.l  #TRAC_M,%d3
    moveq   #0x28,%d2
cs_a:
    move.l  %d2,%d0
    jsr     cl_cmpw
    tst.l   %d0
    bne.b   cs_out
    addq.l  #2,%a0
    addq.l  #2,%a1
    move.l  %d3,%d0
    sub.l   %d2,%d0
    subq.l  #2,%d0
    jsr     cl_cmpw
cs_out:
    movem.l (%sp),%d2-%d3
    lea     8(%sp),%sp
    rts

| d1 += number of set bits in d0 (uses d0, a1)
cl_popc:
    tst.l   %d0
    beq.b   pc_out
    movea.l %d0,%a1
    subq.l  #1,%d0
    move.l  %a1,-(%sp)
    and.l   (%sp)+,%d0                  | clear the lowest set bit
    addq.l  #1,%d1
    bra.b   cl_popc
pc_out:
    rts

| ================================================================ the Clyps grid (LED slot 0)
| no args: stock calls it from 0x4007e998 / its rebuilds. Per slot of the shown bank, first match
| (the user, 2026-11-04):
|   yellow, flashing   the active track's cued sequence (cl_blink: off half of every period)
|   red / yellow blink the active track's sequence: where what it plays was loaded from (cl_srccode;
|                      cl_blink lights its green die 3 ticks a period, as stock's p-locked trig)
|   yellow             the select box on any other slot
|   red                the pattern you are on
|   green 15 / 7       a slot with sample/note trigs / other data only; off = empty
cl_paint:
    lea     -36(%sp),%sp
    movem.l %d2-%d6/%a2-%a5,(%sp)
    lea     LED_BRI,%a3
    lea     LED_ON,%a4
    lea     LED_OFF,%a5
    jsr     cl_hstate
    btst    #1,%d0
    bne.w   cp_pview                    | the [PTN]+[BANK] chord held: the pattern view
    jsr     cl_trk
    add.l   %d0,%d0
    lea     cl_cue,%a0
    moveq   #0,%d0
    move.w  (%a0,%d0.l),%d0
    movea.l %d0,%a2                     | a2 = the active track's cue (0xffff = none)
    jsr     cl_srccode
    move.l  %d0,%d5                     | d5 = its sequence's slot
    moveq   #0,%d6
    move.b  cl_sbank,%d6
    lsl.l   #8,%d6
    move.b  cl_cur,%d6                  | d6 = the box
    moveq   #0,%d2
cp_lp:
    lea     LED_TBL,%a0
    move.l  (%a0,%d2.l*4),%d3           | d3 = red die, d4 = green die
    move.l  %d3,%d4
    addq.l  #1,%d4
    pea     15
    move.l  %d3,-(%sp)
    jsr     (%a3)
    move.l  %d4,(%sp)
    jsr     (%a3)                       | full brightness on both (half green is set below)
    addq.l  #8,%sp
    moveq   #0,%d0
    move.b  cl_bank,%d0
    lsl.l   #8,%d0
    or.l    %d2,%d0                     | d0 = this slot
    cmp.l   %a2,%d0
    beq.b   cp_yellow                   | cued (cl_blink flashes it)
    cmp.l   %d5,%d0
    beq.b   cp_red                      | its sequence (cl_blink: red / yellow)
    cmp.l   %d6,%d0
    beq.b   cp_yellow                   | the box: solid yellow
    move.b  cl_bank,%d0
    cmp.b   PLAY_BANK,%d0
    bne.b   cp_green
    moveq   #0,%d0
    move.b  ACT_PAT,%d0
    cmp.l   %d2,%d0
    bne.b   cp_green
cp_red:
    move.l  %d3,-(%sp)                  | red: the pattern you are on / the track's sequence
    jsr     (%a4)
    move.l  %d4,(%sp)
    jsr     (%a5)
    addq.l  #4,%sp
    bra.w   cp_next
cp_yellow:
    move.l  %d3,-(%sp)                  | yellow: red + green
    jsr     (%a4)
    move.l  %d4,(%sp)
    jsr     (%a4)
    addq.l  #4,%sp
    bra.w   cp_next
cp_green:
    move.l  %d3,-(%sp)
    jsr     (%a5)                       | red off
    addq.l  #4,%sp
    lea     cl_cls,%a0
    moveq   #0,%d0
    move.b  (%a0,%d2.l),%d0
    beq.b   cp_off
    moveq   #15,%d1
    subq.l  #2,%d0
    beq.b   cp_bri
    moveq   #7,%d1                      | half: stock's dim level
cp_bri:
    move.l  %d1,-(%sp)
    move.l  %d4,-(%sp)
    jsr     (%a3)
    move.l  %d4,(%sp)
    jsr     (%a4)
    addq.l  #8,%sp
    bra.b   cp_next
cp_off:
    move.l  %d4,-(%sp)
    jsr     (%a5)
    addq.l  #4,%sp
cp_next:
    addq.l  #1,%d2
    cmpi.l  #16,%d2
    bne.w   cp_lp
cp_done:
    movem.l (%sp),%d2-%d6/%a2-%a5
    lea     36(%sp),%sp
    rts
| the pattern view (the user, 2026-10-30: with [PTN]+[BANK] held, whichever came first): the playing
| bank's patterns as stock's [PTN] view lights them -- your pattern red, a cued one yellow, those
| with data green (stock's own test PAT_HASDATA), empty off
cp_pview:
    moveq   #0,%d2
pv_lp:
    lea     LED_TBL,%a0
    move.l  (%a0,%d2.l*4),%d3
    move.l  %d3,%d4
    addq.l  #1,%d4
    pea     15
    move.l  %d3,-(%sp)
    jsr     (%a3)
    move.l  %d4,(%sp)
    jsr     (%a3)
    addq.l  #8,%sp
    moveq   #0,%d0
    move.b  ACT_PAT,%d0
    cmp.l   %d2,%d0
    bne.b   pv_cue
    move.l  %d3,-(%sp)                  | red
    jsr     (%a4)
    move.l  %d4,(%sp)
    jsr     (%a5)
    addq.l  #4,%sp
    bra.b   pv_next
pv_cue:
    tst.l   RUNNING
    beq.b   pv_data
    move.b  PEND_BANK,%d0
    cmp.b   PLAY_BANK,%d0
    bne.b   pv_data
    moveq   #0,%d0
    move.b  PEND_PAT,%d0
    cmp.l   %d2,%d0
    bne.b   pv_data
    move.l  %d3,-(%sp)                  | yellow
    jsr     (%a4)
    move.l  %d4,(%sp)
    jsr     (%a4)
    addq.l  #4,%sp
    bra.b   pv_next
pv_data:
    move.l  %d3,-(%sp)
    jsr     (%a5)                       | red off
    addq.l  #4,%sp
    moveq   #0,%d0
    move.b  PLAY_BANK,%d0
    move.l  %d0,-(%sp)
    move.l  %d2,-(%sp)
    jsr     PAT_HASDATA
    addq.l  #8,%sp
    move.l  %d4,-(%sp)
    lea     LED_OFF,%a0
    tst.l   %d0
    beq.b   pv_g
    lea     LED_ON,%a0
pv_g:
    jsr     (%a0)
    addq.l  #4,%sp
pv_next:
    addq.l  #1,%d2
    cmpi.l  #16,%d2
    bne.w   pv_lp
    bra.w   cp_done

| cl_ppaint: LED slot 7, the page LEDs. Stock's step indicator (PAGE_PAINT), except while the box
| is on ORIG or the [PTN]+[BANK] chord is held (the user, 2026-10-29): then all four LEDs show that
| original's status in the grid's colours -- red = playing (original, also once ORIG has run),
| yellow = its restore is cued, red with stock's p-lock yellow flash (cl_blink) = selected, changed.
cl_ppaint:
    jsr     cl_pstat
    move.b  %d0,cl_pled
    tst.l   %d0
    beq.w   pp_stock
    lea     -12(%sp),%sp
    movem.l %d2-%d4,(%sp)
    move.l  %d0,%d4                     | d4 = status
    moveq   #0x48,%d2                   | d2 = LED k's red die (0x48 + 2k), green = + 1
ppl_k:
    pea     15
    move.l  %d2,-(%sp)
    jsr     LED_BRI
    addq.l  #1,(%sp)
    jsr     LED_BRI
    addq.l  #8,%sp
    move.l  %d2,-(%sp)
    jsr     LED_ON
    addq.l  #1,(%sp)
    lea     LED_OFF,%a0
    cmpi.l  #2,%d4
    bne.b   ppl_g
    lea     LED_ON,%a0
ppl_g:
    jsr     (%a0)
    addq.l  #4,%sp
    addq.l  #2,%d2
    cmpi.l  #0x50,%d2
    bne.b   ppl_k
    movem.l (%sp),%d2-%d4
    lea     12(%sp),%sp
    rts
pp_stock:
    jmp     PAGE_PAINT

| cl_pstat -> d0 = 0 not ours (stock's page LEDs), 1 red: original, 2 yellow: restore cued, 3 flash.
| The box on ORIG: the active track (its sequence); the chord held: the whole pattern (every track's
| sequence and the Part).
cl_pstat:
    tst.b   cl_open
    beq.w   pst_no
    lea     -8(%sp),%sp
    movem.l %d2-%d3,(%sp)
    jsr     cl_hstate
    btst    #1,%d0
    bne.b   pst_pat
    jsr     cl_onorig                   | the box on your own pattern's slot (its original)
    tst.l   %d0
    beq.w   pst_none
    jsr     cl_trk
    move.l  %d0,%d2
    add.l   %d0,%d0
    lea     cl_cue,%a0
    moveq   #0,%d1
    move.w  (%a0,%d0.l),%d1
    cmpi.l  #SRC_ORIG<<8,%d1
    beq.w   pst_y
    move.l  %d2,%d0
    jsr     cl_diff
    tst.l   %d0
    beq.w   pst_r
    bra.w   pst_f
pst_pat:
    moveq   #0,%d2                      | any track's restore cued: yellow
pst_c:
    move.l  %d2,%d0
    add.l   %d0,%d0
    lea     cl_cue,%a0
    moveq   #0,%d1
    move.w  (%a0,%d0.l),%d1
    cmpi.l  #SRC_ORIG<<8,%d1
    beq.b   pst_y
    addq.l  #1,%d2
    cmpi.l  #16,%d2
    bne.b   pst_c
    moveq   #0,%d2                      | every track original ...
pst_d:
    move.l  %d2,%d0
    jsr     cl_diff
    tst.l   %d0
    bne.b   pst_f
    addq.l  #1,%d2
    cmpi.l  #16,%d2
    bne.b   pst_d
    jsr     cl_origok                   | ... and the Part as loaded
    tst.l   %d0
    beq.b   pst_r
    moveq   #0,%d0
    move.b  PLAY_BANK,%d0
    moveq   #0,%d1
    move.b  ACT_PAT,%d1
    movea.l #SNAPB,%a1
    jsr     cl_partin
    move.l  %a0,%d3
    moveq   #0,%d0
    move.b  PLAY_BANK,%d0
    moveq   #0,%d1
    move.b  ACT_PAT,%d1
    movea.l #BLOB,%a1
    jsr     cl_partin
    movea.l %d3,%a1
    move.l  #PARTSZ,%d0
    jsr     cl_cmpw
    tst.l   %d0
    bne.b   pst_f
pst_r:
    moveq   #1,%d0
    bra.b   pst_out
pst_y:
    moveq   #2,%d0
    bra.b   pst_out
pst_f:
    moveq   #3,%d0
    bra.b   pst_out
pst_none:
    moveq   #0,%d0
pst_out:
    movem.l (%sp),%d2-%d3
    lea     8(%sp),%sp
    rts
pst_no:
    moveq   #0,%d0
    rts

| ================================================================ names on the card (worker task)
    .section .dram,"ax"
| cl_cpath(dst, n 0..15, ext): "<set>/<project>/clypsNN.ext" into dst
cl_cpath:
    move.l  12(%sp),-(%sp)              | ext
    move.l  12(%sp),%d0
    addq.l  #1,%d0
    move.l  %d0,-(%sp)                  | NN
    clr.l   -(%sp)
    clr.l   -(%sp)
    jsr     PROJDIR
    addq.l  #8,%sp
    move.l  %d0,-(%sp)                  | the project folder
    pea     cl_fmt_cpath
    move.l  20(%sp),-(%sp)              | dst
    jsr     SPRINTF
    lea     20(%sp),%sp
    rts

| cl_nwrite(n): bank n's names -> clypsNN.work (errors ignored)
cl_nwrite:
    lea     -152(%sp),%sp               | 0 handle (24), 24 path (128)
    pea     cl_s_work
    move.l  160(%sp),-(%sp)
    pea     32(%sp)
    jsr     cl_cpath
    lea     12(%sp),%sp
    pea     FBUFSZ
    pea     FBUF
    pea     S_W
    pea     36(%sp)                     | path
    pea     16(%sp)                     | handle
    jsr     FOPEN
    lea     20(%sp),%sp
    tst.l   %d0
    ble.b   nw_out
    pea     8
    pea     cl_nfhdr
    pea     8(%sp)
    jsr     FWRITE
    lea     12(%sp),%sp
    move.l  156(%sp),%d0
    move.l  #256*NAME_W,%d1
    muls.l  %d1,%d0
    addi.l  #NAMES,%d0
    pea     256*NAME_W
    move.l  %d0,-(%sp)
    pea     8(%sp)
    jsr     FWRITE
    lea     12(%sp),%sp
    pea     (%sp)
    jsr     FCLOSE
    addq.l  #4,%sp
nw_out:
    lea     152(%sp),%sp
    rts

| cl_nread(n): clypsNN.work -> bank n's names; missing, the wrong size or a bad header -> none
cl_nread:
    lea     -160(%sp),%sp               | 0 handle (24), 24 path (128), 152 header (8)
    move.l  164(%sp),%d0
    move.l  #256*NAME_W,%d1
    muls.l  %d1,%d0
    addi.l  #NAMES,%d0
    move.l  %d0,-(%sp)                  | the bank's names (kept at 0(sp) below: offsets + 4)
    movea.l %d0,%a0                     | none, until the file says otherwise
    move.l  #256*NAME_W/4,%d0
rd_clr:
    clr.l   (%a0)+
    subq.l  #1,%d0
    bne.b   rd_clr
    pea     cl_s_work
    move.l  172(%sp),-(%sp)
    pea     36(%sp)
    jsr     cl_cpath
    lea     12(%sp),%sp
    pea     FBUFSZ
    pea     FBUF
    pea     S_R
    pea     40(%sp)
    pea     20(%sp)
    jsr     FOPEN
    lea     20(%sp),%sp
    tst.l   %d0
    ble.w   rd_out
    move.l  4(%sp),-(%sp)               | size(fd) must be exactly NF_SIZE
    movea.l FS_SIZE,%a0
    jsr     (%a0)
    addq.l  #4,%sp
    cmpi.l  #NF_SIZE,%d0
    bne.b   rd_close
    pea     8
    pea     160(%sp)
    pea     12(%sp)
    jsr     FREAD
    lea     12(%sp),%sp
    cmpi.l  #1,%d0
    bne.b   rd_close
    move.l  156(%sp),%d0
    cmpi.l  #0x434c5950,%d0             | "CLYP"
    bne.b   rd_close
    move.l  160(%sp),%d0
    cmpi.l  #0x00010100,%d0             | version 1, 256 names
    bne.b   rd_close
    pea     256*NAME_W
    move.l  4(%sp),-(%sp)
    pea     12(%sp)
    jsr     FREAD
    lea     12(%sp),%sp
    cmpi.l  #1,%d0
    beq.b   rd_term
    movea.l (%sp),%a0                   | a short read: none after all
    move.l  #256*NAME_W/4,%d0
rd_clr2:
    clr.l   (%a0)+
    subq.l  #1,%d0
    bne.b   rd_clr2
rd_term:
    movea.l (%sp),%a0                   | every name ends within its 10 bytes
    moveq   #0,%d0
    move.w  #256,%d0
rd_t:
    clr.b   NAME_W-1(%a0)
    lea     NAME_W(%a0),%a0
    subq.l  #1,%d0
    bne.b   rd_t
rd_close:
    pea     4(%sp)
    jsr     FCLOSE
    addq.l  #4,%sp
rd_out:
    lea     164(%sp),%sp
    rts

| cl_ncopy(n, from_ext, to_ext): clypsNN.from -> clypsNN.to; the source missing -> the destination is
| removed too, so .work and .strd stay mirrors of stock's own (errors ignored)
cl_ncopy:
    lea     -256(%sp),%sp               | 0 src path (128), 128 dst path (128)
    move.l  264(%sp),-(%sp)
    move.l  264(%sp),-(%sp)
    pea     8(%sp)
    jsr     cl_cpath                    | src
    lea     12(%sp),%sp
    move.l  268(%sp),-(%sp)
    move.l  264(%sp),-(%sp)
    pea     136(%sp)
    jsr     cl_cpath                    | dst
    lea     12(%sp),%sp
    clr.l   -(%sp)
    pea     4(%sp)
    pea     136(%sp)
    jsr     FCOPY
    lea     12(%sp),%sp
    cmpi.l  #-12,%d0
    bne.b   nc_out
    pea     128(%sp)
    movea.l FS_UNLINK,%a0
    jsr     (%a0)
    addq.l  #4,%sp
nc_out:
    lea     256(%sp),%sp
    rts

| cl_ncopy_mask(mask, from, to)
cl_ncopy_mask:
    move.l  %d2,-(%sp)
    moveq   #0,%d2
cm_l:
    move.l  8(%sp),%d0
    btst    %d2,%d0
    beq.b   cm_n
    move.l  16(%sp),-(%sp)
    move.l  16(%sp),-(%sp)
    move.l  %d2,-(%sp)
    jsr     cl_ncopy
    lea     12(%sp),%sp
cm_n:
    addq.l  #1,%d2
    cmpi.l  #16,%d2
    bne.b   cm_l
    move.l  (%sp)+,%d2
    rts

| the loader's return (cl_ldexit): the names of the banks just read -- all 16 on a project load (the
| power-on resume reads every bank but the current one from the card; its names come from its
| clypsNN.work too)
cl_nload_all:
    tst.b   cl_namesok
    beq.b   na_out
    move.l  %d2,-(%sp)
    moveq   #0,%d2
na_l:
    moveq   #0,%d0
    move.w  cl_ldmask,%d0
    move.l  %d0,%d1
    andi.l  #0xffff,%d1
    cmpi.l  #0xfe00,%d1                 | (cheap "8 banks or more": the project loads are 0xffff
    bcc.b   na_rd                       | and ~(1 << current))
    btst    %d2,%d0
    beq.b   na_n
na_rd:
    move.l  %d2,-(%sp)
    jsr     cl_nread
    addq.l  #4,%sp
na_n:
    addq.l  #1,%d2
    cmpi.l  #16,%d2
    bne.b   na_l
    move.l  (%sp)+,%d2
na_out:
    rts

| ---- the hooks (each replays what it replaced; its own registers saved around the work)
| 0x400919d6, the bank writer's common exit (`move.l d2,d0 ; movem.l -324(fp),d2-d7/a2-a5`):
| bankNN.work were written for the mask fp@(12) -> clypsNN.work too, unless nothing was written
| (mask 0, d2 -53 outside a project, -7 no project folder)
cl_hwrite:
    lea     -56(%sp),%sp
    movem.l %d0-%d7/%a0-%a5,(%sp)
    tst.b   cl_namesok
    beq.b   hw_done
    cmpi.l  #-53,%d2
    beq.b   hw_done
    cmpi.l  #-7,%d2
    beq.b   hw_done
    moveq   #0,%d3
    move.w  14(%fp),%d3                 | the mask
    beq.b   hw_done
    moveq   #0,%d2
hw_l:
    btst    %d2,%d3
    beq.b   hw_n
    move.l  %d2,-(%sp)
    jsr     cl_nwrite
    addq.l  #4,%sp
hw_n:
    addq.l  #1,%d2
    cmpi.l  #16,%d2
    bne.b   hw_l
hw_done:
    movem.l (%sp),%d0-%d7/%a0-%a5
    lea     56(%sp),%sp
    move.l  %d2,%d0
    movem.l -324(%fp),%d2-%d7/%a2-%a5
    jmp     0x400919de

| 0x4008f0a2, SAVE PROJECT's .work -> .strd copies (0x4008ee74) done: ours too
cl_hstorep:
    lea     -56(%sp),%sp
    movem.l %d0-%d7/%a0-%a5,(%sp)
    cmpi.l  #-53,%d2
    beq.b   sp_done
    pea     cl_s_strd
    pea     cl_s_work
    pea     0xffff
    jsr     cl_ncopy_mask
    lea     12(%sp),%sp
    jsr     cl_snapall                  | the originals = the project as saved (the user, 2026-11-02)
sp_done:
    movem.l (%sp),%d0-%d7/%a0-%a5
    lea     56(%sp),%sp
    move.l  %d2,%d0
    movem.l -560(%fp),%d2-%d7/%a2-%a5
    jmp     0x4008f0aa

| 0x4008f3ae, RELOAD PROJECT's .strd -> .work restore (0x4008f180) done: ours too
cl_hrestp:
    lea     -56(%sp),%sp
    movem.l %d0-%d7/%a0-%a5,(%sp)
    cmpi.l  #-53,%d2
    beq.b   rp_done
    pea     cl_s_work
    pea     cl_s_strd
    pea     0xffff
    jsr     cl_ncopy_mask
    lea     12(%sp),%sp
rp_done:
    movem.l (%sp),%d0-%d7/%a0-%a5
    lea     56(%sp),%sp
    move.l  %d2,%d0
    movem.l -560(%fp),%d2-%d7/%a2-%a5
    jmp     0x4008f3b6

| 0x4008ee66, SAVE BANK's copies (0x4008eda4, mask d6) done (`move.l d4,d0 ; movem.l (sp),...`)
cl_hstoreb:
    lea     -56(%sp),%sp
    movem.l %d0-%d7/%a0-%a5,(%sp)
    cmpi.l  #-53,%d4
    beq.b   sb_done
    pea     cl_s_strd
    pea     cl_s_work
    move.l  %d6,-(%sp)
    jsr     cl_ncopy_mask
    lea     12(%sp),%sp
    move.l  %d6,-(%sp)                  | the originals = those banks as saved (the user, 2026-11-02)
    jsr     cl_snapmask
    addq.l  #4,%sp
sb_done:
    movem.l (%sp),%d0-%d7/%a0-%a5
    lea     56(%sp),%sp
    move.l  %d4,%d0
    movem.l (%sp),%d2-%d7/%a2-%a6
    jmp     0x4008ee6c

| 0x4008f172, RELOAD BANK's restore (0x4008f0b0, mask d6) done
cl_hrestb:
    lea     -56(%sp),%sp
    movem.l %d0-%d7/%a0-%a5,(%sp)
    cmpi.l  #-53,%d4
    beq.b   rb_done
    pea     cl_s_work
    pea     cl_s_strd
    move.l  %d6,-(%sp)
    jsr     cl_ncopy_mask
    lea     12(%sp),%sp
rb_done:
    movem.l (%sp),%d0-%d7/%a0-%a5
    lea     56(%sp),%sp
    move.l  %d4,%d0
    movem.l (%sp),%d2-%d7/%a2-%a6
    jmp     0x4008f178

| 0x4008ed5e, DELETE PROJECT after its known files, before the folder goes: ours too (with its own
| helper, a1 = its context d5), or the folder would not be empty
cl_hdel:
    lea     -56(%sp),%sp
    movem.l %d0-%d7/%a0-%a5,(%sp)
    moveq   #0,%d2
hd_l:
    moveq   #0,%d3                      | .work, then .strd
hd_e:
    pea     cl_s_work
    tst.l   %d3
    beq.b   hd_w
    addq.l  #4,%sp
    pea     cl_s_strd
hd_w:
    move.l  %d2,%d0
    addq.l  #1,%d0
    move.l  %d0,-(%sp)
    pea     cl_fmt_cname
    pea     cl_tname
    jsr     SPRINTF
    lea     16(%sp),%sp
    pea     cl_tname
    movea.l %d5,%a1
    jsr     DEL_ONE
    addq.l  #4,%sp
    addq.l  #1,%d3
    cmpi.l  #2,%d3
    bne.b   hd_e
    addq.l  #1,%d2
    cmpi.l  #16,%d2
    bne.b   hd_l
    movem.l (%sp),%d0-%d7/%a0-%a5
    lea     56(%sp),%sp
    move.l  24(%sp),-(%sp)              | displaced
    move.l  32(%sp),-(%sp)
    jmp     0x4008ed66

| 0x400914de, EXPORT TO SET after the arrangements: ours too, not required (a4 set, d7 name, d6 cb)
cl_hexp:
    lea     -56(%sp),%sp
    movem.l %d0-%d7/%a0-%a5,(%sp)
    moveq   #0,%d2
he_l:
    moveq   #0,%d3
he_e:
    pea     cl_s_work
    tst.l   %d3
    beq.b   he_w
    addq.l  #4,%sp
    pea     cl_s_strd
he_w:
    move.l  %d2,%d0
    addq.l  #1,%d0
    move.l  %d0,-(%sp)
    pea     cl_fmt_cname
    pea     cl_tname
    jsr     SPRINTF
    lea     16(%sp),%sp
    move.l  %d6,-(%sp)                  | cb
    clr.l   -(%sp)                      | not required
    move.l  %d7,-(%sp)
    move.l  %a4,-(%sp)
    pea     cl_tname
    pea     cl_tname
    jsr     EXP_ONE
    lea     24(%sp),%sp
    addq.l  #1,%d3
    cmpi.l  #2,%d3
    bne.b   he_e
    addq.l  #1,%d2
    cmpi.l  #16,%d2
    bne.b   he_l
    movem.l (%sp),%d0-%d7/%a0-%a5
    lea     56(%sp),%sp
    move.l  %d6,-(%sp)                  | displaced
    pea     1
    jmp     0x400914e4

    .section .dram,"ax"
    .include "tools/clyps/clyps_reload.s"

| ================================================================ data (both parts run from RAM)
    .align 2
cl_layer:   .long 0, cl_keys, cl_encs, 0, 0     | +16 is written -1 by the push

| key record: code, 0, press, release, hold, sub-map, 4 x 0, hold delay (w), repeat (w)
    .macro KREC code, press, rel, hold, dly=0, rep=0, sub=0
    .byte \code, 0
    .long \press, \rel, \hold, \sub, 0
    .short \dly, \rep
    .endm
cl_keys:
| ⚠️ Every record's hold delay / repeat MUST equal the base keymap's (T1 0x400bfc10) for that key.
| set_key_state appends a key's timer record to the repeat list 0x460d1660 at press when its
| delay is non-zero, and removes it at release only when the record it then holds has a non-zero
| delay. A key pressed under one layer and released under another (the chord's second key: our
| layer goes up inside its press handler) with differing delays leaves a stale entry, and that
| key's next press links the record to itself: the UI task loops forever (measured, emulator).
    .irp c, 0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15
    KREC \c, cl_k_trig, 0, 0, 16, 0
    .endr
    .irp c, 0x10,0x11,0x12,0x13,0x14,0x15,0x16,0x17
    KREC \c, cl_k_track, cl_k_track, cl_k_track, 30, 0
    .endr
    KREC 0x33, cl_k_ud, 0, cl_k_ud, 15, 4
    KREC 0x20, cl_k_ud, 0, cl_k_ud, 15, 4
    KREC 0x34, cl_k_lr, 0, 0, 15, 6      | the other column, no repeat (the delay stays non-zero:
    KREC 0x21, cl_k_lr, 0, 0, 15, 6      | the add/remove rule above holds)
    KREC 0x31, cl_k_yes, 0, 0, 0, 0
    KREC 0x32, cl_k_no, 0, 0, 0, 0
    KREC 0x2e, cl_k_chord, cl_k_chord, cl_k_chord, 30, 0    | holds: stock's tap-eligible re-arm
    KREC 0x2f, cl_k_chord, cl_k_chord, cl_k_chord, 30, 0
    KREC 0x2d, cl_k_func, cl_k_func, 0, 0, 0, cl_fsub
    KREC 0x1b, cl_k_page, 0, 0, 0, 0     | [PAGE]: the original back ([FUNC]+[PAGE]: every track's)
    KREC 0x2a, cl_k_cue, cl_k_cue, 0, 0, 0, cl_csub    | [CUE]: the group (scope §1.9); delay 0 as T1's
    .byte 0xff, 0
    .align 2
| [CUE]'s sub-map: chained after stock's 0x400bf2a0 (TRACK = cue, [YES], [TEMPO] = metronome, the
| scene keys 0x2b / 0x2c), it wins for the keys it lists. Delays 0, as stock's. The rest stay stock's.
cl_csub:    .long 0, cl_ckeys, 0, 0, 0
cl_ckeys:
    .irp c, 0x10,0x11,0x12,0x13,0x14,0x15,0x16,0x17
    KREC \c, cl_k_cuet, 0, 0, 0, 0       | [CUE]+TRACK: in / out of the group
    .endr
    KREC 0x31, cl_k_nop, 0, 0, 0, 0      | [CUE]+[YES]: nothing (stock's 0x400402ec is a cue action)
    .byte 0xff, 0
    .align 2
| [FUNC]'s sub-map. A key's sub-maps are not overridden by a higher layer but CHAINED: the rebuild
| (0x4003125c) appends each layer's sub-map for the key after the ones below, and the press links
| the chain at the end of the layer list (0x40031766), stock's FUNC sub-map 0x400bfa1e first. So
| ours comes after it and wins for the keys it lists (measured: without it, [FUNC]+[YES] reached
| stock's 0x4005e3d8). Delays as stock's sub-map; a key held across [FUNC]'s release keeps the
| record it was pressed with (0x400312e2). +12 / +16 are written by stock: RAM.
cl_fsub:    .long 0, cl_fkeys, 0, 0, 0
cl_fkeys:
    KREC 0x31, cl_k_yes, 0, 0, 0, 0      | [FUNC]+[YES]: nothing in Clyps
    KREC 0x32, cl_k_no, 0, 0, 0, 0       | [FUNC]+[NO]: nothing in Clyps
    KREC 0x1b, cl_k_page, 0, 0, 0, 0     | [FUNC]+[PAGE] restore all
    KREC 0x33, cl_k_ud, 0, cl_k_ud, 15, 4
    KREC 0x20, cl_k_ud, 0, cl_k_ud, 15, 4
    KREC 0x34, cl_k_lr, 0, 0, 15, 5
    KREC 0x21, cl_k_lr, 0, 0, 15, 5
    KREC 0x2e, cl_k_chord, cl_k_chord, 0, 0, 0
    KREC 0x2f, cl_k_chord, cl_k_chord, 0, 0, 0
|   no TRACK keys here: [FUNC]+TRACK is stock's mute (0x40083dfc, its FUNC sub-map), in Clyps too
|   (the user, 2026-10-29). Same delays (0), so a TRACK held across [FUNC] leaves no stale timer.
|   no [MIDI] (0x35) either: [FUNC]+[MIDI] = stock's Parts menu (0x4002e7c8), opening over Clyps
|   (the user, 2026-10-29; PRIO 0).
    .byte 0xff, 0
    .align 2

| encoder records (22 B): id, 0, handler 0 = locked (stock lists do the same)
cl_encs:
    .irp e, 0,1,2,3,4,5,6
    .byte \e, 0
    .long 0, 0, 0, 0, 0
    .endr
    .byte 0xff, 0
    .align 2

| LED layer: {next, records}; record {slot, paint, tick, period, pad}, ended by -1
cl_led:     .long 0, cl_ledrec
cl_ledrec:  .long 0, cl_paint, cl_blink
            .byte CL_BLINK, 0
            .long 7, cl_ppaint, 0       | the page LEDs: stock's, except on ORIG / with the chord held
            .byte 0, 0
            .long -1
            .align 2

cl_win:     .long 0
cl_gmask:   .long 0                     | the painters' group test (cl_gupd): 0 = none, else 0x10000 | members
cl_grp:     .short 0                    | the group's members: bit t, MIDI 8..15 (scope §1.9)
cl_cuh:     .byte 0                     | [CUE] held (our own press / release record)
cl_gn:      .byte 0                     | cl_gord's entries
cl_gpre:    .byte 0                     | the track (0..15) you were on when the group began
cl_gord:    .space 16                   | the group's members in add order, newest last (cl_k_cuet)
cl_open:    .byte 0
cl_sbank:   .byte 0                     | the select box's bank (cl_cur its slot, 16 = ORIG)
cl_bank:    .byte 0
cl_cur:     .byte 0
cl_fn:      .byte 0                     | [FUNC] held (our own press/release record)
cl_flash:   .byte 0                     | the header shows SAVED (a save) until the next key
cl_lastt:   .byte 0                     | the track (0..15, MIDI 8..15) at the last cl_refresh
cl_flk:     .byte 0                     | the load confirmation: UI ticks left (0 = none)
cl_fph:     .byte 0                     | ... its phase: 1 = inverted
cl_fcnt:    .byte 0                     | ... ticks left in this phase
cl_ftgt:    .byte 0                     | ... 0 = the select box (or the highlight), 1 = the header label
cl_ptpop:   .byte 0                     | stock's [PTN] overlay taken down for the chord (cl_k_chord)
cl_hdrst:   .byte 0                     | the header was drawn for this cl_hstate
cl_bkdef:   .byte 0                     | a [BANK] press outside Clyps was deferred (SELECT BANK on release)
cl_chordout:.byte 0                     | Clyps was opened by the chord, still held: chord + SCALE closes
cl_pled:    .byte 0                     | the 4th page LED: 0 stock's, 1 red, 2 yellow, 3 flashing red
cl_ptfwd:   .byte 0                     | a [PTN] pressed in Clyps: its events go to stock's handler
cl_bkfwd:   .byte 0                     | a [BANK] pressed in Clyps: stock's gesture, ours to finish
cl_bkarm:   .byte 0                     | ... BANK_SEL 2 from now on is a pick (closes Clyps)
cl_bkused:  .byte 0                     | ... the arrows paged during it: no SELECT BANK on release
cl_nproj:   .byte 0                     | project loads seen (the emulator gate reads it)
            .align 2
cl_cls:     .space 16
| the valid marks: inside the loaded image, so every boot's depack zeroes them (the buffers they
| describe are not)
cl_lastp:   .short 0xffff               | the pattern you were on at the last redraw (cl_uitail)
cl_magic:   .long CL_MAGIC              | the DRAM part is in place (the boot loader put it there)
cl_svalid:  .space 16                   | per track: a saved sequence is held
cl_namesok: .byte 0                     | the names are cleared (at the first project load) and usable
            .align 2
cl_nedit:   .long 0                     | the name being edited (its index)
cl_nbuf:    .space NAME_W               | the editor's scratch copy
            .align 2
cl_snapok:  .short 0                    | bit b: bank b's load snapshot (its originals) is valid
cl_ldmask:  .short 0                    | the masked loader in progress: its banks
cl_ldret:   .long 0                     | ... and its caller's return address
cl_buf:     .space 32

| the tick's state: in the ROM part, beside the code that writes it
    ROMSEC
    .align 2
cl_src:     .space 32                   | per track: (bank, pattern) the sequence came from
cl_home:    .fill 32, 1, 0xff           | per track: the playing (bank, pattern) at that load
cl_cue:     .fill 16, 2, 0xffff         | per track: the cued (bank<<8 | pattern), 0xffff = none
cl_cueh:    .fill 16, 2, 0xffff         | per track: the playing (bank<<8 | pattern) it aims at
cl_arm:     .space 16                   | per track: the gate has passed; waiting for a window start
cl_cuef:    .space 16                   | per track: the cue is FULL (its machine / FX too)
cl_self:    .byte 0                     | ORIG PTN+PART playing: a pattern change to itself is pending
cl_wpart:   .byte 0                     | the rest of a Part changed (cl_slrest, a card pattern): its whole mirror
cl_wslab:   .byte 0                     | a NORMAL -> PER TRACK conversion: the mirror owes the whole slab
cl_bat:     .byte 0                     | a batch of loads is running (cl_bbeg / cl_bend): immediate posts wait
    .align 2
cl_batm:    .long 0                     | ... the tracks they owe (cl_postmask at cl_bend)
cl_postf:   .space 16                   | per track: a FULL landing the UI side owes (cl_postpart)
cl_postm:   .space 8                    | per audio track: ... and its machine changed
cl_pwhole:  .byte 0                     | ORIG PTN/PART pending: the first landing copies cl_slR too
            .align 2
cl_post:    .short 0                    | tracks whose landing the UI side has not followed up yet
cl_bph:     .byte 0                     | the cue flash phase (cl_blink)
cl_nq:      .byte 0                     | cues pending (the tick's fast path)
            .align 2

    .section .dram,"ax"

cl_corners: .short 0,63, 1,63, 0,62, WIN_W-1,63, WIN_W-2,63, WIN_W-1,62
cl_xpix:    .byte 0,1, 2,1, 1,2, 0,3, 2,3   | the "x": corners and centre of a 3 x 3 at rows y + 1..3
            .align 2
cl_colx:    .short 6, 8, 52, 3          | column 1: number field, bar / box 8..52, its x at 3..5
            .short 62, 60, 108, 55      | column 2: numbers 62..68, bar / box 60..108, its x at 55..57
cl_fmt_hdrt:.asciz "%c%d "
cl_s_multi: .asciz "MULTI LD:"            | a group, or the [PTN]+[BANK] chord held (32 px)
cl_fmt_hdrb:.asciz "BNK %c"
cl_s_gseq:  .asciz "TRK SEQS"
cl_s_gfull: .asciz "TRKS FULL"
cl_s_gorig: .asciz "ORIG SEQS"
cl_s_gorigf:.asciz "ORIGS FULL"
cl_s_load:  .asciz "LOAD:"
cl_s_seqb:  .asciz "TRK SEQ"
cl_s_seqf:  .asciz "TRK FULL"
cl_fmt_num: .asciz "%d"
cl_fmt_trg: .asciz "%c%02d %02d TR"       | 33 px: "A01 15 TR", as a source label (the user)
cl_s_lck:   .asciz "LOCKS"
cl_s_emp:   .asciz "---"
cl_s_orig:  .asciz "ORIG"
cl_s_origs: .asciz "ORIG TRK SEQ"
cl_s_origf: .asciz "ORIG TRK FULL"
cl_s_origp: .asciz "ORIG PTN+PRT"         | 46 px: its box ends at x 86, as T6 LOAD:'s longest
cl_s_saved: .asciz "SAVED TRK"           | 34 px: the slot label after a temp reload (the user, 2026-11-02)
cl_fmt_srct:.asciz "%c%02d %02d TR"       | 33 px: "B14 06 TR" (the user, 2026-10-29)
cl_fmt_srcl:.asciz "%c%02d LOCKS"         | 34 px
cl_fmt_srce:.asciz "%c%02d ---"
cl_s_rename:.asciz "RENAME SEQUENCE"
cl_fmt_cpath:.asciz "%s/clyps%02d.%s"
cl_fmt_cname:.asciz "clyps%02d.%s"
cl_s_work:  .asciz "work"
cl_s_strd:  .asciz "strd"
            .align 2
cl_nfhdr:   .ascii "CLYP"
            .short 1, 256
cl_tname:   .space 16
            .align 2
cl_s_savef2:.asciz "SAVE FIRST!"
cl_s_ttsv:  .asciz "TEMP TRK SAVED"        | toast font 0x400ba862: 81 px
cl_s_ttrl:  .asciz "TEMP TRK RELOADED"     | 99 px
    .align 4
| the buffers: past the loaded image, uninitialised (dram.build's bss); read only behind a valid
| mark. The snapshot is every bank as loaded (16 slabs + its Parts each: the Parts are there for
| FULL restores), so every track's original is always there.
cl_bss:
    .equ SNAPB,       cl_bss                    | 16 x BANKSZ: the banks as loaded (the originals)
    .equ SAVED_BASE,  cl_bss + 16*BANKSZ        | 16 x TRAC_A: the saved sequences
    .equ NAMES,       SAVED_BASE + 16*TRAC_A    | 4096 x NAME_W: (bank, pattern, track) -> its name
    .equ SNAMES,      NAMES + 4096*NAME_W       | 16 x NAME_W: the saved sequences' names (right after
                                                | NAMES: one clear covers both)
    .equ NAMESNAP,    SNAMES + 16*NAME_W        | 4096 x NAME_W: the names as loaded (ORIG)
    .equ SAVEPART,    NAMESNAP + 4096*NAME_W    | 16 x PARTSZ: the Part a saved sequence was saved
                                                | with (its slice goes with a FULL reload)
    .equ RQ_SLAB,     SAVEPART + 16*PARTSZ      | the card reload's pattern (clyps_reload.s)
    .equ RQ_PART,     RQ_SLAB + PATSTRIDE       | ... and its Part, both parsed from the .strd (+2: the bss is a multiple of 4)
    .equ CL_BSS_SIZE, 16*BANKSZ + 16*TRAC_A + 4096*NAME_W + 16*NAME_W + 4096*NAME_W + 16*PARTSZ + PATSTRIDE + PARTSZ + 2
    .global CL_BSS_SIZE, cl_bss
