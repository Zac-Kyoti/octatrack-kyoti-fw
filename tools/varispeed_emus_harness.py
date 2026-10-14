#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
VARISPEED_EMUS -- the black-box equivalence harness (spec §5), outputs only.

Runs two images in ot_emu on the same REAL hardware-exported project, sets the matrix by
RUNTIME pokes (Part bytes + SRAM shadow + live bytes + base words, sample settings,
set_tempo) -- no project file is edited -- and compares what each DSP voice pass
receives: x:$40 / y:$40 (l:$40, the increment as the voice kernel sees it) at the kernel
entry (payload A P:0x40b core 0, B P:0x20e core 1), logged by the scratch ot_emu's
OT_VEM_LOG patch (tools/varispeed_emus_ot_emu.patch). Never disassembles, diffs or traces
the oracle's code; the observation point is the unchanged DSP kernel's entry.

    new     VARI (TSTR 4) + EMUS S950 / OT / SP12     out/mainos_varispeed_emus.bin
    oracle  TSTR 5 (RPS9) / 4 (RPCH) / 6 (RPSP)       out/oracle/shipped_repitch_repeat98_kyoti_FINAL.bin
    stock   for the out-of-range cases: TSTR OFF      out/raw/section_3_MAIN_OS.bin

Per track the comparison starts at its first trig pass after the value pokes (the new
image latches the engine at a trig, the oracle takes it from TSTR at once).

  python3 tools/varispeed_emus_harness.py [--quick] [--only NAME] [--jobs N]

Environment: VEM_EMU (the patched ot_emu), VEM_CARD (card image), VEM_OUT (run dir).
"""
import argparse, json, os, pathlib, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCR = ROOT / "out/vem"
EMU = pathlib.Path(os.environ.get("VEM_EMU", SCR / "octabam/out/emu/ot_emu"))
# REAL hardware-exported projects, staged as cards (stage_card.py): OTDEMO (T1-T7 FLEX,
# T8 THRU, part 1 playing) and MMTESTDT (T1-T8 STATIC, part 0).
PROJECTS = {
    "otdemo": dict(card=SCR / "img/otdemo.img", set="KYOTI", project="OTDEMO", part=1, m=1,
                   slots={0: 20, 1: 5, 2: 3, 3: 10, 4: 16, 5: 4, 6: 15}),
    "mmtestdt": dict(card=SCR / "img/mmtestdt.img", set="MMTESTDT", project="test", part=0, m=0,
                     slots={t: t for t in range(8)}),
}
PRJ = PROJECTS[os.environ.get("VEM_PROJECT", "otdemo")]
CARD = pathlib.Path(os.environ.get("VEM_CARD", PRJ["card"]))
OUTD = pathlib.Path(os.environ.get("VEM_OUT", SCR / ("harness_" + os.environ.get("VEM_PROJECT", "otdemo"))))
IMAGES = {"new": ROOT / "out/mainos_varispeed_emus.bin",
          "oracle": ROOT / "out/oracle/shipped_repitch_repeat98_kyoti_FINAL.bin",
          "stock": ROOT / "out/raw/section_3_MAIN_OS.bin"}
for _k, _e in (("new", "VEM_IMG_NEW"), ("oracle", "VEM_IMG_ORACLE")):
    if os.environ.get(_e):                  # the harness's own oracle check: stock vs stock,
        IMAGES[_k] = pathlib.Path(os.environ[_e]).resolve()   # a deliberately wrong build
ORACLE_SHA = "90b4a1c11b40b93901b0a0c3f9500d22193facf82c13aeac447eb97f9a45acfa"

DB = 0x400e21e0                     # [0x46c82456] in these projects (checked by the dump step)
PART = PRJ["part"]                  # the project's current part (0-based; checked)
PSTRIDE = 0x18b2
OFF_P1, OFF_P2, OFF_SLOT5, OFF_MACH = 0x8edaa, 0x8ef5a, 0x8f04a, 0x8eda2
SHADOW = 0x100a4ece - 0x8ed80
LIVE_P1, LIVE_P2, BASE_W = 0x80000810, 0x80000830, 0x80000a50
SET_FLEX, SET_STATIC, SET_STRIDE = 0x100b14f0, 0x100d5b30, 0x448
SET_TEMPO = 0x4009c708
SLOT = PRJ["slots"]                 # the track's sample slot (dumped from the loaded project)
MACH = PRJ["m"]                     # its machine: 1 FLEX / 0 STATIC
PICKUP, SET_MACHINE = 4, 0x400972fc  # machine select's refresher (part, track)
QUAN = [4 + 15 * i for i in range(9)]          # the 9 stops: 1/2 .. 2/1
EMUS = {"S950": 1, "OT": 64, "SP12": 127}
ORACLE_TSTR = {"S950": 5, "OT": 4, "SP12": 6}
T_SET, T_VAL = 2, 40                            # poke frames (after the transport start)
SKIP_FRAMES = 60                                # compare from each track's first trig after this


def u8(a, v):
    return f"{a:#x}={v & 0xff:#x}"


def u32(a, v):
    return [u8(a + i, (v >> (24 - 8 * i)) & 0xff) for i in range(4)]


def p1(t, m, flat, v):
    o = OFF_P1 + PART * PSTRIDE + 30 * t + 6 * m + flat
    return [u8(DB + o, v), u8(SHADOW + o, v), u8(LIVE_P1 + 72 * t + flat, v),
            u8(BASE_W + 64 * t + 2 * flat, v), u8(BASE_W + 64 * t + 2 * flat + 1, 0)]


def p2(t, m, slot2, v):
    o = OFF_P2 + PART * PSTRIDE + 30 * t + 6 * m + slot2
    return [u8(DB + o, v), u8(SHADOW + o, v), u8(LIVE_P2 + 72 * t + slot2, v)]


def settings(t, field, v):
    return u32((SET_FLEX if MACH == 1 else SET_STATIC) + SLOT[t] * SET_STRIDE + field, v)


def scenario_steps(cfg, image):
    """cfg: dict(tempo=bpm24|None, tracks={t: dict(mode, emus, tsmode, bpm24, quan, rate,
    ratemode)}). mode: 'VARI' (TSTR 4 / oracle 4-6), 'AUTO' (TSTR 1, the sample's TSMODE
    4 / oracle 4-6), 'OFF' (TSTR 0)."""
    s1, s2, s0 = [], [], []
    for t, c in cfg["tracks"].items():
        m = MACH
        e = c.get("emus", "OT")
        if c["mode"] == "PICKUP":                        # the track becomes a PICKUP machine
            m = PICKUP
            o = OFF_MACH + PART * PSTRIDE + t
            s0 += [u8(DB + o, PICKUP), u8(SHADOW + o, PICKUP)]
            s1 += p2(t, m, 4, c.get("tstr", 0))
        elif c["mode"] == "VARI":
            ts = 4 if image == "new" else ORACLE_TSTR[e] if image == "oracle" else 0
            s1 += p2(t, m, 4, ts)
        elif c["mode"] == "AUTO":
            s1 += p2(t, m, 4, 1)
            tsm = 4 if image == "new" else ORACLE_TSTR[e] if image == "oracle" else 0
            s1 += settings(t, 0x110, c.get("tsmode", tsm))
        elif c["mode"] == "OFF":
            s1 += p2(t, m, 4, 0)
        elif c["mode"] == "RAW":                         # a stock TSTR (and TSMODE) on both images
            s1 += p2(t, m, 4, c["tstr"])
            if "tsmode" in c:
                s1 += settings(t, 0x110, c["tsmode"])
        if "bpm24" in c:
            s1 += settings(t, 0x114, c["bpm24"])
        if "ratemode" in c:
            s1 += p2(t, m, 3, c["ratemode"])
        if "quan" in c:
            s2 += p1(t, m, 0, c["quan"])
        if "rate" in c:
            s2 += p1(t, m, 3, c["rate"])
        if image == "new" and c["mode"] in ("VARI", "AUTO"):
            s2 += p2(t, m, 5, EMUS[e])
    st = []
    if s0:
        st.append(f"1:poke:" + ";".join(s0))
        for t, c in cfg["tracks"].items():
            if c["mode"] == "PICKUP":
                st.append(f"1:call:{SET_MACHINE:#x},{PART},{t}")
    if cfg.get("tempo"):
        st.append(f"{T_SET}:call:{SET_TEMPO:#x},{cfg['tempo']}")
    if s1:
        st.append(f"{T_SET}:poke:" + ";".join(s1))
    if s2:
        st.append(f"{T_VAL}:poke:" + ";".join(s2))
    return st


def run(image, scens, frames, jobs, tag):
    """One load, one forked child per scenario. Returns {name: log path}."""
    d = OUTD / tag / image
    d.mkdir(parents=True, exist_ok=True)
    args = [str(EMU), "--image", str(IMAGES[image]), "--card", str(CARD), "--set", PRJ["set"],
            "--project", PRJ["project"], "--load-ms", "20000", "--dsp", "--main-level", "64",
            "--scenario-jobs", str(jobs)]
    for name, steps in scens.items():
        log = d / f"{name}.log"
        a = f"{log} --sequencer --internal-clock --frames {frames} --audio-out {d / (name + '.wav')}"
        a += f" --step -:dump:0x46c82456,4={d / (name + '.dbptr')};0x80000003,1={d / (name + '.part')}"
        for s in steps:
            a += f" --step {s}"
        args += ["--scenario", a]
    env = dict(os.environ, OT_VEM_LOG="%o")
    with open(d / "parent.log", "w") as f:
        subprocess.run(args, env=env, stdout=f, stderr=subprocess.STDOUT, timeout=7200)
    return {n: d / f"{n}.log" for n in scens}


def parse(vem):
    """-> {core: [(off, lc, x, y, trig)]}"""
    out = {0: [], 1: []}
    for line in open(vem):
        f = line.split()
        if len(f) < 8:
            continue
        e = (int(f[2], 16), int(f[3], 16), int(f[4], 16), int(f[5], 16), (int(f[7], 16) >> 12) & 1)
        L = out[int(f[0])]
        # an interrupt taken AT the kernel entry re-arrives at the same PC: one pass
        # logged twice (same track offset and LC in a row, which no real sequence has)
        if L and L[-1][:2] == e[:2]:
            L[-1] = e
        else:
            L.append(e)
    return out




def track_of(core, off):
    return (0 if core == 1 else 4) + off // 0x20


def compare(a, b, cfg, label, ymask=0xffffff):
    """a/b: parse() results. Per track, from its first trig pass after SKIP_FRAMES.
    ymask: the y:$40 bits compared (out of range vs stock: all but the engine bits 0-1,
    which stock leaves arbitrary and the new image must keep 0 -- counted separately)."""
    res = {"label": label, "tracks": {}, "ok": True, "tagged": 0}
    for core in (0, 1):
        A, B = a[core], b[core]
        ntrk = max(1, len({e[0] for e in A[:200]}))     # voice passes per frame: 2 per track
        if len(A) != len(B):
            n = min(len(A), len(B))
            res.setdefault("notes", []).append(f"core {core}: {len(A)} vs {len(B)} passes, first {n} compared")
            A, B = A[:n], B[:n]
        per = {}
        for i, (x, y) in enumerate(zip(A, B)):
            t = track_of(core, x[0])
            if (x[0], x[1]) != (y[0], y[1]):
                res["ok"] = False
                res.setdefault("notes", []).append(f"core {core} pass {i}: pass order differs {x[:2]} {y[:2]}")
                break
            st = per.setdefault(t, dict(started=False, n=0, diff=0, first=None, trigs=0))
            frame = i // (2 * ntrk)
            if not st["started"]:
                if frame >= SKIP_FRAMES and x[4] and x[1] == 1:
                    st["started"] = True
                else:
                    continue
            st["n"] += 1
            st["trigs"] += x[4] and x[1] == 1
            if ymask != 0xffffff and x[3] & 3:
                res["tagged"] += 1
                res["ok"] = False
            if (x[2], x[3] & ymask) != (y[2], y[3] & ymask):
                st["diff"] += 1
                if st["first"] is None:
                    st["first"] = dict(pass_=i, frame=frame, lc=x[1], a=f"{x[2]:06x}:{x[3]:06x}",
                                       b=f"{y[2]:06x}:{y[3]:06x}")
        for t, st in per.items():
            res["tracks"][t] = st
            if st["diff"]:
                res["ok"] = False
    return res


def matrix(quick):
    """name -> cfg. Each scenario sets all seven FLEX tracks, so one run covers 7 cases."""
    sc = {}
    rates = [127, 96, 32, 0, 127, 112, 16]          # fwd unity, fwd, rev, rev full, ...
    emus_list = ["OT", "S950", "SP12"]
    tempos = [None, 2100, 3600] if not quick else [None]  # project 87.5 / 150 BPM; None = the project's
    for e in emus_list:
        for tempo in tempos:
            for qset in (0, 1) if not quick else (0,):
                tr = {}
                for t in range(7):
                    q = QUAN[(t + 7 * qset) % 9]
                    tr[t] = dict(mode="VARI", emus=e, quan=q, rate=rates[t])
                sc[f"vari_{e}_T{tempo or 'p'}_q{qset}"] = dict(tempo=tempo, tracks=tr)
    if not quick:
        # AUTO with the sample's TSMODE (VARISPEED / 4 / 5 / 6 on the oracle)
        for e in emus_list:
            tr = {t: dict(mode="AUTO", emus=e, quan=QUAN[(t * 2) % 9], rate=rates[(t + 3) % 7])
                  for t in range(7)}
            sc[f"auto_{e}"] = dict(tempo=None, tracks=tr)
        # SETUP RATE mode TSTR (RATE not applied), sample tempos at the range edges
        for e in emus_list:
            tr = {t: dict(mode="VARI", emus=e, quan=QUAN[(t * 4) % 9], rate=rates[t], ratemode=1,
                          bpm24=[720, 7200, 721, 7199, 2880, 1440, 5760][t]) for t in range(7)}
            sc[f"ratemode_edges_{e}"] = dict(tempo=None, tracks=tr)
        # stock TSTR / TSMODE on both images (not VARI): identical to the oracle
        for k, (tstrs, tsms) in enumerate((([0, 1, 2, 3, 0, 1, 2], [0, 2, 3, 0, 2, 3, 0]),
                                            ([3, 2, 1, 0, 1, 1, 1], [2, 0, 0, 3, 3, 2, 0]))):
            tr = {t: dict(mode="RAW", tstr=tstrs[t], tsmode=tsms[t], quan=QUAN[(t * 3 + k) % 9],
                          rate=rates[(t + k) % 7]) for t in range(7)}
            sc[f"stock_tstr_{k}"] = dict(tempo=None, tracks=tr)
        # PICKUP tracks (switched at runtime) beside VARI ones: PICKUP untouched
        tr = {t: dict(mode="VARI", emus=emus_list[t % 3], quan=QUAN[(t * 2) % 9], rate=rates[t])
              for t in range(7)}
        for t in (2, 5):
            tr[t] = dict(mode="PICKUP", tstr=t % 3, quan=QUAN[t], rate=rates[t])
        sc["pickup_mix"] = dict(tempo=None, tracks=tr)
        # project tempo at the edges with mixed samples
        for tempo in (720, 7200):
            tr = {t: dict(mode="VARI", emus=emus_list[t % 3], quan=QUAN[(t * 5) % 9], rate=rates[t])
                  for t in range(7)}
            sc[f"tempo_edge_{tempo}"] = dict(tempo=tempo, tracks=tr)
    return sc


def oor_matrix():
    """Out of range (sample BPM 0 / 719 / 7201): the new image must equal STOCK with TSTR OFF."""
    sc = {}
    for bpm in (0, 719, 7201):
        trn = {t: dict(mode="VARI", emus="SP12", quan=QUAN[t], rate=[127, 96, 32, 0, 127, 112, 16][t],
                       bpm24=bpm) for t in range(7)}
        sc[f"oor_{bpm}"] = dict(tempo=None, tracks=trn)
    return sc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--only", default="")
    ap.add_argument("--jobs", type=int, default=6)
    ap.add_argument("--frames", type=int, default=3000)
    ap.add_argument("--reuse", action="store_true", help="compare existing logs only")
    a = ap.parse_args()
    import hashlib
    if not os.environ.get("VEM_IMG_ORACLE") and \
            hashlib.sha256(IMAGES["oracle"].read_bytes()).hexdigest() != ORACLE_SHA:
        sys.exit("the oracle image is not the shipped FINAL (sha256 90b4a1c1...)")
    results = []
    sc = matrix(a.quick)
    if a.only:
        sc = {k: v for k, v in sc.items() if a.only in k}
    groups = [("eq", sc, ("new", "oracle"))]
    oor = oor_matrix()
    if not a.only or "oor" in a.only:
        groups.append(("oor", oor, ("new", "stock")))
    for tag, scens, (ia, ib) in groups:
        if not scens:
            continue
        logs = {}
        for img in (ia, ib):
            st = {}
            for n, cfg in scens.items():
                # the stock reference of an out-of-range case: TSTR OFF, same values
                c = cfg if img != "stock" else dict(cfg, tracks={t: dict(v, mode="OFF")
                                                                for t, v in cfg["tracks"].items()})
                st[n] = scenario_steps(c, img)
            if a.reuse:
                logs[img] = {n: OUTD / tag / img / f"{n}.log" for n in scens}
            else:
                print(f"[{tag}] running {img}: {len(scens)} scenarios ...", flush=True)
                logs[img] = run(img, st, a.frames, a.jobs, tag)
        for n in scens:
            la, lb = logs[ia][n], logs[ib][n]
            ok_run = all("run ended REACHED" in p.read_text() for p in (la, lb) if p.exists())
            r = compare(parse(str(la) + ".vem"), parse(str(lb) + ".vem"), scens[n],
                        f"{tag}:{n} {ia} vs {ib} [{PRJ['project']}]",
                        0xfffffc if tag == "oor" else 0xffffff)
            r["reached"] = ok_run
            results.append(r)
            tr = " ".join(f"T{t + 1}:{s['n']}/{s['diff']}{'' if s['started'] else '(no trig)'}"
                          for t, s in sorted(r["tracks"].items()))
            print(f"  {'IDENTICAL' if r['ok'] and ok_run else 'DIFFER   '} {r['label']}  [{tr}]"
                  + ("" if ok_run else "  (a run did not reach its frame count)"))
            for t, s in sorted(r["tracks"].items()):
                if s["first"]:
                    print(f"      T{t + 1} first difference: {s['first']}")
            if r["tagged"]:
                print(f"      {r['tagged']} passes of the new image carry an engine tag out of range")
            for nt in r.get("notes", []):
                print("     ", nt)
    OUTD.mkdir(parents=True, exist_ok=True)
    (OUTD / "results.json").write_text(json.dumps(results, indent=1, default=str))
    bad = [r for r in results if not (r["ok"] and r["reached"])]
    print(f"\n{len(results) - len(bad)}/{len(results)} scenarios identical")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
