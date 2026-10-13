#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
#
# OT-303 on the DSP: one payload's words and addresses (no image I/O), for either wrapper:
#   the hardware probe (tools/ot303/hwprobe.asm; tools/build_ot303_hwprobe.py, bench hwprobe_check.py)
#   the machine's host (tools/ot303/host.asm, host=True; tools/build_ot303.py, bench host_check.py)
#
# Placement (both payloads; reference/handoffs/OT303_SCOPE.md §11-12, REPITCH Session 112's census):
#   P  SPRING REV's module, its first 1,028 words (engine + wrapper, one piece); the builder moves
#      DARK REV's 35-word helper from inside it to its last 35 words (octabam ANALOG BD's layout)
#   X  SPRING's five X records, unread by stock at runtime: run 1 (3 x 72) = the engine's X block
#      and the wrapper's words, loaded ready; run 2 (116 + 384) = b0 and kp (the slopes are built)
#   Y  $7a5..$feb, never touched by stock: the tanh table at the bottom (cleared: the square is
#      cost-only in this probe), the coefficient table above $800 (octabam: absolute scratch at
#      $800 or above), the Y state block
import os, pathlib, re, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'tools' / 'ot303'))
import dsp_xasm  # noqa: E402
import asm_macros  # noqa: E402

# the private toolchain (octabam's 4 Oct 2026 dsp_asm: ALU + two parallel moves, X:R / R:Y)
NEW = ROOT / 'out' / 'ot303' / 'dsp56300_new'
dsp_xasm.DSP_ASM = NEW / 'build/source/dsp_host/dsp_asm'
dsp_xasm.DSP_DIS = NEW / 'build/source/disassemble/dsp56kDisassemble'

PAYLOAD = {
    # xd: the run-time X block sits xd words BELOW the loader's copy (hq_reloc moves it on the first
    # call). Payload A = core 0, the only core running ESAI DMA (X:$8000-$833f, boot P:$3001d); its
    # engine block moves out of that memory block to X:$3224.. (Analog BD's free region $2840-$3940).
    # DIAG13: run 1 (the engine's X working set, 216 words) runs at X:$7b24 on both cores, in stock's
    # unreferenced X:$7a92-$7fff (a partition no DMA touches); run 2 (b0/kp, read only while the
    # tables build) stays in SPRING's records. xd = the loader's copy minus the run-time address.
    'A': dict(org=0x1252, djeq_proc=0x1d7d, xd=0x0e80, seam=0x39c, cont=0x426, rawp=1,
              xrun1=((0x89a4, 72), (0x89ec, 72), (0x8a34, 72)), xrun2=((0x8afc, 116), (0x8b70, 384))),
    'B': dict(org=0x1012, djeq_proc=0x1b3d, xd=0x0940, seam=0x1a2, cont=0x221, rawp=0,
              xrun1=((0x8464, 72), (0x84ac, 72), (0x84f4, 72)), xrun2=((0x85bc, 116), (0x8630, 384))),
}
SPRING_N, DARK_N = 1063, 35     # SPRING's P module; DARK REV's helper (moved to its end)
CODE_N = SPRING_N - DARK_N
YS, TH, LT = 0xf40, 0x7a5, 0xba7  # Y: TH $7a5..$ba6 (the square's, cleared), LT $ba7..$f02, state $f40..$feb

# the riff: the Hot scene (voice_study `twin hot`), its host words at the first bar's events
HOST = dict(CS=0x000c62, C2=0x7fce80, L0_16=0x08c434, ES8=0x4e4ffe, RS=0x7fffff, AG_8=0x000000,
            BG=0x787878, SC=0x4026e7)
# the machine's level: SC (Open303's volume, the ampScaler) 0.89 = +5 dB over the riff's 0.501 -- every
# twin scene peaks below full scale (Hot -0.8 dBFS; the user found DIAG14's -6 dBFS too quiet)
SC_HOST = 0x71eb85
# MT9 (listening pack round 9, the user's picks): the soft attack, the main envelope smoothed with
# tau 1 ms (Open303's rc1), and the output drive tanh(1.68 y) (+4.5 dB into the soft clip). Since MT10
# only start values: the record rewrites both every frame (from RES and VOL, tools/ot303/cf/params.c)
import math
RC1W = round(math.exp(-1.0 / (0.001 * 44100.0)) * 8388608)
GD8 = round(1.68 / 8.0 * 8388608)
VARS = [  # C_MEG M_AMP AG8 AGFM K8
    (0x7ffc49, 0x7fff65, 0x100000, 0xffffff, 0x473333),   # accent, gate on
    (0x7ffc49, 0x7ff125, 0x100000, 0xffffff, 0x000000),   # accent, gate off
    (0x7fff81, 0x7fff65, 0x000000, 0x000000, 0x073333),   # normal, gate on
    (0x7fff81, 0x7d2153, 0x000000, 0x000000, 0x000000),   # normal, gate off
]
TRIG = (0x4001db, 0x925661, 0x40003f, 0x680c27)            # M48 hi, lo: accent, normal
AMPT = 0x40004e
SAW = (0xc00000, 0x000000, 0x000000, 0x000000)            # W1 W2 W3 SQ
SQUARE = (0x000000, 0x200000, 0xfe0078, 0x000001)
REST, ACC = 1 << 23, 1 << 22
PATTERN = [ACC | 0x184d, REST, 0x3099, REST, ACC | 0x1ce6, 0x184d, 0x2469, 0x184d,
           ACC | 0x184d, 0x2b4c, 0x184d, 0x15a6, ACC | 0x184d, REST, 0x184d, ACC | 0x2070]
STEP, GATE = 5088, 2544          # samples: a 16th at 130 BPM, 50 % gate (EVC reload is GATE)


# the machine's continuous X words, in the record's order (host.asm CDST; tools/ot303/cf/record.c)
CONT_X = ('CS', 'ES8', 'RS', 'BG', 'SC', 'SQ', 'W1', 'W1A', 'W2', 'W3', 'RC1W', 'GD8')


def yimage(T, S):
    """the machine's Y image, YBEG..YEND (host.asm): what the ColdFire streams to the DSP. The tanh
    table (value, slope pairs), the coefficient table (b0, its slope, kp/64, its slope), the state
    block (zero but the 15-tap's odd taps, twice); the rest zero. The twin's tables word for word."""
    beg, end = S['YBEG'], S['YEND']
    y = [0] * (end - beg)

    def put(a, v):
        y[a - beg] = v & 0xffffff
    th = [((v ^ 0x800000) - 0x800000) for v in T['TH']]
    assert len(th) == 513
    for i in range(513):
        put(S['TH'] + 2 * i, th[i]); put(S['TH'] + 2 * i + 1, th[i + 1] - th[i] if i < 512 else 0)
    b0 = [((v ^ 0x800000) - 0x800000) for v in T['B0']]
    kp = [((v ^ 0x800000) - 0x800000) for v in T['KP']]
    for i in range(215):
        put(S['LT'] + 4 * i, b0[i]); put(S['LT'] + 4 * i + 1, b0[i + 1] - b0[i] if i < 214 else 0)
        put(S['LT'] + 4 * i + 2, kp[i]); put(S['LT'] + 4 * i + 3, kp[i + 1] - kp[i] if i < 214 else 0)
    for i, v in enumerate(T['HB1C'] + T['HB1C']):
        put(S['HB1C'] + i, v)
    return y


def write_ytab(path):
    """the Y image as C (tools/ot303/cf/record.h: ot_ybeg, ot_ylen, ot_ytab), for the ColdFire runtime
    and the bench; both payloads' images are the same"""
    a, b = build('A', host=True), build('B', host=True)
    assert a['y'] == b['y'] and a['syms']['YBEG'] == b['syms']['YBEG']
    y = a['y']
    rows = ',\n'.join('    ' + ', '.join(f'0x{v:06x}' for v in y[i:i + 8]) for i in range(0, len(y), 8))
    pathlib.Path(path).write_text(
        '/* generated by tools/ot303/hwprobe_image.py write_ytab: the OT-303 voice\'s Y image */\n'
        '#include <stdint.h>\n'
        f'const uint32_t ot_ybeg = 0x{a["syms"]["YBEG"]:x}, ot_ylen = {len(y)};\n'
        f'const uint32_t ot_ytab[{len(y)}] = {{\n{rows}\n}};\n')
    return y


def twin_constants():
    exe = ROOT / 'out' / 'ot303' / 'twin_dump'
    src = ROOT / 'tools' / 'ot303' / 'twin_dump.cpp'
    if not exe.exists() or exe.stat().st_mtime < max(src.stat().st_mtime, (ROOT / 'tools/ot303/twin.h').stat().st_mtime):
        subprocess.run(['c++', '-std=c++17', '-O1', '-w', f'-I{ROOT}/tools/ot303', str(src), '-o', str(exe)], check=True)
    out = {}
    for line in subprocess.run([str(exe)], capture_output=True, text=True, check=True).stdout.splitlines():
        f = line.split()
        v = [int(x, 16) for x in f[1:]]
        out[f[0]] = v if len(v) > 1 else v[0]
    return out


def source(tag, host=False):
    d = PAYLOAD[tag]
    xd = d['xd']
    xb = d['xrun1'][0][0] + 0x1c - xd
    assert xb % 64 == 0 and xd % 64 == 0, f'payload {tag}: X block {xb:x} not 64-aligned'
    if xd:
        assert 0x7b08 <= xb - 0x1c and xb - 0x1c + 216 <= 0x8000, 'run 1 outside X:$7b00-$7fff'
    eng = (ROOT / 'tools/ot303/ot303_engine.asm').read_text()
    if not host:                        # the hardware probe: without MT9's soft attack and drive
        eng = re.sub(r'^(SOFTATK|ODRIVE)(\s+)macro\n.*?^\s+endm\n', r'\1\2macro\n        endm\n', eng, flags=re.M | re.S)
    wrap = (ROOT / 'tools/ot303' / ('host.asm' if host else 'hwprobe.asm')).read_text()
    lay = dict(XD=xd, NXD=(-xd) & 0xffffff, CONT=d['cont'], RAWP=d['rawp'])
    if not host:
        lay['R2'] = d['xrun2'][0][0]
    src = asm_macros.layout(eng, XB=xb, YS=YS, LT=LT, TH=TH) + asm_macros.layout(wrap, **lay)
    return src, asm_macros.yspace(eng)


def labels_ok(src):
    """dsp_asm substitutes a label inside a longer one: refuse any label that prefixes another"""
    labs = re.findall(r'^([A-Za-z_][A-Za-z0-9_]*):', src, flags=re.M)
    bad = [(a, b) for a in labs for b in labs if a != b and b.startswith(a)]
    if bad:
        raise ValueError(f'label prefixes another: {bad[:5]}')


def build(tag, host=False):
    """-> dict(org, words, syms, ysyms, p2=(addr, words), x={addr: word})"""
    d = PAYLOAD[tag]
    src, ysyms = source(tag, host)
    src = asm_macros.expand(src)
    labels_ok(src)
    words, syms = dsp_xasm.assemble(src, d['org'])
    if len(words) > CODE_N:
        raise ValueError(f'payload {tag}: {len(words)} words; SPRING\'s module leaves {CODE_N} beside DARK REV\'s helper')
    consts = {}
    for line in src.splitlines():
        m = re.match(r'^\s*([A-Za-z_][A-Za-z0-9_]*)\s+equ\s+(.+)$', line.split(';', 1)[0].rstrip())
        if m:
            consts[m.group(1)] = int(eval(m.group(2).replace('$', '0x'), {}, dict(consts)))
    S = dict(consts); S.update(syms)
    # the probe's exit branch -> DJ EQ's stock proc
    bra = S.get('hq_djeq')
    if bra is not None:
        assert words[bra - d['org']] == 0x0d10c0 and words[bra - d['org'] + 1] == 0, 'bra placeholder moved'
        words[bra - d['org'] + 1] = (d['djeq_proc'] - bra) & 0xffffff
    dis = dsp_xasm.disassemble(words, d['org'])
    # no REP: stock never uses one (a REP holds off interrupts, and the host-port handlers must
    # answer at once: DIAG2-4 on the unit tore the ColdFire transfers whenever ours ran early)
    reps = [f'P:{a:x}' for a, l in dis.items() if l[0].split()[:1] == ['rep']]
    if reps:
        raise ValueError(f'payload {tag}: REP at {reps[:6]}')
    jm = [a for a, l in dis.items() if l[0].startswith('jmp')]
    if [dis[a][0] for a in jm] != [f'jmp     func_{d["cont"]:06x}'] * len(jm) or len(jm) != 1:
        raise ValueError(f'payload {tag}: the continuation jmp disassembles as {[dis[a][0] for a in jm]}')
    line = dis.get(bra, ('',))[0] if bra is not None else None
    if line is not None and f'bra     func_{d["djeq_proc"]:06x}' not in line:
        raise ValueError(f'payload {tag}: exit branch disassembles as {line!r}')

    T = twin_constants()
    x = {}

    def X(name, v):
        a = S[name] if isinstance(name, str) else name
        assert a not in x or x[a] == v & 0xffffff, f'X:{a:x} written twice'
        x[a] = v & 0xffffff
    # the engine's X block: constants (engine_probe.cpp's list) and the Hot patch's host words
    for n in ('LMAX', 'S70', 'C437', 'HP1B', 'HP1A', 'FBB', 'FBA', 'APB', 'APA', 'HP2B', 'HP2A', 'TOPA',
              'NA1', 'NA2', 'NA3', 'NKK', 'DA1', 'DA2', 'DA3', 'DA2B'):
        X(n, T[n])
    X('MASK4', 0xfffffc); X('LTBASE', S['LT']); X('MASKF', 0x7fffff); X('SEVENF', 0x7fffff)
    X('MASKE', 0xfffffe); X('THMW', S['THM'])
    if host:
        X('RC1W', RC1W); X('GD8', GD8)
    for i, v in enumerate(T['HB2C']):
        X(S['HB2C'] + i, v)
    for n in ('CS', 'C2', 'ES8', 'RS', 'BG', 'SC'):
        X(n, SC_HOST if host and n == 'SC' else HOST[n])
    for n, v in zip(('C_MEG', 'M_AMP', 'AG8', 'AGFM', 'K8'), VARS[3]):
        X(n, v)
    for n, v in zip(('W1', 'W2', 'W3', 'SQ'), SAW):
        X(n, v)
    X('W1A', SAW[0])
    X('P_R3', S['HB1A']); X('P_R7', S['HB2A']); X('P_N2', S['HB1B']); X('P_N7', S['HB2B'])
    y = None
    if host:
        # the machine: the record's words go to the engine through two address lists; the tables
        # arrive from the ColdFire (yimage, streamed in the record), run 2 is not used
        for i, n in enumerate(CONT_X):
            X(S['CDST'] + i, S[n])
        for i, n in enumerate(('C_MEG', 'AG8', 'AGFM', 'K8')):
            X(S['NDST'] + i, S[n])
        X(S['NDST'] + 4, S['XM'] + S['D_MOFF']); X(S['NDST'] + 5, S['XM'] + S['D_EVC'])
        X(S['XM'] + S['D_EXP'], S['YBEG'])
        X(S['XM'] + S['D_EVC'], 0x7fffff)
        y = yimage(T, S)
    else:
        # the wrapper's words
        for i, v in enumerate(SAW + SQUARE):
            X(S['SAWW'] + i, v)
        X('L0C', HOST['L0_16']); X('AG8C', HOST['AG_8']); X('AMPT', AMPT)
        if 'TINC' in S:
            X('TINC', S['T110'])                                           # the probe's tone: 110 Hz
        for i, v in enumerate(T['HB1C'] + T['HB1C']):
            X(S['HB1I'] + i, v)
        for i, v in enumerate(PATTERN):
            X(S['PAT'] + i, v)
        for i, v in enumerate(w for row in VARS for w in row):
            X(S['VARS'] + i, v)
        for i, v in enumerate(TRIG):
            X(S['TRIG'] + i, v)
        # b0 and kp/64 in run 2 (one entry more each: the last slope is 0)
        b0, kp = T['B0'], T['KP']
        assert len(b0) == len(kp) == 215
        for i, v in enumerate(b0 + [b0[-1]]):
            X(S['BX'] + i, v)
        for i, v in enumerate(kp + [kp[-1]]):
            X(S['KX'] + i, v)
    # the loader's copy: run 1's words xd above their run-time addresses; run 2 in place
    r1lo = S['PB']
    x = {(a + d['xd'] if r1lo <= a < r1lo + 216 else a): v for a, v in x.items()}
    # every X word inside SPRING's five records, the rest of them zero
    runs = d['xrun1'] + d['xrun2']
    for a in x:
        assert any(r <= a < r + n for r, n in runs), f'X:{a:x} outside SPRING\'s records'
    for r, n in runs:
        for a in range(r, r + n):
            x.setdefault(a, 0)
    # the Y footprint stays in the free region
    assert TH + 1026 <= LT and LT >= 0x800 and LT + 860 <= YS and S['YS'] + 0xab <= 0x1000 and TH >= 0x7a5
    return dict(org=d['org'], words=words, syms=S, ysyms=ysyms, x=x, y=y, xd=d['xd'], djeq_proc=d['djeq_proc'],
                entry=S.get('hq_entry'), seam_entry=S['sg_entry'], seam=d['seam'], cont=d['cont'], rawp=d['rawp'])


if __name__ == '__main__':
    for tag in ('A', 'B'):
      for host in (False, True):
        b = build(tag, host)
        print('host' if host else 'probe', end=' ')
        print(f'payload {tag}: {len(b["words"])} of {CODE_N} words at P:{b["org"]:x} (to {b["org"] + len(b["words"]) - 1:x}); '
              f'DJ EQ entry P:{b["entry"] or 0:x}, seam entry P:{b["seam_entry"]:x}; X {len(b["x"])} words')
