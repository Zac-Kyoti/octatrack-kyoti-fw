#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
#
# OT-303 machine test image 1 (tools/build_ot303.py) under the firmware (ot_emu, the BOTLI project).
#   ui       panel events (transport stopped): FUNC+SRC (SRC SETUP) -> the bottom row -> YES on T2
#            makes it an OT-303 (FLEX + 'OT',1, the defaults seeded in both Part copies); with T2 an
#            OT-303, the same on T3 is refused (one per core) and leaves T3 as it was, and on T6 (core 0)
#            it lands. The page table's row 5 is our descriptor, named OT-303 with our twelve knobs.
#            (This ot_emu ignores the track keys: the current track is poked.)
#   seq      the sequencer playing, T2 and T6 made OT-303 by pokes into the loaded Part (no file
#            edited): the stopwatch over each track's source: the voice on T2 / T6 only, the other
#            tracks = stock + the glue's signature check; the ColdFire renderer ran and saw trigs; the
#            DSP started steps on them (a pcwatch at hq_start)
#   inert    no OT-303 track: every track's source = stock + the glue, the renderer never took over
#   SPRING (id 0x15) -> the passthrough stub; DARK REV (0x16) and PLATE REV (0x14) against stock
import concurrent.futures as cf, os, re, shutil, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, 'tools', 'ot303'))
import hwprobe_image  # noqa: E402

EMU = os.path.join(ROOT, 'out', 'ot303', 'ot_emu_8d0ad6f4')
CARD = os.path.join(os.path.realpath(os.path.join(ROOT, 'refs', 'octabam')), 'out', 'botli_card2.img')
IMAGE = os.path.join(ROOT, 'out', os.environ.get('MT1_IMAGE', 'mainos_ot303_mt1.bin'))
STOCK = os.path.join(ROOT, 'out', 'raw', 'section_3_MAIN_OS.bin')
ELF = os.path.join(ROOT, 'out', 'ot303', 'cf', 'ot303_cf.elf')
FRAMES = int(os.environ.get('MT1_FRAMES', '3000'))
SEQ_FRAMES = int(os.environ.get('MT1_SEQ_FRAMES', '16000'))   # BOTLI's T2/T6 trigs after step 1 (whose trigs land while the tables build)
PART = 0x40170f60                     # BOTLI's Part 1 in RAM (bank 0x400e21e0 + 0x8ed80, read under ot_emu)
SHADOW = 0x100a4ece
SRC = {1: '1:1a2:221', 0: '0:39c:426'}
FX2 = {1: '1:302:303', 0: '0:50d:50e'}
IDS = {1: 0x80000ec4, 2: 0x80000ecc}
DEFAULTS = bytes([64, 64, 64, 64, 64, 64, 0, 64, 64, 64, 100, 0])


def syms():
    out = {}
    for line in subprocess.run(['m68k-elf-nm', ELF], capture_output=True, text=True, check=True).stdout.splitlines():
        f = line.split()
        if len(f) == 3:
            out[f[2]] = int(f[0], 16)
    return out


def emu(image, extra, td):
    card = os.path.join(td, 'card.img'); shutil.copyfile(CARD, card)
    p = subprocess.run([EMU, '--image', image, '--card', card, '--set', 'OCTABAM', '--project', 'BOTLI', '--mount',
                        '--dsp', *extra], capture_output=True, text=True, timeout=7200)
    return p


def key(code, gap=600, hold=600):
    return [(gap, f'key {code:#x} down'), (hold, f'key {code:#x} up')]


def ui(S, track, pre):
    """one panel run: the current track set to `track` (this ot_emu ignores the track keys: the two
    current-track bytes are poked), `pre` OT-303 tracks poked into the Part, then FUNC+SRC (SRC SETUP)
    -> the bottom row -> YES -> NO"""
    ev = [(600, 'key 0x2d down'), (300, 'key 0x22 down'), (300, 'key 0x22 up'), (300, 'key 0x2d up')]
    for _ in range(6):
        ev += key(0x20, 250, 250)
    ev += key(0x31) + key(0x32) + [(800, 'quit')]
    with tempfile.TemporaryDirectory() as td:
        t, lines = 0, []
        for d, e in ev:
            t += d; lines.append(f'{t} {e}\n')
        evf = os.path.join(td, 'events.txt'); open(evf, 'w').writelines(lines)
        dumps = {'part': (PART, 6322), 'shadow': (SHADOW, 6322), 'page': (0x400d5f4c, 4), 'desc': (S['desc'], 458)}
        spans = ';'.join(f'{a:#x},{n}={os.path.join(td, k)}.bin' for k, (a, n) in dumps.items())
        pokes = [f'0x100b14cc={track:#x}', f'0x80000000={track:#x}'] + ot303_pokes(pre)
        p = emu(IMAGE, ['--mem-dump', spans, '--step', '-:poke:' + ';'.join(pokes), '--live-script', evf], td)
        got = {k: open(os.path.join(td, k + '.bin'), 'rb').read() for k in dumps if os.path.exists(os.path.join(td, k + '.bin'))}
        return p, got


def run(image, core, sw, pokes=(), fxslot=None, fxid=None, pcw=None, dump=None, frames=FRAMES):
    with tempfile.TemporaryDirectory() as td:
        steps = list(pokes)
        if fxslot:
            first = 0 if core == 1 else 4
            steps += [f'{IDS[fxslot] + first + i:#x}={fxid:#x}' for i in range(4)]
        args = ['--sequencer', '--internal-clock', '--frames', str(frames), '--main-level', '64', '--dsp-stopwatch', sw]
        if steps:
            args += ['--step', '-:poke:' + ';'.join(steps)] if not fxslot else ['--step', '5:poke:' + ';'.join(steps)]
        if pcw:
            args += ['--dsp-pcwatch', pcw]
        if dump:
            args += ['--mem-dump', ';'.join(f'{a:#x},{n}={os.path.join(td, k)}.bin' for k, (a, n) in dump.items())]
        p = emu(image, args, td)
        m = re.search(r'last 24:([\d ]+)', p.stdout)
        hits = 0
        sec = p.stdout.split('dsp pcwatch:', 1)
        if len(sec) == 2:
            mm = re.search(r'last (\d+) arrival', sec[1])
            hits = int(mm.group(1)) if mm else 0
        got = {k: open(os.path.join(td, k + '.bin'), 'rb').read() for k in (dump or {}) if os.path.exists(os.path.join(td, k + '.bin'))}
        return ([int(x) for x in m.group(1).split()] if m else None), p.returncode, hits, got, p.stdout


def ot303_pokes(tracks):
    out = []
    for t in tracks:
        out.append(f'{PART + 0x22 + t:#x}=1')
        for i, c in enumerate(b'OT\x01'):
            out.append(f'{PART + 60 + 30 * t + i:#x}={c:#x}')
        for k, v in enumerate(DEFAULTS):
            out.append(f'{PART + (0x2a if k < 6 else 0x1da) + 30 * t + 6 + k % 6:#x}={v:#x}')
    return out


def main():
    S = syms()
    hs = {tag: hwprobe_image.build(tag, host=True)['syms']['hq_start'] for tag in ('A', 'B')}
    counters = {'calls': (S['ot_render_calls'], 4), 'trigs': (S['ot_trigs'], 4)}
    jobs = {('ui', 'T2'): (1, ()), ('ui', 'T3'): (2, (1,)), ('ui', 'T6'): (5, (1,))}
    for core in (1, 0):
        jobs[('src-stock', core)] = (STOCK, core, SRC[core])
        jobs[('src-inert', core)] = (IMAGE, core, SRC[core], (), None, None, None, counters)
        jobs[('src-seq', core)] = (IMAGE, core, SRC[core], ot303_pokes((1, 5)), None, None,
                                   f'{core}:{hs["B" if core == 1 else "A"]:x}', counters, SEQ_FRAMES)
        jobs[('spring', core)] = (IMAGE, core, FX2[core], (), 2, 0x15)
        for name, fx in (('dark', 0x16), ('plate', 0x14)):
            jobs[(name, core)] = (IMAGE, core, FX2[core], (), 2, fx)
            jobs[(name + '-stock', core)] = (STOCK, core, FX2[core], (), 2, fx)
    with cf.ThreadPoolExecutor(len(jobs)) as ex:
        fut = {k: ex.submit(ui, S, *v) if k[0] == 'ui' else ex.submit(run, *v) for k, v in jobs.items()}
        res = {k: f.result() for k, f in fut.items()}
    ok = True
    # ---- ui
    for name, t, want in (('T2', 1, True), ('T3', 2, False), ('T6', 5, True)):
        p, got = res[('ui', name)]
        part, shadow = got.get('part', b''), got.get('shadow', b'')
        if len(part) != 6322 or len(shadow) != 6322:
            print(f'ui {name}: no Part dump (rc {p.returncode})'); ok = False; continue
        sig = part[60 + 30 * t:63 + 30 * t] == b'OT\x01' and part[0x22 + t] == 1
        sh = shadow[60 + 30 * t:63 + 30 * t] == b'OT\x01'
        kn = bytes(part[0x2a + 30 * t + 6 + k] for k in range(6)) + bytes(part[0x1da + 30 * t + 6 + k] for k in range(6))
        print(f'ui {name}: rc {p.returncode}; type {part[0x22 + t]} sig {part[60 + 30 * t:63 + 30 * t]!r} shadow {sh} knobs {list(kn)}'
              f' -> {"OT-303" if sig else "not OT-303"} (want {"OT-303" if want else "refused"})')
        ok &= sig == want and sh == want and (kn == DEFAULTS if want else True)
        ok &= p.returncode == 0 and 'ILLEGAL' not in p.stdout and 'ended on quit' in p.stdout
        if name == 'T2':
            page = int.from_bytes(got.get('page', b'\0' * 4), 'big')
            desc = got.get('desc', b'')
            names = [desc[0x4e + 6 * i:0x4e + 6 * i + 6].split(b'\0')[0].decode() for i in range(12)]
            print(f'   page row 5 0x{page:08x} (desc+0x38 0x{S["desc"] + 0x38:08x}); name {desc[0x41:0x48]!r}; knobs {names}')
            ok &= page == S['desc'] + 0x38 and desc[0x41:0x47] == b'OT-303' and names[:6] == ['PTCH', 'CUT', 'RES', 'ENV', 'DEC', 'ACC']
    # ---- sequencer
    for k, v in sorted(((k, v) for k, v in res.items() if k[0] != 'ui'), key=lambda kv: (kv[0][1], kv[0][0])):
        print(f'{k[0]:10} core {k[1]}: rc {v[1]}  last 8 {v[0][-8:] if v[0] else None}')
        ok &= v[1] == 0 and bool(v[0])
    if not ok:
        print('FAILED'); return 1

    def by_track(v):
        return [v[-24:][i::4] for i in range(4)]
    for core in (1, 0):
        print(f'core {core}:')
        s, i, q = (by_track(res[(n, core)][0]) for n in ('src-stock', 'src-inert', 'src-seq'))
        d = [[b - a for a, b in zip(x, y)] for x, y in zip(s, i)]
        print(f'   source, inert - stock per track: {d}')
        ok &= all(0 <= v <= 20 for row in d for v in row)
        print(f'   source with T2/T6 an OT-303: track 2 {q[1]}; track 1 (ages the claim) {[b - a for a, b in zip(i[0], q[0])]} '
              f'over inert; tracks 3/4 as inert {[q[k] == i[k] for k in (2, 3)]}')
        ok &= all(q[k] == i[k] for k in (2, 3)) and all(0 <= b - a <= 8 for a, b in zip(i[0], q[0])) and min(q[1]) > 3000
        c = {k: int.from_bytes(v, 'big') for k, v in res[('src-seq', core)][3].items()}
        ci = {k: int.from_bytes(v, 'big') for k, v in res[('src-inert', core)][3].items()}
        print(f'   ColdFire renderer: inert calls {ci.get("calls")} trigs {ci.get("trigs")}; with OT-303 tracks calls {c.get("calls")} '
              f'trigs {c.get("trigs")}; DSP hq_start arrivals (last-24 window) {res[("src-seq", core)][2]}')
        ok &= ci.get('calls') == 0 and c.get('calls', 0) > 0 and c.get('trigs', 0) > 0 and res[('src-seq', core)][2] > 0
        sp = res[('spring', core)][0][-4:]
        print(f'   SPRING id -> {sp} (stub ~69)')
        ok &= all(x < 200 for x in sp)
        for name in ('dark', 'plate'):
            dk, dks = res[(name, core)][0], res[(name + '-stock', core)][0]
            same = True
            for t in range(4):
                a, b = dks[t::4], dk[t::4]
                same &= (b == a) if len(set(a)) == 1 else (min(a) <= min(b) and max(b) <= max(a) + 100)
            print(f'   {name.upper()} REV {dk[-4:]} vs stock {dks[-4:]}: {"same" if same else "DIFFERS"}')
            ok &= same
    print('ALL GOOD' if ok else 'FAILED')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
