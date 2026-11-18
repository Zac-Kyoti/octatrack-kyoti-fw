#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
"""
KYOTI V1.8BC: one BLKPYRAMD per DSP core through Clyps' FULL loads (tools/clyps/patch_clyps.s cl_bpgate ->
BLACKPYRAMIDS_303's bp_refuse_load). Route A (refs/octabam's emu_rtos, as tools/diag_clyps_ui.py: real key events
through stock's set_key_state, transport stopped), a real exported project (OT DEMO) loaded; the BLKPYRAMD tracks
are made in RAM the way the chooser's commit makes them (the voice runtime's ot_assign, then the machine byte, both
Part copies), a pattern's Part link as the PART menu sets it (trailer +0x8e57). No file is edited.

  setup     the playing pattern's Part (P): T1 a BLKPYRAMD (core 1). Slot q (another pattern) linked to another Part
            (Q): T2 and T5 BLKPYRAMD there.
  single    T2 active, [FUNC] + trig q (TRK FULL): refused -- T2's sequence and Part slice unchanged, nothing cued,
            no load confirmation, ONE toast (ONE 303 PER CORE!, NOTIFY counted)
  group     a [CUE] group T2 + T5, [CUE] + [FUNC] + trig q (every member slot q, FULL): refused whole -- T5 (which
            alone would land: core 0 has none) unchanged too, ONE toast
  lands     T5 active, [FUNC] + trig q: no clash (core 0 has none) -- T5 lands as a BLKPYRAMD with q's sequence,
            no toast
  temp      outside Clyps: T5 saved (TRACK 5 + [YES]); T5 back to FLEX (ot_assign 0, what the chooser does), T6 a
            BLKPYRAMD; TRACK 5 + [NO] (the temp reload, FULL): refused -- T5 stays FLEX, no TEMP TRK RELOADED, ONE
            toast
  seq       a sequence-only load (trig q without [FUNC]) onto T2: lands (a sequence never brings a machine)

    python3 tools/kyoti_bc_check_onepercore.py [--project DIR --name NAME]
"""
import argparse, json, os, pathlib, shutil, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
OUT = ROOT / "out/KYOTI_WIP/KYOTI_V1.8BC"
SET_KEY, NOTIFY = 0x40031734, 0x4005A2B8
BLOB, BANKSTRIDE, PATSTRIDE, TRAC_A, PART_OFF, PARTSZ, SRAM_PART = 0x400E21E0, 0x9B340, 0x8ED8, 0x91A, 0x8ED80, 0x18B2, 0x100A4ECE
PTN, BANK, YES, NO, FUNC, CUE = 0x2E, 0x2F, 0x31, 0x32, 0x2D, 0x2A
SLA = [(0x000, 1, 1, 1, 0), (0x008, 1, 1, 1, 0), (0x012, 2, 2, 1, 0), (0x022, 1, 1, 1, 0),
       (0x02A, 30, 30, 1, 0), (0x1DA, 30, 30, 1, 0), (0x11A, 24, 24, 1, 0), (0x2F2, 30, 30, 1, 0),
       (0x2CA, 5, 5, 1, 0), (0x602, 12, 12, 1, 0), (0x662, 32, 32, 16, 0x100), (0x1662, 1, 1, 16, 10),
       (0x1702, 16, 16, 1, 0), (0x1782, 2, 2, 1, 0)]


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", default=str(OUT / "mainos_kyoti_v1.8bc.bin"))
    ap.add_argument("--map", default=str(OUT / "kyoti_v1.8bc_map.json"))
    ap.add_argument("--project", default="~/Desktop/OT Backup/KYOTI/OT DEMO")
    ap.add_argument("--name", default="OT DEMO")
    a = ap.parse_args(argv)
    image = str(pathlib.Path(a.image).resolve())
    m = json.load(open(a.map))["symbols"]
    num = lambda v: int(v, 16) if isinstance(v, str) else v
    cl = {k: num(v) for k, v in m["patch_clyps_dram"].items()}
    bp = {k: num(v) for k, v in m["ot303/cf/ot303_runtime"].items()}
    assert cl["BP_CLASH"] == bp["bp_refuse_load"] and cl["BP_UITAIL"] == bp["bp_uitail"], "Clyps not built with the voice's entries"
    project = str(pathlib.Path(a.project).expanduser().resolve())

    os.chdir(OCTABAM)
    sys.path.insert(0, str(OCTABAM / "tools"))
    import toolpath  # noqa: F401
    sys.path.insert(0, str(OCTABAM / "tools" / "emu"))
    import emu_rtos as er
    tree = f"out/_emu_kbc_onepercore_{os.getpid()}"
    card, staged = er.stage_project(project, "OCTABAM", a.name, tree=tree)
    r, rt = er.attach(image, card, ips=3990.0, pit_clock_hz=264e6, quantum=4096, step_quantum=32, tick=True)
    if not rt.gate_m6a()[0]:
        rt.run(ms=1000, until=lambda x: x.gate_m6a()[0])
    bank = rt.load_project_live("OCTABAM", staged, run_ms=6000)[3]
    u = rt.uc
    rd = lambda ad, n: int.from_bytes(bytes(u.mem_read(ad, n)), "big")
    wr = lambda ad, v, n=1: u.mem_write(ad, v.to_bytes(n, "big"))
    notes = []

    def on_notify(uc, ad, sz, ud):                # NOTIFY(text, duration): every toast, its text
        notes.append(rd(u.reg_read(er.eb.UC_M68K_REG_A7) + 4, 4))
    u.hook_add(er.eb.UC_HOOK_CODE, on_notify, begin=NOTIFY, end=NOTIFY)

    def main_call_r(addr, args=(), budget=600000):
        sp0 = u.reg_read(er.eb.UC_M68K_REG_A7)
        r_ = rt.call_as_main(addr, args=args, budget=budget)
        u.reg_write(er.eb.UC_M68K_REG_A7, sp0)
        return r_

    def key(code, ev, settle=60):
        rt.run(until=lambda x: x.pc == er.MAIN_SPIN)
        if ev and 0x10 <= code <= 0x17:
            u.mem_write(0x460D5DE0, (100).to_bytes(4, "big"))   # diag_clyps_ui: route A's TRACK double-tap timer
        main_call_r(SET_KEY, args=(code, ev), budget=4_000_000)
        rt.run(ms=settle)

    def tap(code):
        key(code, 1)
        key(code, 0)

    def callm(addr, *args):
        rt.run(until=lambda x: x.pc == er.MAIN_SPIN)
        return main_call_r(addr, args=args)
    act = rd(0x800065BE, 1)
    bankb = BLOB + bank * BANKSTRIDE
    partidx = lambda pat: rd(bankb + pat * PATSTRIDE + 0x8E57, 1) & 3
    partof = lambda pat: bankb + PART_OFF + partidx(pat) * PARTSZ
    rec = lambda pat, t: bytes(u.mem_read(bankb + pat * PATSTRIDE + t * TRAC_A, TRAC_A))

    def pslice(t, base):
        out = b""
        for off, stride, size, count, step in SLA:
            o = off + stride * t
            for _ in range(count):
                out += bytes(u.mem_read(base + o, size))
                o += step
        return out

    def signed(base, t):
        return rd(base + 0x22 + t, 1) == 1 and bytes(u.mem_read(base + 60 + 30 * t, 3)) == b"OT\x01"

    def make(pat, t, sign=1):
        """track t of pattern pat's Part a BLKPYRAMD (sign 1) or not (0), as the chooser's commit does"""
        base = partof(pat)
        callm(bp["ot_assign"], base, t, sign)
        if sign:
            wr(base + 0x22 + t, 1)
            wr(SRAM_PART + partidx(pat) * PARTSZ + 0x22 + t, 1)
    ctr = lambda: (rd(bp["bp_toasts"], 4), rd(bp["bp_refusals"], 4))
    ours = lambda: sum(1 for x in notes if x == bp["ot_reject_name"])
    fails = []

    def check(cond, what):
        print(f"   {'ok  ' if cond else 'FAIL'} {what}")
        if not cond:
            fails.append(what)

    rt.run(ms=300)
    tap(NO)                                       # the SET DATE/TIME dialog (diag_clyps_ui)
    rt.run(ms=200)
    print(f"bank {bank}, playing pattern {act} (Part {partidx(act) + 1}), BANK ptr 0x{rd(0x46C82456, 4):08x}")
    check(rd(0x46C82456, 4) == bankb, "the UI bank is the playing bank (the mirror is this bank's)")
    q = next(x for x in range(16) if x != act and rec(x, 1) != rec(act, 1) and rec(x, 4) != rec(act, 4))
    wr(bankb + q * PATSTRIDE + 0x8E57, (partidx(act) + 1) & 3)
    P, Q = partof(act), partof(q)
    print(f"slot q = pattern {q + 1} (Part {partidx(q) + 1}); the playing Part {partidx(act) + 1}")
    make(act, 0)
    make(q, 1)
    make(q, 4)
    check(signed(P, 0) and not any(signed(P, t) for t in range(1, 8)), "setup: the playing Part's T1 a BLKPYRAMD, alone")
    check(signed(Q, 1) and signed(Q, 4), "setup: slot q's Part has T2 and T5 BLKPYRAMD")

    def opened():
        key(PTN, 1); key(BANK, 1); key(BANK, 0); key(PTN, 0)
        return rd(cl["cl_open"], 1) == 1

    # ---- single
    print("single: T2, [FUNC] + trig q")
    tap(0x11)
    check(opened() and rd(0x80000000, 1) == 1, "Clyps open on T2")
    r2, s2, t0, n0 = rec(act, 1), pslice(1, P), ctr(), ours()
    key(FUNC, 1); tap(q); key(FUNC, 0)
    t1 = ctr()
    check(rec(act, 1) == r2 and pslice(1, P) == s2, "T2's sequence and Part slice unchanged")
    check(not signed(P, 1) and signed(P, 0), "T1 still the only BLKPYRAMD on core 1")
    check(rd(cl["cl_cue"] + 2, 2) == 0xFFFF and rd(cl["cl_bpno"], 1) == 1, "nothing cued for T2; cl_bpno set")
    check(all(rd(cl["cl_xc"] + 4 * k, 4) == 0xFFFFFFFF for k in range(16)), "cl_exec's codes all cleared")
    check(rd(cl["cl_flk"], 1) == 0, "no load confirmation flash")
    check(t1[0] - t0[0] == 1 and t1[1] - t0[1] == 1 and ours() - n0 == 1, f"exactly one toast, ours (toasts {t0}->{t1})")
    # ---- group
    print("group: [CUE] T2 + T5, [CUE] + [FUNC] + trig q")
    r5, s5 = rec(act, 4), pslice(4, P)
    key(CUE, 1); tap(0x11); tap(0x14); key(CUE, 0)
    check(rd(cl["cl_grp"], 2) == 0x12, f"the group T2 + T5 (0x{rd(cl['cl_grp'], 2):x})")
    t0, n0 = ctr(), ours()
    key(CUE, 1); key(FUNC, 1); tap(q); key(FUNC, 0); key(CUE, 0)   # [CUE] first: with [FUNC] held it is stock's
    t1 = ctr()
    check(rec(act, 1) == r2 and pslice(1, P) == s2 and rec(act, 4) == r5 and pslice(4, P) == s5,
          "T2 AND T5 unchanged (T5 alone would land: refused whole)")
    check(rd(cl["cl_cue"] + 2, 2) == 0xFFFF and rd(cl["cl_cue"] + 8, 2) == 0xFFFF, "nothing cued")
    check(t1[0] - t0[0] == 1 and ours() - n0 == 1, f"exactly one toast for the group (toasts {t0}->{t1})")
    tap(NO)                                       # the group goes, Clyps stays
    check(rd(cl["cl_grp"], 2) == 0 and rd(cl["cl_open"], 1) == 1, "[NO]: the group dismissed")
    # ---- lands
    print("lands: T5, [FUNC] + trig q")
    tap(0x14)
    t0, n0 = ctr(), ours()
    key(FUNC, 1); tap(q); key(FUNC, 0)
    check(signed(P, 4) and signed(P, 0), "T5 landed as a BLKPYRAMD (core 0), T1 still one (core 1)")
    check(rec(act, 4) == rec(q, 4), "T5 plays q's sequence")
    check(pslice(4, P) == pslice(4, Q), "T5's Part slice is q's")
    check(ctr() == t0 and ours() == n0, "no toast, no refusal")
    # ---- seq
    print("seq: T2, trig q (sequence only)")
    tap(0x11)
    t0 = ctr()
    tap(q)
    check(rec(act, 1) == rec(q, 1) and pslice(1, P) == s2 and not signed(P, 1), "T2 has q's sequence, its slice (FLEX) kept")
    check(ctr() == t0, "no toast")
    tap(NO)
    check(rd(cl["cl_open"], 1) == 0, "Clyps closed")
    # ---- temp
    print("temp: TRACK 5 + [YES]; T5 FLEX, T6 a BLKPYRAMD; TRACK 5 + [NO]")
    key(0x14, 1); tap(YES); key(0x14, 0)
    check(rd(cl["cl_svalid"] + 4, 1) == 1, "T5 temp-saved")
    make(act, 4, 0)
    make(act, 5)
    check(not signed(P, 4) and signed(P, 5), "T5 FLEX, T6 a BLKPYRAMD")
    r5, s5, t0, n0 = rec(act, 4), pslice(4, P), ctr(), ours()
    nall = len(notes)
    key(0x14, 1); tap(NO); key(0x14, 0)
    check(rec(act, 4) == r5 and pslice(4, P) == s5 and not signed(P, 4) and signed(P, 5), "T5 unchanged (FLEX), T6 still one")
    check(ctr()[0] - t0[0] == 1 and ours() - n0 == 1 and len(notes) - nall == 1,
          f"exactly one toast, ours -- no TEMP TRK RELOADED (NOTIFY calls {len(notes) - nall})")
    shutil.rmtree(OCTABAM / tree, ignore_errors=True)
    print(f"{'ALL GOOD' if not fails else 'FAILED: ' + '; '.join(fails)}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
