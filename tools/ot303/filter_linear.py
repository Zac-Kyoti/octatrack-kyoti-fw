#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
#
# OT-303 Phase 1, linear half: exact frequency responses of the TB-303 filter variants.
# reference/handoffs/OT303_SCOPE.md §9 "The filter study".
#
# Variants (all linear, all at fixed cutoff/resonance, so each is an LTI system and its
# response is computed exactly -- no simulation):
#   analog      the continuous-time model Open303's TB_303 mode discretises: Zavalishin's diode
#               ladder (VA Filter Design 2.1.0, eq. 5.18) with omega_c = 2 x Open303's stage
#               rate, k = 17 r, and Open303's 150 Hz one-pole high-pass in the feedback path
#   o303@N      Open303's actual per-sample update (TeeBeeFilter::getSample, TB_303 mode, with its
#               fitted b0/k/g from calculateCoefficientsApprox4) at N x 44.1 kHz. N=4 is what
#               Open303 ships; N=2/3 show what its explicit update does off its design rate
#   zdf@N       the analog model discretised trapezoidally (= TPT for this structure), omega_c
#               prewarped at the diode ladder's resonance omega_c/sqrt(2), at N x 44.1 kHz
#
# Open303 (c) 2009 Robin Schmidt, MIT -- coefficient formulas transcribed from
# rosic_TeeBeeFilter.h / rosic_OnePoleFilter.cpp @ 313bf0d9.
#
# usage: filter_linear.py [--out DIR]   (needs numpy + matplotlib)
import argparse, json, math, os
import numpy as np

FS = 44100.0
FS_O303 = 4 * FS          # the rate Open303's fitted coefficients were designed for
HP_FC = 150.0             # TeeBeeFilter feedback high-pass (Open303 constructor)


def skew(res01):
    """TeeBeeFilter::setResonance: resonanceSkewed from the 0..1 knob."""
    return (1.0 - math.exp(-3.0 * res01)) / (1.0 - math.exp(-3.0))


def o303_coeffs(fc, r, fs):
    """calculateCoefficientsApprox4, TB_303 branch. r = resonanceSkewed."""
    fc = min(max(fc, 200.0), 20000.0)
    wc = 2 * math.pi / fs * fc
    fx = wc * (1 / math.sqrt(2)) / (2 * math.pi)
    b0 = (0.00045522346 + 6.1922189 * fx) / (1.0 + 12.358354 * fx + 4.4156345 * fx * fx)
    k = fx*(fx*(fx*(fx*(fx*(fx+7198.6997)-5837.7917)-476.47308)+614.95611)+213.87126)+16.998792
    g = k * (1 / 17.0)
    g = (g - 1.0) * r + 1.0
    g = g * (1.0 + r)
    k = k * r
    return b0, k, g


def o303_step_matrices(fc, r, fs):
    """Open303's TB_303 update as an LTI step s' = A s + B u, y = C s' (state
    [y1 y2 y3 y4 hp_x1 hp_y1]); built by pushing basis vectors through the exact update."""
    b0, k, g = o303_coeffs(fc, r, fs)
    x = math.exp(-2.0 * math.pi * HP_FC / fs)
    hb0, hb1, ha1 = 0.5 * (1 + x), -0.5 * (1 + x), x

    def step(s, u):
        y1, y2, y3, y4, hx1, hy1 = s
        fbin = k * y4
        hy1 = hb0 * fbin + hb1 * hx1 + ha1 * hy1
        hx1 = fbin
        y0 = u - hy1
        y1 = y1 + 2 * b0 * (y0 - y1 + y2)
        y2 = y2 + b0 * (y1 - 2 * y2 + y3)
        y3 = y3 + b0 * (y2 - 2 * y3 + y4)
        y4 = y4 + b0 * (y3 - 2 * y4)
        return np.array([y1, y2, y3, y4, hx1, hy1])

    n = 6
    A = np.column_stack([step(np.eye(n)[i], 0.0) for i in range(n)])
    B = step(np.zeros(n), 1.0)
    C = np.zeros(n); C[3] = 2 * g
    return A, B, C


def analog_matrices(fc, r):
    """The continuous model: z' = A z + B u, y = C z, z = [y1 y2 y3 y4 l] (l = the HP's
    internal low-pass, HP out = k y4 - l). Analog limits of Open303's mapping."""
    fc = min(max(fc, 200.0), 20000.0)
    w = 0.00045522346 * FS_O303 + 6.1922189 * fc / math.sqrt(2)   # Open303 stage rate, rad/s
    wc = 2 * w                                                      # Zavalishin's omega_c
    k = 16.998792 * r
    g = ((16.998792 / 17.0 - 1.0) * r + 1.0) * (1.0 + r)
    wh = 2 * math.pi * HP_FC
    A = np.zeros((5, 5)); B = np.zeros(5)
    # y1' = wc (u - k y4 + l - y1 + y2)
    A[0, 0] = -wc; A[0, 1] = wc; A[0, 3] = -wc * k; A[0, 4] = wc; B[0] = wc
    # y2' = wc/2 (y1 - 2 y2 + y3)
    A[1, 0] = wc / 2; A[1, 1] = -wc; A[1, 2] = wc / 2
    A[2, 1] = wc / 2; A[2, 2] = -wc; A[2, 3] = wc / 2
    # y4' = wc/2 (y3 - 2 y4)
    A[3, 2] = wc / 2; A[3, 3] = -wc
    # l' = wh (k y4 - l)
    A[4, 3] = wh * k; A[4, 4] = -wh
    C = np.zeros(5); C[3] = 2 * g
    return A, B, C, wc


def h_analog(f, fc, r, prewarp_fs=None):
    """H(j w) of the analog model; with prewarp_fs, the trapezoidal/TPT discretisation at
    that rate (omega_c prewarped at the resonance), evaluated on the unit circle."""
    A, B, C, wc = analog_matrices(fc, r)
    if prewarp_fs is None:
        s = 1j * 2 * math.pi * f
    else:
        h = 1.0 / prewarp_fs
        wres = wc / math.sqrt(2)
        arg = min(wres * h / 2, 0.98 * math.pi / 2)
        p = math.tan(arg) / (wres * h / 2)
        A = A.copy(); B = B.copy()
        A[:4, :] *= p; B[:4] *= p            # every ladder integrator runs at p * omega_c
        s = 1j * (2 / h) * np.tan(math.pi * f * h)
    I = np.eye(A.shape[0])
    return np.array([C @ np.linalg.solve(si * I - A, B) for si in np.atleast_1d(s)])


def h_o303(f, fc, r, fs):
    A, B, C = o303_step_matrices(fc, r, fs)
    I = np.eye(A.shape[0])
    z = np.exp(1j * 2 * math.pi * np.atleast_1d(f) / fs)
    # y[n] = C s[n], s[n] = A s[n-1] + B u[n]  ->  H(z) = C (I - A z^-1)^-1 B
    return np.array([C @ np.linalg.solve(I - A / zi, B) for zi in z])


def peak(f, H):
    m = 20 * np.log10(np.abs(H))
    i = int(np.argmax(m))
    return f[i], m[i]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default='out/ot303/linear')
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    f = np.geomspace(20, 20000, 600)
    fcs = [200, 400, 800, 1600, 3200, 6400, 12800, 20000]
    knobs = [0.0, 0.25, 0.5, 0.75, 0.9, 1.0]
    variants = {'o303@4': ('o303', 4), 'o303@3': ('o303', 3), 'o303@2': ('o303', 2),
                'zdf@4': ('zdf', 4), 'zdf@3': ('zdf', 3), 'zdf@2': ('zdf', 2)}
    rows = []
    curves = {}
    for fc in fcs:
        for kn in knobs:
            r = skew(kn)
            Ha = h_analog(f, fc, r)
            Ho = h_o303(f, fc, r, 4 * FS)
            ref = {'analog': Ha, 'o303@4': Ho}
            curves[(fc, kn, 'analog')] = Ha
            for name, (kind, n) in variants.items():
                H = h_o303(f, fc, r, n * FS) if kind == 'o303' else h_analog(f, fc, r, n * FS)
                curves[(fc, kn, name)] = H
                stable = True
                if kind == 'o303':
                    A, _, _ = o303_step_matrices(fc, r, n * FS)
                    stable = bool(np.max(np.abs(np.linalg.eigvals(A))) < 1.0)
                row = {'fc': fc, 'knob': kn, 'variant': name, 'stable': stable}
                for rn, Hr in ref.items():
                    mh = 20 * np.log10(np.abs(H)); mr = 20 * np.log10(np.abs(Hr))
                    d = mh - mr
                    # audible window: where the reference is within 40 dB of its own peak
                    win = mr >= mr.max() - 40
                    row['maxdB_vs_' + rn] = float(np.max(np.abs(d[win])))
                    band = win & (f <= 10000)
                    row['maxdB10k_vs_' + rn] = float(np.max(np.abs(d[band]))) if band.any() else 0.0
                    if kn >= 0.5:      # a real resonance peak exists
                        pf, pm = peak(f, H); rf, rm = peak(f, Hr)
                        row['peak_cents_vs_' + rn] = float(1200 * math.log2(pf / rf))
                        row['peak_dB_vs_' + rn] = float(pm - rm)
                rows.append(row)

    with open(os.path.join(a.out, 'linear_metrics.json'), 'w') as fh:
        json.dump(rows, fh, indent=1)

    # summary table: worst deviation over the grid, per variant, vs analog and vs Open303@4x
    def w(rs, key):
        v = [abs(x[key]) for x in rs if key in x]
        return max(v) if v else 0.0
    print('worst over the grid, inside the -40 dB window (peak pitch in cents, height in dB):')
    print(f"{'variant':8} {'stable':>6} | {'vs analog: dB':>13} {'peak c':>7} {'peak dB':>7} | "
          f"{'vs o303@4: dB':>13} {'peak c':>7} {'peak dB':>7}")
    for name in variants:
        rs = [x for x in rows if x['variant'] == name]
        print(f"{name:8} {str(all(x['stable'] for x in rs)):>6} | "
              f"{w(rs,'maxdB_vs_analog'):13.2f} {w(rs,'peak_cents_vs_analog'):7.1f} "
              f"{w(rs,'peak_dB_vs_analog'):7.2f} | "
              f"{w(rs,'maxdB_vs_o303@4'):13.2f} {w(rs,'peak_cents_vs_o303@4'):7.1f} "
              f"{w(rs,'peak_dB_vs_o303@4'):7.2f}")
    print()
    print('per cutoff, worst over resonance (dB vs analog | vs o303@4):')
    print(f"{'fc':>6} " + ' '.join(f'{n:>15}' for n in variants))
    for fc in fcs:
        cells = []
        for name in variants:
            rs = [x for x in rows if x['variant'] == name and x['fc'] == fc]
            cells.append(f"{max(x['maxdB_vs_analog'] for x in rs):6.2f}|"
                         f"{max(x['maxdB_vs_o303@4'] for x in rs):6.2f}  ")
        print(f'{fc:6d} ' + ' '.join(f'{c:>15}' for c in cells))

    try:
        import matplotlib; matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        for fc in [400, 1600, 6400, 20000]:
            fig, axs = plt.subplots(1, 3, figsize=(16, 4.5), sharey=True)
            for ax, kn in zip(axs, [0.0, 0.75, 1.0]):
                for name, sty in [('analog', 'k-'), ('o303@4', 'C0-'), ('zdf@2', 'C1--'),
                                  ('zdf@3', 'C2:'), ('zdf@4', 'C3-.'), ('o303@2', 'C4:')]:
                    H = curves[(fc, kn, name)]
                    ax.semilogx(f, 20 * np.log10(np.abs(H)), sty, lw=1, label=name)
                ax.set_title(f'fc {fc} Hz, RES knob {kn}')
                ax.set_ylim(-60, 30); ax.grid(True, which='both', alpha=.3)
            axs[0].legend(); axs[0].set_ylabel('dB')
            fig.tight_layout(); fig.savefig(os.path.join(a.out, f'resp_fc{fc}.png'), dpi=110)
            plt.close(fig)
    except ImportError:
        pass


if __name__ == '__main__':
    main()
