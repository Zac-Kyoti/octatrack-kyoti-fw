| SPDX-License-Identifier: MIT
| SPDX-FileCopyrightText: 2026 Zac Kyoti
|
| CLYPS -- reloads from the CF card (scope §1.8), .include'd by patch_clyps.s into its DRAM part.
|
| Forked from RELOAD_FROM_PROJECT (octabam-modules/reload-from-project/patch_reload3.s), whose card
| job this keeps as it was proven on hardware: stock's own type-0x14 storage job (posted with
| JOB_POST, run by the project worker task), our worker in its case (cl_rljob), stock's PTRN parser
| on the bank's .strd, the message armed BEFORE the post (S93), the "ours" flag set only on success
| (S90) so stock's doneFn skips its whole-bank reload exactly once, the trig-mask verify at the
| finish (SEQ RELOAD LOST), the live-cache refresh, the 2-line block toast. What differs (the user,
| 2026-10-30):
|   * the requests come only from Clyps' keys -- [PTN] alone + TRACK = the track's sequence;
|     [BANK] alone + TRACK = the sequence + that track's Part slice (Clyps' FULL load: machine, FX,
|     pages, scene locks, designer), never the whole Part; [PTN]+[BANK] + trig N = pattern N of the
|     bank Clyps shows (CL41, the user 2026-11-21; was the playing bank), its slab and its whole Part;
|   * the Part comes from the card: the .strd's WORKING Part chunk (stock's bank reader reads the
|     16 PTRN chunks, then the 4 working PART chunks, then the 4 SAVE PART copies), parsed with
|     stock's own 0x4008be2c into our buffer;
|   * toasts "TRACK n SEQ" / "RELOADED FROM PROJ", "TRACK n FULL" / ... (MIDI: "MIDI TRACK n ..."),
|     "PATTERN A05" / "RELOADED FROM PROJ" (the user, 2026-10-30).
| Runs in two contexts: cl_rlreq from a key handler (UI task), cl_rljob / cl_rldone in the project
| worker task (prio 1). Nothing here runs from a sequencer tick.

    .equ RL_JOBPOST,  0x40022778        | (mask): post the type-0x14 storage job for those banks
    .equ RL_J14EXIT,  0x400858a8        | the 0x14 case's exit: d0 = result (>= 0 ok, -12 never saved)
    .equ RL_J14ORIG,  0x4008586c        | the 0x14 case after its 2 displaced instructions (stock's)
    .equ RL_PARSEPAT, 0x4008cebc        | (fh, slab, ver): parse one PTRN chunk
    .equ RL_PARSEPRT, 0x4008be2c        | (fh, part, i, ver): parse one PART chunk (stock bank reader)
    .equ RL_FMTSTRD,  0x400b86d8        | "%s/bank%02d.strd"
    .equ RL_LLSEEK,   0x46c8243e        | -> the card filesystem's seek (id, byte offset)
    .equ RL_SCRATCH,  0x460aff60        | FBUF + 0x7000: one slab of scratch (the open uses 0x7000)
    .equ RL_CKSUM,    0x460fab5c        | the parsers' running checksum: saved / restored around us
    .equ RL_MASKSAV,  0x460bd910        | doneFn's displaced read
    .equ RL_DONERES,  0x40023c68        | doneFn after it
    .equ RL_DONEEPI,  0x40023c76        | doneFn's epilogue: skips stock's whole-bank reload
    .equ RL_PARTAPP,  0x40009094        | (bank, part): stock's whole-Part apply
    .equ RL_CURPART,  0x80000003        | the playing pattern's Part (mirror)
    .equ RL_TSLOT,    0x460d1e70        | the toast slot
    .equ RL_TDISMISS, 0x40056bec
    .equ RL_TFONT,    0x400ba862
    .equ RL_TEXTW,    0x40012f30        | (font, maxlen, text) -> px
    .equ RL_WDRAW1,   0x40057008        | (handle, text, 0, font)
    .equ RL_TH1,      0x12              | a one-line toast's height
    .equ RL_TSTYLE,   0xa
    .equ RQ_TRKSEQ,   1                 | request kinds
    .equ RQ_TRKFULL,  2
    .equ RQ_PTN,      3

| ================================================================ the request (UI task)
| cl_rlreq(kind, pattern, t): arm the message, then post the job (S93: the message first).
| t = 0..15 (MIDI 8..15) for the track kinds (the playing pattern); RQ_PTN: pattern = bank << 8 | N, the bank
| Clyps shows (CL41) -- the job reads, writes and cues THAT bank's pattern (rq_tgt -> rq_jbk).
    .global cl_rlreq
cl_rlreq:
    lea     -16(%sp),%sp
    movem.l %d2-%d5,(%sp)
    move.l  20(%sp),%d2                 | kind
    move.l  24(%sp),%d3                 | pattern
    move.l  28(%sp),%d4                 | t
    move.b  %d4,rq_t
|   the message: line 1 / line 2 (one line for the pattern)
    lea     rq_s_proj,%a0               | line 2 for every kind (the user, 2026-10-30; "RELOADED FROM
    move.l  %a0,rq_l2p                  | PROJECT" is 123 px: wider than a toast line)
    moveq   #2,%d0
    move.b  %d0,rq_nl
    cmpi.l  #RQ_PTN,%d2
    bne.b   rr_trk
    moveq   #15,%d0
    and.l   %d3,%d0
    addq.l  #1,%d0
    move.l  %d0,-(%sp)                  | pattern 1..16
    move.l  %d3,%d0
    lsr.l   #8,%d0
    addi.l  #'A',%d0
    move.l  %d0,-(%sp)                  | its bank
    pea     rq_fmt_ptn
    pea     rq_line1
    jsr     SPRINTF
    lea     16(%sp),%sp
    bra.b   rr_post
rr_trk:
    pea     rq_s_seq                    | "TRK SEQ" / "TRK ALL", either side (the user, 2026-11-02: no track
    cmpi.l  #RQ_TRKSEQ,%d2              | numbers); line 2 "RELOADED FROM PROJ"
    beq.b   rr_k
    move.l  #rq_s_full,(%sp)
rr_k:
    pea     rq_line1
    jsr     SPRINTF                     | (no % in either string)
    addq.l  #8,%sp
rr_post:
|   GENERATIONS (the user, 2026-11-08 / 09; RELOAD's rl_req): one target (bank, pattern) and what is wanted
|   of it -- the whole pattern, or tracks (the latest kind per track wins). A pattern reload, a pending
|   pattern one, another target, or nothing alive starts a new generation: what was pending goes (its card
|   cues, a superseded pattern's switch). The card is read ONCE per generation; a chord for a target already
|   staged arms that track at once. A job is never posted while one is queued: a second post of stock's one
|   message would reach the 0x14 case with rq_kind consumed and run stock's whole-bank reload.
    moveq   #0,%d5                      | d5 = the target: bank << 8 | (the pattern / the one you are on)
    move.b  PLAY_BANK,%d5
    lsl.l   #8,%d5
    cmpi.l  #RQ_PTN,%d2
    beq.b   rr_tp
    move.b  ACT_PAT,%d5
    bra.b   rr_tg
rr_tp:
    move.l  %d3,%d5                     | CL41: the bank asked for << 8 | N
    andi.l  #15,%d3
rr_tg:
    cmpi.l  #RQ_PTN,%d2
    beq.b   rr_new
    tst.b   rq_ptnr
    bne.b   rr_new
    cmp.w   rq_tgt,%d5
    bne.b   rr_new
    tst.b   rq_live
    bne.b   rr_same
rr_new:
    moveq   #0,%d0
    move.b  rq_gen,%d0
    addq.l  #1,%d0
    move.b  %d0,rq_gen
    move.w  %d5,rq_tgt
    clr.w   rq_seqm
    clr.w   rq_fullm
    clr.b   rq_ptnr
    clr.b   rq_stok
    clr.b   cl_ptngo                    | a superseded pattern job may not switch any more (2026-11-09, HW)
    jsr     cl_dropcard                 | the old generation's pending landings go
    moveq   #1,%d0
    move.b  %d0,rq_live
    move.b  %d0,rq_need                 | this target must be read
rr_same:
    cmpi.l  #RQ_PTN,%d2
    bne.b   rr_trk2
    moveq   #1,%d0
    move.b  %d0,rq_ptnr
    move.b  %d3,rq_pat
    moveq   #0,%d0                      | the pattern you are on while another is cued: that cue goes, by
    move.b  PLAY_BANK,%d0               | stock's own cue (as [PTN] + its trig does; 2026-11-09, HW) --
    lsl.l   #8,%d0                      | and every track's pending load: nothing cued may land after it
    move.b  ACT_PAT,%d0                 | (item 11). CL41: bank and pattern
    cmp.l   %d5,%d0
    bne.w   rr_msgx
    jsr     cl_dropall
    jsr     cl_ptncancel
    bra.w   rr_msgx
rr_trk2:
    move.l  %d6,-(%sp)                  | the track's pending load goes now: the card's copy lands in place,
    move.l  %d4,%d6                     | nothing cued may land after it (item 11, the user 2026-11-09)
    jsr     cl_dropone
    move.l  (%sp)+,%d6
    move.b  ACT_PAT,%d0
    move.b  %d0,rq_pat
    moveq   #1,%d0
    lsl.l   %d4,%d0                     | d0 = the track's bit, d1 = the others
    move.l  %d0,%d1
    not.l   %d1
    cmpi.l  #RQ_TRKFULL,%d2
    beq.b   rr_f
    move.w  rq_seqm,%d3
    or.l    %d0,%d3
    move.w  %d3,rq_seqm
    move.w  rq_fullm,%d3
    and.l   %d1,%d3
    move.w  %d3,rq_fullm
    moveq   #0,%d2                      | d2 = full
    bra.b   rr_st
rr_f:
    move.w  rq_fullm,%d3
    or.l    %d0,%d3
    move.w  %d3,rq_fullm
    move.w  rq_seqm,%d3
    and.l   %d1,%d3
    move.w  %d3,rq_seqm
    moveq   #1,%d2
rr_st:
    tst.b   rq_stok                     | this generation is staged already: the track lands at once
    beq.b   rr_msgx
    move.b  rq_sgen,%d0
    cmp.b   rq_gen,%d0
    bne.b   rr_msgx
    moveq   #1,%d0
    move.b  %d0,rq_msg
    move.l  %d4,%d0
    move.l  %d2,%d1
    jsr     cl_rqarm1
    bra.b   rr_out
rr_msgx:
    moveq   #1,%d0
    move.b  %d0,rq_msg                  | its toast: at the landing (a pattern you are not on: the job's end)
    tst.b   rq_need
    beq.b   rr_out
    tst.b   rq_kind                     | posted, not started: it reads this target when it starts
    beq.b   rr_nq
    jsr     rq_setkind
    bra.b   rr_out
rr_nq:
    tst.b   rq_busy                     | running (an older target): cl_rldone posts again
    bne.b   rr_out
    jsr     rq_post
rr_out:
    movem.l (%sp),%d2-%d5
    lea     16(%sp),%sp
    rts

| rq_setkind: the job's kind for the generation -- the pattern, or tracks (their Part is always read: a
| FULL chord may join). rq_post: that, then the type-0x14 storage job for the target's bank. UI task.
rq_setkind:
    moveq   #RQ_TRKFULL,%d0
    tst.b   rq_ptnr
    beq.b   rk_k
    moveq   #RQ_PTN,%d0
rk_k:
    move.b  %d0,rq_kind
    rts
rq_post:
    bsr.b   rq_setkind
    moveq   #0,%d0
    move.b  rq_tgt,%d0                  | CL41: the target's bank (rq_tgt = bank << 8 | pattern)
    moveq   #1,%d1
    lsl.l   %d0,%d1
    move.l  %d1,-(%sp)
    jsr     RL_JOBPOST                  | FUN_40022778(1 << bank)
    addq.l  #4,%sp
    rts

| ================================================================ the job (worker task)
| The type-0x14 case 0x40085864, replaces 8 B: move.l %a2,-650(%fp) ; move.l 4(%a2),-(%sp).
| rq_kind 0 = not ours (stock's own RELOAD BANK); 1..3 ours; anything else is dropped (S84).
    .global cl_rljob
cl_rljob:
    move.l  %a2,-650(%fp)               | displaced #1
    move.l  %d0,-(%sp)
    moveq   #0,%d0
    move.b  rq_kind,%d0
    beq.b   rj_stock
    cmpi.l  #RQ_PTN,%d0
    bls.b   rj_ours
    clr.b   rq_kind
rj_stock:
    move.l  (%sp)+,%d0
    move.l  4(%a2),-(%sp)               | displaced #2
    jmp     RL_J14ORIG
rj_ours:
    move.l  (%sp)+,%d0
    lea     -40(%sp),%sp
    movem.l %d2-%d7/%a2-%a5,(%sp)
    moveq   #0,%d5
    move.b  rq_pat,%d5                  | d5 = pattern P (of bank rq_jbk)
    move.b  rq_tgt,%d0                  | CL41: the bank this read serves -- the request's (a pattern: the bank
    move.b  %d0,rq_jbk                  | Clyps showed; a track: the playing one); every site below uses it
    moveq   #0,%d7
    move.b  rq_kind,%d7                 | d7 = kind
    clr.b   rq_kind                     | consumed: a re-entrant stock job must not see it
    move.b  rq_gen,%d0                  | the generation this read serves
    move.b  %d0,rq_jgen
    clr.b   rq_need
    moveq   #1,%d0
    move.b  %d0,rq_busy
    clr.b   rq_own                      | set only on success (S90)
    clr.b   rq_varm
    move.w  RL_CKSUM,%d0
    move.w  %d0,rq_cksum
    jsr     cl_rlopen
    tst.l   %d0
    bpl.b   rj_opened
    moveq   #-12,%d0                    | stock: "THIS BANK HAS NEVER BEEN SAVED!"
    bra.w   rj_exit
rj_opened:
    pea     22
    pea     rq_hdr
    pea     rq_fh
    jsr     FREAD
    lea     12(%sp),%sp
    tst.l   %d0
    ble.w   rj_fail
    moveq   #0,%d6
    move.b  rq_hdr+0x14,%d6
    lsl.l   #8,%d6
    moveq   #0,%d0
    move.b  rq_hdr+0x15,%d0
    or.l    %d0,%d6                     | d6 = the version word
    tst.b   rq_seq
    bne.w   rj_seq0                     | the fallback's second open: chunk by chunk
|   straight to pattern P, and then to its Part (the user, 2026-11-04: not every pattern before it).
|   The chunks sit at fixed offsets per version, checked on 816 real bank files (.strd + .work,
|   versions 0x14..0x17): PTRN n at 0x16 + st * n, st = 0x8eec from version 0x17 on, 0x8ee8 before;
|   PART p (0..3 the working Parts) at 0x16 + 16 * st + 0x18bb * p. Both parsers check their chunk's
|   tag (PTRN 0x400d1694 / PART 0x400d1690), so a wrong offset fails -> rj_seq.
    cmpi.l  #0x14,%d6
    bcs.w   rj_seq                      | an older format: chunk by chunk
    move.l  #0x8ee8,%d4
    cmpi.l  #0x17,%d6
    bcs.b   rj_st
    move.l  #0x8eec,%d4                 | d4 = the pattern chunk stride
rj_st:
    move.l  %d4,%d0
    muls.l  %d5,%d0
    addi.l  #0x16,%d0
    move.l  %d0,-(%sp)
    jsr     rq_seek
    addq.l  #4,%sp
    tst.l   %d0
    bmi.w   rj_seq
    move.l  %d6,-(%sp)
    pea     RL_SCRATCH
    pea     rq_fh
    jsr     RL_PARSEPAT
    lea     12(%sp),%sp
    tst.l   %d0
    bmi.w   rj_seq
    pea     PATSTRIDE
    pea     RL_SCRATCH
    pea     RQ_SLAB
    jsr     MEMCPY
    lea     12(%sp),%sp
    cmpi.l  #RQ_TRKSEQ,%d7
    beq.b   rj_dok                      | the sequence only: no Part needed
    moveq   #0,%d3
    movea.l #RQ_SLAB,%a0
    adda.l  #TRAILER,%a0
    move.b  T_PART(%a0),%d3
    andi.l  #3,%d3                      | d3 = the Part the saved pattern is linked to
    move.l  #0x18bb,%d0
    muls.l  %d3,%d0
    lsl.l   #4,%d4
    add.l   %d4,%d0
    addi.l  #0x16,%d0
    move.l  %d0,-(%sp)
    jsr     rq_seek
    addq.l  #4,%sp
    tst.l   %d0
    bmi.w   rj_seq
    move.l  %d6,-(%sp)
    move.l  %d3,-(%sp)
    pea     RQ_PART
    pea     rq_fh
    jsr     RL_PARSEPRT
    lea     16(%sp),%sp
    tst.l   %d0
    bmi.w   rj_seq
rj_dok:
    addq.l  #1,rq_ndir                  | gate X / L: the direct path ran
    bra.w   rj_parsed
|   anything unexpected on the direct path: open the file again, chunk by chunk from the top
|   (RELOAD_FROM_PROJECT's proven path)
rj_seq:
    pea     rq_fh
    jsr     FCLOSE
    addq.l  #4,%sp
    moveq   #1,%d0
    move.b  %d0,rq_seq
    jsr     cl_rlopen
    tst.l   %d0
    bpl.w   rj_opened
    clr.b   rq_seq
    moveq   #-12,%d0
    bra.w   rj_exit
rj_seq0:
    clr.b   rq_seq
|   the 16 patterns: P is kept in our slab buffer; the track sequence reload stops after it
    moveq   #0,%d4
rj_pl:
    move.l  %d6,-(%sp)
    pea     RL_SCRATCH
    pea     rq_fh
    jsr     RL_PARSEPAT
    lea     12(%sp),%sp
    tst.l   %d0
    bmi.w   rj_fail
    cmp.l   %d5,%d4
    bne.b   rj_pn
    pea     PATSTRIDE
    pea     RL_SCRATCH
    pea     RQ_SLAB
    jsr     MEMCPY
    lea     12(%sp),%sp
    cmpi.l  #RQ_TRKSEQ,%d7
    beq.b   rj_parsed                   | the sequence only: no Part needed
rj_pn:
    addq.l  #1,%d4
    cmpi.l  #16,%d4
    bne.b   rj_pl
|   the working PART chunks 0..its index (the saved pattern's own Part link) into our buffer
    moveq   #0,%d3
    movea.l #RQ_SLAB,%a0
    adda.l  #TRAILER,%a0
    move.b  T_PART(%a0),%d3
    andi.l  #3,%d3                      | d3 = the Part the saved pattern is linked to
    moveq   #0,%d4
rj_prl:
    move.l  %d6,-(%sp)
    move.l  %d4,-(%sp)
    pea     RQ_PART
    pea     rq_fh
    jsr     RL_PARSEPRT
    lea     16(%sp),%sp
    tst.l   %d0
    bmi.w   rj_fail
    cmp.l   %d3,%d4
    beq.b   rj_parsed
    addq.l  #1,%d4
    bra.b   rj_prl
rj_parsed:
    pea     rq_fh
    jsr     FCLOSE
    addq.l  #4,%sp
    moveq   #0,%d0
    move.b  rq_jbk,%d0
    move.l  %d5,%d1
    movea.l #BLOB,%a1
    jsr     cl_partin                   | a0 = the live pattern's Part (its current link)
    movea.l %a0,%a3                     | a3 = the live Part, d2 = its index
    move.l  %d0,%d2
    move.l  %d5,-(%sp)
    moveq   #0,%d0
    move.b  rq_jbk,%d0
    move.l  %d0,-(%sp)
    jsr     cl_slab
    addq.l  #8,%sp
    movea.l %a0,%a4                     | a4 = the live slab of P
|   the bytes the bank file never holds -- each audio record's +0x899 and the slab tail +0x8e5c.. --
|   the parser leaves as the scratch had them (255 / 127 measured, gate X). Stock's own reload parses
|   into the live slab, so they keep their live values: ours too. Else a reloaded saved pattern differs
|   from its original there and Clyps marks it edited (the user, 2026-11-04).
    movea.l #RQ_SLAB,%a0
    move.l  #0x899,%d0
rj_ns:
    move.b  (%a4,%d0.l),%d1
    move.b  %d1,(%a0,%d0.l)
    addi.l  #TRAC_A,%d0
    cmpi.l  #8*TRAC_A,%d0
    bcs.b   rj_ns
    move.l  #0x8e5c,%d0
rj_nt:
    move.b  (%a4,%d0.l),%d1
    move.b  %d1,(%a0,%d0.l)
    addq.l  #1,%d0
    cmpi.l  #PATSTRIDE,%d0
    bcs.b   rj_nt
|   2026-11-09 (the user, matching RELOAD): what the card brought is STAGED here (RQ_SLAB / RQ_PART) and
|   lands like temp reload -- a track at its next step start, in phase, its slice in the same tick; the
|   pattern you are on on the first step its tracks share (cl_togarm). cl_rldone arms them (UI task).
|   Only a pattern you are NOT on is written now, and the OT goes to it (stock's cue). A read a newer
|   request has replaced lands nothing.
    move.b  rq_jgen,%d0
    cmp.b   rq_gen,%d0
    bne.w   rj_stale
    cmpi.l  #RQ_PTN,%d7
    bne.w   rj_stage
    move.b  rq_jbk,%d0                  | CL41: a pattern of another bank is never the one you are on
    cmp.b   PLAY_BANK,%d0
    bne.w   rj_ptn
    moveq   #0,%d0
    move.b  ACT_PAT,%d0
    cmp.l   %d5,%d0
    beq.w   rj_stage
    bra.w   rj_ptn
rj_stage:
    move.b  rq_jgen,%d0
    move.b  %d0,rq_sgen
    moveq   #1,%d0
    move.b  %d0,rq_stok
    move.b  %d0,rq_arm                  | cl_rldone arms the landings
    move.b  %d0,rq_own                  | success: doneFn skips its whole-bank reload once
    bsr.w   rq_names                    | the names as saved, staged (rq_nst): they land with the tracks
    moveq   #1,%d0
    bra.w   rj_exit
rj_stale:
    moveq   #1,%d0
    move.b  %d0,rq_own                  | ours all the same: never stock's whole-bank reload
    bra.w   rj_exit
|   ---- the pattern: its whole slab (with its saved Part link) and that whole Part ----
rj_ptn:
    pea     PATSTRIDE
    pea     RQ_SLAB
    move.l  %a4,-(%sp)
    jsr     MEMCPY
    lea     12(%sp),%sp
    moveq   #0,%d0
    move.b  rq_jbk,%d0
    move.l  %d5,%d1
    movea.l #BLOB,%a1
    jsr     cl_partin                   | now the saved link: a0 = that Part (of bank rq_jbk), d0 = its index
    move.l  %d0,%d2
    pea     PARTSZ
    pea     RQ_PART
    move.l  %a0,-(%sp)
    jsr     MEMCPY
    lea     12(%sp),%sp
    move.b  rq_jbk,%d0                  | (P is never the pattern you are on here.) CL41: another bank's Part
    cmp.b   PLAY_BANK,%d0               | never sounds -- written, and stock applies it when the cue lands
    bne.b   rj_pmk
    moveq   #0,%d0
    move.b  RL_CURPART,%d0
    cmp.l   %d2,%d0
    beq.b   rj_papply                   | the Part sounding: applied, and cl_postpart marks it
rj_pmk:
|   another Part than the one sounding: nothing to apply, but stock's edited mark follows the reload --
|   of the Part pattern P links to (as just reloaded) and no other (the user, 2026-11-02)
    moveq   #0,%d0
    move.b  rq_jbk,%d0
    move.l  %d5,%d1
    movea.l #BLOB,%a1
    jsr     cl_partin                   | a0 = P's Part, d0 = its index (= d2)
    movea.l %a0,%a2
    move.l  %d2,%d3
    moveq   #0,%d4                      | the whole Part (cl_pmark: no slice mask)
    moveq   #0,%d0
    move.b  rq_jbk,%d0                  | CL41: of that bank
    jsr     cl_pmarkb
    bra.w   rj_ok
rj_papply:
    move.l  %d2,-(%sp)
    moveq   #0,%d0
    move.b  PLAY_BANK,%d0
    move.l  %d0,-(%sp)
    jsr     RL_PARTAPP                  | FUN_40009094(bank, part), as RELOAD's PART + PTN SEQ
    addq.l  #8,%sp
    moveq   #1,%d0
    move.b  %d0,cl_wpart                | the UI side owes the whole Part's mirror (cl_postpart)
    jsr     cl_trk                      | the pages: owed to the UI side (cl_postpart)
    lea     cl_postf,%a0
    moveq   #1,%d1
    move.b  %d1,(%a0,%d0.l)
rj_ok:
|   what the card brought is no Clyps load any more (the user, 2026-11-05): the reloaded tracks' provenance
|   off -- a track: its own; a pattern: every track homed on it -- so their box / LEDs go to the pattern's
|   own slot (cl_boxreq: cl_boxhome at the UI tail)
    lea     cl_home,%a0
    cmpi.l  #RQ_PTN,%d7
    beq.b   rj_hp
    moveq   #0,%d0
    move.b  rq_t,%d0
    add.l   %d0,%d0
    moveq   #-1,%d1
    move.b  %d1,(%a0,%d0.l)
    move.b  %d1,1(%a0,%d0.l)
    bra.b   rj_hd
rj_hp:
    moveq   #16,%d1
rj_hpl:
    move.b  (%a0),%d0
    cmp.b   rq_jbk,%d0
    bne.b   rj_hpn
    moveq   #0,%d0
    move.b  1(%a0),%d0
    cmp.l   %d5,%d0
    bne.b   rj_hpn
    moveq   #-1,%d0
    move.b  %d0,(%a0)
    move.b  %d0,1(%a0)
rj_hpn:
    addq.l  #2,%a0
    subq.l  #1,%d1
    bne.b   rj_hpl
rj_hd:
    moveq   #1,%d0
    move.b  %d0,cl_boxreq
    moveq   #0,%d0                      | the UI follows: the active track's post (SRAM, dirty,
    move.b  CUR_TRACK,%d0               | the pages)
    andi.l  #7,%d0
    tst.l   MIDI_MODE
    beq.b   rj_pa
    addq.l  #8,%d0
rj_pa:
    cmpi.l  #RQ_PTN,%d7
    beq.b   rj_pb
    moveq   #0,%d0
    move.b  rq_t,%d0
rj_pb:
    moveq   #1,%d1
    lsl.l   %d0,%d1
    move.w  cl_post,%d0
    or.l    %d1,%d0
    move.w  %d0,cl_post
    moveq   #1,%d0
    move.l  %d0,RDRAW
    moveq   #1,%d0
    move.b  %d0,rq_own                  | success: doneFn skips its whole-bank reload once
    cmpi.l  #RQ_PTN,%d7                 | a pattern: the OT goes to it (cl_ptnswitch at the UI tail; the
    bne.b   rj_ng                       | user, 2026-11-06 -- no more silent reloads in the background)
    move.l  %d5,%d0
    ori.l   #0x80,%d0
    move.b  %d0,cl_ptngo
rj_ng:
|   the live cache (SRAM mirror, the UI bank only): only what changed (the user, 2026-11-04 -- stock's
|   0x4000faf0 rewrote the whole bank, ~620 KB of battery NVRAM, for one track). A pattern: its slab
|   here (it need not be the playing one); a track: its record + the trailer at the UI tail
|   (cl_postmask, the cl_post bit above); a Part: cl_pmark (rj_pshare here, or cl_postpart).
|   A track reload copies its record + trailer of P here too: the UI tail's copy is of the pattern
|   playing THEN, which a pattern change in between makes another one.
    move.b  rq_jbk,%d0
    cmp.b   UI_BANK,%d0
    bne.b   rj_lv
    move.l  %d5,%d0
    move.l  #PATSTRIDE,%d1
    muls.l  %d1,%d0
    addi.l  #SRAM_PAT,%d0
    movea.l %d0,%a5                     | a5 = P's mirror
    cmpi.l  #RQ_PTN,%d7
    bne.b   rj_lt
    pea     PATSTRIDE
    move.l  %a4,-(%sp)
    move.l  %a5,-(%sp)
    jsr     MEMCPY
    lea     12(%sp),%sp
    bra.b   rj_lv
rj_lt:
    moveq   #0,%d0
    move.b  rq_t,%d0
    move.l  %d0,-(%sp)
    jsr     cl_toff                     | d0 = offset, d1 = length
    addq.l  #4,%sp
    move.l  %d1,-(%sp)
    move.l  %a4,%d1
    add.l   %d0,%d1
    move.l  %d1,-(%sp)
    move.l  %a5,%d1
    add.l   %d0,%d1
    move.l  %d1,-(%sp)
    jsr     MEMCPY
    lea     12(%sp),%sp
    pea     PATSTRIDE-TRAILER
    move.l  %a4,%d0
    addi.l  #TRAILER,%d0
    move.l  %d0,-(%sp)
    move.l  %a5,%d0
    addi.l  #TRAILER,%d0
    move.l  %d0,-(%sp)
    jsr     MEMCPY
    lea     12(%sp),%sp
rj_lv:
    bsr.w   rq_names                    | the reloaded sequences' names, as saved (staged) ...
    bsr.w   rq_ncopy                    | ... a pattern you are not on: they land with it now
    moveq   #1,%d0
rj_exit:
    move.w  rq_cksum,%d1
    move.w  %d1,RL_CKSUM
    movem.l (%sp),%d2-%d7/%a2-%a5
    lea     40(%sp),%sp
    jmp     RL_J14EXIT
rj_fail:
    pea     rq_fh
    jsr     FCLOSE
    addq.l  #4,%sp
    moveq   #-1,%d0
    bra.b   rj_exit

| rq_names (d5 = pattern P, d7 = kind): the reloaded sequences' names as saved (the user, 2026-11-05) --
| clypsNN.strd (Clyps' names file beside bankNN.strd: "CLYP", u16 1, u16 256, then 256 x NAME_W, index
| pattern * 16 + track): a track reload its one name, a pattern reload its 16. Never saved / no file /
| a bad one: none (the slot shows its default label). Worker context; the bank file is closed.
rq_names:
    tst.b   cl_namesok
    beq.w   rn2_out
    lea     -16(%sp),%sp
    movem.l %d2-%d4/%a2,(%sp)
    move.l  %d5,%d4
    lsl.l   #4,%d4                      | d4 = the first index in the bank: pattern P's 16 names
    moveq   #16,%d3                     | d3 = how many
    lea     rq_nst,%a2                  | a2 = the stage (they land with the tracks, cl_nload)
    moveq   #NAME_W,%d2
    muls.l  %d3,%d2                     | d2 = the bytes
    movea.l %a2,%a0                     | none, until the file says otherwise
    move.l  %d2,%d0
rn2_c:
    clr.b   (%a0)+
    subq.l  #1,%d0
    bne.b   rn2_c
    pea     cl_s_strd
    moveq   #0,%d0
    move.b  rq_jbk,%d0
    move.l  %d0,-(%sp)
    pea     rq_path
    jsr     cl_cpath
    lea     12(%sp),%sp
    lea     rq_fh,%a0
    moveq   #16,%d0
rn2_z:
    clr.l   (%a0)+
    subq.l  #1,%d0
    bne.b   rn2_z
    pea     0x7000
    pea     FBUF
    pea     S_R
    pea     rq_path
    pea     rq_fh
    jsr     FOPEN
    lea     20(%sp),%sp
    tst.l   %d0
    ble.w   rn2_done
    move.l  rq_fh,-(%sp)                | its size must be exactly NF_SIZE
    movea.l FS_SIZE,%a0
    jsr     (%a0)
    addq.l  #4,%sp
    cmpi.l  #NF_SIZE,%d0
    bne.w   rn2_cl
    pea     8
    pea     rq_hdr
    pea     rq_fh
    jsr     FREAD
    lea     12(%sp),%sp
    cmpi.l  #1,%d0
    bne.w   rn2_cl
    move.l  rq_hdr,%d0
    cmpi.l  #0x434c5950,%d0             | "CLYP"
    bne.w   rn2_cl
    move.l  rq_hdr+4,%d0
    cmpi.l  #0x00010100,%d0             | version 1, 256 names
    bne.w   rn2_cl
    move.l  %d4,%d0
    moveq   #NAME_W,%d1
    muls.l  %d1,%d0
    addq.l  #8,%d0
    move.l  %d0,-(%sp)
    jsr     rq_seek
    addq.l  #4,%sp
    tst.l   %d0
    bmi.w   rn2_cl
    move.l  %d2,-(%sp)
    move.l  %a2,-(%sp)
    pea     rq_fh
    jsr     FREAD
    lea     12(%sp),%sp
    cmpi.l  #1,%d0
    beq.b   rn2_t
    movea.l %a2,%a0                     | a short read: none after all
    move.l  %d2,%d0
rn2_c2:
    clr.b   (%a0)+
    subq.l  #1,%d0
    bne.b   rn2_c2
rn2_t:
    movea.l %a2,%a0                     | every name ends within its NAME_W bytes
    move.l  %d3,%d0
rn2_tl:
    clr.b   NAME_W-1(%a0)
    lea     NAME_W(%a0),%a0
    subq.l  #1,%d0
    bne.b   rn2_tl
rn2_cl:
    pea     rq_fh
    jsr     FCLOSE
    addq.l  #4,%sp
rn2_done:
    movem.l (%sp),%d2-%d4/%a2
    lea     16(%sp),%sp
rn2_out:
    rts

| rq_seek(off) -> d0 < 0: error. rq_fh's read position = off, as if read up to there: the backend seek
| (0x46c8243e: the card filesystem's, installed at 0x400145de / 0x400146f0 / 0x40014806) to off's 512 B
| block, the buffer marked empty (+12, the read index: 0 = refill), then off mod 512 read and dropped.
| Not stock's buffered seek 0x4001660c: it keeps a partly read buffer (our 22 B header) and then
| re-seeks the backend to the exact offset -- measured: the parse after it saw no PTRN tag (-51).
rq_seek:
    move.l  4(%sp),%d0
    andi.l  #-512,%d0
    move.l  %d0,-(%sp)
    move.l  rq_fh,-(%sp)                | the backend's file id (+0)
    movea.l RL_LLSEEK,%a0
    jsr     (%a0)
    addq.l  #8,%sp
    tst.l   %d0
    bmi.b   rs_out
    clr.l   rq_fh+12                    | the buffer empty: the next read refills from that block
    move.l  4(%sp),%d0
    andi.l  #511,%d0
    beq.b   rs_ok
    move.l  %d0,-(%sp)
    clr.l   -(%sp)                      | dst 0: read and drop (0x400165ce)
    pea     rq_fh
    jsr     FREAD
    lea     12(%sp),%sp
    tst.l   %d0
    bgt.b   rs_ok
    moveq   #-1,%d0
    rts
rs_ok:
    moveq   #0,%d0
rs_out:
    rts

| cl_rlopen -> d0 = FOPEN's result: "<project>/bankNN.strd" of the job's bank (rq_jbk), read-only
cl_rlopen:
    lea     -8(%sp),%sp
    movem.l %d2/%a2,(%sp)
    clr.l   -(%sp)
    clr.l   -(%sp)
    jsr     PROJDIR
    addq.l  #8,%sp
    moveq   #0,%d1
    move.b  rq_jbk,%d1
    addq.l  #1,%d1
    move.l  %d1,-(%sp)
    move.l  %d0,-(%sp)
    pea     RL_FMTSTRD
    pea     rq_path
    jsr     SPRINTF
    lea     16(%sp),%sp
    lea     rq_fh,%a0
    moveq   #16,%d0
ro_z:
    clr.l   (%a0)+
    subq.l  #1,%d0
    bne.b   ro_z
    pea     0x7000                      | the open buffer: the first 28 KB of FBUF (as RELOAD)
    pea     FBUF
    pea     S_R
    pea     rq_path
    pea     rq_fh
    jsr     FOPEN
    lea     20(%sp),%sp
    movem.l (%sp),%d2/%a2
    lea     8(%sp),%sp
    rts

| ================================================================ the finish (worker task)
| doneFn's success path 0x40023c62, replaces 6 B: mvz.w 0x460bd910,%d0. Not ours: stock (its
| whole-bank reload). Ours: verify a track's trig masks are still as reloaded, then the toast,
| and skip the whole-bank reload.
    .global cl_rldone
cl_rldone:
    tst.b   rq_own
    bne.b   rd_ours
    moveq   #0,%d0
    move.w  RL_MASKSAV,%d0
    jmp     RL_DONERES
rd_ours:
    clr.b   rq_own
    clr.b   rq_busy
    tst.b   rq_arm
    beq.b   rd_na
    clr.b   rq_arm
    jsr     cl_rqarm                    | the staged generation's landings (this is the UI task: msg 0x2b)
    bra.b   rd_more
rd_na:
    move.b  rq_jgen,%d0                 | a read a newer request replaced: nothing to show
    cmp.b   rq_gen,%d0
    bne.b   rd_more
    bsr.w   rd_old                      | a pattern you are not on: written, its toast now
rd_more:
    tst.b   rq_need                     | a newer target waits for its read
    beq.w   rd_done
    jsr     rq_post
    bra.w   rd_done
rd_old:
    tst.b   rq_varm
    beq.b   rd_msg
    clr.b   rq_varm
    moveq   #0,%d0
    move.b  ACT_PAT,%d0
    move.l  %d0,-(%sp)
    move.b  PLAY_BANK,%d0
    move.l  %d0,-(%sp)
    jsr     cl_slab
    addq.l  #8,%sp
    adda.l  rq_voff,%a0                 | the live record, recomputed from the live state now
    lea     rq_vsnap,%a1
    moveq   #16,%d1
rd_v:
    move.b  (%a0)+,%d0
    cmp.b   (%a1)+,%d0
    bne.b   rd_lost
    subq.l  #1,%d1
    bne.b   rd_v
    bra.b   rd_msg
rd_lost:
    lea     rq_s_lost1,%a0              | the copy did not survive to the finish
    move.l  %a0,rq_lines
    lea     rq_s_lost2,%a0
    move.l  %a0,rq_lines+4
    moveq   #2,%d0
    bra.b   rd_show
rd_msg:
    tst.b   rq_msg
    beq.b   rt_out
    lea     rq_line1,%a0
    move.l  %a0,rq_lines
    move.l  rq_l2p,%a0
    move.l  %a0,rq_lines+4
    moveq   #0,%d0
    move.b  rq_nl,%d0
rd_show:
    clr.b   rq_msg
    move.l  %d0,-(%sp)
    pea     rq_lines
    jsr     cl_toast2
    addq.l  #8,%sp
    rts
rd_done:
    jmp     RL_DONEEPI                  | skip the whole-bank reload

| cl_rqtoast (UI tail, after a card landing): the request's toast, once.
    .global cl_rqtoast
cl_rqtoast:
    tst.b   rq_msg
    beq.b   rt_out
    lea     rq_line1,%a0
    move.l  %a0,rq_lines
    move.l  rq_l2p,%a0
    move.l  %a0,rq_lines+4
    moveq   #0,%d0
    move.b  rq_nl,%d0
    bra.w   rd_show
rt_out:
    rts

| cl_rqarm (UI task, the job's end): the staged generation's landings -- the pattern you are on lands
| together (cl_togarm); tracks each at their next step start, in phase (cl_rqarm1), as a batch.
cl_rqarm:
    tst.b   rq_stok
    beq.w   qa_out
    move.b  rq_sgen,%d0
    cmp.b   rq_gen,%d0
    bne.w   qa_out
    tst.b   rq_ptnr
    beq.b   qa_trk
    move.b  rq_pat,%d0
    cmp.b   ACT_PAT,%d0
    bne.w   qa_out                      | no longer the pattern you are on (a stock change landed): drop it
    move.b  rq_tgt,%d0                  | CL41: bank and all
    cmp.b   PLAY_BANK,%d0
    bne.w   qa_out
.ifdef BP_CLASH
    move.l  #0xff,%d0                   | KYOTI V1.8BC: refused whole when a core would hold two BLKPYRAMD
    move.l  #0x10000+(SRC_CARD<<8),%d1  | (cl_bpgate)
    jsr     cl_bpgate
    tst.l   %d0
    bne.b   qa_bpg
    clr.b   rq_msg                      | refused: no card toast either
    bra.b   qa_bpp
qa_bpg:
.endif
    pea     SRC_CARD
    jsr     cl_togarm
    addq.l  #4,%sp
.ifdef BP_CLASH
qa_bpp:
.endif
    clr.b   rq_ptnr
    bra.w   qa_out
qa_trk:
.ifdef BP_CLASH
    moveq   #0,%d0                      | KYOTI V1.8BC: the FULL ones, refused whole -- every track of the
    move.w  rq_fullm,%d0                | generation, its sequences too -- when a core would get a second
    move.l  #0x10000+(SRC_CARD<<8),%d1  | BLKPYRAMD (cl_bpgate)
    jsr     cl_bpgate
    tst.l   %d0
    bne.b   qa_bpok
    clr.w   rq_seqm
    clr.w   rq_fullm
    clr.b   rq_msg                      | refused: no card toast either
    bra.w   qa_out
qa_bpok:
.endif
    move.l  %d2,-(%sp)
    jsr     cl_bbeg
    moveq   #0,%d2
qa_l:
    move.w  rq_seqm,%d0
    btst    %d2,%d0
    beq.b   qa_f
    moveq   #0,%d1
    bra.b   qa_go
qa_f:
    move.w  rq_fullm,%d0
    btst    %d2,%d0
    beq.b   qa_n
    moveq   #1,%d1
qa_go:
    move.l  %d2,%d0
    jsr     cl_rqarm1
qa_n:
    addq.l  #1,%d2
    cmpi.l  #16,%d2
    bne.b   qa_l
    jsr     cl_bend
    clr.w   rq_seqm
    clr.w   rq_fullm
    move.l  (%sp)+,%d2
qa_out:
    rts

| cl_rqarm1 (d0 = t, d1 = 1 FULL / 0 the sequence): the card's copy of t, at its next step start, in phase
| (cl_cueload now = 1: Clyps' temp reload path); stopped: at once. A NORMAL pattern whose saved length /
| scale differ changes the pattern's own rate: t lands with every track and the master re-phased
| (cl_tog / cl_togr, the user 2026-11-08: RELOAD's rl_rephase). Keeps d2-d7/a2-a6.
cl_rqarm1:
    move.l  %d2,-(%sp)
    move.l  %d0,%d2                     | d2 = t
.ifdef BP_CLASH
    tst.l   %d1                         | KYOTI V1.8BC: a FULL one on its own (in cl_rqarm's batch the whole
    beq.b   q1_bpok                     | generation was asked), refused when its core would get a second
    tst.b   cl_bat                      | BLKPYRAMD (cl_bpgate)
    bne.b   q1_bpok
    move.l  %d1,-(%sp)
    moveq   #1,%d0
    lsl.l   %d2,%d0
    move.l  #0x10000+(SRC_CARD<<8),%d1
    jsr     cl_bpgate
    move.l  (%sp)+,%d1
    tst.l   %d0
    bne.b   q1_bpok
    clr.b   rq_msg                      | refused: no card toast either
    bra.w   q1_out
q1_bpok:
.endif
    pea     1                           | now
    move.l  #SRC_CARD<<8,%d0
    tst.l   %d1
    beq.b   q1_s
    ori.l   #0x10000,%d0
q1_s:
    move.l  %d0,-(%sp)
    move.l  %d2,-(%sp)
    jsr     cl_cueload
    lea     12(%sp),%sp
    move.l  %d2,%d0                     | its name as saved, even when nothing needed to land
    jsr     cl_cardname
    tst.l   RUNNING
    bne.b   q1_run
    moveq   #1,%d0                      | stopped: it landed now -- its toast at the UI tail
    move.b  %d0,cl_ctoast
    bra.b   q1_out
q1_run:
    move.l  %d2,%d0
    add.l   %d0,%d0
    lea     cl_cue,%a0
    move.b  (%a0,%d0.l),%d0
    cmpi.b  #SRC_CARD,%d0
    bne.b   q1_out                      | nothing to land (it already plays)
    jsr     cl_live
    adda.l  #TRAILER,%a0
    tst.b   T_SMODE(%a0)
    bne.b   q1_out                      | PER TRACK: the track's own rate lands with it
    movea.l #RQ_SLAB+TRAILER,%a1
    move.b  T_LEN(%a0),%d0
    cmp.b   T_LEN(%a1),%d0
    bne.b   q1_rate
    move.b  T_SCALE(%a0),%d0
    cmp.b   T_SCALE(%a1),%d0
    beq.b   q1_out
q1_rate:
    move.w  cl_tog,%d0
    bset    %d2,%d0
    move.w  %d0,cl_tog
    moveq   #1,%d0
    move.b  %d0,cl_togr
    move.b  #SRC_CARD,%d0
    move.b  %d0,cl_togs
q1_out:
    move.l  (%sp)+,%d2
    rts

| cl_dropcard (UI task): every pending card landing goes (a new generation replaced it). Keeps d2-d7.
cl_dropcard:
    move.l  %d6,-(%sp)
    moveq   #0,%d6
dc_l:
    move.l  %d6,%d0
    add.l   %d0,%d0
    lea     cl_cue,%a0
    move.b  (%a0,%d0.l),%d0
    cmpi.b  #SRC_CARD,%d0
    bne.b   dc_n
    jsr     cl_dropone
dc_n:
    addq.l  #1,%d6
    cmpi.l  #16,%d6
    bne.b   dc_l
    move.l  (%sp)+,%d6
    rts

| rq_ncopy (worker, a pattern you are not on): its staged names -> its names now.
rq_ncopy:
    moveq   #0,%d0
    move.b  rq_jbk,%d0
    lsl.l   #4,%d0
    add.l   %d5,%d0
    lsl.l   #4,%d0
    moveq   #NAME_W,%d1
    muls.l  %d1,%d0
    movea.l #NAMES,%a1
    adda.l  %d0,%a1
    lea     rq_nst,%a0
    move.l  #16*NAME_W,%d0
nc_l:
    move.b  (%a0)+,(%a1)+
    subq.l  #1,%d0
    bne.b   nc_l
    rts

| cl_rqidle (UI tail): a generation is over once nothing of it is queued, read or pending -- the next chord
| reads the card again (a SAVE in between must never land the older copy).
    .global cl_rqidle
cl_rqidle:
    tst.b   rq_live
    beq.b   qi_out
    tst.b   rq_kind
    bne.b   qi_out
    tst.b   rq_busy
    bne.b   qi_out
    tst.b   rq_need
    bne.b   qi_out
    tst.b   rq_arm
    bne.b   qi_out
    tst.b   rq_ptnr
    bne.b   qi_out
    tst.w   rq_seqm
    bne.b   qi_out
    tst.w   rq_fullm
    bne.b   qi_out
    lea     cl_cue,%a0
    moveq   #16,%d1
qi_l:
    move.b  (%a0),%d0
    cmpi.b  #SRC_CARD,%d0
    beq.b   qi_out
    addq.l  #2,%a0
    subq.l  #1,%d1
    bne.b   qi_l
    clr.b   rq_live
    clr.b   rq_stok
qi_out:
    rts

| cl_toast2(lines[], n): stock's block toast grown to n lines (RELOAD's rl3_toast2, unchanged in
| effect): width = widest + 15, height 0x12 + 7(n-1), line 0 on top through stock's own drawer.
cl_toast2:
    lea     -40(%sp),%sp
    movem.l %d2-%d7/%a2-%a5,(%sp)
    move.l  44(%sp),%a4
    move.l  48(%sp),%d7
    tst.l   RL_TSLOT
    beq.b   t2_np
    jsr     RL_TDISMISS
t2_np:
    moveq   #0,%d6
    moveq   #0,%d5
t2_w:
    cmp.l   %d7,%d5
    bge.b   t2_wd
    move.l  %d5,%d0
    lsl.l   #2,%d0
    move.l  (%a4,%d0.l),%a0
    bsr.w   t2_meas
    cmp.l   %d6,%d0
    ble.b   t2_wn
    move.l  %d0,%d6
t2_wn:
    addq.l  #1,%d5
    bra.b   t2_w
t2_wd:
    addi.l  #15,%d6
    move.l  %d7,%d0
    subq.l  #1,%d0
    move.l  %d0,%d1
    lsl.l   #3,%d0
    sub.l   %d1,%d0
    addi.l  #RL_TH1,%d0
    move.l  %d0,%d4                     | d4 = height
    pea     RL_TDISMISS
    pea     RL_TSTYLE
    clr.l   -(%sp)
    clr.l   -(%sp)
    move.l  %d4,-(%sp)
    move.l  %d6,-(%sp)
    jsr     WIN_NEW
    lea     24(%sp),%sp
    tst.l   %d0
    beq.w   t2_out
    move.l  %d0,RL_TSLOT
    move.l  %d0,%a3
    pea     RL_TFONT
    clr.l   -(%sp)
    move.l  (%a4),-(%sp)
    move.l  %a3,-(%sp)
    jsr     RL_WDRAW1                   | line 0: stock's own drawer, at y = h - 11
    lea     16(%sp),%sp
    move.l  %a3,%d3
    addi.l  #36,%d3
    moveq   #1,%d2
t2_d:
    cmp.l   %d7,%d2
    bge.b   t2_done
    move.l  %d2,%d0
    lsl.l   #2,%d0
    move.l  (%a4,%d0.l),%a2
    move.l  %a2,%a0
    bsr.w   t2_meas
    move.l  %d6,%d1
    sub.l   %d0,%d1
    bpl.b   t2_x
    moveq   #0,%d1
t2_x:
    asr.l   #1,%d1
    move.l  %d2,%d0
    move.l  %d0,%d5
    lsl.l   #3,%d0
    sub.l   %d5,%d0
    move.l  %d4,%d5
    subi.l  #11,%d5
    sub.l   %d0,%d5                     | y = h - 11 - 7i
    move.l  %a2,-(%sp)
    pea     -1
    move.l  %d5,-(%sp)
    move.l  %d1,-(%sp)
    move.l  %d3,-(%sp)
    pea     RL_TFONT
    jsr     TEXT
    lea     24(%sp),%sp
    addq.l  #1,%d2
    bra.b   t2_d
t2_done:
    moveq   #1,%d0
    move.l  %d0,RDRAW
    moveq   #TOAST_DUR,%d0
    move.l  %d0,TOAST_T
t2_out:
    movem.l (%sp),%d2-%d7/%a2-%a5
    lea     40(%sp),%sp
    rts
t2_meas:                                | a0 = text -> d0 = px
    move.l  %a0,-(%sp)
    pea     -1
    pea     RL_TFONT
    jsr     RL_TEXTW
    lea     12(%sp),%sp
    rts

| ---- state (DRAM data) ----
    .align 2
rq_cksum:   .long 0
rq_voff:    .long 0
rq_l2p:     .long 0
rq_lines:   .long 0, 0
rq_ndir:    .long 0                     | direct (seek) reloads done: gates X / L read it
rq_seq:     .byte 0                     | the fallback's second open is running
rq_kind:    .byte 0                     | 0 idle, 1 TRK SEQ, 2 TRK FULL, 3 PTN
rq_jbk:     .byte 0                     | CL41: the bank the running / last read serves (rq_tgt's at its start)
rq_pat:     .byte 0
rq_t:       .byte 0
rq_nl:      .byte 0
rq_msg:     .byte 0                     | armed before the post
rq_own:     .byte 0                     | the job succeeded: doneFn's next success is ours
rq_varm:    .byte 0
rq_gen:     .byte 0                     | the generation (cl_rlreq) ...
rq_jgen:    .byte 0                     | ... the one the running read serves
rq_sgen:    .byte 0                     | ... the one staged in RQ_SLAB / RQ_PART
rq_stok:    .byte 0                     | the stage holds the current generation's copy
rq_live:    .byte 0                     | a generation is alive (queued, read, or landings pending)
rq_need:    .byte 0                     | its target must still be read
rq_busy:    .byte 0                     | a read is running
rq_arm:     .byte 0                     | the read staged: cl_rldone arms the landings
rq_ptnr:    .byte 0                     | the generation is a whole pattern
            .align 2
rq_tgt:     .short 0xffff               | bank << 8 | pattern
rq_seqm:    .short 0                    | tracks wanted, sequence only
rq_fullm:   .short 0                    | tracks wanted with their slice
rq_nst:     .space 16*NAME_W            | the staged names (cl_nload)
            .align 2
rq_vsnap:   .space 16
rq_hdr:     .space 32
rq_fh:      .space 64
rq_path:    .space 128
rq_line1:   .space 24
                                        | "RELOADED FROM PROJ": one line would be 151+ px (toast font)
rq_fmt_ptn: .asciz "PATTERN %c%02d"
rq_s_seq:   .asciz "TRK SEQ"
rq_s_full:  .asciz "TRK FULL"             | the track + its machine / FX
rq_s_proj:  .asciz "RELOADED FROM PROJ"     | 105 px
rq_s_lost1: .asciz "SEQ RELOAD LOST"
rq_s_lost2: .asciz "NOT RESTORED!"
            .align 2
