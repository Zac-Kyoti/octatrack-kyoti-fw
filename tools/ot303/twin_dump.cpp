// SPDX-License-Identifier: MIT
// SPDX-FileCopyrightText: 2026 Zac Kyoti
//
// OT-303: the lean engine's constants and tables from the integer twin, as "NAME hex [hex ...]" lines,
// for the builders that place the DSP engine in a firmware image (tools/ot303/hwprobe_image.py).
// The values are the ones engine_probe.cpp writes on the bench; this prints them instead.
#include <cstdio>
#include "halfband4x.h"
#include "halfband2x.h"
#include "twin.h"

static void one(const char* n, twin::W v) { std::printf("%s %06x\n", n, unsigned(v) & 0xffffff); }
static void many(const char* n, const twin::W* v, int k) {
    std::printf("%s", n);
    for (int i = 0; i < k; i++) std::printf(" %06x", unsigned(v[i]) & 0xffffff);
    std::printf("\n");
}

int main() {
    twin::Engine e;
    e.init(HB2_43_16, 22, 16000.0, HB1_15_18, 8);
    e.meg48 = true; e.inc48 = false; e.FBS = 4;
    one("LMAX", twin::q23(twin::LT_OCT / 16.0)); one("S70", e.S70); one("C437", e.C437);
    one("HP1B", e.HP1_B); one("HP1A", e.HP1_A); one("FBB", e.FB_B); one("FBA", e.FB_A);
    one("APB", e.AP_B); one("APA", e.AP_A); one("HP2B", e.HP2_B); one("HP2A", e.HP2_A); one("TOPA", e.TOP_A);
    one("NA1", e.notch.a1); one("NA2", e.notch.a2); one("NA3", e.notch.a3); one("NKK", e.notch.kk);
    one("DA1", e.decl.a1); one("DA2", e.decl.a2); one("DA3", e.decl.a3); one("DA2B", e.decl.a2);
    twin::W h1[8], h2[22];                         // odd taps, REVERSED (the branches read oldest first)
    for (int i = 0; i < 8; i++) h1[i] = e.hb4.c[7 - i];
    for (int i = 0; i < 22; i++) h2[i] = e.hb2.c[21 - i];
    many("HB1C", h1, 8); many("HB2C", h2, 22);
    many("B0", twin::T.b0, twin::LT_N + 1); many("KP", twin::T.kp, twin::LT_N + 1);
    many("TH", twin::T.th, 513);
    return 0;
}
