/* SPDX-License-Identifier: MIT
 * SPDX-FileCopyrightText: 2026 Zac-Kyoti; registration and render ABI derived from octabam
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

/* SRC (page 1) then SRC SETUP (page 2), stored with the track (params.h has the ranges). Open303's
 * defaults: CUT 30 (500 Hz), RES 64, ENV 32, DEC 71 (400 ms), SLID 38 (60 ms); ACC 0 (an accent is
 * an ACC lock), GATE 63 (half a step), VOL 119 (-1 dB). */
const uint8_t ot_defaults[12] = {64, 30, 64, 32, 71, 0, 0, 64, 38, 63, 119, 0};
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
/* The stock FLEX page descriptor, renamed: twelve 0..127 knobs (an empty name hides a slot). */
static uint32_t page(void) {
    if (!ot_desc_p) {
        const volatile uint8_t *src = (const volatile uint8_t *)0x400d3176u;
        for (unsigned i = 0; i < DESC_SIZE; ++i) desc[i] = src[i];
        /* the header keeps stock's "PB" / "PLAYBACK": the page label reads PLAYBACK>OT-303 */
        for (unsigned i = 0; i < 12; ++i) {
            text(desc + 0x4e + 6 * i, ot_names[i], 6);
            desc[0x96 + i] = ot_defaults[i];
            put32(desc + 0xa2 + 4 * i, 0);
            put32(desc + 0xd2 + 4 * i, ot_names[i][0] ? 128 : 0);
            put32(desc + 0x102 + 4 * i, 0);
            put32(desc + 0x132 + 4 * i, 0);
            put32(desc + 0x162 + 4 * i, 0);
        }
        put32(desc + 0x1c2, 0x111); put32(desc + 0x1c6, 0x11111111u);   /* one nibble a knob, low first: 0-7 on, 8-10 on, 11 off */
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
static void flex_restore(volatile uint8_t *part, unsigned t) {
    const volatile uint8_t *def = (const volatile uint8_t *)FLEX_DEFAULTS;
    if (*stash(part, t, 8) != STASH_MARK) {          /* no stash (an MT1 track): stock's defaults */
        for (unsigned k = 0; k < 12; ++k) *knob(part, t, k) = def[k];
    } else {
        uint32_t acc = 0; unsigned n = 0, in = 0;
        for (unsigned k = 0; k < 12; ++k) {
            while (n < flex_bits[k]) { acc |= (uint32_t)(*stash(part, t, in++) & 0x7f) << n; n += 7; }
            *knob(part, t, k) = (uint8_t)(acc & ((1u << flex_bits[k]) - 1));
            acc >>= flex_bits[k]; n -= flex_bits[k];
        }
    }
    for (unsigned i = 0; i < 9; ++i) *stash(part, t, i) = 0;   /* NEIGHBOR's stock defaults */
}
/* machine.s's commits: sign = 1 makes track t of this Part an OT-303 (FLEX stashed, the OT-303
 * defaults seeded), 0 makes it something else (FLEX put back); both copies (the Part and its SRAM
 * mirror); nothing changes when the track already is / is not one. */
void ot_assign(volatile uint8_t *part, unsigned t, unsigned sign) {
    volatile uint8_t *copies[2] = {part, part - (U32(BANK) + PART_OFF) + SRAM_PART};
    for (unsigned c = 0; c < 2; ++c) {
        volatile uint8_t *p = copies[c], *s = p + SIG + 30 * t;
        unsigned is = s[0] == 'O' && s[1] == 'T' && s[2] == 1;
        if (sign && !is) {
            flex_stash(p, t);
            for (unsigned k = 0; k < 12; ++k) *knob(p, t, k) = ot_defaults[k];
            s[0] = 'O'; s[1] = 'T'; s[2] = 1;
        } else if (!sign && is) {
            flex_restore(p, t);
            s[0] = s[1] = s[2] = 0;
        }
    }
}
/* The main page names the current track's sample: the track box (0x4004c1c0, the UI's current track
 * 0x100b14cc) and the screen's label builder (0x4003d552, the current track 0x80000000) both call the
 * slot lookup. An OT-303 track has no sample: they get a record named OT-303. */
static const uint8_t ot_slot[32] = {0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
                                    'O', 'T', '-', '3', '0', '3', 0, 0};
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
/* The stock validator sees FLEX defaults for every OT-303 track; the twelve bytes come back after.
 * Every other Part byte is checked by stock's real validator (machine.s skips our own detour). */
extern int ot_stock_validate(void *part);
int ot_validate_part(uint8_t *part) {
    uint8_t saved[8][12]; unsigned mask = 0;
    const volatile uint8_t *stock = (const volatile uint8_t *)0x400d320cu;
    for (unsigned t = 0; t < 8; ++t) if (signed_track(part, t)) {
        mask |= 1u << t;
        for (unsigned k = 0; k < 12; ++k) {
            unsigned at = (k < 6 ? 0x2a : 0x1da) + 30 * t + 6 + k % 6;
            saved[t][k] = part[at]; part[at] = stock[k];
        }
    }
    int result = ot_stock_validate(part);
    for (unsigned t = 0; t < 8; ++t) if (mask & (1u << t))
        for (unsigned k = 0; k < 12; ++k) {
            unsigned at = (k < 6 ? 0x2a : 0x1da) + 30 * t + 6 + k % 6;
            part[at] = saved[t][k];
        }
    return result;
}
/* The sequencer (the step handler 0x4009d1e8, entered about 3 frames before its step: machine.s
 * ot_step_hook calls this first). For an OT-303 track's note step it works out the note's gate and
 * slide, held until the renderer sends the note at the trig (a trig that does not fire leaves it
 * for the next step to clear):
 *   slide  the step's slide trig: the note slides from the one before when that gate is still open
 *   gate   GATE's share of the step, plus a whole step for each trigless trig straight after (a tie);
 *          held to the end of the next step when the next step is a note with a slide trig
 * Steps: the bank's pattern masks (0x400e21e0 + bank 0x9b340 + pattern 0x8ed8 + track 0x91a: +0 trig,
 * +8 trigless, +0x48 slide; step s < 32 in the long at +4, bit s, else the long at +0, bit s - 32),
 * the length and scale of the pattern (+0x8e53/+0x8e54) or, in PER TRACK mode (+0x8e55), the
 * track's (+0x50/+0x51); ticks per step 0x400aba50[scale], tempo 0x80001814 = BPM x 24. */
struct ot_pend { uint32_t gl; uint8_t kind, slide, pad[2]; };
#define PEND_NOTE 1u
#define PEND_TIE 2u
static struct ot_pend pend[8] = {{0, 0, 0, {0, 0}}};
static struct ot_voice voice[8] = {{{0}, 0, {0}, 0}};
/* for the firmware check (tools/ot303/verify_ot303.py): note steps seen, the last step handler call
 * (track, bank, pattern, step a byte each), trig flags that came on a tie step or with no note step
 * (ignored), the last 32
 * notes sent (track << 28 | EV << 24 | gate) */
uint32_t ot_steps = 0, ot_last_step = 0, ot_evn = 0, ot_tieflags = 0, ot_strayflags = 0;
uint32_t ot_evlog[32] = {0};
uint8_t ot_evptch[32] = {0};            /* each logged note's PTCH (the step's lock, if any) */
static unsigned step_bit(uintptr_t trk, unsigned mask, unsigned s) {
    return s < 32 ? (U32(trk + mask + 4) >> s) & 1u : (U32(trk + mask) >> (s - 32)) & 1u;
}
static unsigned knob_now(unsigned track, unsigned k) {   /* SETUP's live bytes (page 1: fp, below) */
    return U8(0x80000810u + 72u * track + 0x20u + k - 6u);
}
void ot_step(unsigned track, unsigned bank, unsigned pattern, unsigned s) {
    if (track >= 8 || bank >= 16 || pattern >= 16 || s >= 64 || !signed_track(part_base(), track)) return;
    ++ot_steps;
    ot_last_step = track << 24 | bank << 16 | pattern << 8 | s;
    uintptr_t base = 0x400e21e0u + bank * 0x9b340u + pattern * 0x8ed8u, trk = base + track * 0x91au;
    unsigned len = U8(base + 0x8e53), sc = U8(base + 0x8e54);
    if (U8(base + 0x8e55)) { len = U8(trk + 0x50); sc = U8(trk + 0x51); }
    if (len < 1 || len > 64) len = 16;
    if (sc > 6) sc = 2;
    uint32_t t24 = U32(0x80001814u);
    if (t24 < 720 || t24 > 7200) t24 = 2880;
    uint32_t sl = U8(0x400aba50u + 4 * sc + 3) * 2646000u / t24;
    struct ot_pend *p = &pend[track];
    if (!step_bit(trk, 0x00, s)) {                /* no note here: nothing the next trig flag may play */
        p->kind = step_bit(trk, 0x08, s) ? PEND_TIE : 0;
        return;
    }
    unsigned count = 1, n = s, i;
    for (i = 1; i < len; ++i) {
        n = (n + 1) % len;
        if (step_bit(trk, 0x00, n) || !step_bit(trk, 0x08, n)) break;
        ++count;
    }
    unsigned hold = i < len && step_bit(trk, 0x00, n) && step_bit(trk, 0x48, n);
    uint32_t gl = hold ? (count + 1) * sl : (count - 1) * sl + ot_gate_samples(knob_now(track, OT_GATE), sl);
    p->gl = gl < 1 ? 1 : gl > 0x7ffffeu ? 0x7ffffeu : gl;
    p->slide = (uint8_t)step_bit(trk, 0x48, s);
    p->kind = PEND_NOTE;
}

/* The FLEX renderer (kind table slot 1), ABI measured by octabam at 4000d430/4000d518: every track
 * is rendered twice per frame around its event's sample offset; the second call has end = 16.
 * An OT-303 track reserves FLEX's space (later tracks keep their record boundaries) and, once the
 * second segment exists, its record becomes the control record (record.h): the signature, the
 * continuous words from the knobs (page 1 live: p-locks, LFOs, scenes; then SETUP), at a trig the
 * note (the step's pending gate and slide), and the next chunk of the voice's tables. (Stock w0 is the high half of a source
 * count, 0; w2 the high half of a bounded ring position, never $0909: octabam REVIEW.md.) */
int ot_render(unsigned track, unsigned ping, unsigned start, unsigned end) {
    if (track >= 8 || !signed_track(part_base(), track))
        return ((int (*)(unsigned, unsigned, unsigned, unsigned))FLEX_RENDER)(track, ping, start, end);
    ++ot_render_calls;
    volatile uint32_t *cursor = (volatile uint32_t *)(uintptr_t)U32(0x80001c80u);
    volatile uint16_t *fp = (volatile uint16_t *)(uintptr_t)U32(0x800062a8u);
    unsigned n = end > start && end <= 16 ? end - start : 0;
    for (unsigned i = 0; i < 4 + 2 * n; ++i) cursor[i] = 0;
    if (end == 16) {
        uint8_t p[12];
        for (unsigned k = 0; k < 12; ++k) p[k] = k < 6 ? (uint8_t)(fp[k] >> 8) : (uint8_t)knob_now(track, k);
        /* the packer's fixed slot, not this call's cursor (the first call can still be stock FLEX) */
        volatile uint32_t *record = (volatile uint32_t *)(uintptr_t)(0x80001c90u + (ping & 1) * 0xa80u + 336u * track);
        unsigned ev = 0; uint32_t gl = 0;
        if (U8(0x46104d0cu + track) & 16) {
            /* the flag is the frame builder's copy of a per-track trigger byte (0x4000c62e) that the
             * trig apply, a track start and a Part load all set; only a note step's flag plays (MT4 on
             * the unit: pattern + Part changes set it with no trig on the step, once a frame for up to
             * a second). Notes played live (track keys, MIDI) do not sound yet. */
            struct ot_pend *pd = &pend[track];
            if (pd->kind == PEND_NOTE) {
                ++ot_trigs;
                ev = OT_EV_NOTE | (pd->slide ? OT_EV_SLIDE : 0);
                gl = pd->gl;
            } else if (pd->kind == PEND_TIE) {
                ++ot_tieflags;
            } else {
                ++ot_strayflags;
            }
            pd->kind = 0;
        }
        if (ev) { ot_evptch[ot_evn & 31] = p[OT_PTCH]; ot_evlog[ot_evn++ & 31] = track << 28 | ev << 24 | (gl & 0xffffffu); }
        ot_record(record, &voice[track], p, ev, gl);
    }
    U32(0x80001c80u) = (uint32_t)(uintptr_t)(cursor + 4 + 2 * n);
    return 0;
}
