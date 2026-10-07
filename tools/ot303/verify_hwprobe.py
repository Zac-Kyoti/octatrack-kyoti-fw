#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
#
# OT-303 hardware probe under the firmware (ot_emu, the BOTLI project playing): DJ EQ on all four
# FX1 slots of a core, page 2 poked per run.
#   inert   303 = 0, BURN = 0 everywhere: per call = stock DJ EQ + the wrapper's guard
#   saw     303 = 32 on the core's second track: that track's calls grow by the engine; its audio
#           (the core's ESAI capture) carries the riff
#   square  303 = 100: the same code path at the square's cost; its output is silence (cost only)
#   SPRING (id 0x15) -> the passthrough stub; DARK REV unchanged against stock
# Instruction counts are the stopwatch's unit; the bench (hwprobe_check.py) prices cycles and checks
# the samples. ot_emu 8d0ad6f4's --audio-out capture is all zeros here, stock included: no audio check.
import concurrent.futures as cf, os, re, shutil, struct, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EMU = os.path.join(ROOT, 'out', 'ot303', 'ot_emu_8d0ad6f4')
CARD = os.path.join(os.path.realpath(os.path.join(ROOT, 'refs', 'octabam')), 'out', 'botli_card2.img')
PROBE = os.path.join(ROOT, 'out', os.environ.get('HWP_IMAGE', 'mainos_ot303_hwprobe_diag2.bin'))
STOCK = os.path.join(ROOT, 'out', 'raw', 'section_3_MAIN_OS.bin')
SW = {(1, 1): '1:2cc:2cd', (0, 1): '0:4d7:4d8', (0, 2): '0:50d:50e', (1, 2): '1:302:303'}
IDS = {1: 0x80000ec4, 2: 0x80000ecc}
LANE = lambda t, slot: 0x80000810 + 72 * t + (0x32 if slot == 1 else 0x38)    # slot 6's byte; slot 7 = +1
FRAMES = int(os.environ.get('HWP_FRAMES', '3000'))


def wav_rms(path):
    """per-slot RMS of an 8-slot capture (skipping the first quarter: the tables build, the riff starts)"""
    data = open(path, 'rb').read()
    i = data.index(b'fmt ')
    ch, bits = struct.unpack('<H', data[i + 10:i + 12])[0], struct.unpack('<H', data[i + 22:i + 24])[0]
    j = data.index(b'data'); n = struct.unpack('<I', data[j + 4:j + 8])[0]; pcm = data[j + 8:j + 8 + n]
    w = bits // 8
    frames = len(pcm) // (w * ch)
    out = []
    for c in range(ch):
        acc, cnt = 0.0, 0
        for f in range(frames // 4, frames):
            o = (f * ch + c) * w
            v = int.from_bytes(pcm[o:o + w], 'little', signed=True) / float(1 << (bits - 1))
            acc += v * v; cnt += 1
        out.append((acc / max(cnt, 1)) ** 0.5)
    return out


def run(image, core, slot, fxid, t303=None, val=0):
    first = 0 if core == 1 else 4
    pokes = [f'{IDS[slot] + first + i:#x}={fxid:#x}' for i in range(4)]
    if image == PROBE:
        pokes += [f'{LANE(first + i, slot):#x}=0' for i in range(4)] + [f'{LANE(first + i, slot) + 1:#x}=0' for i in range(4)]
    if t303 is not None:
        pokes.append(f'{LANE(t303, slot) + 1:#x}={val:#x}')
    with tempfile.TemporaryDirectory() as td:
        card = os.path.join(td, 'card.img'); shutil.copyfile(CARD, card)
        pre = os.path.join(td, 'cap')
        p = subprocess.run([EMU, '--image', image, '--card', card, '--set', 'OCTABAM', '--project',
                            'BOTLI', '--mount', '--sequencer', '--internal-clock', '--frames',
                            str(FRAMES), '--dsp', '--main-level', '64', '--dsp-stopwatch',
                            SW[(core, slot)], '--audio-out', pre, '--step', '5:poke:' + ';'.join(pokes)],
                           capture_output=True, text=True, timeout=7200)
        m = re.search(r'last 24:([\d ]+)', p.stdout)
        rms = None
        cap = f'{pre}_core{core}.wav'
        if os.path.exists(cap):
            rms = wav_rms(cap)
            if t303 is not None:
                shutil.copyfile(cap, os.path.join(ROOT, 'out', 'ot303', 'hwprobe', f'emu_core{core}_303_{val}.wav'))
        return ([int(x) for x in m.group(1).split()] if m else None), p.returncode, rms


def main():
    os.makedirs(os.path.join(ROOT, 'out', 'ot303', 'hwprobe'), exist_ok=True)
    jobs = {}
    for core in (1, 0):
        t = 1 if core == 1 else 5
        jobs[('stock', core)] = (STOCK, core, 1, 0x0d)
        jobs[('inert', core)] = (PROBE, core, 1, 0x0d)
        jobs[('saw', core)] = (PROBE, core, 1, 0x0d, t, 40)
        jobs[('square', core)] = (PROBE, core, 1, 0x0d, t, 100)
        jobs[('spring', core)] = (PROBE, core, 2, 0x15)
        jobs[('dark', core)] = (PROBE, core, 2, 0x16)
        jobs[('dark-stock', core)] = (STOCK, core, 2, 0x16)
    with cf.ThreadPoolExecutor(len(jobs)) as ex:
        res = dict(zip(jobs, ex.map(lambda a: run(*a), jobs.values())))
    ok = True
    for k, (last, rc, rms) in sorted(res.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        print(f'{k[0]:10} core {k[1]}: rc {rc}  last 4 calls {last[-4:] if last else None}  '
              f'rms {[round(r, 4) for r in rms] if rms else None}')
        ok &= rc == 0 and bool(last)
    for core in (1, 0):
        s, i = res[('stock', core)][0][-4:], res[('inert', core)][0][-4:]
        print(f'core {core}: inert overhead per call {[b - a for a, b in zip(s, i)]}')
        ok &= all(0 <= b - a <= 12 for a, b in zip(s, i))
        for v in ('saw', 'square'):
            e = res[(v, core)][0][-4:]
            print(f'   {v:6}: extra per call {[b - a for a, b in zip(i, e)]} (the engine, DJ EQ bypassed, on the 2nd track only)')
            ok &= e[1] != i[1] and all(e[k] == i[k] for k in (0, 2, 3))
        sp = res[('spring', core)][0][-4:]
        dk, dks = res[('dark', core)][0], res[('dark-stock', core)][0]
        # DARK REV's work on a track with signal varies call to call (stock alike: 3207..3277 seen);
        # a track whose 6 stock calls are all equal must match exactly, the others stay in range
        same = True
        for t in range(4):
            a, b = dks[t::4], dk[t::4]
            same &= (b == a) if len(set(a)) == 1 else (min(a) <= min(b) and max(b) <= max(a) + 100)
        print(f'   SPRING id -> {sp} (stub ~69)   DARK REV {dk[-4:]} vs stock {dks[-4:]}: {"same" if same else "DIFFERS"}')
        ok &= all(x < 200 for x in sp) and same
    print('ALL GOOD' if ok else 'FAILED')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
