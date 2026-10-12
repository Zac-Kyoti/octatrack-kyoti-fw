#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
#
# OT-303 machine test image (tools/build_ot303.py, MT5) under the firmware (ot_emu, the BOTLI project).
#   ui       panel events (transport stopped): FUNC+SRC (SRC SETUP) -> the bottom row -> YES on T2
#            makes it an OT-303 (FLEX + 'OT',1, the defaults seeded in both Part copies); with T2 an
#            OT-303, the same on T3 is refused (one per core) and leaves T3 as it was, and on T6 (core 0)
#            it lands. The page table's row 5 is our descriptor, named OT-303 with our twelve knobs.
#            (This ot_emu ignores the track keys: the current track is poked.)
#   flex     the round trip through the panel: T2 -> OT-303 -> back (SRC SETUP, four rows up, YES)
#            leaves both Part copies byte for byte as stock had them (FLEX's twelve values stashed and
#            put back, the stash and the signature cleared); the page's label is stock's PB / PLAYBACK
#   seq      the sequencer playing, T2 and T6 made OT-303 and given a test line by pokes into the
#            loaded Part and pattern (no file edited): notes, a tie (trigless trig), a note held into
#            a slide, a slide after a rest, a tied slide. The stopwatch over each track's source: the
#            voice on T2 / T6 only, the other tracks = stock + the glue's signature check. The step
#            hook ran; every note the renderer sent (its event log) has the gate, slide and PTCH
#            (two steps carry PTCH locks) the line implies at the emulator's tempo; the DSP started notes (a pcwatch at hq_start); the voice's
#            Y image arrived through the records word for word on both cores (a --dsp-peek of it
#            against tools/ot303/hwprobe_image.py yimage) and the voice runs (STG 2)
#   inert    no OT-303 track: every track's source = stock + the glue, the renderer never took over
#   dram     the DRAM runtime (tools/ot303/dram.py): the appended loader runs once from the boot site and
#            never reaches its hang; after boot, project load and play the reserve's code and constants
#            equal the linked runtime; every write into the reserve comes from the runtime itself
#   SPRING (id 0x15) -> the passthrough stub; DARK REV (0x16) and PLATE REV (0x14) against stock
import concurrent.futures as cf, os, re, shutil, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, 'tools', 'ot303'))
import hwprobe_image  # noqa: E402
import dram  # noqa: E402

EMU = os.path.join(ROOT, 'out', 'ot303', 'ot_emu_8d0ad6f4')
CARD = os.path.join(os.path.realpath(os.path.join(ROOT, 'refs', 'octabam')), 'out', 'botli_card2.img')
IMAGE = os.path.join(ROOT, 'out', os.environ.get('OT303_IMAGE', 'mainos_ot303_mt6.bin'))
STOCK = os.path.join(ROOT, 'out', 'raw', 'section_3_MAIN_OS.bin')
ELF = os.path.join(ROOT, 'out', 'ot303', 'cf', 'ot303_runtime.elf')
LOADER = os.path.join(ROOT, 'out', 'ot303', 'cf', 'loader.elf')
RUNTIME = os.path.join(ROOT, 'out', 'ot303', 'cf', 'ot303_runtime.bin')
FRAMES = int(os.environ.get('MT1_FRAMES', '3000'))
SEQ_FRAMES = int(os.environ.get('MT1_SEQ_FRAMES', '16000'))   # BOTLI's T2/T6 trigs after step 1 (whose trigs land while the tables build)
PART = 0x40170f60                     # BOTLI's Part 1 in RAM (bank 0x400e21e0 + 0x8ed80, read under ot_emu)
SHADOW = 0x100a4ece
SRC = {1: '1:1a2:221', 0: '0:39c:426'}
FX2 = {1: '1:302:303', 0: '0:50d:50e'}
IDS = {1: 0x80000ec4, 2: 0x80000ecc}
DEFAULTS = bytes([64, 30, 64, 32, 71, 0, 0, 64, 38, 63, 119, 0])
BANK0 = 0x400e21e0                    # BOTLI plays bank 0, pattern 0 (PER TRACK scale; T2/T6: 16 steps, 1x)
# the test line, steps 0..15: N note, T trigless trig (a tie), S note with a slide trig, . empty
LINE = 'NTNS.SNST...N...'
LOCKS = {2: 76, 6: 52}                # PTCH locks on two of its notes (the pattern's p-lock records, TRAC + 0x59)
# T2's line: every step a note, each with its own PTCH lock, and a trig condition that never fires in
# play (FILL, code 1: the trig word TRAC + 0x89a + 2 step, low byte) on two of them -- the notes must
# come in order and skip exactly those (MT5 on the unit dropped step 2 of a full bar every other bar)
LINE2 = 'N' * 16
LOCKS2 = {s: 40 + s for s in range(16)}
CONDS2 = {4: 1, 10: 1}



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


def ui(S, track, pre, back=False, image=None):
    """one panel run: the current track set to `track` (this ot_emu ignores the track keys: the two
    current-track bytes are poked), `pre` OT-303 tracks poked into the Part, then FUNC+SRC (SRC SETUP)
    -> the bottom row -> YES -> NO"""
    ev = [(600, 'key 0x2d down'), (300, 'key 0x22 down'), (300, 'key 0x22 up'), (300, 'key 0x2d up')]
    for _ in range(6):
        ev += key(0x20, 250, 250)
    ev += key(0x31) + key(0x32)
    if back:                                         # again, up four rows to FLEX, YES
        ev += [(600, 'key 0x2d down'), (300, 'key 0x22 down'), (300, 'key 0x22 up'), (300, 'key 0x2d up')]
        for _ in range(4):
            ev += key(0x33, 250, 250)
        ev += key(0x31) + key(0x32)
    if image is not None:                            # the stock image: no panel events, the Part as loaded
        ev = []
    ev += [(800, 'quit')]
    with tempfile.TemporaryDirectory() as td:
        t, lines = 0, []
        for d, e in ev:
            t += d; lines.append(f'{t} {e}\n')
        evf = os.path.join(td, 'events.txt'); open(evf, 'w').writelines(lines)
        dumps = {'part': (PART, 6322), 'shadow': (SHADOW, 6322)}
        if image is None:
            dumps.update(page=(0x400d5f4c, 4), desc=(S['desc'], 458))
        spans = ';'.join(f'{a:#x},{n}={os.path.join(td, k)}.bin' for k, (a, n) in dumps.items())
        pokes = [f'0x100b14cc={track:#x}', f'0x80000000={track:#x}'] + ot303_pokes(pre)
        p = emu(image or IMAGE, ['--mem-dump', spans, '--step', '-:poke:' + ';'.join(pokes), '--live-script', evf], td)
        got = {k: open(os.path.join(td, k + '.bin'), 'rb').read() for k in dumps if os.path.exists(os.path.join(td, k + '.bin'))}
        return p, got


def run(image, core, sw, pokes=(), fxslot=None, fxid=None, pcw=None, dump=None, frames=FRAMES, peek=None):
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
        if peek:
            args += ['--dsp-peek', peek]
        p = emu(image, args, td)
        m = re.search(r'last 24:([\d ]+)', p.stdout)
        hits = 0
        sec = p.stdout.split('dsp pcwatch:', 1)
        if len(sec) == 2:
            mm = re.search(r'last (\d+) arrival', sec[1])
            hits = int(mm.group(1)) if mm else 0
        got = {k: open(os.path.join(td, k + '.bin'), 'rb').read() for k in (dump or {}) if os.path.exists(os.path.join(td, k + '.bin'))}
        return ([int(x) for x in m.group(1).split()] if m else None), p.returncode, hits, got, p.stdout


def dram_audit():
    sym = {}
    for line in subprocess.run(['m68k-elf-nm', LOADER], capture_output=True, text=True, check=True).stdout.splitlines():
        f = line.split()
        if len(f) == 3:
            sym[f[2]] = int(f[0], 16)
    blob = open(RUNTIME, 'rb').read()
    lo = dram.RESERVE
    with tempfile.TemporaryDirectory() as td:
        p = emu(IMAGE, ['--sequencer', '--internal-clock', '--frames', str(FRAMES), '--watch-pc',
                        f'{sym["ot_loader"]:#x},{sym["fatal"]:#x}', '--watch-mem', f'{lo:#x},0x18000',
                        '--mem-dump', f'{lo:#x},{len(blob)}={td}/reserve.bin'], td)
        got = open(f'{td}/reserve.bin', 'rb').read() if os.path.exists(f'{td}/reserve.bin') else b''
    hits = re.findall(r'\] at (0x[0-9a-f]+) ', p.stdout)
    pcs = [int(x, 16) for x in re.findall(r'<- .* at pc (0x[0-9a-f]+)', p.stdout)]
    return p, hits, pcs, got, blob, lo


def ot303_pokes(tracks):
    out = []
    for t in tracks:
        out.append(f'{PART + 0x22 + t:#x}=1')
        for i, c in enumerate(b'OT\x01'):
            out.append(f'{PART + 60 + 30 * t + i:#x}={c:#x}')
        for k, v in enumerate(DEFAULTS):
            out.append(f'{PART + (0x2a if k < 6 else 0x1da) + 30 * t + 6 + k % 6:#x}={v:#x}')
            if k >= 6:                               # SETUP's live bytes (the step hook reads GATE there)
                out.append(f'{0x80000810 + 72 * t + 0x20 + k - 6:#x}={v:#x}')
    return out


def line_pokes(tracks, line=LINE, locks=LOCKS, conds={}):
    """a test line into bank 0 pattern 0: steps 0..31 in the masks' second long (trig +4,
    trigless +0xc, slide +0x4c), PTCH locks, trig conditions"""
    m = {0x04: 0, 0x0c: 0, 0x4c: 0}
    for s, c in enumerate(line):
        m[0x04] |= (c in 'NS') << s
        m[0x0c] |= (c == 'T') << s
        m[0x4c] |= (c == 'S') << s
    out = []
    for t in tracks:
        for off, v in m.items():
            for i, b in enumerate(v.to_bytes(4, 'big')):
                out.append(f'{BANK0 + t * 0x91a + off + i:#x}={b:#x}')
        for s, v in locks.items():               # p-lock record[step][param], PTCH = param 0
            out.append(f'{BANK0 + t * 0x91a + 0x59 + 32 * s:#x}={v:#x}')
        for s, v in conds.items():
            out.append(f'{BANK0 + t * 0x91a + 0x89a + 2 * s + 1:#x}={v:#x}')
    return out


def line_events(steplen, gate, line=LINE, locks=LOCKS, conds={}):
    """the (EV, gate, PTCH) each note of a line sends (control.c ot_note): ties extend by whole steps, a
    note before a slide trig is held to the end of the next step; a FILL step does not play"""
    out = []
    gs = steplen * (gate + 1) >> 7
    LINE = line
    for s, c in enumerate(LINE):
        if c not in 'NS' or s in conds:
            continue
        count, n = 1, s
        for _ in range(1, 16):
            n = (n + 1) % 16
            if LINE[n] != 'T':
                break
            count += 1
        hold = LINE[n] == 'S'
        out.append((1 | (2 if c == 'S' else 0), (count + 1) * steplen if hold else (count - 1) * steplen + gs,
                    locks.get(s, DEFAULTS[0])))
    return out


def main():
    S = syms()
    hs = {tag: hwprobe_image.build(tag, host=True)['syms']['hq_start'] for tag in ('A', 'B')}
    counters = {'calls': (S['ot_render_calls'], 4), 'trigs': (S['ot_trigs'], 4)}
    seqdump = dict(counters, steps=(S['ot_steps'], 4), evn=(S['ot_evn'], 4), evlog=(S['ot_evlog'], 128),
                   evptch=(S['ot_evptch'], 32), clears=(S['ot_qclears'], 4), drops=(S['ot_qdrops'], 4), stray=(S['ot_strayflags'], 4), tempo=(0x80001814, 4))
    hb = {tag: hwprobe_image.build(tag, host=True) for tag in ('A', 'B')}
    yimg = hb['A']['y']
    ys = hb['A']['syms']
    stg = ys['XM'] + ys['D_STG']
    assert all(hb['B']['syms'][k] == ys[k] for k in ('XM', 'D_STG', 'YBEG', 'CB', 'CHH', 'HB1C')) and hb['B']['y'] == yimg
    peek = ';'.join(f'{c}:Y:{ys["YBEG"]:#x},{len(yimg)};{c}:X:{stg:#x},4' for c in (1, 0))
    jobs = {('ui', 'T2'): (1, ()), ('ui', 'T3'): (2, (1,)), ('ui', 'T6'): (5, (1,)),
            ('ui', 'back'): (1, (), True), ('ui', 'stock'): (1, (), False, STOCK), ('dram', ''): None}
    for core in (1, 0):
        jobs[('src-stock', core)] = (STOCK, core, SRC[core])
        jobs[('src-inert', core)] = (IMAGE, core, SRC[core], (), None, None, None, counters)
        jobs[('src-seq', core)] = (IMAGE, core, SRC[core], ot303_pokes((1, 5)) + line_pokes((5,)) + line_pokes((1,), LINE2, LOCKS2, CONDS2), None, None,
                                   f'{core}:{hs["B" if core == 1 else "A"]:x}', seqdump, SEQ_FRAMES, peek)
        jobs[('spring', core)] = (IMAGE, core, FX2[core], (), 2, 0x15)
        for name, fx in (('dark', 0x16), ('plate', 0x14)):
            jobs[(name, core)] = (IMAGE, core, FX2[core], (), 2, fx)
            jobs[(name + '-stock', core)] = (STOCK, core, FX2[core], (), 2, fx)
    with cf.ThreadPoolExecutor(len(jobs)) as ex:
        fut = {k: ex.submit(ui, S, *v) if k[0] == 'ui' else ex.submit(dram_audit) if k[0] == 'dram' else ex.submit(run, *v)
               for k, v in jobs.items()}
        res = {k: f.result() for k, f in fut.items()}
    ok = True
    # ---- the DRAM runtime
    p, hits, pcs, got, blob, lo = res[('dram', '')]
    data0 = next(int(l.split()[3], 16) for l in subprocess.run(['m68k-elf-objdump', '-h', ELF], capture_output=True, text=True,
                 check=True).stdout.splitlines() if len(l.split()) > 3 and l.split()[1] == '.data')   # the runtime's own state
    outside = sorted({hex(x) for x in pcs if not lo <= x < lo + len(blob)})
    print(f'dram: loader hits {hits}; {len(pcs)} writes into the reserve, writers outside the runtime {outside}; '
          f'code + constants equal after the run: {got[:data0 - lo] == blob[:data0 - lo]}')
    ok &= p.returncode == 0 and len(hits) == 1 and not outside and len(got) == len(blob) and got[:data0 - lo] == blob[:data0 - lo]
    # ---- ui
    for name, t, want in (('T2', 1, True), ('T3', 2, False), ('T6', 5, True)):  # ('back', 'stock': below)
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
            print(f'   page label fields {desc[0x3c:0x3e]!r} / {desc[0x41:0x49]!r} (stock PB / PLAYBACK: PLAYBACK>OT-303)')
            ok &= page == S['desc'] + 0x38 and desc[0x3c:0x3f] == b'PB\0' and desc[0x41:0x4a] == b'PLAYBACK\0' \
                and names[:6] == ['PTCH', 'CUT', 'RES', 'ENV', 'DEC', 'ACC']
    # the FLEX round trip against stock's Part as loaded
    (pb, gb), (ps, gs) = res[('ui', 'back')], res[('ui', 'stock')]
    for c in ('part', 'shadow'):
        a, b = gs.get(c, b''), gb.get(c, b'')
        diff = [i for i in range(min(len(a), len(b))) if a[i] != b[i]]
        t = 1
        flex = [b[0x2a + 30 * t + 6 + k] for k in range(6)] + [b[0x1da + 30 * t + 6 + k] for k in range(6)] if b else []
        print(f'flex round trip, {c}: {len(diff)} bytes differ from stock {[hex(i) for i in diff[:8]]}; T2 type {b[0x22 + t] if b else None}, '
              f'FLEX knobs {flex}, signature {b[60 + 30 * t:63 + 30 * t]!r}' if b else f'flex round trip, {c}: no dump')
        ok &= len(a) == len(b) == 6322 and not diff
    ok &= pb.returncode == 0 and 'ended on quit' in pb.stdout
    # ---- sequencer
    for k, v in sorted(((k, v) for k, v in res.items() if k[0] not in ('ui', 'dram')), key=lambda kv: (kv[0][1], kv[0][0])):
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
        got = res[('src-seq', core)][3]
        c = {k: int.from_bytes(v, 'big') for k, v in got.items() if k not in ('evlog', 'evptch')}
        ci = {k: int.from_bytes(v, 'big') for k, v in res[('src-inert', core)][3].items()}
        print(f'   ColdFire renderer: inert calls {ci.get("calls")} trigs {ci.get("trigs")}; with OT-303 tracks calls {c.get("calls")} '
              f'notes {c.get("trigs")}, step-hook calls {c.get("steps")}, trig flags with no note queued {c.get("stray")}, '
              f'queue clears {c.get("clears")}, notes dropped unplayed {c.get("drops")}; '
              f'DSP hq_start arrivals (last-24 window) {res[("src-seq", core)][2]}')
        ok &= ci.get('calls') == 0 and c.get('calls', 0) > 0 and c.get('trigs', 0) > 0 and c.get('steps', 0) > 0 \
            and res[('src-seq', core)][2] > 0
        # every note sent, against the line at the emulator's tempo (T2 and T6: 16 steps at 1x = 6 ticks)
        steplen = 6 * 2646000 // c['tempo']
        want = sorted(set(line_events(steplen, DEFAULTS[9])))
        log = got.get('evlog', b'')
        ring = [int.from_bytes(log[i:i + 4], 'big') for i in range(0, len(log), 4)]
        pt0 = got.get('evptch', b'')
        m = min(c['evn'], 32)
        at = [(c['evn'] - m + i) & 31 for i in range(m)]        # the ring, oldest first
        ents, pt = [ring[a] for a in at], [pt0[a] for a in at]
        order = {}
        for i, e in enumerate(ents):
            order.setdefault(e >> 28, []).append(((e >> 24) & 3, e & 0xffffff, pt[i]))
        # T6: the tie / hold / slide / lock line; T2: every step but the two FILL steps, in order, each with
        # its own PTCH (halfway to 90: BOTLI's scene on T2's pitch, the crossfader in the middle -- the note
        # follows the knob's live value, as stock FLEX's pitch does)
        full6 = line_events(steplen, DEFAULTS[9])
        full2 = [(e, g, (v + 91) // 2) for e, g, v in line_events(steplen, DEFAULTS[9], LINE2, LOCKS2, CONDS2)]
        def in_order(seq, line):
            return bool(seq) and any(all(seq[i] == line[(o + i) % len(line)] for i in range(len(seq))) for o in range(len(line)))
        ok6, ok2 = in_order(order.get(5, []), full6), in_order(order.get(1, []), full2)
        print(f'   notes sent ({c["evn"]}; tempo {c["tempo"] / 24:.1f} BPM, step {steplen} samples), the last {m} in order:')
        print(f'     T6 (ties, holds, slides, locks) {order.get(5, [])[:7]}...: as the line {ok6}')
        print(f'     T2 (16 notes, FILL on steps 5 and 11) PTCH {[x[2] for x in order.get(1, [])]}: as the line, none skipped {ok2}')
        ok &= ok6 and ok2 and c.get('stray', 1) == 0 and c.get('drops', 1) == 0
        # the Y image through the records, both cores; the voice running
        for cc in (1, 0):
            m = re.search(rf'core {cc} Y:0x0*{ys["YBEG"]:x}:((?: [0-9a-f]{{6}})+)', res[('src-seq', core)][4])
            ws = [int(x, 16) for x in m.group(1).split()] if m else []
            # the constants: tanh, the coefficient table, the 15-tap's taps (the state block and the host's
            # scratch change once the voice runs)
            const = lambda a: a < ys['CB'] or ys['HB1C'] <= a < ys['HB1C'] + 16
            bad = [i for i, (a, b) in enumerate(zip(ws, yimg)) if a != b and const(ys['YBEG'] + i)]
            m2 = re.search(rf'core {cc} X:0x0*{stg:x}: ([0-9a-f]{{6}})', res[('src-seq', core)][4])
            st = int(m2.group(1), 16) if m2 else None
            print(f'   core {cc} Y image: {len(ws)} words read, its constants ({sum(const(ys["YBEG"] + i) for i in range(len(yimg)))}) '
                  f'equal to the image but {len(bad)} {bad[:6]}; STG {st}')
            ok &= len(ws) == len(yimg) and not bad and st == 2
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
