/* SPDX-License-Identifier: MIT
 * SPDX-FileCopyrightText: 2026 Zac Kyoti; registration and render ABI derived from octabam
 * modules/analog-bassdrum/control.c (repeat98, MIT), which measured the seams.
 *
 * OT-303 machine, ColdFire side: the page descriptor, the Part validator wrapper, the admission
 * rule (one OT-303 per DSP core: tracks 1-4 run on core 1, 5-8 on core 0) and the FLEX renderer
 * hook that sends an OT-303 track's control record to the DSP instead of sample data.
 * The track is stored as FLEX plus the signature 'O','T',1 in unused NEIGHBOR page bytes, so a
 * stock OS sees a FLEX track. The voice itself is DSP code (tools/ot303/host.asm); the sequencer
 * drives it: the step hook (machine.s ot_step_hook) reads each note step's slide and look-ahead,
 * the renderer sends the note at the trig with the knobs of that moment (record.c, params.c).
 */
#include <stdint.h>
#include "record.h"
#define U8(a) (*(volatile uint8_t *)(uintptr_t)(a))
#define U32(a) (*(volatile uint32_t *)(uintptr_t)(a))
#define U16(a) (*(volatile uint16_t *)(uintptr_t)(a))
#define BANK 0x46c82456u
#define PART_IDX 0x100b14cfu
#define PART_OFF 0x8ed80u
#define PART_STRIDE 0x18b2u
#define SIG 60u
#define DESC_SIZE 0x1cau
#define FLEX_RENDER 0x40004008u
#define PB_TABLE 0x400d5f38u
#define SRAM_PART 0x100a4eceu
#define FLEX_DEFAULTS 0x400d320cu   /* the stock FLEX page descriptor's twelve defaults (E + 0x96) */
#define SLOT_REC 0x40031d18u        /* stock (machine, slot) -> the sample slot's record, name at +24 */
#define STASH_MARK 0x55u
#define PARK_MARK 0x50u             /* NEIGHBOR's page-1 byte 0 on a track that left the OT-303 (never 'O') */
#define NEIGHBOR 3u

/* SRC (page 1) then SRC SETUP (page 2), stored with the track (params.h has the ranges). PTCH 36 = C3.
 * Open303's
 * defaults: CUT 30 (500 Hz), RES 64, ENV 32, DEC 72 (405 ms; 50 ms .. 2 s since MT25), SLID 38 (60 ms); ACC 100 (MT27: the
 * accent SCALE; a step is accented only by an ACC p-lock, and plays lock x ACC / 127; MT30: the default 100, not
 * 127, so a lock can be turned up from the knob's value; before MT27 ACC 0: an accent was an ACC lock), GATE 63 (half a step), VOL 99 (driven +2.5 dB, MT10's default sound). The 12th slot is
 * hidden (MT13's OSC test switch is gone: the saw runs free, the user's choice on the unit). */
/* body: the same default sound on the new CUT knob (44 = engine 30), and the 303's gate (GATE 74: 75/128 of a step,
 * its 3.5 of 6 clocks) and slide (SLID 73: tau 22.8 ms, its 103.3k x 0.22 uF) */
const uint8_t ot_defaults[12] = {36, 44, 64, 32, 72, 100, 0, 64, 73, 74, 99, 0};
static const char *const ot_names[12] = {
    "PTCH", "CUT", "RES", "ENV", "DEC", "ACC", "WAVE", "TUNE", "SLID", "GATE", "VOL", ""
};
static uint8_t desc[DESC_SIZE] = {0};
uint32_t ot_desc_p = 0;
uint32_t ot_render_calls = 0, ot_trigs = 0;

static unsigned signed_track(const volatile uint8_t *part, unsigned t) {
    const volatile uint8_t *s = part + SIG + 30 * t;
    return t < 8 && part[0x22 + t] == 1 && s[0] == 'O' && s[1] == 'T' && s[2] == 1;
}
static volatile uint8_t *part_base(void) {
    return (volatile uint8_t *)(uintptr_t)(U32(BANK) + PART_OFF + (U8(PART_IDX) & 3) * PART_STRIDE);
}
/* One voice per DSP core: refuse a second OT-303 among tracks 1-4 or 5-8. */
static const volatile uint8_t *play_part(unsigned t);   /* the Part a track's sound comes from (ot_render) */
unsigned ot_admit_track(const volatile uint8_t *part, unsigned track) {
    if (track >= 8) return 0;
    for (unsigned t = track & 4; t < (track & 4) + 4; ++t)
        if (t != track && signed_track(part, t)) return 0;
    return 1;
}
unsigned ot_type(unsigned type, const volatile uint8_t *ptr) {
    volatile uint8_t *part = part_base();
    uintptr_t t = (uintptr_t)ptr - (uintptr_t)(part + 0x22);
    return type == 1 && t < 8 && signed_track(part, (unsigned)t) ? 5 : type;
}
static void put32(uint8_t *p, uint32_t v) {
    p[0] = (uint8_t)(v >> 24); p[1] = (uint8_t)(v >> 16); p[2] = (uint8_t)(v >> 8); p[3] = (uint8_t)v;
}
static void text(uint8_t *p, const char *s, unsigned n) {
    unsigned i = 0; for (; i + 1 < n && s[i]; ++i) p[i] = (uint8_t)s[i];
    for (; i < n; ++i) p[i] = 0;
}
/* PTCH's value as stock draws it: a knob's formatter (descriptor +0x102, stock FLEX's PTCH has
 * 0x4003b4b0) is called as f(buf, value) and writes the text; this one writes the note's name. */
int ot_fmt_ptch(char *buf, int v) {
    return (int)ot_note_name((unsigned)v, buf);
}
/* PTCH's step handler (descriptor +0x162; every caller passes (knob, turn, value) and clamps what
 * comes back). FUNC held (0x46c7dd26, unless PERSONALIZE's DISABLE FUNC+ENC is on, 0x800000a0 --
 * stock FLEX's PTCH handler gates the same way) moves a whole octave per step and keeps the note: an
 * octave that would leave C0 .. C8 is not taken. OCT_DETENTS detents an octave (one was too quick
 * on the unit), tallied here: a reversal starts the tally again, so the first octave back takes
 * the same turn; a turn without FUNC clears it. Not stock's generic handler (0x4003240c) for the
 * count: it tallies 256 a detent against a step of 270 on this knob (ot_emu), so it swallows a
 * detent now and then; its own tally (0x46c7d244 + 20 k) is left alone. Without FUNC the knob is
 * that handler's, as before. MT28: the knob pushed while turned (the flag the generic handler reads,
 * 0x46c7d8ee + 24 (k + 56), which makes a stock knob move 7 a detent) takes the same octave path. */
#define OCT_DETENTS 3
/* MT31: with trigs held, the p-lock editor (0x40050c7c..) calls the handler once per held trig, lowest
 * step first, all in one pass per detent; machine.s ot_plock_hook passes the step of each call (pl_step,
 * pl_have). A detent is tallied once, at the pass's first call (a step not above the last one); the
 * pass's other calls take the same outcome. Before MT31 each held trig's call tallied: with three held,
 * only the third trig's call ever reached the octave. */
static int oct_tally = 0, oct_jump = 0;
static unsigned pl_have = 0, pl_step = 0, pl_last = 0, pl_last_ok = 0;
static unsigned ptch_coarse(int k) {
    unsigned func = U32(0x46c7dd26u) && !U32(0x800000a0u);
    return func || U32(0x46c7d8eeu + 24u * (unsigned)(k + 56)) != 0;
}
int ot_ptch_step(int k, int turn, int v) {
    int (*generic)(int, int, int) = (int (*)(int, int, int))0x4003240cu;
    unsigned locked = pl_have, step = pl_step;
    pl_have = 0;
    if (!ptch_coarse(k)) { oct_tally = 0; pl_last_ok = 0; return generic(k, turn, v); }
    unsigned same_pass = locked && pl_last_ok && step > pl_last;
    pl_last = step; pl_last_ok = locked;
    if (!same_pass) {
        if ((oct_tally ^ turn) < 0) oct_tally = 0;
        oct_tally += turn;
        oct_jump = 0;
        if (oct_tally <= -OCT_DETENTS || oct_tally >= OCT_DETENTS) { oct_jump = oct_tally > 0 ? 12 : -12; oct_tally = 0; }
    }
    int o = v + oct_jump;
    return !oct_jump || o < 0 || o > (int)OT_PTCH_MAX ? v : o;
}
/* The stock FLEX page descriptor, renamed: twelve knobs (an empty name hides a slot; +0xa2 a knob's
 * minimum, +0xd2 its number of values, +0x102 its value formatter, +0x162 its step handler); PTCH
 * runs 0..96 (C0 .. C8), shows note names and steps by octaves with FUNC, the rest run 0..127. */
static uint32_t page(void) {
    if (!ot_desc_p) {
        const volatile uint8_t *src = (const volatile uint8_t *)0x400d3176u;
        for (unsigned i = 0; i < DESC_SIZE; ++i) desc[i] = src[i];
        /* the header keeps stock's "PB" / "PLAYBACK": the page label reads PLAYBACK>OT-303 */
        for (unsigned i = 0; i < 12; ++i) {
            text(desc + 0x4e + 6 * i, ot_names[i], 6);
            desc[0x96 + i] = ot_defaults[i];
            put32(desc + 0xa2 + 4 * i, 0);
            put32(desc + 0xd2 + 4 * i, !ot_names[i][0] ? 0 : i == OT_PTCH ? OT_PTCH_MAX + 1 : 128);
            put32(desc + 0x102 + 4 * i, i == OT_PTCH ? (uint32_t)(uintptr_t)ot_fmt_ptch : 0);
            put32(desc + 0x132 + 4 * i, 0);
            put32(desc + 0x162 + 4 * i, i == OT_PTCH ? (uint32_t)(uintptr_t)ot_ptch_step : 0);
        }
        /* one nibble a knob, low first (knobs 8..11, then 0..7): bit 0 on (stock FLEX also sets 4 on some,
         * meaning unknown); the first eleven on. Bit 1 draws the link clip to the knob on the left: RES to
         * CUT and ACC to DEC, on the slots stock FLEX links (STRT/LEN, RTRG/RTIM) */
        put32(desc + 0x1c2, 0x0111); put32(desc + 0x1c6, 0x11311311u);
        ot_desc_p = (uint32_t)(uintptr_t)(desc + 0x38);
    }
    return ot_desc_p;
}
uint32_t ot_track_page(const volatile uint8_t *type_ptr) {
    (void)type_ptr;
    return page();
}
void ot_ui_tick(void) {
    U32(PB_TABLE + 5 * 4) = page();
}
/* An OT-303 track's twelve knobs live in the track's FLEX bytes (the stock page editor and the
 * engine reach them there), so FLEX's own values are stashed while the track is an OT-303 and put
 * back when it leaves: packed into NEIGHBOR's unused bytes (NEIGHBOR has no parameters; stock shows
 * them as ---). Page 1 bytes 3..5 (0..2 hold the signature) and the SETUP block's six: 8 data bytes
 * of 7 bits (stock's validator keeps them <= 127) and the mark. FLEX's ranges make 56 bits: page 1
 * PTCH STRT LEN RATE RTRG RTIM 7 each, SETUP LOOP 2, SLIC 1, LEN 1, RATE 1, TSTR 2, TSNS 7. */
static const uint8_t flex_bits[12] = {7, 7, 7, 7, 7, 7, 2, 1, 1, 1, 2, 7};
static volatile uint8_t *knob(volatile uint8_t *part, unsigned t, unsigned k) {
    return part + (k < 6 ? 0x2a : 0x1da) + 30 * t + 6 + k % 6;
}
/* MT31: ot_plock_hook (machine.s), at the p-lock editor's test for an existing lock (0x40050ce2), for
 * every held trig: its step (the handler's call follows), and for a trig with no lock yet the value its
 * lock starts from, or -1. Stock starts a new lock at the knob + the raw turn without calling the
 * handler, so FUNC / push + turn on PTCH moved the first detent a semitone; on an OT-303 track, PTCH
 * (page 1) with FUNC or push, the lock starts at the knob's value and goes through the handler. */
int ot_plock_new(unsigned k, unsigned page, unsigned step, int lock) {
    unsigned t = U8(0x100b14ccu);
    if (page || k != OT_PTCH || t >= 8 || !signed_track(part_base(), t)) return -1;
    if (lock == -1 && !ptch_coarse((int)k)) return -1;          /* stock's new lock: no handler call */
    pl_have = 1; pl_step = step;                                  /* the handler's call follows */
    return lock == -1 ? *knob(part_base(), t, OT_PTCH) : -1;
}
static volatile uint8_t *stash(volatile uint8_t *part, unsigned t, unsigned i) {   /* i = 0..8 */
    return i < 3 ? part + SIG + 30 * t + 3 + i : part + 0x1da + 30 * t + 18 + (i - 3);
}
static void flex_stash(volatile uint8_t *part, unsigned t) {
    uint32_t acc = 0; unsigned n = 0, out = 0;
    for (unsigned k = 0; k < 12; ++k) {
        acc |= (uint32_t)(*knob(part, t, k) & ((1u << flex_bits[k]) - 1)) << n;
        n += flex_bits[k];
        while (n >= 7) { *stash(part, t, out++) = (uint8_t)(acc & 0x7f); acc >>= 7; n -= 7; }
    }
    *stash(part, t, 8) = STASH_MARK;
}
/* FLEX's twelve values as stashed (stock's FLEX defaults when there is no stash: an MT1 track) */
static void flex_values(const volatile uint8_t *part, unsigned t, uint8_t v[12]) {
    const volatile uint8_t *def = (const volatile uint8_t *)FLEX_DEFAULTS;
    if (*stash((volatile uint8_t *)part, t, 8) != STASH_MARK) {
        for (unsigned k = 0; k < 12; ++k) v[k] = def[k];
        return;
    }
    uint32_t acc = 0; unsigned n = 0, in = 0;
    for (unsigned k = 0; k < 12; ++k) {
        while (n < flex_bits[k]) { acc |= (uint32_t)(*stash((volatile uint8_t *)part, t, in++) & 0x7f) << n; n += 7; }
        v[k] = (uint8_t)(acc & ((1u << flex_bits[k]) - 1));
        acc >>= flex_bits[k]; n -= flex_bits[k];
    }
}
static void flex_restore(volatile uint8_t *part, unsigned t) {
    uint8_t v[12];
    flex_values(part, t, v);
    for (unsigned k = 0; k < 12; ++k) *knob(part, t, k) = v[k];
    for (unsigned i = 0; i < 9; ++i) *stash(part, t, i) = 0;   /* NEIGHBOR's stock defaults */
}
/* The OT-303's own knobs while the track is another machine (MT35; before, leaving the machine dropped
 * them and coming back seeded the defaults, unlike every stock machine): the same twelve NEIGHBOR bytes,
 * which hold nothing else then. Page 1 byte 0 the mark, bytes 1..5 PTCH .. DEC; the SETUP block's bytes
 * 0..4 WAVE .. VOL, in their SETUP order, so SRC SETUP edits the OT-303 row there on such a track
 * (machine.s ot_setup_edit6), and byte 5 ACC. One value a byte, each <= 127 (the stock validator's
 * rule); a track with no mark takes the defaults. */
static volatile uint8_t *parked(volatile uint8_t *part, unsigned t, unsigned k) {   /* k = 0..10 */
    return k < OT_ACC ? part + SIG + 30 * t + 1 + k
                      : part + 0x1da + 30 * t + 18 + (k == OT_ACC ? 5 : k - OT_WAVE);
}
static unsigned parked_value(const volatile uint8_t *part, unsigned t, unsigned k) {
    if (k > OT_VOL || part[SIG + 30 * t] != PARK_MARK) return ot_defaults[k];
    unsigned v = *parked((volatile uint8_t *)part, t, k);
    return v > (k == OT_PTCH ? OT_PTCH_MAX : 127u) ? ot_defaults[k] : v;
}
static void park_defaults(volatile uint8_t *part, unsigned t) {
    for (unsigned k = 0; k <= OT_VOL; ++k) *parked(part, t, k) = ot_defaults[k];
    part[SIG + 30 * t] = PARK_MARK;
}
/* SRC SETUP previews the machine under its cursor with that machine's six bytes (0x4003ce02 reads
 * Part + 0x1da + 30 track + 6 row + k; machine.s ot_setup_value). An OT-303's SETUP knobs live in
 * FLEX's bytes, so on an OT-303 track the FLEX row would show OT-303's values in FLEX's slots (MT6 on
 * the unit: missing knobs): it shows FLEX's own, from the stash. machine.s ot_setup_draw6 sets
 * ot_preview_flex when the drawn row is FLEX itself (not the OT-303 row, which reads the same bytes), and
 * ot_preview_ot for the OT-303 row: on another machine's track that shows the parked knobs (MT35). */
uint32_t ot_preview_flex = 0, ot_preview_ot = 0;
/* A setup byte stock reads for the track's current machine (machine.s ot_slic_a/b/c: the LEN label's
 * formatter 0x4003b33c and two slice checks 0x40044dbe, 0x4004fee2 read its SLIC byte, Part + 0x1da +
 * 30 track + 6 type + 1). An OT-303 is stored as FLEX, and FLEX's bytes hold OT-303's SETUP knobs
 * (TUNE there), so on an OT-303 track they get FLEX's own value from the stash (MT7 on the unit: odd
 * characters under SLIC and LEN in the STATIC preview, LEN blank in FLEX's). */
unsigned ot_setup_byte(uint32_t addr) {
    uint32_t off = addr - (U32(BANK) + PART_OFF + 0x1da);
    unsigned pidx = off / PART_STRIDE, rem = off % PART_STRIDE, t = rem / 30, row = (rem % 30) / 6, k = rem % 6;
    if (pidx < 4 && t < 8 && row == 1) {
        const volatile uint8_t *part = (const volatile uint8_t *)(uintptr_t)(U32(BANK) + PART_OFF + pidx * PART_STRIDE);
        if (signed_track(part, t)) { uint8_t v[12]; flex_values(part, t, v); return v[6 + k]; }
    }
    return U8(addr);
}
unsigned ot_setup_value(uint32_t off, unsigned k, unsigned row6) {
    const volatile uint8_t *b = (const volatile uint8_t *)(uintptr_t)(U32(BANK) + PART_OFF + 0x1da + off + row6 + k);
    unsigned pidx = off / PART_STRIDE, t = (off % PART_STRIDE) / 30;
    if ((ot_preview_flex || ot_preview_ot) && row6 == 6 && k < 6 && pidx < 4 && t < 8) {
        const volatile uint8_t *part = (const volatile uint8_t *)(uintptr_t)(U32(BANK) + PART_OFF + pidx * PART_STRIDE);
        unsigned is = signed_track(part, t);
        if (ot_preview_flex && is) { uint8_t v[12]; flex_values(part, t, v); return v[6 + k]; }
        if (ot_preview_ot && !is) return parked_value(part, t, OT_WAVE + k);   /* the OT-303 row elsewhere */
    }
    return *b;
}
/* machine.s ot_setup_edit6: the bytes SRC SETUP edits for the OT-303 row on track t -- FLEX's on an
 * OT-303 track (its knobs live there), else the parked block (NEIGHBOR's SETUP bytes; a track with
 * none gets the defaults first, in both copies, so the edit lands beside them). */
unsigned ot_setup_edit_row(unsigned t) {
    volatile uint8_t *part = part_base();
    if (t >= 8 || signed_track(part, t)) return 1;
    volatile uint8_t *copies[2] = {part, part - (U32(BANK) + PART_OFF) + SRAM_PART};
    for (unsigned c = 0; c < 2; ++c) {
        volatile uint8_t *s = copies[c] + SIG + 30 * t;
        if (s[0] == 'O' && s[1] == 'T' && s[2] == 1) return 1;   /* stale signature (a stock OS changed the type) */
        if (s[0] != PARK_MARK) park_defaults(copies[c], t);
    }
    return NEIGHBOR;
}
/* machine.s's commits: sign = 1 makes track t of this Part an OT-303 (FLEX stashed, its parked knobs
 * or the defaults seeded), 0 makes it something else (FLEX put back, its knobs parked); both copies (the
 * Part and its SRAM mirror); nothing changes when the track already is / is not one. */
void ot_assign(volatile uint8_t *part, unsigned t, unsigned sign) {
    volatile uint8_t *copies[2] = {part, part - (U32(BANK) + PART_OFF) + SRAM_PART};
    for (unsigned c = 0; c < 2; ++c) {
        volatile uint8_t *p = copies[c], *s = p + SIG + 30 * t;
        unsigned is = s[0] == 'O' && s[1] == 'T' && s[2] == 1;
        uint8_t v[12];
        if (sign && !is) {
            for (unsigned k = 0; k < 12; ++k) v[k] = (uint8_t)parked_value(p, t, k);
            flex_stash(p, t);
            for (unsigned k = 0; k < 12; ++k) *knob(p, t, k) = v[k];
            s[0] = 'O'; s[1] = 'T'; s[2] = 1;
        } else if (!sign && is) {
            for (unsigned k = 0; k <= OT_VOL; ++k) v[k] = *knob(p, t, k);
            flex_restore(p, t);
            for (unsigned k = 0; k <= OT_VOL; ++k) *parked(p, t, k) = v[k];
            s[0] = PARK_MARK;
        }
    }
}
/* The main page names the current track's sample: the track box (0x4004c1c0, the UI's current track
 * 0x100b14cc) and the screen's label builder (0x4003d552, the current track 0x80000000) both call the
 * slot lookup. An OT-303 track has no sample: they get a record named as the machine (MT17: BLKPYRAMD). */
static const uint8_t ot_slot[36] = {0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
                                    'B', 'L', 'K', 'P', 'Y', 'R', 'A', 'M', 'D', 0, 0, 0};
static uint32_t slot_rec(unsigned t, unsigned machine, unsigned slot) {
    if (machine == 1 && signed_track(part_base(), t)) return (uint32_t)(uintptr_t)ot_slot;
    return ((uint32_t (*)(unsigned, unsigned))SLOT_REC)(machine, slot);
}
uint32_t ot_slot_rec(unsigned machine, unsigned slot) { return slot_rec(U8(0x80000000u), machine, slot); }
uint32_t ot_slot_rec_ui(unsigned machine, unsigned slot) { return slot_rec(U8(0x100b14ccu), machine, slot); }
/* The side columns' machine glyph for an OT-303 track: a 3, in stock's format (0x400a81a4's six:
 * width 3, height 4, one plane, ink, mask; a column a word, row r at bit 31 - r, stored bottom-up:
 * shown top to bottom ###, .##, ..#, ###). Mask as stock's S/F/T. */
static const uint32_t ot_glyph3_ink[3] = {0x90000000u, 0xb0000000u, 0xf0000000u};
static const uint32_t ot_glyph3_mask[3] = {0xfe000000u, 0xfe000000u, 0xfe000000u};
const uint32_t ot_glyph3[5] = {3, 4, 1, (uint32_t)(uintptr_t)ot_glyph3_ink, (uint32_t)(uintptr_t)ot_glyph3_mask};
/* machine.s ot_glyph: the side columns' machine letter for track t (d4 in the stock drawer) */
unsigned ot_track_is(unsigned t) {
    return signed_track(part_base(), t);
}
/* ---- One BLKPYRAMD per DSP core, on every path (the author, 2026-11-17) ----------------------------------
 * The chooser and SRC SETUP refuse a second one on a core (ot_admit_track, machine.s's commits). The other ways in:
 *   TRACK PASTE      stock's paste wrapper 0x4002b988 (machine.s ot_paste_hook): refused whole (ot_paste_ok).
 *   Clyps' FULL loads (KYOTI V1.8BC only: tools/clyps/patch_clyps.s cl_bpgate): refused whole (bp_refuse_load).
 *   anything else    a project or bank load (ot_validate_part notes it), an undo of a paste, a stock writer that
 *                    sets only the machine byte under a STALE signature (a signature on a track that is no longer
 *                    FLEX: SRC page paste 0x40027e4c, the file browser's assigns 0x40093e9c..): the net (bp_net),
 *                    on the UI task after every UI message. Per core of each of the current bank's four Parts, two
 *                    or more signed tracks: the one that held the core at the net's previous pass stays (after a
 *                    load or a bank change: the lowest-numbered), every other one goes back to FLEX with its pre-303
 *                    settings (ot_assign(part, t, 0): FLEX's stash, the knobs parked), the Part marked edited as
 *                    stock's TRACK PASTE does, the current Part's track republished (0x400972fc, as SRC paste), the
 *                    toast. A stale signature is cleared the same way (no toast: nothing was refused). An idle pass
 *                    is machine.s's fast path (bp_fp below): a full pass only when something can have changed.
 * Every toast here comes from the UI task (a key handler or the loop's tail), never the frame path (CLAUDE.md). */
#define NOTIFY 0x4005a2b8u          /* stock's toast (text, duration), legal from the UI task */
#define TOAST_DUR 0x30u
#define CLIP 0x460c8122u            /* stock's track clipboard: the pattern track (0x91a B), then the Part slice */
#define CLIP_KIND 0x460d0ffau       /* 4: the clipboard holds an audio track */
#define PAT_STRIDE 0x8ed8u
#define EDITED 0x95048u             /* bank + : the Parts' edited bits (a byte); 0x100b145e its other copy */
#define EDITED2 0x100b145eu
#define BANK_DIRTY 0x9b332u         /* bank + : a long, 1 = the bank changed; 0x100f8598 its other copy */
#define BANK_DIRTY2 0x100f8598u
#define RDRAW 0x46c7c72cu           /* the UI tail redraws the screen when non-zero */
#define TRK_REFRESH 0x400972fcu     /* (part, track, 1): the track's machine republished (SRC paste, 0x40027fbc) */
extern const char ot_reject_name[];
/* for the firmware checks: toasts shown, loads / pastes refused, net passes, tracks demoted, stale signatures cleared */
uint32_t bp_toasts = 0, bp_refusals = 0, bp_net_passes = 0, bp_net_demoted = 0, bp_net_stale = 0;
uint32_t bp_pend = 0;               /* ot_validate_part saw a Part with two on a core or a stale signature (a load) */
/* The net's fast path (2026-11-17, the author: cheap when idle, every path still covered). machine.s bp_uitail runs
 * after every UI message and returns at once when nothing the net reads can have changed since its last full pass:
 * the same bank, no flag, the periodic count not run out, the same UI Part (0x100b14cf) and engine Part (0x80000003),
 * the same playing / pending pattern (the long at 0x800065bc: PLAY_BANK, ACT_PAT, PEND_BANK; and PEND_PAT
 * 0x800065c0: a cued pattern change wakes the net BEFORE it lands), and the active Part's eight machine bytes and
 * the first two signature bytes of each track as they were. Else bp_net: the full scan of all four Parts, as before.
 * bp_fp is that state, read by machine.s at fixed offsets (BP_FP_* there):
 *   0 bank  1 count  2 UI Part  3 engine Part  4 pattern long  5 PEND_PAT  6 the active Part
 *   7-8 its machine bytes as two longs (0x22.. 0x29)  9-12 the signature words, two tracks a long  13 the flag
 * The flag (bp_wake) is set by every writer that can reach a Part the fingerprint does not watch: a load (the Part
 * validator), an allowed TRACK PASTE, an allowed Clyps FULL load (KYOTI V1.8BC: bp_refuse_load). Writers of the
 * active Part (SRC page paste, the file browser's assigns, an undo, the chooser) change its fingerprint. The count
 * (NET_EVERY passes, about a second at the UI's 60 Hz tick) runs a full pass anyway: a writer nobody knows of, to a
 * Part that is not active, is caught within it -- and in any case when that Part becomes active (its index or the
 * pattern changes), before it plays a step. */
#define NET_EVERY 60u
uint32_t bp_fp[14] = {0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1};
#define bp_wake bp_fp[13]
uint32_t bp_net_full = 0, bp_net_why = 0, bp_net_fixpart = 0xff;   /* full passes; why the repairing ones ran; and
                                                       the engine Part when the last one repaired (the gate's check) */
static void fp_take(uint32_t bank) {
    unsigned cur = U8(PART_IDX);
    const volatile uint16_t *w = (const volatile uint16_t *)(uintptr_t)(bank + PART_OFF + (cur & 3u) * PART_STRIDE);
    bp_fp[0] = bank; bp_fp[1] = NET_EVERY; bp_fp[2] = cur; bp_fp[3] = U8(0x80000003u);
    bp_fp[4] = U32(0x800065bcu); bp_fp[5] = U8(0x800065c0u); bp_fp[6] = (uint32_t)(uintptr_t)w;
    bp_fp[7] = (uint32_t)w[0x22 / 2] << 16 | w[0x24 / 2];
    bp_fp[8] = (uint32_t)w[0x26 / 2] << 16 | w[0x28 / 2];
    for (unsigned i = 0; i < 4; ++i) bp_fp[9 + i] = (uint32_t)w[(SIG + 60 * i) / 2] << 16 | w[(SIG + 30 + 60 * i) / 2];
    bp_wake = 0;
}
/* why this pass is not the fast one (the bits of bp_net_why) */
static unsigned net_cause(uint32_t bank) {
    if (bp_wake) return 1;
    if (bank != bp_fp[0]) return 2;
    if (!bp_fp[1]) return 16;
    if (U8(PART_IDX) != bp_fp[2] || U8(0x80000003u) != bp_fp[3]) return 4;
    if (U32(0x800065bcu) != bp_fp[4] || U8(0x800065c0u) != bp_fp[5]) return 8;
    return 32;                                           /* the active Part's fingerprint */
}
static void bp_toast(void) {
    ++bp_toasts;
    ((void (*)(const char *, unsigned))NOTIFY)(ot_reject_name, TOAST_DUR);
}
static unsigned has_sig(const volatile uint8_t *part, unsigned t) {
    const volatile uint8_t *s = part + SIG + 30 * t;
    return s[0] == 'O' && s[1] == 'T' && s[2] == 1;
}
static unsigned two(unsigned m) { return (m & (m - 1)) != 0; }
static unsigned lowest(unsigned m) { unsigned t = 0; while (t < 7 && !(m >> t & 1u)) ++t; return t; }
/* TRACK PASTE: machine.s ot_paste_hook, at the paste wrapper's entry (0x4002b988(pattern, track), the [FUNC]+[STOP]
 * handler's: it pastes the clipboard into that track of the pattern and its Part when the clipboard holds an audio
 * track). 0 = refused: the clipboard's track is a BLKPYRAMD and another track on the target's core in the pattern's
 * Part is one (the toast here). The track keeps what it had. */
unsigned ot_paste_ok(const volatile uint8_t *clip, unsigned pattern, unsigned t) {
    bp_wake = 1;                                         /* a paste writes a Part: the net's next pass is a full one */
    if (U32(CLIP_KIND) != 4 || t >= 8 || pattern >= 16) return 1;
    const volatile uint8_t *s = clip + 0x91a;            /* FX1, FX2, the levels (2), the machine, page 1 */
    if (!(s[4] == 1 && s[5 + 18] == 'O' && s[5 + 19] == 'T' && s[5 + 20] == 1)) return 1;
    uint32_t bank = U32(BANK);
    const volatile uint8_t *part = (const volatile uint8_t *)(uintptr_t)(bank + PART_OFF
        + (U8(bank + pattern * PAT_STRIDE + 0x8e57) & 3u) * PART_STRIDE);
    if (ot_admit_track(part, t)) return 1;
    ++bp_refusals;
    bp_toast();
    return 0;
}
/* SRC page copy / paste (the author, 2026-11-18, B3): a page holds one machine's twelve bytes and that machine
 * (0x40026314 copies them into the clipboard 0x460c8122 or the undo buffer 0x460bf218, kind 26 at +0x8ed8 for SRC;
 * 0x40027e4c writes them back with the machine byte). An OT-303 is FLEX in those bytes, so a FLEX page pasted onto
 * one left it an OT-303 with FLEX's numbers (VOL 0 ...), and an OT-303's page pasted elsewhere made a FLEX with the
 * OT-303's. Now the page carries what it was copied from (bp_pg[]: machine.s ot_pgcopy_hook) and a paste turns the
 * track into that: onto an OT-303 from any other page, the track leaves the OT-303 first (FLEX's values back, the
 * knobs parked) and then takes the pasted values; an OT-303's page onto another machine makes it an OT-303 with the
 * copied knobs, refused with the toast when another track on its core in that Part is one (ot_pgpaste_hook: the
 * page paste 0x40028fc4 returns 0, as stock's when nothing is pasted; the key handler then clears the undo state).
 * An UNDO of a page paste (0x40028f40, machine.s ot_pgundo_hook) restores the same way, never refused (a refusal
 * there makes the key handler paste instead); the track stays FLEX if its core has another one then. */
#define UNDO_BUF 0x460bf218u
#define PG_KIND 0x8ed8u
uint8_t bp_pg[2] = {0, 0};                               /* the clipboard's / the undo buffer's SRC page is an OT-303's */
void ot_pgcopy(uint32_t buf, unsigned part, unsigned t, unsigned page, unsigned midi) {
    unsigned v = 0;
    if (!page && !midi && part < 4 && U32(BANK))
        v = signed_track((const volatile uint8_t *)(uintptr_t)(U32(BANK) + PART_OFF + part * PART_STRIDE), t);
    if (buf == CLIP) bp_pg[0] = (uint8_t)v;
    else if (buf == UNDO_BUF) bp_pg[1] = (uint8_t)v;
}
unsigned ot_pgpaste(uint32_t buf, unsigned part, unsigned t, unsigned page, unsigned midi) {
    uint32_t bank = U32(BANK);
    if (page || midi || part >= 4 || t >= 8 || !bank || U32(buf + PG_KIND) != 26) return 1;
    volatile uint8_t *p = (volatile uint8_t *)(uintptr_t)(bank + PART_OFF + part * PART_STRIDE);
    unsigned src = bp_pg[buf == UNDO_BUF], is = signed_track(p, t);
    if (src && !is) {
        if (!ot_admit_track(p, t)) {
            if (buf == UNDO_BUF) return 1;
            ++bp_refusals;
            bp_toast();
            return 0;
        }
        ot_assign(p, t, 1);
    } else if (!src && is)
        ot_assign(p, t, 0);
    else
        return 1;
    bp_wake = 1;
    return 1;
}
/* KYOTI V1.8BC: Clyps' FULL loads (patch_clyps.s cl_bpgate, before anything is loaded or cued). dst = the Part the
 * loads land in; src[t] = the Part track t's slice will come from (this load's, or a FULL load still cued for t),
 * 0 = t keeps its own; mask = the tracks of this load. 1 = refused (the toast here): after it a core would hold two
 * BLKPYRAMD tracks, one of them brought by this load. */
unsigned bp_refuse_load(const volatile uint8_t *dst, const uint32_t *src, unsigned mask) {
    unsigned fin = 0, inc = 0;
    for (unsigned t = 0; t < 8; ++t) {
        const volatile uint8_t *p = src[t] ? (const volatile uint8_t *)(uintptr_t)src[t] : dst;
        if (signed_track(p, t)) {
            fin |= 1u << t;
            if (src[t] && (mask >> t & 1u)) inc |= 1u << t;
        }
    }
    if (!((inc & 0x0fu) && two(fin & 0x0fu)) && !((inc & 0xf0u) && two(fin & 0xf0u))) { bp_wake = 1; return 0; }
    ++bp_refusals;
    bp_toast();
    return 1;
}
/* the net's state: the track (1-8) that alone held each core of each Part at the last pass (0: none), for this bank */
static uint8_t net_hold[4][2] = {{0, 0}, {0, 0}, {0, 0}, {0, 0}};
static uint32_t net_bank = 0, net_sig = 0;
void bp_net(void) {                                     /* machine.s bp_uitail's slow path: a full pass */
    uint32_t bank = U32(BANK);
    if (!bank) return;                                   /* no bank yet (early boot) */
    ++bp_net_passes; ++bp_net_full;
    unsigned why = net_cause(bank);
    uint8_t sgn[4], stl[4];
    unsigned work = 0;
    uint32_t sig = bank;
    for (unsigned p = 0; p < 4; ++p) {                   /* the scan: a byte or two a track */
        const volatile uint8_t *part = (const volatile uint8_t *)(uintptr_t)(bank + PART_OFF + p * PART_STRIDE);
        unsigned m = 0, st = 0;
        for (unsigned t = 0; t < 8; ++t)
            if (part[SIG + 30 * t] == 'O' && has_sig(part, t)) {
                if (part[0x22 + t] == 1) m |= 1u << t;
                else st |= 1u << t;
            }
        sgn[p] = (uint8_t)m; stl[p] = (uint8_t)st;
        work |= st | (two(m & 0x0fu) || two(m & 0xf0u));
        sig = sig * 33u + (m | st << 8);
    }
    if (bank != net_bank) {                              /* another bank: nothing held there yet */
        for (unsigned p = 0; p < 4; ++p) net_hold[p][0] = net_hold[p][1] = 0;
        net_bank = bank;
    }
    if (bp_pend) {                                       /* a load: act on a state seen twice in a row (the load may */
        if (sig != net_sig) { net_sig = sig; bp_wake = 1; return; }   /* still be writing), keeping the lowest-numbered;
                                                       the next pass is a full one again */
        bp_pend = 0;
        for (unsigned p = 0; p < 4; ++p) net_hold[p][0] = net_hold[p][1] = 0;
    }
    net_sig = sig;
    if (work) {
        unsigned demoted = 0, cur = U8(PART_IDX) & 3u;
        for (unsigned p = 0; p < 4; ++p) {
            volatile uint8_t *part = (volatile uint8_t *)(uintptr_t)(bank + PART_OFF + p * PART_STRIDE);
            unsigned fixed = 0;
            for (unsigned c = 0; c < 2; ++c) {
                unsigned cm = c ? 0x0fu : 0xf0u, m = sgn[p] & cm;   /* c = 1: core 1 (T1-4), c = 0: core 0 (T5-8) */
                if (!two(m)) continue;
                unsigned h = net_hold[p][c], keep = h && (m >> (h - 1) & 1u) ? h - 1 : lowest(m);
                for (unsigned t = 0; t < 8; ++t)
                    if ((m >> t & 1u) && t != keep) {
                        ot_assign(part, t, 0);
                        if (p == cur) ((void (*)(unsigned, unsigned, unsigned))TRK_REFRESH)(p, t, 1);
                        ++bp_net_demoted; ++demoted; fixed = 1;
                    }
                sgn[p] = (uint8_t)((sgn[p] & ~cm) | 1u << keep);
            }
            for (unsigned t = 0; t < 8; ++t)
                if (stl[p] >> t & 1u) { ot_assign(part, t, 0); ++bp_net_stale; fixed = 1; }
            if (fixed) {                                 /* as stock's TRACK PASTE marks its Part (0x4002b8b6..) */
                U8(bank + EDITED) |= (uint8_t)(1u << p);
                U8(EDITED2) |= (uint8_t)(1u << p);
                U32(bank + BANK_DIRTY) = 1;
                U32(BANK_DIRTY2) = 1;
            }
        }
        U32(RDRAW) = 1;
        if (demoted) bp_toast();
        bp_net_why |= why; bp_net_fixpart = U8(0x80000003u);
    }
    for (unsigned p = 0; p < 4; ++p)                     /* who holds each core now */
        for (unsigned c = 0; c < 2; ++c) {
            unsigned m = sgn[p] & (c ? 0x0fu : 0xf0u);
            net_hold[p][c] = (uint8_t)(m && !two(m) ? lowest(m) + 1 : 0);
        }
    fp_take(bank);                                       /* the state the fast path compares against */
}
/* The stock validator sees FLEX defaults for every OT-303 track; the twelve bytes come back after.
 * Every other Part byte is checked by stock's real validator (machine.s skips our own detour). A Part with two
 * BLKPYRAMD tracks on a core, or a stale signature, is only noted here (bp_pend: this runs inside the load; the net
 * repairs it on the UI task). */
extern int ot_stock_validate(void *part);
int ot_validate_part(uint8_t *part) {
    uint8_t saved[8][12]; unsigned mask = 0;
    const volatile uint8_t *stock = (const volatile uint8_t *)0x400d320cu;
    bp_wake = 1;                                         /* a load: the net's next pass is a full one */
    for (unsigned t = 0; t < 8; ++t)
        if (has_sig(part, t) && part[0x22 + t] != 1) bp_pend = 1;
    for (unsigned t = 0; t < 8; ++t) if (signed_track(part, t)) {
        mask |= 1u << t;
        for (unsigned k = 0; k < 12; ++k) {
            unsigned at = (k < 6 ? 0x2a : 0x1da) + 30 * t + 6 + k % 6;
            saved[t][k] = part[at]; part[at] = stock[k];
        }
    }
    if (two(mask & 0x0fu) || two(mask & 0xf0u)) bp_pend = 1;
    int result = ot_stock_validate(part);
    for (unsigned t = 0; t < 8; ++t) if (mask & (1u << t))
        for (unsigned k = 0; k < 12; ++k) {
            unsigned at = (k < 6 ? 0x2a : 0x1da) + 30 * t + 6 + k % 6;
            part[at] = saved[t][k];
        }
    return result;
}
/* The sequencer: the step handler 0x4009d1e8 schedules a track's next step right after the step
 * before it fires -- about a step ahead (ot_emu trace; MT5 on the unit: our renderer saw that next
 * step's call before or after the current trig, in either order). Two hooks:
 *   ot_step (machine.s ot_step_hook, the handler's entry): which step of which pattern is being
 *     scheduled; a step out of sequence (the transport started again, a jump) clears the track's
 *     queue, a note still queued from two steps back is dropped (its trig never came)
 *   ot_note (machine.s ot_note_hook, 0x4009d422: the handler writes the note code 29 there, after the
 *     step's trig condition passed -- a note that will fire): queues its gate and slide
 * The trig takes the oldest queued note, so trigs and notes pair one for one in order.
 *   slide  the step's slide trig: the note slides from the one before when that gate is still open
 *   gate   GATE's share of the step, plus a whole step for each trigless lock or trigless trig straight
 *          after (a tie; a trigless trig still does its stock job -- LFO / FX envelope resets -- and
 *          never retriggers the voice: the user's choice, MT9);
 *          held to the end of the next step when the next step is a note with a slide trig
 * At the end of a pattern the handler is already scheduling the next pattern: whether the track is
 * an OT-303 there is read from that pattern's own Part (+0x8e57). (One-shot trigs, code 61, are not
 * queued: the frame builder can still drop them.)
 * Steps: the bank's pattern masks (0x400e21e0 + bank 0x9b340 + pattern 0x8ed8 + track 0x91a: +0 trig,
 * +8 trigless trig, +0x10 trigless lock, +0x48 slide; step s < 32 in the long at +4, bit s, else the
 * long at +0, bit s - 32),
 * the length and scale of the pattern (+0x8e53/+0x8e54) or, in PER TRACK mode (+0x8e55), the
 * track's (+0x50/+0x51); ticks per step 0x400aba50[scale], tempo 0x80001814 = BPM x 24. */
struct ot_qn { uint32_t gl, sl; uint8_t step, slide, call, acc, len, toend, gate; };
#define QN 4u
static struct ot_qn q[8][QN] = {{{0, 0, 0, 0, 0, 0, 0, 0, 0}}};
static uint8_t qn[8] = {0}, qcall[8] = {0}, qlast[8] = {0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff}, qlen[8] = {0};
static uint32_t qctx[8] = {0};          /* the step being scheduled: 1 << 24 | bank << 16 | pattern << 8 | step */
static struct ot_voice voice[8] = {{{0}, 0, {0}, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0}};
/* MT26: a push-and-turn (coarse) knob step. The editor writes such a step to the engine's base value at
 * once, without the 1/16-a-frame slew it gives a normal turn (0x40055190: the knob's coarse flag
 * 0x46c7d244 + 20 k + 8 -> 0x400551bc), so CUT / ENV jumped several values. Only the knob writes the
 * Part's value (the live byte and the base word also show a playing step's p-lock): when it moves and
 * the lane's value jumped more than one knob value in that frame, the value sent is slewed the
 * editor's way (1/16 a frame) until it arrives. A normal turn arrives slewed already; an LFO or a
 * p-lock leaves the Part alone and is sent as is; a note's frame ends a glide. */
struct ot_cg { uint16_t s, lane; uint8_t live, gliding, have; };
static struct ot_cg cg[8][2] = {{{0, 0, 0, 0, 0}}};
static unsigned coarse_glide(struct ot_cg *g, unsigned live, unsigned lane, unsigned ev) {
    if (!g->have) { g->s = g->lane = (uint16_t)lane; g->live = (uint8_t)live; g->have = 1; return lane; }
    int32_t jump = (int32_t)lane - (int32_t)g->lane;
    if (live != g->live && (jump > 256 || jump < -256) && !(ev & OT_EV_NOTE)) g->gliding = 1;
    if (ev & OT_EV_NOTE) g->gliding = 0;
    if (g->gliding) {
        int32_t d = (int32_t)lane - (int32_t)g->s;
        if (d > -16 && d < 16) { g->s = (uint16_t)lane; g->gliding = 0; }
        else g->s = (uint16_t)((int32_t)g->s + d / 16);
    } else g->s = (uint16_t)lane;
    g->live = (uint8_t)live; g->lane = (uint16_t)lane;
    return g->s;
}
/* MT20, AMP ATK > 0: stock's AMP (mode RTRG) drops the track's level to ~0 at every trig, no fade --
 * a sample restarts there, this voice may still sound (a long gate, an accent's tail, a slide, a held
 * live note): a click. While the voice is estimated to sound, the frame's AMP record (0x80000110 +
 * 0x200 ping + 64 track, hw 0x15 high byte: 0 ANLG, 1 RTRG, 2/3 the trigless-trig pair) is switched
 * to its analog twin for that frame (no reset; ATK still fades in a note from silence). */
static uint32_t snd_until[8] = {0, 0, 0, 0, 0, 0, 0, 0};
/* MT27: the accent of the note each track last started (0: none), and lock x scale / 127 */
static uint8_t acc_now[8] = {0, 0, 0, 0, 0, 0, 0, 0};
static unsigned acc_amount(unsigned lock, unsigned scale) { return (lock * scale + 63u) / 127u; }
/* MT21, short AMP HOLD / REL: the AMP envelope can close while this voice still sounds (its gate is
 * longer); the next trig then opened it in one sample (ATK 0) onto a sounding voice: a pop (a sample
 * restarts from its start there). While the voice sounds, a trig's AMP gets at least ATK 1 (a linear
 * ~5 ms fade from where the level is) for the frames its ramp takes. */
static uint32_t atk_until[8] = {0, 0, 0, 0, 0, 0, 0, 0};
uint32_t ot_amp_legato = 0;
/* for the firmware check (tools/ot303/verify_ot303.py): note steps seen, the last step handler call
 * (track, bank, pattern, step a byte each), trig flags with no note queued (ignored), queue clears
 * and notes dropped unplayed, the last 32 notes sent (track << 28 | EV << 24 | gate) */
uint32_t ot_steps = 0, ot_last_step = 0, ot_evn = 0, ot_strayflags = 0, ot_qclears = 0, ot_qdrops = 0;
uint32_t ot_evlog[32] = {0};
uint8_t ot_evptch[32] = {0};            /* each logged note's PTCH (the step's lock, if any) */
uint8_t ot_evacc[32] = {0};             /* and its accent (0: none) */
/* a trace for the firmware check: kind << 28 | track << 24 | a << 16 | b, kind 1 the step handler
 * (a step, b pattern << 8 | 1 for a note queued), 2 a trig flag (a the step played or $ff, b the flag
 * byte << 8 | the notes queued); stamped by ot_frames (the renderer's second calls) */
uint32_t ot_trace[128] = {0}, ot_tracen = 0, ot_frames = 0, ot_tracet[128] = {0};
static unsigned fr_last = 8;            /* the last OT-303 track rendered (8: none yet) */
static void trace(unsigned kind, unsigned track, unsigned a, unsigned b) {
    ot_tracet[ot_tracen & 127] = ot_frames;
    ot_trace[ot_tracen++ & 127] = kind << 28 | track << 24 | (a & 0xff) << 16 | (b & 0xffff);
}
static unsigned step_bit(uintptr_t trk, unsigned mask, unsigned s) {
    return s < 32 ? (U32(trk + mask + 4) >> s) & 1u : (U32(trk + mask) >> (s - 32)) & 1u;
}
static unsigned knob_now(unsigned track, unsigned k) {   /* SETUP's live bytes (page 1: fp, below) */
    return U8(0x80000810u + 72u * track + 0x20u + k - 6u);
}
static uintptr_t pattern_at(unsigned bank, unsigned pattern) { return 0x400e21e0u + bank * 0x9b340u + pattern * 0x8ed8u; }
static unsigned step_len(uintptr_t base, uintptr_t trk, uint32_t *sl) {
    unsigned len = U8(base + 0x8e53), sc = U8(base + 0x8e54);
    if (U8(base + 0x8e55)) { len = U8(trk + 0x50); sc = U8(trk + 0x51); }
    if (len < 1 || len > 64) len = 16;
    if (sc > 6) sc = 2;
    uint32_t t24 = U32(0x80001814u);
    if (t24 < 720 || t24 > 7200) t24 = 2880;
    *sl = U8(0x400aba50u + 4 * sc + 3) * 2646000u / t24;
    return len;
}
/* Ties across a pattern change (the author on OCTABAM41, 2026-11-19: a note tied to the end of a pattern was cut at a
 * cued change although the next pattern starts with ties). A note's gate is worked out when it starts, its ties
 * counted on to the end of its pattern and wrapped to that pattern's own first steps: right while the pattern loops,
 * not when another pattern follows. When the step handler schedules another pattern's first step after the last
 * step (a step ahead), the gate of a note whose ties reach that last step is worked out again from the incoming
 * pattern's first steps -- longer through its ties, or ending in the last step where the outgoing pattern's own first
 * steps had made it run on -- and sent as a slide to the same pitch, which moves an open gate's end without a
 * retrigger (host.asm: a slide into an open gate takes the note words, GL included, and no restart). Not for a
 * DIRECT JUMP landing (the author: a jump into a tie keeps the old rule). */
static uint32_t nt_frame[8] = {0}, nt_sl[8] = {0}, gate_end[8] = {0};
static uint8_t nt_step[8] = {0}, nt_len[8] = {0}, nt_toend[8] = {0}, nt_ptch[8] = {0}, nt_gate[8] = {0};
static int32_t xt_rem[8] = {0};
static uint32_t xt_frame[8] = {0};
static uint8_t xt_have[8] = {0};
uint32_t ot_tie_xfers = 0, ot_tie_sent = 0;
static void tie_xfer(unsigned track, const volatile uint8_t *part, uintptr_t trk, unsigned len, uint32_t sl) {
    if (!nt_toend[track]) return;
    int32_t old_rem = (int32_t)(gate_end[track] - ot_frames) * 16;
    if (old_rem < 48 || old_rem > 0x3fffffff) return;          /* the gate closing now (or held live) */
    int32_t b = (int32_t)(nt_frame[track] - ot_frames) * 16 + (int32_t)((nt_len[track] - nt_step[track]) * nt_sl[track]);
    if (b < 0 || b > 2 * (int32_t)nt_sl[track]) return;      /* not in the outgoing pattern's last step */
    unsigned k = 0;
    while (k < len && !step_bit(trk, 0x00, k) && (step_bit(trk, 0x08, k) | step_bit(trk, 0x10, k))) ++k;
    unsigned hold = k < len && step_bit(trk, 0x00, k) && step_bit(trk, 0x48, k);
    unsigned g = *knob((volatile uint8_t *)part, track, OT_GATE);
    int32_t nr = !k ? b - (int32_t)nt_sl[track] + (int32_t)ot_gate_samples(nt_gate[track], nt_sl[track])
               : hold ? b + (int32_t)((k + 1) * sl) : b + (int32_t)((k - 1) * sl + ot_gate_samples(g, sl));
    if (nr > old_rem - 16 && nr < old_rem + 16) return;
    xt_rem[track] = nr; xt_frame[track] = ot_frames; xt_have[track] = 1;
    ++ot_tie_xfers;
}
void ot_step(unsigned track, unsigned bank, unsigned pattern, unsigned s) {
    if (track >= 8) return;
    uint32_t prev = qctx[track];
    qctx[track] = 0;
    if (bank >= 16 || pattern >= 16 || s >= 64) return;
    uintptr_t base = pattern_at(bank, pattern), trk = base + track * 0x91au;
    const volatile uint8_t *part = (const volatile uint8_t *)(0x400e21e0u + bank * 0x9b340u + PART_OFF + (U8(base + 0x8e57) & 3u) * PART_STRIDE);
    if (!signed_track(part, track)) return;
    ++ot_steps;
    ot_last_step = track << 24 | bank << 16 | pattern << 8 | s;
    uint32_t sl;
    unsigned len = step_len(base, trk, &sl);
    unsigned last = qlast[track], same = s == last;
    if (prev && !same && s == 0 && last + 1u == qlen[track] && (prev >> 8 & 0xffffu) != (bank << 8 | pattern))
        tie_xfer(track, part, trk, len, sl);                 /* another pattern follows the last step */
    if (!same && !(s == last + 1u || (s == 0 && last + 1u == qlen[track]))) { if (qn[track]) ++ot_qclears; qn[track] = 0; }
    qlast[track] = (uint8_t)s; qlen[track] = (uint8_t)len;
    if (!same) {
        ++qcall[track];
        unsigned k = qn[track], j = 0;          /* a note queued two steps back never played */
        while (j < k && (uint8_t)(qcall[track] - q[track][j].call) >= 2) ++j;
        for (unsigned i = j; i < k; ++i) q[track][i - j] = q[track][i];
        qn[track] = (uint8_t)(k - j); ot_qdrops += j;
    }
    qctx[track] = 1u << 24 | bank << 16 | pattern << 8 | s;
    trace(1, track, s, pattern << 8);
}
void ot_note(unsigned track) {
    if (track >= 8 || !qctx[track]) return;
    unsigned bank = qctx[track] >> 16 & 0xff, pattern = qctx[track] >> 8 & 0xff, s = qctx[track] & 0xff;
    uintptr_t base = pattern_at(bank, pattern), trk = base + track * 0x91au;
    uint32_t sl;
    unsigned len = step_len(base, trk, &sl);
    unsigned count = 1, n = s, i;
    for (i = 1; i < len; ++i) {
        n = (n + 1) % len;
        if (step_bit(trk, 0x00, n) || !(step_bit(trk, 0x08, n) | step_bit(trk, 0x10, n))) break;
        ++count;
    }
    unsigned hold = i < len && step_bit(trk, 0x00, n) && step_bit(trk, 0x48, n);
    /* GATE from the Part of the pattern being scheduled (OCTABAM42 on the unit, 2026-11-19: the first note after a
     * load, or the first into another Part, took the live byte 0x80000810 + 72 t + 0x23, which stock re-stages only at
     * the track's trig -- a step after this runs -- so it played the old Part's GATE, or a load's leftover: a blip).
     * A SETUP knob has no p-lock slot (a step record is PLAYBACK, AMP, LFO, FX1, FX2), so the Part's value is it. */
    unsigned gate = *knob((volatile uint8_t *)(uintptr_t)(0x400e21e0u + bank * 0x9b340u + PART_OFF
                                                         + (U8(base + 0x8e57) & 3u) * PART_STRIDE), track, OT_GATE);
    uint32_t gl = hold ? (count + 1) * sl : (count - 1) * sl + ot_gate_samples(gate, sl);
    gl = gl < 1 ? 1 : gl > 0x7ffffeu ? 0x7ffffeu : gl;
    unsigned acc = U8(trk + 0x59 + 32u * s + OT_ACC);      /* MT27: the step's ACC p-lock (0xff: none) */
    struct ot_qn e = {gl, sl, (uint8_t)s, (uint8_t)step_bit(trk, 0x48, s), qcall[track], (uint8_t)(acc > 127 ? 0 : acc),
                      (uint8_t)len, (uint8_t)(s + count >= len), (uint8_t)gate};   /* toend: its ties reach the last step */
    unsigned k = qn[track];
    if (k && q[track][k - 1].step == s && q[track][k - 1].call == qcall[track]) q[track][k - 1] = e;   /* the same call again */
    else {
        if (k == QN) { for (unsigned j = 1; j < QN; ++j) q[track][j - 1] = q[track][j]; --k; ++ot_qdrops; }
        q[track][k] = e; qn[track] = (uint8_t)(k + 1);
    }
    trace(1, track, s, pattern << 8 | 1);
}
/* Live notes (MT18): the track keys (TRACKS / SLOTS / SLICES modes), the chromatic trig keys, MIDI
 * notes (36-43 and the chromatic 72-96) and the trig preview (TRIG + YES) post a START (0x1d) to the
 * stock voice mailbox without the sequencer's note scheduling, so the renderer saw a flag with no
 * queued note (a stray) and stayed silent. machine.s's hooks mark the track's live note pending, with
 * a pitch offset for chromatic keys and MIDI; the renderer plays it on the next flag, held until the
 * key-up / note-off / YES release (0x40 in the mailbox: ot_live_release). A pending note lapses after
 * LIVE_TTL frames, so a later pattern or Part flag never plays it. */
#define LIVE_TTL 2756u                    /* frames: 1 s */
struct ot_live { uint32_t pending; int32_t semis; uint8_t release, sounding, ptch, armed, abs, note, vacc; };
static struct ot_live live[8] = {{0, 0, 0, 0, 0, 0, 0, 0, 0}};
/* the frames each DSP core's voice has been sent records since boot (T1-T4, T5-T8): the DSP takes the
 * table chunks in order, so two full passes of chunks guarantee its tables (it renders silence and
 * drops notes until then). Nothing plays a track while the transport is stopped and idle, so the
 * first live note after boot comes while they are still arriving: it waits for them (~30 ms). */
static uint32_t core_frames[2] = {0, 0};
static unsigned dsp_ready(unsigned t) {
    return core_frames[t >= 4] >= 2u * ((ot_ylen + OT_CHUNK - 1u) / OT_CHUNK) + 4u;
}
uint32_t ot_live_reqs = 0, ot_live_notes = 0, ot_live_rels = 0, ot_oneshots = 0;
static const uint32_t live_rets[6] = {0x40044770u, 0x4004fcc6u, 0x40043d7au, 0x4000e568u, 0x4004f9f2u, 0x4004fb36u};
/* 0x40005030(track, cmd, flags, slot) from one of the live callers (ret) */
void ot_live_req(uint32_t ret, unsigned t, unsigned cmd) {
    if (t >= 8 || cmd != 0x1d || !signed_track(part_base(), t)) return;
    for (unsigned i = 0; i < 6; ++i)
        if (ret == live_rets[i]) {
            if (ret != 0x4004fcc6u) { live[t].semis = 0; live[t].abs = 0; }   /* the chromatic keys set theirs first */
            live[t].pending = ot_frames + LIVE_TTL; live[t].armed = 0; live[t].vacc = 0;
            ++ot_live_reqs;
            return;
        }
}
/* a chromatic trig key (0x4004fc84: raw = 5 idx + 4; ret = the chromatic handler's caller): 1 on an
 * OT-303 track (its PTCH byte is not overwritten with FLEX's value). MT23: from the trig keys the
 * note is absolute -- idx = key + 12 octaves (0..3), PTCH 12 + idx: C1 at page 1's first key, C4 at
 * page 4's; MIDI's follow-the-trig-mode path (0x4005014a) stays a transpose around PTCH. */
#define CHROM_MIDI_RET 0x4005014au
static unsigned chrom_abs(unsigned raw) {
    unsigned n = 12u + (raw - 4u) / 5u;
    return n > OT_PTCH_MAX ? OT_PTCH_MAX : n;
}
int ot_live_chrom(unsigned t, unsigned raw, uint32_t ret) {
    if (t >= 8 || !signed_track(part_base(), t)) return 0;
    live[t].semis = (int32_t)((raw - 4u) / 5u) - 12;
    live[t].abs = ret != CHROM_MIDI_RET;
    live[t].note = (uint8_t)chrom_abs(raw);
    live[t].pending = ot_frames + LIVE_TTL; live[t].armed = 0; live[t].vacc = 0;
    return 1;
}
/* a MIDI chromatic note (0x4000e746: notes 72-96, 84 = the track's pitch): 1 on an OT-303 track. MT27: a
 * velocity above 100 accents it, by the ACC knob (the accent scale) */
#define ACC_VELOCITY 100u
int ot_live_midi(unsigned t, unsigned note, unsigned vel) {
    if (t >= 8 || !signed_track(part_base(), t)) return 0;
    live[t].semis = (int32_t)(note & 0xffu) - 84; live[t].abs = 0;
    live[t].pending = ot_frames + LIVE_TTL; live[t].armed = 0; live[t].vacc = (vel & 0x7fu) > ACC_VELOCITY;
    ++ot_live_reqs;
    return 1;
}
/* MT22: an idle track's frame (no voice: the packer calls the silent renderer 0x400047f0 for it). An
 * OT-303 track whose core has not had the voice's tables yet renders as a playing one would -- its
 * records (no note) feed the DSP the tables, so the first trigs after the transport starts sound
 * (MT21 on the unit: the first two were missed). 1: render it (machine.s ot_idle_hook). */
int ot_idle_feed(unsigned t, unsigned end) {
    if (end != 16 || t >= 8 || (dsp_ready(0) && dsp_ready(4))) return 0;
    return !dsp_ready(t) && signed_track(play_part(t), t);
}
/* the frame builder found a release (0x40) in the track's mailbox (0x4000b4f6) */
void ot_live_release(unsigned t) {
    if (t >= 8) return;
    if (live[t].pending) live[t].pending = 0;           /* not played yet (a short tap, the tables arriving) */
    else if (live[t].sounding) live[t].release = 1;
    ++ot_live_rels;
}
/* A chromatic key or MIDI note recorded live (0x40042158(track, param 0, value, step, ..) from
 * 0x4004fd1a and from the MIDI path at 0x40062604) writes the PTCH lock in FLEX's units: 64 + 5
 * semitones. On an OT-303 track it becomes this machine's PTCH: the track's PTCH knob plus the
 * semitones (MT19). */
unsigned ot_rec_pitch(unsigned t, int raw) {
    if (t >= 8 || !signed_track(part_base(), t)) return (unsigned)raw;
    int semis = (raw - 64) / 5;
    int v = (int)*knob(part_base(), t, OT_PTCH) + semis;
    return (unsigned)(v < 0 ? 0 : v > (int)OT_PTCH_MAX ? (int)OT_PTCH_MAX : v);
}
/* the chromatic key recorded live (0x4004fd0c): the lock it plays (absolute from the trig keys) */
unsigned ot_rec_chrom_pitch(unsigned t, int raw, uint32_t ret) {
    if (t < 8 && ret != CHROM_MIDI_RET && signed_track(part_base(), t)) return chrom_abs((unsigned)raw);
    return ot_rec_pitch(t, raw);
}
/* MT23, the trig-key modes on an OT-303 track (tmode 0x460d16f0: 0 TRACKS, 1 CHROMATIC, 2 SLOTS, 3
 * SLICES; the octave 0x460d16fc; the track 0x100b14cc). SLOTS / SLICES: nothing to play -- the LEDs
 * dark (stock's own no-slot path) and the keys inert. CHROMATIC: four octaves (0..3) instead of two. */
#define TMODE U32(0x460d16f0u)
#define TOCT U32(0x460d16fcu)
int ot_trigmode_dark(void) {
    return (TMODE == 2 || TMODE == 3) && signed_track(part_base(), U8(0x100b14ccu));
}
void ot_chrom_oct(unsigned key) {           /* FUNC + LEFT (0x34) / RIGHT (0x21) */
    uint32_t o = TOCT;
    /* RIGHT (0x21) up, LEFT (0x34) down (the user, on the unit: the other way round was backwards),
     * wrapping at the ends (stock's 0/1 toggle wraps too) */
    if (signed_track(part_base(), U8(0x100b14ccu))) o = key == 0x21u ? (o >= 3 ? 0 : o + 1) : (o == 0 || o > 3 ? 3 : o - 1);
    else o = o == 0;                        /* stock: a toggle (2, 3 from an OT-303 track: back to 0) */
    TOCT = o;
}
void ot_chrom_sanitize(void) {              /* a chromatic key on any other track: stock's 0 / 1 */
    if (TOCT > 1 && !signed_track(part_base(), U8(0x100b14ccu))) TOCT = 0;
}
unsigned ot_chrom_limit(unsigned t, uint32_t ret) {   /* the highest idx the chromatic handler takes */
    return (t < 8 && ret != CHROM_MIDI_RET && signed_track(part_base(), t)) ? 52u : 24u;
}
/* CHROMATIC's PAGE key (0x4004fde4): stock plays it as idx 16, the note above trig 16, on octave 0
 * only. On an OT-303 track it plays on every octave: idx 16 + 12 octaves (E2 .. E5, trig 16 + 1).
 * -1: stock's path. */
int ot_page_idx(void) {
    unsigned t = U8(0x100b14ccu);
    if (t >= 8 || !signed_track(part_base(), t)) return -1;
    return 16 + 12 * (int)(TOCT > 3 ? 0 : TOCT);
}
/* a one-shot trig (code 61) the step handler schedules (0x4009d4a8): a note when it is armed (its
 * track's bit in 0x8000184e clear: the frame builder plays it once, then sets the bit) */
void ot_oneshot(unsigned t) {
    if (t >= 8 || (U16(0x8000184eu) & (1u << t))) return;
    ++ot_oneshots;
    ot_note(t);
}

#ifdef KYOTI_MM_GATE
/* KYOTI V1.8BC only (tools/build_kyoti.py --clyps-bp passes -DKYOTI_MM_GATE and MUTE_MODES' KEYMASK address;
 * every other build compiles none of this). MUTE_MODES drops a silenced track's new trigs in OTFX-T and DT-T at
 * stock's voice binds (fresh_bind, dt_trig), but this voice starts its notes from the trigger flag, before a
 * voice is bound, so in DT-T a muted track kept playing (ot_emu, BOTLI: T6 muted in DT-T at the unmuted level).
 * The same question MUTE_MODES' Modwerk form answers for FM Synth (mm_trig_muted, Modwerk #777): GATE
 * 0x800000dc is OTFX-T (1) or DT-T (2), and the track is muted, or something is soloed and it is not; a
 * SIDE-CHAIN key track (KEYMASK) keeps its trigs, as there. */
uint32_t ot_mm_drops = 0;
static unsigned mm_drops(unsigned t) {
    uint32_t g = U32(0x800000dcu), ms = U32(0x80000008u);
    if (g != 1u && g != 2u) return 0;
    unsigned sil = (ms >> 8) & 0xffu;
    if (ms & 0xffu) sil |= ~ms & 0xffu;
    return (sil & ~(unsigned)U8(KYOTI_MM_KEYMASK)) >> t & 1u;
}
#endif

/* the trig's note: the oldest queued, or none */
static unsigned take(unsigned track, struct ot_qn *out) {
    unsigned k = qn[track];
    if (!k) return 0;
    *out = q[track][0];
    for (unsigned i = 1; i < k; ++i) q[track][i - 1] = q[track][i];
    qn[track] = (uint8_t)(k - 1);
    return 1;
}

/* The FLEX renderer (kind table slot 1), ABI measured by octabam at 4000d430/4000d518: every track
 * is rendered twice per frame around its event's sample offset; the second call has end = 16.
 * An OT-303 track reserves FLEX's space (later tracks keep their record boundaries) and, once the
 * second segment exists, its record becomes the control record (record.h): the signature, the
 * continuous words from the knobs (page 1 live: p-locks, LFOs, scenes; then SETUP), at a trig the
 * note (its queued gate and slide), and the next chunk of the voice's tables. (Stock w0 is the high half of a source
 * count, 0; w2 the high half of a bounded ring position, never $0909: octabam REVIEW.md.) */
/* The Part a track's sound comes from (OCTABAM40 on the unit, 2026-11-19: a cued Part switch dropped the outgoing
 * voice mid-note with a quiet pop, and the outgoing pattern's last-step note never sounded). Stock moves the UI Part
 * (0x100b14cf) about 7 ticks before the boundary, but each track keeps playing its old Part's sound until its own
 * first trig in the new pattern: the frame builder keeps that Part per track, bank 0x8000182a + t and Part
 * 0x80001832 + t, written at the track's trig (0x4000bf62 / 0x4000bf6a) and by a full Part apply, 0xff after PLAY
 * or a load until the next trig. The renderer asks that Part whether the track is an OT-303, as every stock machine
 * carries its sound; 0xff: the UI Part. So an outgoing OT-303 rings over the boundary like a carried FLEX sample and
 * plays its last step, and an incoming one takes the voice at its own first trig. */
static const volatile uint8_t *play_part(unsigned t) {
    unsigned b = U8(0x8000182au + t), p = U8(0x80001832u + t);
    if (b >= 16 || p >= 4) return part_base();
    return (const volatile uint8_t *)(uintptr_t)(0x400e21e0u + b * 0x9b340u + PART_OFF + p * PART_STRIDE);
}
/* One voice a core: while a track still carries the voice from the old Part, another track on its core can be an
 * OT-303 too. Who keeps the voice, by what each track plays: 2 its own trig in the engine's Part (0x80000002 /
 * 0x80000003) has come -- the incoming track, from its first trig; 1 it plays another Part -- the outgoing track,
 * carrying; 0 no trig since PLAY or a load (0xff), which the UI Part's early move alone makes an OT-303 (the engine
 * Part moves early too, so it decides nothing alone). A tie: the lower track. The other renders as FLEX (its stock
 * record frees the voice on the DSP). */
static unsigned play_rank(unsigned t) {
    unsigned b = U8(0x8000182au + t), p = U8(0x80001832u + t);
    if (b >= 16 || p >= 4) return 0;
    return b == U8(0x80000002u) && p == U8(0x80000003u) ? 2u : 1u;
}
static unsigned yields(unsigned t) {
    unsigned r = play_rank(t);
    for (unsigned u = t & 4; u < (t & 4) + 4; ++u) {
        if (u == t || !signed_track(play_part(u), u)) continue;
        unsigned ru = play_rank(u);
        if (ru > r || (ru == r && u < t)) return 1;
    }
    return 0;
}
/* The DSP serves a core's tracks in order: when the track that held the voice in the last frame is a higher one, it
 * frees the voice only after this track's record, so this track's first note is held one frame (16 samples). */
static uint8_t own_cur[2] = {8, 8}, own_prev[2] = {8, 8};
struct ot_dfr { uint32_t gl; uint8_t ev, acc, have; };
static struct ot_dfr dfr[8] = {{0, 0, 0, 0}};
uint32_t ot_handovers = 0, ot_yields = 0;
int ot_render(unsigned track, unsigned ping, unsigned start, unsigned end) {
    const volatile uint8_t *pp = track < 8 ? play_part(track) : 0;
    if (track >= 8 || !signed_track(pp, track) || (yields(track) && (++ot_yields, 1)))
        return ((int (*)(unsigned, unsigned, unsigned, unsigned))FLEX_RENDER)(track, ping, start, end);
    ++ot_render_calls;
    volatile uint32_t *cursor = (volatile uint32_t *)(uintptr_t)U32(0x80001c80u);
    volatile uint16_t *fp = (volatile uint16_t *)(uintptr_t)U32(0x800062a8u);
    unsigned n = end > start && end <= 16 ? end - start : 0;
    for (unsigned i = 0; i < 4 + 2 * n; ++i) cursor[i] = 0;
    if (end == 16) {
        /* MT32: one count a frame. The packer renders the tracks in order, so a frame starts where the track
         * number does not rise; before, every OT-303 track counted, and with two the frame windows below
         * (a voice's estimated end, MT20 / MT21's, the live note's TTL) ran at half length */
        if (track <= fr_last) {
            ++ot_frames;
            own_prev[0] = own_cur[0]; own_prev[1] = own_cur[1]; own_cur[0] = own_cur[1] = 8;
        }
        fr_last = track;
        unsigned core = track >= 4, held = own_prev[core] < 8 && own_prev[core] > track;
        own_cur[core] = (uint8_t)track;
        uint8_t p[12];
        for (unsigned k = 0; k < 12; ++k) p[k] = k < 6 ? (uint8_t)(fp[k] >> 8) : (uint8_t)knob_now(track, k);
        /* the packer's fixed slot, not this call's cursor (the first call can still be stock FLEX) */
        volatile uint32_t *record = (volatile uint32_t *)(uintptr_t)(0x80001c90u + (ping & 1) * 0xa80u + 336u * track);
        unsigned ev = 0; uint32_t gl = 0;
        unsigned flag = U8(0x46104d0cu + track);
#ifdef KYOTI_MM_GATE
        unsigned drop = mm_drops(track);
#endif
        /* MT27: the ACC knob is the accent SCALE: its value in the Part (the knob writes it; a p-lock or an
         * LFO never does -- the live byte and the base word show a step's lock while it plays). A sequencer
         * note is accented only by its step's ACC p-lock, at lock x scale / 127; a live note by MIDI
         * velocity (at the scale) or by a lock the preview carries in fp; anything else is not. */
        volatile uint8_t *pb = (volatile uint8_t *)pp;
        unsigned acc_scale = *knob(pb, track, OT_ACC);
        acc_scale = acc_scale > 127u ? 127u : acc_scale;
        unsigned acc_lane = p[OT_ACC];
        p[OT_ACC] = acc_now[track];
        ++core_frames[track >= 4];
        if (live[track].pending && (int32_t)(ot_frames - live[track].pending) > 0) live[track].pending = 0;   /* lapsed */
        if ((flag & 16) && live[track].pending && !dsp_ready(track)) {
            live[track].armed = 1;                           /* its START came; the DSP's tables have not */
            struct ot_qn e;
            if (!(flag & 0x20)) (void)take(track, &e);
        } else if (live[track].pending && (live[track].armed || (flag & 16)) && dsp_ready(track)
#ifdef KYOTI_MM_GATE
                   && !drop                                  /* a silenced track's live note lapses unplayed */
#endif
                   ) {
            /* a live note: the knobs (with the preview's or the chromatic key's locks in fp), held */
            struct ot_qn e;
            if ((flag & 16) && !(flag & 0x20)) (void)take(track, &e);   /* a sequencer START merged into this frame */
            int32_t pt = live[track].abs ? (int32_t)live[track].note : (int32_t)p[OT_PTCH] + live[track].semis;
            pt = pt < 0 ? 0 : pt > (int32_t)OT_PTCH_MAX ? (int32_t)OT_PTCH_MAX : pt;
            p[OT_PTCH] = (uint8_t)pt;
            p[OT_ACC] = (uint8_t)(live[track].vacc ? acc_scale : acc_lane != acc_scale ? acc_amount(acc_lane, acc_scale) : 0u);
            live[track].pending = 0; live[track].armed = 0; live[track].release = 0; live[track].sounding = 1; live[track].ptch = (uint8_t)pt;
            ev = OT_EV_NOTE; gl = OT_GL_HELD;
            ++ot_live_notes;
        } else if (!(flag & 16) && live[track].release) {
            /* the key is up: the gate closes (host.asm EV bit 2 -- it never starts a note) */
            live[track].release = 0;
            if (live[track].sounding) { live[track].sounding = 0; ev = OT_EV_OFF; }
        } else if ((flag & 16) && U32(0x800065b8u) != 1) {   /* the sequencer stepping (kb memory-map) */
            ++ot_strayflags;                                 /* transport stopped: no sequencer note */
            trace(2, track, 0xfe, flag << 8 | qn[track]);
        } else if (flag & 16) {
            /* the flag is the frame builder's copy of a per-track trigger byte (0x4000c62e) that the
             * trig apply, a track start and a Part load all set; only a note step's flag plays (MT4 on
             * the unit: pattern + Part changes set it with no trig on the step, once a frame for up to
             * a second). Notes played live (track keys, MIDI) do not sound yet. */
            struct ot_qn e;
            unsigned qd = qn[track];
#ifdef KYOTI_MM_GATE
            if (drop) {
                if (take(track, &e)) ++ot_mm_drops;          /* consumed unplayed: trigs and notes stay paired */
            } else
#endif
            if (take(track, &e)) {
                ++ot_trigs;
                ev = OT_EV_NOTE | (e.slide ? OT_EV_SLIDE : 0);
                gl = e.gl;
                nt_frame[track] = ot_frames; nt_step[track] = e.step; nt_len[track] = e.len; nt_sl[track] = e.sl;
                nt_toend[track] = e.toend; nt_ptch[track] = p[OT_PTCH]; nt_gate[track] = e.gate; xt_have[track] = 0;
                p[OT_ACC] = (uint8_t)acc_amount(e.acc, acc_scale);
                live[track].sounding = 0;                    /* a sequencer note takes the voice */
                trace(2, track, e.step, (unsigned)U8(0x46104d0cu + track) << 8 | qd);
            } else {
                ++ot_strayflags;
                trace(2, track, 0xff, (unsigned)U8(0x46104d0cu + track) << 8 | qd);
            }
        }
        if (!ev && xt_have[track]) {                     /* a tie's gate across a pattern change (tie_xfer) */
            int32_t r = xt_rem[track] - (int32_t)(ot_frames - xt_frame[track]) * 16;
            xt_have[track] = 0;
            if (r < 16) ev = OT_EV_OFF;
            else { ev = OT_EV_NOTE | OT_EV_SLIDE; gl = r > 0x7ffffe ? 0x7ffffeu : (uint32_t)r; p[OT_PTCH] = nt_ptch[track]; }
            ++ot_tie_sent;
        }
        if (held && (ev & OT_EV_NOTE)) {                 /* the voice is still the higher track's: next frame */
            dfr[track].ev = (uint8_t)ev; dfr[track].gl = gl; dfr[track].acc = p[OT_ACC]; dfr[track].have = 1;
            ev = 0; gl = 0;
            ++ot_handovers;
        } else if (!held && !ev && dfr[track].have) {
            ev = dfr[track].ev; gl = dfr[track].gl; p[OT_ACC] = dfr[track].acc;
        }
        if (!held) dfr[track].have = 0;
        if (ev & OT_EV_NOTE) {
            acc_now[track] = p[OT_ACC];                   /* the sounding note's accent (its release) */
            gate_end[track] = gl >= OT_GL_HELD ? ot_frames + 0x40000000u : ot_frames + gl / 16u;
        } else if (ev & OT_EV_OFF) gate_end[track] = ot_frames;
        if (ev) { ot_evptch[ot_evn & 31] = p[OT_PTCH]; ot_evacc[ot_evn & 31] = p[OT_ACC]; ot_evlog[ot_evn++ & 31] = track << 28 | ev << 24 | (gl & 0xffffffu); }
        volatile uint16_t *amp = (volatile uint16_t *)(uintptr_t)(0x80000110u + 0x200u * (ping & 1u) + 64u * track);
        if ((amp[0x1e] & 0x10u) && (int32_t)(snd_until[track] - ot_frames) > 0) {
            unsigned m = amp[0x15] >> 8;
            if (m == 1 || m == 2) { amp[0x15] = (uint16_t)(amp[0x15] ^ 0x0100u); ++ot_amp_legato; }
            atk_until[track] = ot_frames + 24u;
        }
        if ((int32_t)(atk_until[track] - ot_frames) > 0 && amp[0] < 0x0100u) amp[0] = 0x0100u;
        {   /* the voice sounds until its gate ends plus 7 time constants of its release (2 ms / accent 50 ms) */
            uint32_t rel = p[OT_ACC] ? 960u : 40u;
            if (ev & OT_EV_NOTE) snd_until[track] = gl >= OT_GL_HELD ? ot_frames + 0x40000000u : ot_frames + gl / 16u + 2u + rel;
            else if (ev & OT_EV_OFF) snd_until[track] = ot_frames + rel;
        }
        /* MT24: CUT and ENV with the lane's fraction. The page editor slews a turned page-1 knob's base
         * value toward the new one 1/16 a frame (memory-map.md, "Page 1: the base words"), in 8.8; taking
         * only the high byte made a turn step half a semitone at a time. */
        unsigned cut_q8 = fp[OT_CUT] > 0x7f00u ? 0x7f00u : fp[OT_CUT];
        unsigned env_q8 = fp[OT_ENV] > 0x7f00u ? 0x7f00u : fp[OT_ENV];
        cut_q8 = coarse_glide(&cg[track][0], *knob(pb, track, OT_CUT), cut_q8, ev);
        env_q8 = coarse_glide(&cg[track][1], *knob(pb, track, OT_ENV), env_q8, ev);
        ot_record(record, &voice[track], p, ev, gl, cut_q8, env_q8);
    }
    U32(0x80001c80u) = (uint32_t)(uintptr_t)(cursor + 4 + 2 * n);
    return 0;
}
