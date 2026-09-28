#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
repitch-kyoti rev 11: the "virtual sampler" engine, as a float reference model.

The ground truth the DSP code (tools/patch_repitch_dsp.asm) must match, and
the single place its tables are designed (the builder imports fir_q23() and
sp_channel_filter() and appends them to the DSP cave as data). Sources and
reasoning: reference/handoffs/REPITCH_FIDELITY_SCOPE.md; the OT-side
measurements behind the plumbing: NOTES Session 110.

  RPSP (E-mu SP-1200)   stored samples on a fixed 26.04 kHz grid; a fixed
                        26.04 kHz output clock steps through them by the pitch
                        ratio (repeat/skip: a phase accumulator); 12-bit; the
                        DAC output is a staircase; then an output channel's
                        filter (ch 5's by default).
  RPS9 (Akai S900/950)  each voice's DAC clock runs at (recording rate x ratio)
                        into a steep filter that follows that clock and removes
                        the staircase's images, so what leaves the machine is
                        the source band-limited by the RECORD filter (6th order
                        at 0.4 x FS_AKAI), stored at 12 bits, pitched cleanly.
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
    accumulator fraction so repeats/skips land on its 26.04 kHz grid; then the
    output channel's filter.

Tempo lock is untouched: the engine never changes where the OT reads.
"""
import math

import numpy as np

SR = 44100.0
FS_SP = 20e6 / 768                 # 26,041.67 Hz: E-mu's 20 MHz crystal / 768
FS_AKAI = 32000.0                  # the virtual recording rate for RPS9: bandwidth 0.4 x = 12.8 kHz
PSP = SR / FS_SP                   # 1.69344 output samples per SP tick = source frames per SP grid step
# the DSP's fixed-point copies (tools/repitch_dsp_src.py), used by the model
# when it is checked against the DSP: the tick period is Q20, the lag Q23/2
PSP_TICK = round(PSP * (1 << 20)) / (1 << 20)
PSP_LAG = round(PSP / 2 * (1 << 23)) * 2 / (1 << 23)
MODE_RPS9, MODE_RPSP = 1, 2
SP_CHANNEL = 5                     # which SP-1200 output channel's filter RPSP uses (3..6, or 7 = none)


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
PHASES = 32
FIR = {MODE_RPS9: dict(taps=16, fc=13000.0, beta=6.0),   # ~ the MF6CN-50: 6th-order Butterworth @ 0.4 x 32 kHz
       MODE_RPSP: dict(taps=8, fc=11000.0, beta=4.0)}    # ~ 4th-order @ 11 kHz (E-mu: ~42 dB/oct, < 13 kHz)


def fir_table(mode):
    """[PHASES][taps] Kaiser-windowed sinc, unity DC per phase. Row ph serves
    fractions in [ph/32, (ph+1)/32) and is designed for the middle of that
    range. Tap t reads ring frame k - c + t (k = floor(position), c = taps/2 - 1).
    Rows are mirror images: row 31-ph is row ph reversed."""
    n, fc, beta = FIR[mode]["taps"], FIR[mode]["fc"], FIR[mode]["beta"]
    c = n // 2 - 1
    tab = np.zeros((PHASES, n))
    for ph in range(PHASES):
        x = np.arange(n) - c - (ph + 0.5) / PHASES
        w = np.i0(beta * np.sqrt(np.clip(1 - (x / (n / 2)) ** 2, 0, 1))) / np.i0(beta)
        h = np.sinc(2 * fc / SR * x) * w
        tab[ph] = h / h.sum()
    return tab


def fir_q23(mode):
    """The table as the DSP holds it: Q23, each row's rounding error folded
    into its largest tap so the DC gain stays exactly 1."""
    tab = fir_table(mode)
    q = np.round(tab * (1 << 23)).astype(np.int64)
    for row in q:
        row[np.argmax(row)] += (1 << 23) - row.sum()
    return q


def design_post(mode):
    """SP: the chosen output channel's filter. Akai: none (see the header)."""
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

    def fill(self, start, frames):
        for j, fr in enumerate(frames):
            self.ring[(start + j) % self.RING] = fr

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
            acc = np.zeros(2); last = 0.0
            while self.tau < 1.0:
                u = self.tau
                acc += self.held * (u - last)
                self.phi = (self.phi + r) % 1.0
                pos = pk + pf + u * r - PSP_LAG * self.phi
                self.held = q12(self.adc(pos - self.c - 1))
                last = u
                self.tau += PSP_TICK
            acc += self.held * (1.0 - last)
            self.tau -= 1.0
            out.append(self.post(acc))       # PSP > 1: at most one tick per interval
            self.prev = (k, f)
        return np.array(out)


# ------------------------------------------------------------ DSP-exact twin
class DspExact:
    """The same engine in the DSP's integer arithmetic, bit for bit: what
    tools/repitch_dsp_engine_check.py compares the emulated DSP against. The
    float Engine above is the design; this is the implementation's contract.
    Samples are 24-bit ints (Q23); `consts` is repitch_dsp_src.constants()[0]."""
    RING = 64

    def __init__(self, mode, consts, post_words, fir_rows):
        self.mode, self.c = mode, consts
        self.ring = np.zeros((self.RING, 2), dtype=np.int64)
        self.fir = np.array(fir_rows, dtype=np.int64)          # [32][taps], Q23 signed
        self.taps = self.fir.shape[1]
        self.cc = self.taps // 2 - 1
        pw = [w - (1 << 24) if w & 0x800000 else w for w in post_words]
        self.post_c = pw
        self.post_s = np.zeros((2, 4), dtype=np.int64)
        self.tau = self.phi = 0
        self.held = np.zeros(2, dtype=np.int64)
        self.prev = None

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

    def post(self, x, ch):
        c, s = self.post_c, self.post_s[ch]
        b0, ma1 = c[0], c[1]                                  # b0 (x + x1) - a1 y1
        y = self.lim((b0 * x + b0 * s[0] + ma1 * s[1]) >> 22)
        s[0], s[1] = x, y
        x = y
        b0, ma1, ma2 = c[2:5]                                 # all-pole: b0 x - a1 y1 - a2 y2
        y = self.lim((b0 * x + ma1 * s[2] + ma2 * s[3]) >> 22)
        s[3], s[2] = s[2], y
        return y

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
                box = new + ((u * (self.held - new)) >> 23)    # old for u, new for 1 - u
                self.held = new
            else:
                self.tau -= one
                box = self.held
            out.append([self.post(int(box[0]), 0), self.post(int(box[1]), 1)])
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


if __name__ == "__main__":
    f = np.array([1e3, 5e3, 8e3, 10e3, 12.8e3, 14e3, 16e3, 18e3, 20e3])
    for ch in (3, 4, 5, 6):
        h = 20 * np.log10(np.abs(response(sp_channel_filter(ch), f)))
        print(f"SP ch{ch} post: " + " ".join(f"{x/1e3:g}k {v:+.1f}" for x, v in zip(f, h)))
    for mode in (MODE_RPS9, MODE_RPSP):
        tab = fir_table(mode); n = tab.shape[1]; c = n // 2 - 1
        for ph in (0, 15):
            x = np.arange(n) - c - (ph + 0.5) / PHASES
            h = np.abs(np.sum(tab[ph][None, :] * np.exp(-2j * np.pi * f[:, None] / SR * x[None, :]), axis=1))
            print(f"ADC mode {mode} phase {ph:2d}: " + " ".join(f"{x/1e3:g}k {v:+.1f}" for x, v in zip(f, 20 * np.log10(h))))
