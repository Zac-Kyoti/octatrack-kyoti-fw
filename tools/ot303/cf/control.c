/* SPDX-License-Identifier: MIT
 * SPDX-FileCopyrightText: 2026 Zac-Kyoti; registration and render ABI derived from octabam
 * modules/analog-bassdrum/control.c (repeat98, MIT), which measured the seams.
 *
 * OT-303 machine, ColdFire side: the page descriptor, the Part validator wrapper, the admission
 * rule (one OT-303 per DSP core: tracks 1-4 run on core 1, 5-8 on core 0) and the FLEX renderer
 * hook that sends an OT-303 track's control record to the DSP instead of sample data.
 * The track is stored as FLEX plus the signature 'O','T',1 in unused NEIGHBOR page bytes, so a
 * stock OS sees a FLEX track. The voice itself is DSP code (tools/ot303/host.asm).
 */
#include <stdint.h>
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

/* SRC (page 1) then SRC SETUP (page 2). Stored with the track; the DSP reads them from the record. */
const uint8_t ot_defaults[12] = {64, 64, 64, 64, 64, 64, 0, 64, 64, 64, 100, 0};
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
        text(desc + 0x3c, "SYN", 5); text(desc + 0x41, "OT-303", 13);
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
/* The FLEX renderer (kind table slot 1), ABI measured by octabam at 4000d430/4000d518: every track
 * is rendered twice per frame around its event's sample offset; the second call has end = 16.
 * An OT-303 track reserves FLEX's space (later tracks keep their record boundaries) and, once the
 * second segment exists, its record becomes the control record. The transport sends each long as
 * high/low 16-bit DSP words:
 *   w0 $3303, w2 $0909   the signature (stock w0 is the high half of a source count, 0; w2 the high
 *                        half of a bounded ring position, never $0909: octabam REVIEW.md)
 *   w3                   1 when this frame carries the track's trig (its offset is the stock x:$20c)
 *   w8..w19              the twelve knob bytes: page 1 live (p-locks, LFOs, scenes), then SETUP */
int ot_render(unsigned track, unsigned ping, unsigned start, unsigned end) {
    if (track >= 8 || !signed_track(part_base(), track))
        return ((int (*)(unsigned, unsigned, unsigned, unsigned))FLEX_RENDER)(track, ping, start, end);
    ++ot_render_calls;
    volatile uint32_t *cursor = (volatile uint32_t *)(uintptr_t)U32(0x80001c80u);
    volatile uint16_t *fp = (volatile uint16_t *)(uintptr_t)U32(0x800062a8u);
    uint8_t p[12];
    for (unsigned k = 0; k < 12; ++k)
        p[k] = k < 6 ? (uint8_t)(fp[k] >> 8) : U8(0x80000810u + 72 * track + 0x20 + k - 6);
    unsigned n = end > start && end <= 16 ? end - start : 0;
    for (unsigned i = 0; i < 4 + 2 * n; ++i) cursor[i] = 0;
    if (end == 16) {
        /* the packer's fixed slot, not this call's cursor (the first call can still be stock FLEX) */
        volatile uint32_t *record = (volatile uint32_t *)(uintptr_t)(0x80001c90u + (ping & 1) * 0xa80u + 336u * track);
        unsigned trig = (U8(0x46104d0cu + track) & 16) != 0;
        record[0] = 0x33030000u; record[1] = 0x09090000u | trig;
        record[2] = record[3] = 0;
        for (unsigned k = 0; k < 6; ++k) record[4 + k] = ((uint32_t)p[2 * k] << 16) | p[2 * k + 1];
        if (trig) ++ot_trigs;
    }
    U32(0x80001c80u) = (uint32_t)(uintptr_t)(cursor + 4 + 2 * n);
    return 0;
}
