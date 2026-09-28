#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Frequency response of the SP-1200's fixed output filters (panel channels 3-6),
computed from the component values on E-mu's schematic "SP1200 MAIN - Output
Channels", DOC# SK103 page 17 of 18 (SP-1200 Service Manual, 1987).

    python3 tools/sp1200_filter_response.py

Topology read off the schematic (identical for CNL2..CNL5, values differ):

    in -R1-+-R2-+-R3-+ (+)TL084 follower -R4-+-R5-+ (+)TL084 follower -> out
           |    |    |       |               |    |       |
          C0   Ca---(out1)  Cb              Cc---(out2)  Cd
           |              |  |                            |
          gnd            gnd gnd                         gnd

    C0 = 4700 pF, Ca = Cc = 0.01 uF, Cb = Cd = 1000 pF.

i.e. one RC pole loading a unity-gain Sallen-Key pair, then a second
Sallen-Key pair: a 5-pole low-pass. Ideal op-amps assumed. Marked 🟡 in the
scope (REPITCH_FIDELITY_SCOPE.md): the values are the manufacturer's, the
response is our computation.
"""
import numpy as np

C0, Ca, Cb, Cc, Cd = 4.7e-9, 10e-9, 1e-9, 10e-9, 1e-9
CHANNELS = {                     # R1, R2, R3, R4, R5 (schematic refs in order)
    "ch3 (CNL2: R81 R88 R110 R95 R122)":  (7.5e3, 3.6e3, 6.2e3, 6.2e3, 6.2e3),
    "ch4 (CNL3: R80 R87 R109 R94 R121)":  (6.2e3, 3.0e3, 5.1e3, 5.1e3, 5.1e3),
    "ch5 (CNL4: R79 R86 R108 R93 R120)":  (5.1e3, 2.4e3, 4.3e3, 4.3e3, 4.3e3),
    "ch6 (CNL5: R78 R85 R107 R92 R119)":  (4.3e3, 2.2e3, 3.9e3, 3.9e3, 3.9e3),
}


def response(f, R):
    """Nodal analysis; returns out/in at frequency f."""
    R1, R2, R3, R4, R5 = R
    s = 2j * np.pi * f
    A = np.zeros((5, 5), complex)
    b = np.zeros(5, complex)
    A[0] = [1/R1 + s*C0 + 1/R2, -1/R2, 0, 0, 0];               b[0] = 1/R1
    A[1] = [-1/R2, 1/R2 + s*Ca + 1/R3, -(s*Ca + 1/R3), 0, 0]   # Ca returns from out1 = n3
    A[2] = [0, -1/R3, 1/R3 + s*Cb, 0, 0]
    A[3] = [0, 0, -1/R4, 1/R4 + s*Cc + 1/R5, -(s*Cc + 1/R5)]   # Cc returns from out2 = n5
    A[4] = [0, 0, 0, -1/R5, 1/R5 + s*Cd]
    return np.linalg.solve(A, b)[4]


def main():
    f = np.linspace(10, 30000, 30000)
    for name, R in CHANNELS.items():
        db = 20 * np.log10(np.abs([response(x, R) for x in f]))
        f3 = f[np.where(db < -3)[0][0]]
        at = lambda hz: 20 * np.log10(abs(response(hz, R)))
        print(f"{name}: -3 dB at {f3:6.0f} Hz | 10 kHz {at(1e4):+6.1f} | 13 kHz {at(13020):+6.1f}"
              f" | 20 kHz {at(2e4):+6.1f} dB | peak {db.max():+.1f} dB")


if __name__ == "__main__":
    main()
