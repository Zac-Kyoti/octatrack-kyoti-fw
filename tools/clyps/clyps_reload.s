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
|     playing bank, its slab and its whole Part;
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
| t = 0..15 (MIDI 8..15) for the track kinds; the pattern is in the PLAYING bank.
    .global cl_rlreq
cl_rlreq:
    lea     -12(%sp),%sp
    movem.l %d2-%d4,(%sp)
    move.l  16(%sp),%d2                 | kind
    move.l  20(%sp),%d3                 | pattern
    move.l  24(%sp),%d4                 | t
    move.b  %d3,rq_pat
    move.b  %d4,rq_t
|   the message: line 1 / line 2 (one line for the pattern)
    lea     rq_s_proj,%a0               | line 2 for every kind (the user, 2026-10-30; "RELOADED FROM
    move.l  %a0,rq_l2p                  | PROJECT" is 123 px: wider than a toast line)
    moveq   #2,%d0
    move.b  %d0,rq_nl
    cmpi.l  #RQ_PTN,%d2
    bne.b   rr_trk
    move.l  %d3,%d0
    addq.l  #1,%d0
    move.l  %d0,-(%sp)                  | pattern 1..16
    moveq   #0,%d0
    move.b  PLAY_BANK,%d0
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
    moveq   #1,%d0
    move.b  %d0,rq_msg                  | armed before the post (S93)
    move.b  %d2,rq_kind
    moveq   #0,%d0
    move.b  PLAY_BANK,%d0
    moveq   #1,%d1
    lsl.l   %d0,%d1
    move.l  %d1,-(%sp)
    jsr     RL_JOBPOST                  | FUN_40022778(1 << bank)
    addq.l  #4,%sp
    movem.l (%sp),%d2-%d4
    lea     12(%sp),%sp
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
    move.b  rq_pat,%d5                  | d5 = pattern P (playing bank)
    moveq   #0,%d7
    move.b  rq_kind,%d7                 | d7 = kind
    clr.b   rq_kind                     | consumed: a re-entrant stock job must not see it
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
    move.b  PLAY_BANK,%d0
    move.l  %d5,%d1
    movea.l #BLOB,%a1
    jsr     cl_partin                   | a0 = the live pattern's Part (its current link)
    movea.l %a0,%a3                     | a3 = the live Part, d2 = its index
    move.l  %d0,%d2
    move.l  %d5,-(%sp)
    moveq   #0,%d0
    move.b  PLAY_BANK,%d0
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
    cmpi.l  #RQ_PTN,%d7
    beq.w   rj_ptn
|   ---- a track: its record (and, for a NORMAL pattern, the pattern's own length / scale) ----
    moveq   #0,%d0
    move.b  rq_t,%d0
    move.l  %d0,-(%sp)
    jsr     cl_toff                     | d0 = offset, d1 = length
    addq.l  #4,%sp
    move.l  %d0,rq_voff
    move.l  %d1,-(%sp)
    move.l  #RQ_SLAB,%d1
    add.l   %d0,%d1
    move.l  %d1,-(%sp)
    move.l  %a4,%d1
    add.l   %d0,%d1
    move.l  %d1,-(%sp)
    jsr     MEMCPY
    lea     12(%sp),%sp
    movea.l #RQ_SLAB,%a0                | the trig masks as reloaded (the finish verifies them)
    adda.l  rq_voff,%a0
    lea     rq_vsnap,%a1
    moveq   #16,%d0
rj_sn:
    move.b  (%a0)+,(%a1)+
    subq.l  #1,%d0
    bne.b   rj_sn
    moveq   #1,%d0
    move.b  %d0,rq_varm
    movea.l %a4,%a0
    adda.l  #TRAILER,%a0
    tst.b   T_SMODE(%a0)
    bne.b   rj_tfull                    | PER TRACK: the record's own bytes
    movea.l #RQ_SLAB,%a1
    adda.l  #TRAILER,%a1
    move.b  T_LEN(%a1),%d0
    move.b  %d0,T_LEN(%a0)
    move.b  T_SCALE(%a1),%d0
    move.b  %d0,T_SCALE(%a0)
    cmp.b   SCALE_IX,%d0
    beq.b   rj_tfull
    move.b  %d0,SCALE_IX                | the saved rate differs: apply it (as RELOAD does)
rj_tfull:
    cmpi.l  #RQ_TRKFULL,%d7
    bne.w   rj_ok
|   FULL: the track's slice from the card's Part, published for that track (Clyps' FULL load)
    moveq   #0,%d6
    move.b  rq_t,%d6                    | d6 = t
    cmpi.l  #8,%d6
    bcc.b   rj_fcopy
    movea.l #RQ_PART,%a0
    move.b  0x22(%a0,%d6.l),%d0
    cmp.b   0x22(%a3,%d6.l),%d0
    beq.b   rj_fcopy
    moveq   #1,%d0                      | a new machine: restart the voice, PICKUP setup owed
    lsl.l   %d6,%d0
    move.b  ENG_RESTART,%d1
    or.l    %d1,%d0
    move.b  %d0,ENG_RESTART
    lea     cl_postm,%a0
    moveq   #1,%d0
    move.b  %d0,(%a0,%d6.l)
rj_fcopy:
    pea     RQ_PART
    move.l  %a3,-(%sp)
    move.l  %d6,-(%sp)
    jsr     cl_slice
    lea     12(%sp),%sp
    move.l  %d6,%d0
    cmpi.l  #8,%d0
    bcs.b   rj_ft
    subq.l  #8,%d0
rj_ft:
    move.l  %d0,-(%sp)
    move.l  %d2,-(%sp)
    moveq   #0,%d0
    move.b  PLAY_BANK,%d0
    move.l  %d0,-(%sp)
    cmpi.l  #8,%d6
    bcc.b   rj_fm
    jsr     TRK_APPLY
    bra.b   rj_fp
rj_fm:
    jsr     cl_mapply
rj_fp:
    lea     12(%sp),%sp
    lea     cl_postf,%a0                | the UI side: SRAM Part, edited flags, PICKUP, pages
    moveq   #1,%d0
    move.b  %d0,(%a0,%d6.l)
    bra.w   rj_ok
|   ---- the pattern: its whole slab (with its saved Part link) and that whole Part ----
rj_ptn:
    pea     PATSTRIDE
    pea     RQ_SLAB
    move.l  %a4,-(%sp)
    jsr     MEMCPY
    lea     12(%sp),%sp
    moveq   #0,%d0
    move.b  PLAY_BANK,%d0
    move.l  %d5,%d1
    movea.l #BLOB,%a1
    jsr     cl_partin                   | now the saved link: a0 = that Part, d0 = its index
    move.l  %d0,%d2
    pea     PARTSZ
    pea     RQ_PART
    move.l  %a0,-(%sp)
    jsr     MEMCPY
    lea     12(%sp),%sp
    moveq   #0,%d0
    move.b  ACT_PAT,%d0
    cmp.l   %d5,%d0
    bne.b   rj_pshare
    move.b  %d2,RL_CURPART              | the playing pattern: its Part is the sounding one
    bra.b   rj_papply
rj_pshare:
    moveq   #0,%d0
    move.b  RL_CURPART,%d0
    cmp.l   %d2,%d0
    beq.b   rj_papply                   | the Part sounding: applied, and cl_postpart marks it
|   another Part than the one sounding: nothing to apply, but stock's edited mark follows the reload --
|   of the Part pattern P links to (as just reloaded) and no other (the user, 2026-11-02)
    moveq   #0,%d0
    move.b  PLAY_BANK,%d0
    move.l  %d5,%d1
    movea.l #BLOB,%a1
    jsr     cl_partin                   | a0 = P's Part, d0 = its index (= d2)
    movea.l %a0,%a2
    move.l  %d2,%d3
    moveq   #0,%d4                      | the whole Part (cl_pmark: no slice mask)
    jsr     cl_pmark
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
|   the live cache (SRAM mirror, the UI bank only): only what changed (the user, 2026-11-04 -- stock's
|   0x4000faf0 rewrote the whole bank, ~620 KB of battery NVRAM, for one track). A pattern: its slab
|   here (it need not be the playing one); a track: its record + the trailer at the UI tail
|   (cl_postmask, the cl_post bit above); a Part: cl_pmark (rj_pshare here, or cl_postpart).
|   A track reload copies its record + trailer of P here too: the UI tail's copy is of the pattern
|   playing THEN, which a pattern change in between makes another one.
    move.b  PLAY_BANK,%d0
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

| cl_rlopen -> d0 = FOPEN's result: "<project>/bankNN.strd" of the playing bank, read-only
cl_rlopen:
    lea     -8(%sp),%sp
    movem.l %d2/%a2,(%sp)
    clr.l   -(%sp)
    clr.l   -(%sp)
    jsr     PROJDIR
    addq.l  #8,%sp
    moveq   #0,%d1
    move.b  PLAY_BANK,%d1
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
    beq.w   rd_done
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
rd_done:
    jmp     RL_DONEEPI                  | skip the whole-bank reload

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
rq_pat:     .byte 0
rq_t:       .byte 0
rq_nl:      .byte 0
rq_msg:     .byte 0                     | armed before the post
rq_own:     .byte 0                     | the job succeeded: doneFn's next success is ours
rq_varm:    .byte 0
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
