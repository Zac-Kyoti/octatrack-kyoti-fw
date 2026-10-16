// SPDX-License-Identifier: MIT
// SPDX-FileCopyrightText: 2026 Zac Kyoti
// OT-303 first decimation stage 4x->2x (176.4 -> 88.2 kHz): 23-tap half-band (12 odd taps + centre 0.5),
// scipy remez, pass 0-22 kHz, stop from 63.1 kHz (aliases land >= 25.1 kHz, which the 79-tap stage removes).
static const int HB4_N = 23;
static const double HB4_ODD[12] = {
    -0.00034706776192091184,
    0.0025138306320679283,
    -0.010160416907524622,
    0.030554747740356641,
    -0.081984076072889919,
    0.30942153769393504,
    0.30942153769393504,
    -0.081984076072889919,
    0.030554747740356641,
    -0.010160416907524622,
    0.0025138306320679283,
    -0.00034706776192091184
};
