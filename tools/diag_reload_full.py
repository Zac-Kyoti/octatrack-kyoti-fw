#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
"""
RELOAD_FROM_PROJECT, both chords, against the card (emulator, 2026-11-08).

[BANK] + [TRACK n] used to run stock's PART RELOAD (the whole Part, from its SAVE PART copy). It now
reloads track n's sequence AND track n's slice of the card's working Part, as CLYPS does (its gate L
is the model for this one). On a project that loads on the side to test (audio: OT DEMO; MIDI: JAM2):

  1. SAVE PROJECT (0x40022850 as the main task): the bank file on the staged card = RAM now.
  2. Edit tracks 1 and 2 in RAM: a trig-mask byte of each record, a byte of each Part slice.
  3. [PTN] + [TRACK 1]   PASS: T1's record from the card; T1's slice stays edited.
  4. [BANK] + [TRACK 1]  PASS: T1's record AND slice from the card; T2's record and slice stay
                         edited; stock's PART RELOAD (0x4004aab4) never runs; the toast is up;
                         the page redraw (0x4005e0a8) ran; the Part-edited bit follows "differs
                         from its SAVE PART copy"; the direct seek path read the Part chunk.
     MIDI: also the engine's record of that track (0x46c76dc0 + 68 m) = its Part values again.

  python3 tools/diag_reload_full.py --image out/mainos_reload_from_project.bin \
      --elf out/patch_reload3.elf --project DIR --name NAME [--side audio|midi]
"""
import argparse, os, pathlib, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
SET_KEY = 0x40031734
SAVE_PROJECT = 0x40022850
PART_RELOAD, PART_RFRSH, PICKUP_SET = 0x4004AAB4, 0x4005E0A8, 0x40097290
BLOB, BANKSTRIDE, PATSTRIDE, TRAC_A, MIDI_BASE, TRAC_M = 0x400E21E0, 0x9B340, 0x8ED8, 0x91A, 0x48D0, 0x8B0
PART_OFF, PARTSZ, PEDIT, PSAVECPY, PSAVED = 0x8ED80, 0x18B2, 0x95048, 0x9504A, 0x9B312
MENG = 0x46C76DC0
PTN, BANK = 0x2E, 0x2F
# the slices, as rl_slA / rl_slM (off, stride, size, count, step)
SL_A = [(0x000, 1, 1, 1, 0), (0x008, 1, 1, 1, 0), (0x012, 2, 2, 1, 0), (0x022, 1, 1, 1, 0),
        (0x02A, 30, 30, 1, 0), (0x1DA, 30, 30, 1, 0), (0x11A, 24, 24, 1, 0), (0x2F2, 30, 30, 1, 0),
        (0x2CA, 5, 5, 1, 0), (0x602, 12, 12, 1, 0), (0x662, 32, 32, 16, 0x100), (0x1662, 1, 1, 16, 10),
        (0x1702, 16, 16, 1, 0), (0x1782, 2, 2, 1, 0)]
SL_M = [(0x3E2, 32, 32, 1, 0), (0x4E2, 36, 36, 1, 0), (0x1792, 16, 16, 1, 0), (0x1812, 2, 2, 1, 0)]


def slice_offsets(t):
    tab, i = (SL_A, t) if t < 8 else (SL_M, t - 8)
    out = []
    for off, stride, size, count, step in tab:
        o = off + stride * i
        for _ in range(count):
            out.extend(range(o, o + size))
            o += step
    return out


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True, type=lambda p: str(pathlib.Path(p).resolve()))
    ap.add_argument("--elf", required=True, type=lambda p: str(pathlib.Path(p).resolve()))
    ap.add_argument("--project", required=True, type=lambda p: str(pathlib.Path(p).expanduser().resolve()))
    ap.add_argument("--name", required=True)
    ap.add_argument("--side", choices=("audio", "midi"), default="audio")
    ap.add_argument("--save-ms", type=int, default=8000)
    a = ap.parse_args(argv)
    nm = subprocess.run(["m68k-elf-nm", a.elf], capture_output=True, text=True, check=True).stdout
    syms = {p[2]: int(p[0], 16) for p in (l.split() for l in nm.splitlines()) if len(p) == 3}
    os.chdir(OCTABAM)
    sys.path.insert(0, str(OCTABAM / "tools"))
    import toolpath  # noqa: F401
    sys.path.insert(0, str(OCTABAM / "tools" / "emu"))
    import emu_rtos as er
    card, staged = er.stage_project(a.project, "OCTABAM", a.name,
                                    tree=f"out/_emu_reload_full_{pathlib.Path(a.image).stem}_{a.side}")
    r, rt = er.attach(a.image, card, ips=3990.0, pit_clock_hz=264e6, quantum=4096, step_quantum=32, tick=True)
    if not rt.gate_m6a()[0]:
        rt.run(ms=1000, until=lambda x: x.gate_m6a()[0])
    bank = rt.load_project_live("OCTABAM", staged, run_ms=6000)[3]
    rt.run(ms=300)
    u = rt.uc
    rd = lambda ad, n: int.from_bytes(bytes(u.mem_read(ad, n)), "big")

    def key(code, ev):
        rt.run(until=lambda x: x.pc == er.MAIN_SPIN)
        rt.call_as_main(SET_KEY, args=(code, ev), budget=600000)
        rt.run(ms=60)

    def worker(fn, ms):
        rt.run(until=lambda x: x.pc == er.MAIN_SPIN)
        rt.call_as_main(fn, budget=600000)
        rt.run(ms=ms)

    fails = []

    def check(ok, what):
        print(f"  {'ok  ' if ok else 'FAIL'} {what}", flush=True)
        if not ok:
            fails.append(what)

    midi = bool(rd(0x80000012, 4))
    if midi != (a.side == "midi"):
        sys.exit(f"this project loads on the {'MIDI' if midi else 'audio'} side; --side {a.side} needs the other")
    act = rd(0x800065BE, 1)
    bb = BLOB + bank * BANKSTRIDE
    slab = bb + act * PATSTRIDE
    link = rd(slab + 0x8E57, 1) & 3
    part = bb + PART_OFF + link * PARTSZ
    t1, t2 = (8, 9) if midi else (0, 1)
    recad = lambda t: slab + (MIDI_BASE + (t - 8) * TRAC_M if t >= 8 else t * TRAC_A)
    reclen = lambda t: TRAC_M if t >= 8 else TRAC_A
    rec = lambda t: bytes(u.mem_read(recad(t), reclen(t)))
    pbytes = lambda: bytes(u.mem_read(part, PARTSZ))
    sl = {t: slice_offsets(t) for t in (t1, t2)}
    pslice = lambda t: bytes(pbytes()[i] for i in sl[t])
    same_rec = lambda x, y: all(x[i] == y[i] for i in range(len(x)) if i != 0x899)
    print(f"bank {bank + 1} pattern {act + 1} Part {link + 1}; {'MIDI' if midi else 'audio'} side; "
          f"reload size {syms.get('rl_kind', 0) - 0x400d6500} B before state", flush=True)

    print("SAVE PROJECT ...", flush=True)
    worker(SAVE_PROJECT, a.save_ms)
    pre = {t: rec(t) for t in (t1, t2)}
    psl = {t: pslice(t) for t in (t1, t2)}
    prepart = pbytes()
    # the slice byte to edit: machine page 1 (audio) / page values (MIDI), first byte of track t
    sl_edit = lambda t: part + (0x2A + 30 * t if t < 8 else 0x3E2 + 32 * (t - 8))
    flip = lambda ad, m: u.mem_write(ad, bytes([rd(ad, 1) ^ m]))

    calls = {"part_reload": 0, "rfrsh": 0, "pickup": 0}
    for ad, k in ((PART_RELOAD, "part_reload"), (PART_RFRSH, "rfrsh"), (PICKUP_SET, "pickup")):
        u.hook_add(er.eb.UC_HOOK_CODE, lambda uc, ad_, sz, ud, k=k: calls.__setitem__(k, calls[k] + 1),
                   begin=ad, end=ad)
    path = []
    for n in ("rl_job", "rl_full", "rf_seq", "rr_parsed", "rf_fail0", "rf_out", "rlj_setflag", "rl_done", "rld_epi"):
        if n in syms:
            u.hook_add(er.eb.UC_HOOK_CODE, lambda uc, ad_, sz, ud, n=n: path.append(n),
                       begin=syms[n], end=syms[n])

    # --- [PTN] + [TRACK 1]: the sequence only ---
    print("[PTN] + [TRACK 1]", flush=True)
    flip(recad(t1), 0x81)
    flip(sl_edit(t1), 0x55)
    tk = 0x10 + (t1 & 7)
    key(PTN, 1); key(tk, 1); rt.run(ms=4500); key(tk, 0); key(PTN, 0)
    print(f"      path {path}", flush=True)
    check(same_rec(rec(t1), pre[t1]), "T1's sequence from the card")
    check(pslice(t1) != psl[t1], "T1's Part slice stays as edited (sequence only)")
    check(rd(0x460D1E70, 4) != 0, "a toast is up")

    # --- [BANK] + [TRACK 1]: the sequence + the track's slice ---
    print("[BANK] + [TRACK 1]", flush=True)
    path.clear()
    for k in calls:
        calls[k] = 0
    flip(recad(t1), 0x81)
    flip(recad(t2), 0x81)
    flip(sl_edit(t2), 0x55)
    e2, es2 = rec(t2), pslice(t2)
    u.mem_write(bb + PEDIT, bytes([rd(bb + PEDIT, 1) | (1 << link)]))
    key(BANK, 1); key(tk, 1); rt.run(ms=4500); key(tk, 0); key(BANK, 0)
    print(f"      path {path}; calls {calls}", flush=True)
    dd = lambda x, y: [hex(i) for i in range(len(x)) if x[i] != y[i]][:12]
    print(f"      T1 record differs at {dd(rec(t1), pre[t1])}; T1 slice differs at {dd(pslice(t1), psl[t1])}",
          flush=True)
    check(same_rec(rec(t1), pre[t1]), "T1's sequence from the card")
    check(pslice(t1) == psl[t1], "T1's Part slice from the card")
    check(rec(t2) == e2 and pslice(t2) == es2, "T2's sequence and slice untouched (not the whole Part)")
    now = pbytes()
    diffs = [i for i in range(PARTSZ) if now[i] != prepart[i]]
    check(set(diffs) <= set(sl[t2]), f"the Part differs from the card only in T2's edit ({[hex(i) for i in diffs][:8]})")
    check(calls["part_reload"] == 0, "stock's PART RELOAD (0x4004aab4) never ran")
    check(calls["rfrsh"] >= 1, "the Part-reload page redraw (0x4005e0a8) ran")
    check("rr_parsed" in path and "rf_seq" not in path, "the direct seek read the Part chunk")
    check(rd(0x460D1E70, 4) != 0, "a toast is up")
    saved = rd(bb + PSAVED + link, 1)
    eq = saved and bytes(u.mem_read(bb + PSAVECPY + link * PARTSZ, PARTSZ)) == pbytes()
    check(bool(rd(bb + PEDIT, 1) >> link & 1) == (not eq),
          f"the Part-edited bit follows its SAVE PART copy (saved {saved}, equal {bool(eq)})")
    check(rd(syms["rl_pfull"], 1) == 0 and rd(syms["rl_mch"], 1) == 0, "rl_done consumed the UI half")
    if not midi:
        # --- 3: a new machine on T1 (PICKUP setup from doneFn, the voice restart) and the direct seek
        # forced to fail (rl_seek returns -1 at rs_out): the chunk-by-chunk fallback reads the Part ---
        print("[BANK] + [TRACK 1], T1's machine changed, the seek failing: the fallback", flush=True)
        path.clear()
        for k in calls:
            calls[k] = 0
        mach = part + 0x22
        m0 = rd(mach, 1)
        u.mem_write(mach, bytes([(m0 + 1) % 5]))
        flip(recad(t1), 0x81)
        restarts = []
        u.hook_add(er.eb.UC_HOOK_CODE, lambda uc, ad_, sz, ud: uc.reg_write(er.eb.UC_M68K_REG_D0, 0xFFFFFFFF),
                   begin=syms["rs_out"], end=syms["rs_out"])
        u.hook_add(er.eb.UC_HOOK_MEM_WRITE, lambda uc, acc, ad_, sz, val, ud: restarts.append(val),
                   begin=0x8000184C, end=0x8000184C)
        key(BANK, 1); key(tk, 1); rt.run(ms=6000); key(tk, 0); key(BANK, 0)
        print(f"      path {path}; calls {calls}; writes to 0x8000184c {[hex(v) for v in restarts][:6]}", flush=True)
        check("rf_seq" in path and "rr_parsed" in path, "the seek failed and the chunk-by-chunk fallback read the Part")
        check(same_rec(rec(t1), pre[t1]) and pslice(t1) == psl[t1], "T1's sequence and slice from the card")
        check(rd(mach, 1) == m0, f"T1's machine back to the card's ({m0})")
        check(any(v & 1 for v in restarts), "T1's voice restart bit was set (0x8000184c bit 0)")
        check(calls["pickup"] == 1 and calls["rfrsh"] >= 1, "the PICKUP setup ran once, then the page redraw")
        check(rd(syms["rl_pfull"], 1) == 0 and rd(syms["rl_mch"], 1) == 0, "rl_done consumed the UI half")
    if midi:
        m = t1 - 8
        eng = bytes(u.mem_read(MENG + 68 * m, 68))
        want = bytes(u.mem_read(part + 0x3E2 + 32 * m, 32)) + bytes(u.mem_read(part + 0x4E2 + 36 * m, 36))
        check(eng == want, "the MIDI engine's record of M1 = its Part values")
    print("VERDICT:", "PASS" if not fails else f"FAIL ({len(fails)})")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
