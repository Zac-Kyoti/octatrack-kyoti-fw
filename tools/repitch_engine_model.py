#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
repitch-kyoti rev 13: the "virtual sampler" engine, as a float reference model.

The ground truth the DSP code (tools/patch_repitch_dsp.asm) must match, and
the single place its tables are designed (tools/repitch_dsp_src.py imports
fir_q23() and appends the tables to the DSP cave as data). Sources and
reasoning: reference/handoffs/REPITCH_FIDELITY_SCOPE.md; the OT-side
measurements behind the plumbing: NOTES Session 110; rev 12's tonal
correction and rev 13's band-limited render: NOTES Session 111.

  RPSP (E-mu SP-1200)   stored samples on a fixed 26.04 kHz grid; a fixed
                        26.04 kHz output clock steps through them by the pitch
                        ratio (repeat/skip: a phase accumulator); 12-bit; the
                        DAC output is a staircase, heard as on the raw outputs
                        7/8 (rev 12: no output filter; the ch 3-6 designs stay
                        below for a future selectable channel).
  RPS9 (Akai S900/950)  each voice's DAC clock runs at (recording rate x ratio)
                        into a steep filter that follows that clock and removes
                        the staircase's images, so what leaves the machine is
                        the source band-limited by the RECORD filter (6th order
                        at 0.4 x FS_AKAI = 16 kHz), stored at 12 bits, pitched cleanly.
                        That is what RPS9 reproduces. (Emulating the clock
                        literally at 44.1 kHz folds the staircase's ultrasonic
                        images into the audible band -- -25 dB at 18 kHz for a
                        6 kHz tone, worse pitched up -- which the real machine
                        never did.)

On the Octatrack (measured in ot_emu against the real firmware): every
16-sample frame each track's voice appends new source frames to a 64-frame
ring and renders 16 output samples in one or two passes; output i has a ring
position p_i advancing by the increment r. The engine only READS the ring:

  * the VIRTUAL ADC (fir_table): one short polyphase kernel = the machine's
    record filter + the fractional read, evaluated only where a stored sample
    is needed, read c+1 frames behind the OT so every tap is at or before the
    OT's floor(p) -- the frame after it is NOT delivered when the fraction is
    0 (the stock kernel weights it 0); reading it put stale audio into the
    last output of every frame (measured in ot_emu, Session 110);
  * RPS9: output i = 12-bit(ADC at p_i - c - 1);
  * RPSP: output i is the staircase averaged over [i-1, i) (a box: cheap, and
    it keeps a 26 kHz staircase from folding at 44.1 kHz); a tick at time
    i-1+u stores 12-bit(ADC at p_{i-1} + u*r - PSP*phi - c - 1), phi being the SP's
    accumulator fraction so repeats/skips land on its 26.04 kHz grid.
    Rev 13 renders the staircase through a BAND-LIMITED kernel (RENDER, the
    converter a real SP is recorded through) instead of rev 11/12's box, whose
    6-8 dB of rejection at 26-31 kHz let the staircase's images above 22 kHz
    fold back into the audible band. Each tick spreads its step over the next
    L outputs (a ring of residuals); the render's own passband response is
    folded out of RPSP's ADC kernel (kernel x render = the SP's record filter).

Tempo lock is untouched: the engine never changes where the OT reads.
"""
import functools
import math

import numpy as np

SR = 44100.0
FS_SP = 20e6 / 768                 # 26,041.67 Hz: E-mu's 20 MHz crystal / 768
FS_AKAI = 40000.0                  # the virtual recording rate for RPS9: bandwidth 0.4 x = 16 kHz (the S900's maximum)
PSP = SR / FS_SP                   # 1.69344 output samples per SP tick = source frames per SP grid step
# the DSP's fixed-point copies (tools/repitch_dsp_src.py), used by the model
# when it is checked against the DSP: the tick period is Q20, the lag Q23/2
PSP_TICK = round(PSP * (1 << 20)) / (1 << 20)
PSP_LAG = round(PSP / 2 * (1 << 23)) * 2 / (1 << 23)
MODE_RPS9, MODE_RPSP = 1, 2
SP_CHANNEL = 7                     # which SP-1200 output RPSP is heard on: 7 (= 8) raw, no filter.
                                   # The DSP has no output-filter stage since rev 12; 3..6 are
                                   # modelled below (sp_channel_filter) for a future selectable channel


# ---------------------------------------------------------------- filter design
def _bilinear_section(poles, gain_at_dc=True, fs=SR, warp=None):
    """Analog poles (1 real or a conjugate pair) -> digital low-pass section
    (b0, b1, b2, a1, a2), unity DC gain, all zeros at z = -1."""
    k = 2 * fs if warp is None else 2 * math.pi * warp / math.tan(math.pi * warp / fs)
    zp = [(k + p) / (k - p) for p in poles]
    if len(poles) == 1:
        a1 = -zp[0].real
        b = np.array([1.0, 1.0, 0.0]); a = np.array([1.0, a1, 0.0])
    else:
        a1 = -(zp[0] + zp[1]).real
        a2 = (zp[0] * zp[1]).real
        b = np.array([1.0, 2.0, 1.0]); a = np.array([1.0, a1, a2])
    g = a.sum() / b.sum()
    b = b * g
    return (b[0], b[1], b[2], a[1], a[2])


def butterworth(order, fc, fs=SR):
    """Low-pass Butterworth as biquads, bilinear with pre-warp at fc."""
    wc = 2 * math.pi * fc
    poles = [wc * np.exp(1j * math.pi * (2 * k + order + 1) / (2 * order)) for k in range(order)]
    secs = []
    for k in range(order // 2):
        p = poles[k]
        secs.append(_bilinear_section([p, np.conj(p)], fs=fs, warp=fc))
    if order % 2:
        secs.append(_bilinear_section([complex(-wc, 0)], fs=fs, warp=fc))
    return secs


# SP-1200 output channels 3..6: one RC pole into two unity-gain Sallen-Key
# stages (schematic SK103 p.17; tools/sp1200_filter_response.py).
SP_RC = {3: (7.5e3, 3.6e3, 6.2e3, 6.2e3, 6.2e3), 4: (6.2e3, 3.0e3, 5.1e3, 5.1e3, 5.1e3),
         5: (5.1e3, 2.4e3, 4.3e3, 4.3e3, 4.3e3), 6: (4.3e3, 2.2e3, 3.9e3, 3.9e3, 3.9e3)}


def sp_channel_poles(ch):
    """The analog filter's 5 poles, from the nodal matrix det(A(s)) = 0."""
    R1, R2, R3, R4, R5 = SP_RC[ch]
    C0, Ca, Cb, Cc, Cd = 4.7e-9, 10e-9, 1e-9, 10e-9, 1e-9

    def A(s):
        return np.array([
            [1/R1 + s*C0 + 1/R2, -1/R2, 0, 0, 0],
            [-1/R2, 1/R2 + s*Ca + 1/R3, -(s*Ca + 1/R3), 0, 0],
            [0, -1/R3, 1/R3 + s*Cb, 0, 0],
            [0, 0, -1/R4, 1/R4 + s*Cc + 1/R5, -(s*Cc + 1/R5)],
            [0, 0, 0, -1/R5, 1/R5 + s*Cd]], dtype=complex)
    # det(A(s)) is a degree-5 polynomial in s: sample it and solve for it exactly
    xs = np.array([1e4 * (k + 1) for k in range(6)], dtype=complex)
    ys = np.array([np.linalg.det(A(s)) for s in xs])
    V = np.vander(xs / 1e5, 6)
    coef = np.linalg.solve(V, ys)
    return np.roots(coef) * 1e5


def _analog_db(ch, f):
    p = sp_channel_poles(ch)
    s = 2j * math.pi * np.asarray(f)[:, None]
    return 20 * np.log10(np.abs(np.prod(-p) / np.prod(s - p, axis=1)))


def sp_channel_filter(ch=SP_CHANNEL):
    """The channel's filter as the DSP runs it: 3 poles -- one conjugate pair
    (all-pole) and one real pole with a zero at Nyquist -- fitted to the
    ANALOG 5-pole response from 0.5 to 18 kHz (ch 5: within 0.5 dB; ch 4:
    1.0; ch 6: 0.3). Close to Nyquist a digital 3-pole does what the analog
    5-pole does, and it is ~40% of the cycles. (The bilinear transform of the
    5-pole is 10 dB out at 13 kHz, so it is not used.) Deterministic grid
    search, coarse then fine."""
    if ch not in SP_RC:
        return []
    f = np.linspace(500, 18000, 80)
    target = _analog_db(ch, f)
    z = np.exp(-2j * math.pi * f / SR)

    def err(F, zeta, q):
        p = 2 * math.pi * F * complex(-zeta, math.sqrt(1 - zeta * zeta))
        zp = np.exp(p / SR)
        a1, a2 = -2 * zp.real, abs(zp) ** 2
        h = ((1 + z) / 2) / ((1 + a1 * z + a2 * z * z) * (1 - q * z)) * (1 + a1 + a2) * (1 - q)
        return np.max(np.abs(20 * np.log10(np.abs(h)) - target)), a1, a2

    best = None
    for F in np.linspace(7e3, 17e3, 41):
        for zeta in np.linspace(0.15, 0.95, 33):
            for q in np.linspace(0.0, 0.85, 35):
                e = err(F, zeta, q)[0]
                if best is None or e < best[0]:
                    best = (e, F, zeta, q)
    _, F0, z0, q0 = best
    for F in np.linspace(F0 - 250, F0 + 250, 21):
        for zeta in np.linspace(z0 - 0.025, z0 + 0.025, 11):
            for q in np.linspace(q0 - 0.025, q0 + 0.025, 11):
                e = err(F, zeta, q)[0]
                if e < best[0]:
                    best = (e, F, zeta, q)
    _, F, zeta, q = best
    _, a1, a2 = err(F, zeta, q)
    # the gentle real pole first: the resonant pair peaks ~1.7x near 10 kHz, and
    # run first its intermediate would clip at high levels before being tamed
    return [((1 - q) / 2, (1 - q) / 2, 0.0, -q, 0.0), (1 + a1 + a2, 0.0, 0.0, a1, a2)]


# The "virtual ADC": one short kernel per stored sample that is the machine's
# record filter and the fractional-position read in one. Evaluated only where a
# stored sample is needed (each 26 kHz SP tick; each RPS9 output), so its cost
# does not grow with the pitch ratio, and the ring is never modified.
#
# Rev 12: both kernels are least-squares designs (numpy only), one per
# fractional phase, each with an exact unity DC gain:
#   RPS9  16 taps fitted to the MF6CN-50's magnitude, a 6th-order Butterworth
#         at 0.4 x FS_AKAI = 16 kHz, over the whole band.
#   RPSP  12 taps: FLAT to 10 kHz, then a 7-pole (42 dB/oct, E-mu's "on the
#         order of 42 dB per octave") Butterworth shape through the transition
#         (rev 13: corner 10.95 kHz, weight 0.7 -- the overall response lands
#         within 1.5 dB of the estimated real SP out 7/8 to 15 kHz) and >= 40 dB
#         of rejection from 17.5 kHz (everything the 26 kHz grid would fold
#         into the audible band). Divided throughout by the render's passband
#         response (rev 12: the box's sinc(f/44100) droop), which the real SP
#         does not have.
# (rev 11: Kaiser-windowed sinc, 16 taps @ 13 kHz / 8 taps @ 11 kHz; RPSP's 8
# taps rolled off 2-3 dB early and the box's droop stacked on top.)
# Rev 13 stores only rows 0,2,..,14 and 15 of each table (PACKED_ROWS): the DSP
# rebuilds the odd rows 1..13 as the average of their neighbours (<= -54 dB
# from the designed rows, 0-20 kHz) and every mirror row, which frees 196 P words.
PHASES = 32
FIR = {MODE_RPS9: dict(taps=16),
       MODE_RPSP: dict(taps=12, flat=10000.0, stop=17500.0, w_trans=0.7, w_stop=30.0,
                       poles=7, corner=10950.0)}


PACKED_ROWS = (0, 2, 4, 6, 8, 10, 12, 14, 15)


def box_droop(f):
    """Rev 11/12's RPSP renderer: the staircase averaged over one 44.1 kHz
    period. Kept for comparison; rev 13 renders through RENDER."""
    return np.sinc(np.asarray(f) / SR)


# ------------------------------------------------------------ RPSP render
# The staircase's 44.1 kHz render. A kernel g over the last L output periods,
# piecewise constant in 1/R-sample pieces and symmetric (linear phase, delay
# L/2), designed by least squares on its continuous spectrum: flat to `flat`,
# rejecting from `stop` (26.04 kHz = the first staircase image of DC) up to the
# pieces' own Nyquist (R x 22.05 kHz; weight w_stop to 130 kHz, w_hi above --
# without it the pieces alternate wildly). Its running integral Gc is then
# EXACTLY piecewise linear on a 1/R grid, so a (L*R+1)-point table read with
# linear interpolation gives the exact weight at any tick time -- no timing
# jitter (a plain phase table's would be as loud as the fold it removes).
# 10 taps: 18 kHz -1.2 dB, 20 kHz -4.8, 21 kHz -7.6; everything from 26 kHz
# down >= 42 dB (the box: 6-8 dB at 26-31 kHz). Latency L/2 = 5 samples.
RENDER = dict(L=10, R=16, flat=19000.0, stop=26040.0, w_stop=30.0, w_hi=3.0, fmax=352800.0)


@functools.lru_cache(maxsize=None)
def render_kernel():
    """g: (L*R,) piece heights, sum(g)/R = 1, g symmetric."""
    L, R = RENDER["L"], RENDER["R"]
    f = np.linspace(0.0, RENDER["fmax"], 8000)
    w = 2 * math.pi * f / SR
    half = L * R // 2
    tc = (np.arange(half) + 0.5) / R - L / 2                 # piece centres, delay removed
    A = 2 * np.cos(np.outer(w, tc)) * (np.sinc(w / (2 * math.pi * R)) / R)[:, None]
    want = np.where(f <= RENDER["flat"], 1.0, 0.0)
    wt = np.where(f <= RENDER["flat"], 1.0, np.where(
        f >= RENDER["stop"], np.where(f <= 130000.0, RENDER["w_stop"], RENDER["w_hi"]), 0.0))
    Aw, Dw = A * wt[:, None], want * wt
    c = np.full(half, 2.0 / R)
    kkt = np.block([[2 * Aw.T @ Aw, c[:, None]], [c[None, :], np.zeros((1, 1))]])
    gh = np.linalg.solve(kkt, np.concatenate([2 * Aw.T @ Dw, [1.0]]))[:half]
    return np.concatenate([gh, gh[::-1]])


def render_response(f):
    """|G(f)| of the render (the continuous-time kernel g)."""
    L, R = RENDER["L"], RENDER["R"]
    g = render_kernel()
    t = (np.arange(L * R) + 0.5) / R
    w = 2 * math.pi * np.asarray(f, dtype=float) / SR
    return np.abs((np.exp(-1j * np.outer(w, t)) @ g) * np.sinc(w / (2 * math.pi * R)) / R)


def render_gc():
    """Gc[k] = the running integral of g at k/R samples, k = 0..L*R (0 .. 1)."""
    R = RENDER["R"]
    return np.concatenate([[0.0], np.cumsum(render_kernel()) / R])


def render_q23():
    """The table as the DSP holds it: T[k] = -Gc[k]/2 in Q23, k = 0..L*R, made
    exactly antisymmetric (T[LR-k] = -1/2 - T[k], Gc's own symmetry), so only
    k = 0..LR/2 is stored; and D[k] = T[k+1] - T[k]. A tick at u (0..1) gives
    tap m (output i+m) the weight -Gc(L-1-m+u) = 2 x (T + frac x D) at
    k = (L-1-m)R + floor(uR)."""
    L, R = RENDER["L"], RENDER["R"]
    n = L * R
    gc = render_gc()
    T = np.zeros(n + 1, dtype=np.int64)
    for k in range(n // 2 + 1):
        T[k] = int(round(-gc[k] / 2 * (1 << 23)))
    T[n // 2] = -(1 << 21)
    for k in range(n // 2 + 1):
        T[n - k] = -(1 << 22) - T[k]
    return T, np.diff(T)


def fir_target(mode, f):
    """What each phase of the kernel is fitted to: (desired magnitude, weight)."""
    f = np.asarray(f, dtype=float)
    if mode == MODE_RPS9:
        return 1 / np.sqrt(1 + (f / (0.4 * FS_AKAI)) ** 12), np.ones_like(f)
    d = FIR[mode]
    shape = 1 / np.sqrt(1 + (f / d["corner"]) ** (2 * d["poles"]))
    want = np.where(f <= d["flat"], 1.0, np.where(f >= d["stop"], 0.0, shape)) / render_response(f)
    w = np.where(f <= d["flat"], 1.0, np.where(f >= d["stop"], d["w_stop"], d["w_trans"]))
    return want, w


def fir_table(mode):
    """[PHASES][taps], designed by weighted least squares on a dense grid, one
    row per fractional phase, each with sum = 1 (a KKT solve). Row ph serves
    fractions in [ph/32, (ph+1)/32) and is designed for the middle of that
    range. Tap t reads ring frame k - c + t (k = floor(position), c = taps/2 - 1),
    i.e. sits at t - c - frac from the position read. Rows 16..31 are rows
    15..0 reversed (the mirror problem has the mirrored solution; building them
    that way makes the symmetry exact, which the DSP's table expansion needs)."""
    n = FIR[mode]["taps"]
    c = n // 2 - 1
    f = np.linspace(0.0, SR / 2, 1500)
    want, w = fir_target(mode, f)
    tab = np.zeros((PHASES, n))
    for ph in range(PHASES // 2):
        d = np.arange(n) - c - (ph + 0.5) / PHASES
        A = np.exp(2j * math.pi * f[:, None] / SR * d[None, :])
        Aw = np.vstack([A.real * w[:, None], A.imag * w[:, None]])
        Dw = np.concatenate([want * w, np.zeros_like(want)])
        kkt = np.block([[2 * Aw.T @ Aw, np.ones((n, 1))], [np.ones((1, n)), np.zeros((1, 1))]])
        tab[ph] = np.linalg.solve(kkt, np.concatenate([2 * Aw.T @ Dw, [1.0]]))[:n]
        tab[PHASES - 1 - ph] = tab[ph][::-1]
    return tab


def fir_response(tab, ph, f):
    """|H| of row ph at frequencies f (the fractional delay removed)."""
    n = tab.shape[1]
    d = np.arange(n) - (n // 2 - 1) - (ph + 0.5) / PHASES
    return np.abs(np.exp(2j * math.pi * np.asarray(f, dtype=float)[:, None] / SR * d[None, :]) @ tab[ph])


def fir_packed(mode):
    """The rows the DSP stores (PACKED_ROWS), Q23, each row's rounding error
    folded into its largest tap so its DC gain is exactly 1."""
    q = np.round(fir_table(mode) * (1 << 23)).astype(np.int64)
    rows = []
    for ph in PACKED_ROWS:
        row = q[ph].copy()
        row[np.argmax(row)] += (1 << 23) - row.sum()
        rows.append(row)
    return np.array(rows)


def fir_q23(mode):
    """The table as the DSP holds it after zqinit's expansion: the stored rows,
    row 31-ph = row ph reversed, and each odd row 1..13 = floor((row ph-1 +
    row ph+1) / 2), word for word, as the DSP computes it."""
    packed = fir_packed(mode)
    q = np.zeros((PHASES, packed.shape[1]), dtype=np.int64)
    for ph, row in zip(PACKED_ROWS, packed):
        q[ph], q[PHASES - 1 - ph] = row, row[::-1]
    for ph in range(1, 14, 2):
        q[ph] = (q[ph - 1] + q[ph + 1]) >> 1
        q[PHASES - 1 - ph] = q[ph][::-1]
    return q


def design_post(mode):
    """SP: the chosen output channel's filter (none for 7/8, rev 12's choice,
    and the only one the DSP implements). Akai: none (see the header)."""
    return sp_channel_filter() if mode == MODE_RPSP else []


def response(secs, f):
    z = np.exp(-2j * math.pi * np.asarray(f) / SR)
    h = np.ones_like(z)
    for b0, b1, b2, a1, a2 in secs:
        h = h * (b0 + b1 * z + b2 * z * z) / (1 + a1 * z + a2 * z * z)
    return h


# --------------------------------------------------------------------- engine
class Biquads:
    def __init__(self, secs, ch=2):
        self.secs = secs
        self.z = np.zeros((len(secs), ch, 2))           # DF2-transposed state

    def set(self, secs):
        if len(secs) != len(self.secs):
            self.z = np.zeros((len(secs), self.z.shape[1], 2))
        self.secs = secs

    def __call__(self, x):
        y = np.array(x, dtype=float)
        for k, (b0, b1, b2, a1, a2) in enumerate(self.secs):
            z = self.z[k]
            out = b0 * y + z[:, 0]
            z[:, 0] = b1 * y - a1 * out + z[:, 1]
            z[:, 1] = b2 * y - a2 * out
            y = out
        return y


def q12(v):
    """12-bit truncation, as the DSP does it: limit to the 24-bit range
    (the accumulator-to-register move saturates), then floor to 1/2048."""
    v = np.clip(np.asarray(v), -1.0, 1.0 - 2.0 ** -23)
    return np.floor(v * 2048.0) / 2048.0


class Engine:
    """One track's voice in RPS9 or RPSP. The ring holds float stereo frames
    exactly as the OT delivered them (the engine never writes it)."""
    RING = 64

    def __init__(self, mode):
        self.mode = mode
        self.ring = np.zeros((self.RING, 2))
        self.fir = fir_q23(mode) / float(1 << 23)
        self.taps = self.fir.shape[1]
        self.c = self.taps // 2 - 1
        self.post = Biquads(design_post(mode))
        self.tau = 0.0            # SP: time of the next tick from the start of the next interval
        self.phi = 0.0            # SP: accumulator fraction
        self.held = np.zeros(2)   # SP: the staircase's current step
        self.prev = None          # SP: (ring frame, fraction) of the previous output sample
        self.gc = render_gc()     # SP: the render's step response on its 1/R grid
        self.acc = np.zeros((RENDER["L"], 2))   # SP: residuals owed to the next L outputs

    def fill(self, start, frames):
        for j, fr in enumerate(frames):
            self.ring[(start + j) % self.RING] = fr

    def step_weights(self, u):
        """Tap m: -Gc(L-1-m+u), the residual a step at u leaves in output i+m."""
        L, R = RENDER["L"], RENDER["R"]
        x = (L - 1 - np.arange(L) + u) * R
        k = np.floor(x).astype(int)
        return -(self.gc[k] + (x - k) * (self.gc[k + 1] - self.gc[k]))

    def adc(self, pos):
        """The virtual ADC at ring position pos (frames, float): the record
        filter + fractional read. Needs frames floor(pos)-c .. floor(pos)+c+1.
        Callers pass pos = (OT position) - c - 1, so the newest tap is the
        OT's own floor(p), always delivered."""
        k = math.floor(pos)
        ph = min(int((pos - k) * PHASES), PHASES - 1)
        idx = [(k - self.c + t) % self.RING for t in range(self.taps)]
        return self.fir[ph] @ self.ring[idx]

    def render(self, table, r):
        """table: [(ring frame, fraction)] for this pass's output samples;
        r: the increment. Returns the pass's stereo output samples."""
        if self.mode == MODE_RPS9:
            # read c+1 frames behind the OT so every tap is at or before floor(p_i):
            # the OT does NOT deliver floor(p)+1 when the fraction is 0 (the stock
            # kernel gives it zero weight) -- measured in ot_emu, Session 110
            return np.array([q12(self.adc(k + f - self.c - 1)) for k, f in table])
        out = []
        if self.prev is not None and table and (table[0][0] - self.prev[0]) % 64 > 2:
            self.prev = table[0]          # ring positions are continuous: a jump = stale state
        for k, f in table:
            if self.prev is None:
                self.prev = (k, f)
            pk, pf = self.prev
            while self.tau < 1.0:              # PSP > 1: at most one tick per interval
                u = self.tau
                self.phi = (self.phi + r) % 1.0
                pos = pk + pf + u * r - PSP_LAG * self.phi
                new = q12(self.adc(pos - self.c - 1))
                self.acc += np.outer(self.step_weights(u), new - self.held)
                self.held = new
                self.tau += PSP_TICK
            self.tau -= 1.0
            out.append(self.post(self.held + self.acc[0]))
            self.acc = np.roll(self.acc, -1, axis=0)
            self.acc[-1] = 0.0
            self.prev = (k, f)
        return np.array(out)


# ------------------------------------------------------------ DSP-exact twin
class DspExact:
    """The same engine in the DSP's integer arithmetic, bit for bit: what
    tools/repitch_dsp_engine_check.py compares the emulated DSP against. The
    float Engine above is the design; this is the implementation's contract.
    Samples are 24-bit ints (Q23); `consts` is repitch_dsp_src.constants()[0]."""
    RING = 64

    def __init__(self, mode, consts, fir_rows):
        self.mode, self.c = mode, consts
        self.ring = np.zeros((self.RING, 2), dtype=np.int64)
        self.fir = np.array(fir_rows, dtype=np.int64)          # [32][taps], Q23 signed
        self.taps = self.fir.shape[1]
        self.cc = self.taps // 2 - 1
        self.tau = self.phi = 0
        self.held = np.zeros(2, dtype=np.int64)
        self.prev = None
        self.T, self.D = render_q23()
        self.acc = np.zeros((RENDER["L"], 2), dtype=np.int64)  # residuals / 4, Q23

    @staticmethod
    def lim(v):
        return int(min(max(v, -(1 << 23)), (1 << 23) - 1))

    def fill(self, start, frames):
        for j, fr in enumerate(frames):
            self.ring[(start + j) % self.RING] = fr

    def adc(self, first, ph):
        idx = [(first + t) % self.RING for t in range(self.taps)]
        s = self.fir[ph] @ self.ring[idx]                      # exact: sum of Q23 x Q23
        return np.array([self.lim(v >> 23) & ~0xFFF for v in s], dtype=np.int64)

    def render(self, table, rint, rfrac):
        """table: [(ring frame, fraction Q24)]; rint/rfrac: the increment as
        the DSP holds it (x:$40, y:$40 with the mode tag)."""
        c = self.c
        if self.mode == MODE_RPS9:
            out = []
            for k, f in table:
                out.append(self.adc(k - 2 * self.cc - 1, f >> 19))
            return np.array(out)
        out = []
        one = 1 << 20
        if self.prev is not None and table and (table[0][0] - self.prev[0]) % 64 > 2:
            self.prev = table[0]                               # stale state: resync
        for k, f in table:
            if self.prev is None:
                self.prev = (k, f)
            pk, pf = self.prev
            if self.tau < one:                                 # a tick at u (PSP > 1: at most one)
                u = self.tau << 3
                self.tau += c["PSPQ20"] - one
                self.phi = (self.phi + rfrac) & 0xFFFFFF
                lag = (c["PSPH"] * (self.phi >> 1) * 2) >> 22
                ur = (u * (rfrac >> 1) * 2) >> 23
                pos = (pk << 24) + pf + ur - lag + (2 * u if rint else 0) - (c["SPC2"] << 24)
                new = self.adc(pos >> 24, (pos & 0xFFFFFF) >> 19)
                dh = (new - self.held) >> 1                    # the step / 2 (exact: 12-bit values)
                self.held = new
                L, R = RENDER["L"], RENDER["R"]
                j, fr = u >> 19, (u & 0x7FFFF) << 4             # u x R: table index, fraction (Q23)
                for mm in range(L):
                    kk = (L - 1 - mm) * R + j
                    w = int(self.T[kk]) + ((int(self.D[kk]) * fr) >> 23)       # weight / 2
                    for ch in (0, 1):
                        self.acc[mm, ch] = self.lim(int(self.acc[mm, ch]) + ((w * int(dh[ch])) >> 23))
            else:
                self.tau -= one
            o = [self.lim(4 * int(self.acc[0, ch]) + int(self.held[ch])) for ch in (0, 1)]
            self.acc = np.roll(self.acc, -1, axis=0)
            self.acc[-1] = 0
            out.append(o)                                      # raw output 7/8: no filter
            self.prev = (k, f)
        return np.array(out)


# ------------------------------------------------------------ protocol driver
def run(mode, src, r, block=16):
    """Drive an Engine the way the OT does: per 16-sample frame, write the new
    source frames the pass will consume (plus the one after), then render."""
    eng = Engine(mode)
    out = []
    pos = 0.0
    written = 0
    n = len(src)
    while True:
        k0 = math.floor(pos)
        last = pos + (block - 1) * r
        need = math.floor(last) + 2                      # frames k..k+1 of the last output
        if need > n:
            break
        if need > written:
            eng.fill(written, src[written:need])
            written = need
        table = []
        for i in range(block):
            p = pos + i * r
            table.append((math.floor(p), p - math.floor(p)))
        out.append(eng.render(table, r))
        pos += block * r
    return np.concatenate(out)


# the targets rev 12 was designed to (NOTES Session 111): RPSP overall at 1/1
# should land near a real SP-1200's raw outputs 7/8 (estimated: E-mu's steep
# anti-alias filter x the 26.04 kHz staircase's droop, no output filter)
REAL_SP78 = {5e3: -0.5, 8e3: -1.5, 10e3: -3.4, 12e3: -9.4, 13e3: -14.4, 15e3: -26.4}
REPORT_F = np.array([1e3, 5e3, 8e3, 10e3, 12e3, 13e3, 14e3, 15e3, 16e3, 18e3, 20e3, 22e3])


def response_report(quantised=True):
    """The virtual-ADC responses at 1/1 against their targets, and RPSP's
    render, as printed by this module and by tools/repitch_dsp_engine_check.py.
    'worst' is the worst phase in the direction that matters (least gain in the
    passband, most in the stopband); at 1/1 RPSP's ticks visit every phase."""
    f = REPORT_F
    lines = []

    def row(label, v, fs=f):
        return f"  {label:<28}" + " ".join(f"{x/1e3:g}k {y:+6.1f}" for x, y in zip(fs, v))

    for mode, name in ((MODE_RPS9, "RPS9"), (MODE_RPSP, "RPSP")):
        tab = fir_q23(mode) / float(1 << 23) if quantised else fir_table(mode)
        db = np.array([20 * np.log10(np.maximum(fir_response(tab, ph, f), 1e-9)) for ph in range(PHASES)])
        if mode == MODE_RPS9:
            want = 20 * np.log10(fir_target(mode, f)[0])
            lines.append(f"{name}: {tab.shape[1]}-tap kernel vs the MF6CN-50 shape (6th-order Butterworth @ "
                         f"{0.4 * FS_AKAI / 1e3:g} kHz), at 1/1")
            lines.append(row("target", want))
            lines.append(row("kernel, phase 0", db[0]))
            lines.append(row("kernel, phase 15", db[15]))
            lines.append(f"  max |kernel - target| to 18 kHz, any phase: "
                         f"{np.abs(db - want)[:, f <= 18e3].max():.2f} dB")
        else:
            ren = 20 * np.log10(render_response(f))
            kb = db + ren
            zoh = 20 * np.log10(np.sinc(f / FS_SP))
            lines.append(f"{name}: render ({RENDER['L']} taps, band-limited) vs rev 12's box, and the fold "
                         f"sources it must reject (the staircase's images from 26.04 kHz up)")
            lines.append(row("render", ren))
            lines.append(row("box (rev 11/12)", 20 * np.log10(box_droop(f))))
            for lo, hi in ((26.04e3, 45e3), (45e3, 130e3)):
                g = np.linspace(lo, hi, 600)
                lines.append(f"  worst {lo/1e3:g}-{hi/1e3:g} kHz: render {20*np.log10(render_response(g)).max():6.1f} dB,"
                             f" box {20*np.log10(np.abs(box_droop(g))).max():6.1f} dB")
            lines.append(f"{name}: {tab.shape[1]}-tap kernel x render, at 1/1 (targets: >= -0.5 dB @8k, "
                         f">= -1.5 @10k, <= -40 from 18k)")
            lines.append(row("kernel x render, phase 0", kb[0]))
            lines.append(row("kernel x render, worst phase", np.where(f >= 17.5e3, kb.max(0), kb.min(0))))
            g = np.linspace(18e3, SR / 2, 200)
            rej = max(20 * np.log10(fir_response(tab, ph, g) * render_response(g)).max() for ph in range(PHASES))
            lines.append(f"  worst rejection 18-22.05 kHz, any phase: {rej:.1f} dB")
            tot = kb.mean(0) + zoh
            lines.append(f"{name} overall (kernel x render x the 26.04 kHz staircase's droop), mean of phases:")
            lines.append(row("rev 13", tot))
            rf = np.array(list(REAL_SP78))
            lines.append(row("real SP-1200 out 7/8 (est.)", list(REAL_SP78.values()), rf))
    return "\n".join(lines)


if __name__ == "__main__":
    f = np.array([1e3, 5e3, 8e3, 10e3, 12.8e3, 14e3, 16e3, 18e3, 20e3])
    for ch in (3, 4, 5, 6):
        h = 20 * np.log10(np.abs(response(sp_channel_filter(ch), f)))
        print(f"SP ch{ch} post (not used since rev 12): " + " ".join(f"{x/1e3:g}k {v:+.1f}" for x, v in zip(f, h)))
    print(response_report())
