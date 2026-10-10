#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
#
# OT-303 hardware probe: the DSP side of one payload, as words and addresses (no image I/O).
# Shared by tools/build_ot303_hwprobe.py (writes it into the firmware) and
# tools/ot303/hwprobe_check.py (runs it on dsp56kEmu against the twin).
#
# Placement (both payloads; reference/handoffs/OT303_SCOPE.md §11, REPITCH Session 112's census):
#   P  SPRING REV's module up to DARK REV's 35-word helper (engine + wrapper), and after it the
#      wrapper's step events (hwprobe_ev.asm, assembled on its own)
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
    'A': dict(org=0x1252, dark=0x1586, end=0x1679, djeq_proc=0x1d7d, xd=0,     # DIAG6/7's 0x5780 changed nothing
              xrun1=((0x89a4, 72), (0x89ec, 72), (0x8a34, 72)), xrun2=((0x8afc, 116), (0x8b70, 384))),
    'B': dict(org=0x1012, dark=0x1346, end=0x1439, djeq_proc=0x1b3d, xd=0,
              xrun1=((0x8464, 72), (0x84ac, 72), (0x84f4, 72)), xrun2=((0x85bc, 116), (0x8630, 384))),
}
DARK_N = 35
YS, TH, LT = 0xf40, 0x7a5, 0xba7  # Y: TH $7a5..$ba6 (the square's, cleared), LT $ba7..$f02, state $f40..$feb

# the riff: the Hot scene (voice_study `twin hot`), its host words at the first bar's events
HOST = dict(CS=0x000c62, C2=0x7fce80, L0_16=0x08c434, ES8=0x4e4ffe, RS=0x7fffff, AG_8=0x000000,
            BG=0x787878, SC=0x4026e7)
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


def source(tag):
    d = PAYLOAD[tag]
    xd = d['xd']
    xb = d['xrun1'][0][0] + 0x1c - xd
    assert xb % 64 == 0 and xd % 64 == 0, f'payload {tag}: X block {xb:x} not 64-aligned'
    if xd:
        assert 0x2840 <= xb - 0x1c and d['xrun2'][0][0] + 500 - xd <= 0x3940, 'outside Analog BD\'s free X region'
    eng = (ROOT / 'tools/ot303/ot303_engine.asm').read_text()
    wrap = (ROOT / 'tools/ot303/hwprobe.asm').read_text()
    src = asm_macros.layout(eng, XB=xb, YS=YS, LT=LT, TH=TH) + asm_macros.layout(wrap, R2=d['xrun2'][0][0] - xd, HQEV=d['dark'] + DARK_N,
                                                                         XD=xd, NXD=(-xd) & 0xffffff)
    equs = '\n'.join(l for l in src.splitlines() if re.match(r'^[A-Za-z_][A-Za-z0-9_]*\s+equ\s', l))
    ev = equs + '\n' + (ROOT / 'tools/ot303/hwprobe_ev.asm').read_text()
    return src, ev, asm_macros.yspace(eng)


def labels_ok(src):
    """dsp_asm substitutes a label inside a longer one: refuse any label that prefixes another"""
    labs = re.findall(r'^([A-Za-z_][A-Za-z0-9_]*):', src, flags=re.M)
    bad = [(a, b) for a in labs for b in labs if a != b and b.startswith(a)]
    if bad:
        raise ValueError(f'label prefixes another: {bad[:5]}')


def build(tag):
    """-> dict(org, words, syms, ysyms, p2=(addr, words), x={addr: word})"""
    d = PAYLOAD[tag]
    src, evsrc, ysyms = source(tag)
    src = asm_macros.expand(src)
    labels_ok(src + evsrc)
    words, syms = dsp_xasm.assemble(src, d['org'])
    ev_org = d['dark'] + DARK_N
    evw, evs = dsp_xasm.assemble(evsrc, ev_org)
    assert evs['hq_event'] == ev_org, 'hq_event is not hwprobe_ev.asm\'s first word'
    if ev_org + len(evw) > d['end']:
        raise ValueError(f'payload {tag}: the step events run past SPRING\'s module')
    if d['org'] + len(words) > d['dark']:
        raise ValueError(f'payload {tag}: {len(words)} words reach DARK REV\'s helper at P:{d["dark"]:x}')
    consts = {}
    for line in src.splitlines():
        m = re.match(r'^\s*([A-Za-z_][A-Za-z0-9_]*)\s+equ\s+(.+)$', line.split(';', 1)[0].rstrip())
        if m:
            consts[m.group(1)] = int(eval(m.group(2).replace('$', '0x'), {}, dict(consts)))
    S = dict(consts); S.update(syms)
    # the exit branch -> DJ EQ's stock proc
    bra = S['hq_djeq']
    assert words[bra - d['org']] == 0x0d10c0 and words[bra - d['org'] + 1] == 0, 'bra placeholder moved'
    words[bra - d['org'] + 1] = (d['djeq_proc'] - bra) & 0xffffff
    checks = [(bra, f'bra     func_{d["djeq_proc"]:06x}', 'exit branch')]
    for site, target in (('hq_callev', 'hq_event'), ('hq_cbr0', 'hq_burn'), ('hq_cbr1', 'hq_burn'),
                         ('hq_cmeng', 'hq_meng'), ('hq_crel', 'hq_reloc')):
        cal = S[site]
        assert words[cal - d['org']] == 0x0d1080 and words[cal - d['org'] + 1] == 0, f'{site}: bsr placeholder moved'
        if site == 'hq_crel' and not d['xd']:
            words[cal - d['org']] = 0                                       # nothing to move: two nops
            continue
        words[cal - d['org'] + 1] = (evs[target] - cal) & 0xffffff
        checks.append((cal, f'bsr     func_{evs[target]:06x}', f'{site} -> {target}'))
    # region 2's calls into region 1 (assembled apart: placeholders, patched here)
    evchecks = []
    for site, op in (('hq_cot0', 0x0d10c0), ('hq_cot1', 0x0d1080), ('hq_cot2', 0x0d1080)):
        cal = evs[site]
        assert evw[cal - ev_org] == op and evw[cal - ev_org + 1] == 0, f'{site}: placeholder moved'
        evw[cal - ev_org + 1] = (S['ot303'] - cal) & 0xffffff
        evchecks.append((cal, f'{"bra" if op == 0x0d10c0 else "bsr"}     func_{S["ot303"]:06x}', f'{site} -> ot303'))
    evdis = dsp_xasm.disassemble(evw, ev_org)
    for at, want, what in evchecks:
        if want not in evdis.get(at, ('',))[0]:
            raise ValueError(f'payload {tag}: {what} disassembles as {evdis.get(at)!r}')
    dis = dsp_xasm.disassemble(words, d['org'])
    # no REP: stock never uses one (a REP holds off interrupts, and the host-port handlers must
    # answer at once: DIAG2-4 on the unit tore the ColdFire transfers whenever ours ran early)
    for code, extra in ((dis, d['org']), (dsp_xasm.disassemble(evw, ev_org), ev_org)):
        reps = [f'P:{a:x}' for a, l in code.items() if l[0].split()[:1] == ['rep']]
        if reps:
            raise ValueError(f'payload {tag}: REP at {reps[:6]}')
    for at, want, what in checks:
        line = dis.get(at, ('',))[0]
        if want not in line:
            raise ValueError(f'payload {tag}: {what} disassembles as {line!r}')

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
    for i, v in enumerate(T['HB2C']):
        X(S['HB2C'] + i, v)
    for n in ('CS', 'C2', 'ES8', 'RS', 'BG', 'SC'):
        X(n, HOST[n])
    for n, v in zip(('C_MEG', 'M_AMP', 'AG8', 'AGFM', 'K8'), VARS[3]):
        X(n, v)
    for n, v in zip(('W1', 'W2', 'W3', 'SQ'), SAW):
        X(n, v)
    X('W1A', SAW[0])
    X('P_R3', S['HB1A']); X('P_R7', S['HB2A']); X('P_N2', S['HB1B']); X('P_N7', S['HB2B'])
    # the wrapper's words
    for i, v in enumerate(SAW + SQUARE):
        X(S['SAWW'] + i, v)
    X('L0C', HOST['L0_16']); X('AG8C', HOST['AG_8']); X('AMPT', AMPT)
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
    # the loader's copy: every word xd above its run-time address
    x = {a + d['xd']: v for a, v in x.items()}
    # every X word inside SPRING's five records, the rest of them zero
    runs = d['xrun1'] + d['xrun2']
    for a in x:
        assert any(r <= a < r + n for r, n in runs), f'X:{a:x} outside SPRING\'s records'
    for r, n in runs:
        for a in range(r, r + n):
            x.setdefault(a, 0)
    # the Y footprint stays in the free region
    assert TH + 1026 <= LT and LT >= 0x800 and LT + 860 <= YS and S['YS'] + 0xab <= 0x1000 and TH >= 0x7a5
    return dict(org=d['org'], words=words, syms=S, ysyms=ysyms, p2=(ev_org, evw), x=x, xd=d['xd'],
                djeq_proc=d['djeq_proc'], entry=S['hq_entry'])


if __name__ == '__main__':
    for tag in ('A', 'B'):
        b = build(tag)
        print(f'payload {tag}: {len(b["words"])} words at P:{b["org"]:x} (to {b["org"] + len(b["words"]) - 1:x}, '
              f'DARK REV\'s helper at {PAYLOAD[tag]["dark"]:x}); entry P:{b["entry"]:x}; '
              f'step events {len(b["p2"][1])} words at P:{b["p2"][0]:x} (module ends {PAYLOAD[tag]["end"]:x}); X {len(b["x"])} words')
