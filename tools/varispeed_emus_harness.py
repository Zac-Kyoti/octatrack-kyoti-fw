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

    new     VARI (TSTR 4) + EMUS OT / S950 / SP12     out/mainos_varispeed_emus.bin
    oracle  TSTR 4 (RPCH) / 5 (RPS9) / 6 (RPSP)       out/oracle/shipped_repitch_repeat98_kyoti_FINAL.bin
    stock   for the out-of-range cases: TSTR OFF      out/raw/section_3_MAIN_OS.bin

Per track the comparison starts at its first trig pass after the value pokes (the new
image latches the engine at a trig, the oracle takes it from TSTR at once).

  python3 tools/varispeed_emus_harness.py [--quick] [--only NAME] [--jobs N] [--plain]

--plain: VARISPEED, the plain build (out/mainos_varispeed.bin, spec §7), which must equal
VARISPEED_EMUS on EMUS = OT bit for bit: every track on OT, no EMUS pokes (TSNS stays TSNS);
  VARI tracks          vs the oracle's TSTR 4 (the shipped image on RPCH = VARISPEED_EMUS
                       on OT, proven by the default mode), every bit of l:$40
  stock TSTR / TSMODE  vs STOCK 1.40C, every bit (VARISPEED masks nothing: stock's own
                       engine-bit garbage must come through; the count is printed)
  PICKUP (pickup_mix)  vs STOCK, every bit
  out of range         vs STOCK on TSTR OFF, every bit

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
OUTD = pathlib.Path(os.environ.get("VEM_OUT", SCR / (("harness_plain_" if "--plain" in sys.argv else "harness_")
                                                     + os.environ.get("VEM_PROJECT", "otdemo"))))
PLAIN = "--plain" in sys.argv                  # VARISPEED (see the docstring)
IMAGES = {"new": ROOT / ("out/mainos_varispeed.bin" if PLAIN else "out/mainos_varispeed_emus.bin"),
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
VOICE = 0x800049d8                  # per-track voice state, stride 168; +8 = the sample settings it plays
SLOT = PRJ["slots"]                 # the track's sample slot (dumped from the loaded project)
MACH = PRJ["m"]                     # its machine: 1 FLEX / 0 STATIC
PICKUP, SET_MACHINE = 4, 0x400972fc  # machine select's refresher (part, track)
QUAN = [4 + 15 * i for i in range(9)]          # the 9 stops: 1/2 .. 2/1
EMUS = {"OT": 1, "S950": 64, "SP12": 127}      # the EMUS stops, left to right (2026-10-14)
ORACLE_TSTR = {"OT": 4, "S950": 5, "SP12": 6}
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


def part_only(o, v):
    return [u8(DB + o, v), u8(SHADOW + o, v)]


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
            if cfg.get("pre") and c["mode"] in ("VARI", "AUTO"):
                # the value in the slot AND in the park the swap would bring in: adopted or
                # swapped, the track starts with it (new: NEIGHBOR p1 s0 / s5 by machine;
                # the shipped design parks PTCH in NEIGHBOR p1 s0 for both, retained code)
                for pk in ({18 if m == 0 else 23} | ({18} if image == "oracle" else set())):
                    s2 += part_only(OFF_P1 + PART * PSTRIDE + 30 * t + pk, c["quan"])
        if "rate" in c:
            s2 += p1(t, m, 3, c["rate"])
        if image == "new" and c["mode"] in ("VARI", "AUTO") and not PLAIN:
            s2 += p2(t, m, 5, EMUS[e])
            if cfg.get("pre"):
                s2 += part_only(OFF_P2 + PART * PSTRIDE + 30 * t + (23 if m == 0 else 21), EMUS[e])
    st = []
    if s0:
        st.append(f"1:poke:" + ";".join(s0))
        for t, c in cfg["tracks"].items():
            if c["mode"] == "PICKUP":
                st.append(f"1:call:{SET_MACHINE:#x},{PART},{t}")
    f1, f2 = ("-", "-") if cfg.get("pre") else (T_SET, T_VAL)
    if cfg.get("tempo"):
        st.append(f"{f1}:call:{SET_TEMPO:#x},{cfg['tempo']}")
    if s1:
        st.append(f"{f1}:poke:" + ";".join(s1))
    if s2:
        st.append(f"{f2}:poke:" + ";".join(s2))
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
        a = f"{log} --sequencer --internal-clock --frames {frames}"
        a += f" --step -:dump:0x46c82456,4={d / (name + '.dbptr')};0x80000003,1={d / (name + '.part')}"
        a += f" --step {frames - 5}:dump:{VOICE:#x},{168 * 8:#x}={d / (name + '.voice')}"
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


def compare(a, b, cfg, label, ymask=0xffffff, only=None):
    """a/b: parse() results. Per track, from its first trig pass after SKIP_FRAMES.
    ymask: the y:$40 bits compared (out of range vs stock: all but the engine bits 0-1,
    which stock leaves arbitrary and the new image must keep 0 -- counted separately).
    only: the tracks compared (None: all). ref_tagged counts the reference's compared
    passes whose engine bits (y:$40 bits 0-1) are nonzero."""
    res = {"label": label, "tracks": {}, "ok": True, "tagged": 0, "ref_tagged": 0}
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
            if only is not None and t not in only:
                if (x[0], x[1]) != (y[0], y[1]):
                    res["ok"] = False
                    res.setdefault("notes", []).append(f"core {core} pass {i}: pass order differs {x[:2]} {y[:2]}")
                    break
                continue
            if (x[2], x[3] & ymask) != (y[2], y[3] & ymask):       # the whole run, transitions too
                res.setdefault("whole_run", []).append(
                    (i // (2 * ntrk), t + 1, x[1], f"{x[2]:06x}:{x[3]:06x}", f"{y[2]:06x}:{y[3]:06x}"))
            if (x[0], x[1]) != (y[0], y[1]):
                res["ok"] = False
                res.setdefault("notes", []).append(f"core {core} pass {i}: pass order differs {x[:2]} {y[:2]}")
                break
            st = per.setdefault(t, dict(started=False, n=0, diff=0, first=None, trigs=0))
            frame = i // (2 * ntrk)
            if not st["started"]:
                # set before the transport: from frame 10 (the first-sight frames aside, see
                # the whole-run list); a PICKUP track (it never trigs in these patterns): from
                # SKIP_FRAMES; otherwise from the track's first trig after SKIP_FRAMES
                pu = cfg["tracks"].get(t, {}).get("mode") == "PICKUP"
                if (cfg.get("pre") and frame >= 10) or (frame >= SKIP_FRAMES and (pu or (x[4] and x[1] == 1))):
                    st["started"] = True
                else:
                    continue
            st["n"] += 1
            st["trigs"] += x[4] and x[1] == 1
            res["ref_tagged"] += bool(y[3] & 3)
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
    res["compared"] = sum(st["n"] for st in res["tracks"].values())
    if not res["compared"]:                 # nothing compared proves nothing
        res["ok"] = False
        res.setdefault("notes", []).append("NOTHING COMPARED: no compared track reached its start")
    return res


def not_vari(log, cfg):
    """VARISPEED (--plain): the AUTO tracks of a scenario whose voice, at the run's end,
    plays another sample than the slot the scenario set to VARI (a sample lock): they are
    NOT VARI tracks (the runtime gate), so they play stock, and VARISPEED leaves stock's
    increment untouched (no mask, spec §7) where the oracle masks it. They are compared
    against stock 1.40C instead, every bit."""
    v = pathlib.Path(str(log)[:-4] + ".voice").read_bytes()
    base = SET_FLEX if MACH == 1 else SET_STATIC
    out = set()
    for t, c in cfg["tracks"].items():
        ptr = int.from_bytes(v[168 * t + 8:168 * t + 12], "big")
        if c["mode"] == "AUTO" and ptr != base + SLOT[t] * SET_STRIDE:
            out.add(t)
    return out


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
    # set before the transport starts: every pass compared, from the first frame
    for e in emus_list:
        tr = {t: dict(mode="VARI", emus=e, quan=QUAN[(t * 3 + 1) % 9], rate=rates[t]) for t in range(7)}
        sc[f"pre_{e}"] = dict(tempo=None, tracks=tr, pre=True)
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


def plain_matrix(quick):
    """VARISPEED: the matrix with every track on OT (it has no EMUS), one copy of each."""
    sc = {}
    full = matrix(False)
    for k, cfg in full.items():
        if any(x in k for x in ("_S950", "_SP12")) or (quick and k not in matrix(True) and k != "stock_tstr_0"):
            continue                    # the quick set: its own + one stock TSTR scenario
        sc[k] = dict(cfg, tracks={t: dict(c, emus="OT") for t, c in cfg["tracks"].items()})
    return sc


def plain_groups(sc):
    """VARISPEED: (tag, scenarios, (image a, image b), {name: tracks compared or None}).
    VARI tracks against the oracle's TSTR 4; stock TSTR / TSMODE and PICKUP tracks against
    stock 1.40C, every bit."""
    vari = {k: v for k, v in sc.items() if not k.startswith("stock_tstr")}
    only_v = {k: {t for t, c in v["tracks"].items() if c["mode"] != "PICKUP"} for k, v in vari.items()}
    stock = {k: v for k, v in sc.items() if k.startswith("stock_tstr") or k == "pickup_mix"}
    only_s = {k: (None if k.startswith("stock_tstr") else
                  {t for t, c in v["tracks"].items() if c["mode"] == "PICKUP"}) for k, v in stock.items()}
    return [("eq", vari, ("new", "oracle"), only_v), ("stk", stock, ("new", "stock"), only_s)]


def oor_matrix():
    """Out of range (sample BPM 0 / 719 / 7201): the new image must equal STOCK with TSTR OFF."""
    sc = {}
    for bpm in (0, 719, 7201):
        trn = {t: dict(mode="VARI", emus="SP12", quan=QUAN[t], rate=[127, 96, 32, 0, 127, 112, 16][t],
                       bpm24=bpm) for t in range(7)}
        sc[f"oor_{bpm}"] = dict(tempo=None, tracks=trn)
    return sc


def run_audio(image, name, steps, frames, tag):
    """One process per scenario (a --scenario child does not capture audio): --audio-out
    PREFIX writes PREFIX_core0.wav / _core1.wav, every TX0 frame each core put out."""
    d = OUTD / tag / image
    d.mkdir(parents=True, exist_ok=True)
    args = [str(EMU), "--image", str(IMAGES[image]), "--card", str(CARD), "--set", PRJ["set"],
            "--project", PRJ["project"], "--load-ms", "20000", "--dsp", "--main-level", "64",
            "--sequencer", "--internal-clock", "--frames", str(frames), "--audio-out", str(d / name)]
    for st in steps:
        args += ["--step", st]
    return subprocess.Popen(args, stdout=open(d / f"{name}.log", "w"), stderr=subprocess.STDOUT)


def wav(path):
    import wave
    import numpy as np
    w = wave.open(str(path))
    raw = w.readframes(w.getnframes())
    sw = w.getsampwidth()
    if sw == 3:                                      # 24-bit little-endian
        b = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
        a = (b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)).astype(np.int32)
        a = np.where(a & 0x800000, a - 0x1000000, a).astype(float)
    else:
        a = np.frombuffer(raw, dtype={2: np.int16, 4: np.int32}[sw]).astype(float)
    return a.reshape(-1, w.getnchannels()) / 2 ** (8 * sw - 1), w.getframerate()


def audio_compare(pa, pb, skip_s=0.05):
    """Levels and spectra per channel, compared FROM EACH RECORDING'S SOUND ONSET: RMS per
    50 ms window and 1/3-octave band levels over the audible part, after `skip_s`. The two
    images run different ColdFire code, so the emulator starts the sound a few samples
    apart (2026-10-14: 2-5 samples, OT included, whose DSP path is stock) and the files
    are silent until the project has loaded (~16.5 s of a 17.6 s run). Comparing whole
    files therefore compared mostly silence plus a ~1 s tail. Run enough --frames for
    several seconds of sound. Samples are never compared: a few samples of timing
    already moves every high-frequency phase."""
    import numpy as np
    a, fr = wav(pa)
    b, _ = wav(pb)
    def onset(x):
        hot = np.nonzero(np.abs(x).max(axis=1) > 1e-4)[0]
        return int(hot[0]) if len(hot) else 0
    oa, ob = onset(a), onset(b)
    n = min(len(a) - oa, len(b) - ob)
    k = int(skip_s * fr)
    a, b = a[oa + k:oa + n], b[ob + k:ob + n]
    audible_s, lag = round(len(a) / fr, 2), oa - ob
    out = {}
    win = int(0.05 * fr)
    db = lambda x: 20 * np.log10(max(x, 1e-9))
    for ch in range(a.shape[1]):
        ra = [db(np.sqrt(np.mean(a[i:i + win, ch] ** 2))) for i in range(0, len(a) - win, win)]
        rb = [db(np.sqrt(np.mean(b[i:i + win, ch] ** 2))) for i in range(0, len(b) - win, win)]
        loud = [(x, y) for x, y in zip(ra, rb) if max(x, y) > -60]
        if not loud:
            continue
        rms_dev = max(abs(x - y) for x, y in loud)
        fa = np.abs(np.fft.rfft(a[:, ch] * np.hanning(len(a)))) ** 2
        fb = np.abs(np.fft.rfft(b[:, ch] * np.hanning(len(b)))) ** 2
        f = np.fft.rfftfreq(len(a), 1 / fr)
        bands, dev = [], 0.0
        fc = 31.5
        while fc < fr / 2 / 1.12:
            m = (f >= fc / 2 ** (1 / 6)) & (f < fc * 2 ** (1 / 6))
            if m.any():
                la, lb = 10 * np.log10(fa[m].sum() + 1e-30), 10 * np.log10(fb[m].sum() + 1e-30)
                if max(la, lb) > 10 * np.log10(max(fa.sum(), fb.sum()) + 1e-30) - 60:
                    dev = max(dev, abs(la - lb))
            fc *= 2 ** (1 / 3)
        out[ch] = dict(windows=len(loud), rms_max_dev_db=round(rms_dev, 2), band_max_dev_db=round(dev, 2),
                       audible_s=audible_s, onset_lag=lag)
    return out


def main_audio(frames, jobs):
    """New vs oracle audio, by level and spectrum, for the three engines."""
    names = [f"pre_{e}" for e in ("OT", "S950", "SP12")]
    sc = matrix(True)
    if not os.environ.get("VEM_AUDIO_REUSE"):
        procs = []
        for n in names:
            for img in ("new", "oracle"):
                procs.append(run_audio(img, n, scenario_steps(sc[n], img), frames, "audio"))
        for p in procs:
            p.wait()
    res = {}
    ok = True
    for n in names:
        for core in (0, 1):
            pa = OUTD / "audio" / "new" / f"{n}_core{core}.wav"
            pb = OUTD / "audio" / "oracle" / f"{n}_core{core}.wav"
            if not (pa.exists() and pb.exists()):        # only the core that puts out TX0
                continue
            r = audio_compare(pa, pb)
            res[f"{n} core{core}"] = r
            bad = [c for c, v in r.items() if v["rms_max_dev_db"] > 1.0 or v["band_max_dev_db"] > 1.0]
            ok &= not bad
            print(f"  {'MATCH ' if not bad else 'DIFFER'} {n} core {core}: " +
                  "; ".join(f"ch{c} {v['windows']} windows, RMS max {v['rms_max_dev_db']} dB, "
                            f"1/3-oct max {v['band_max_dev_db']} dB" for c, v in r.items())
                  + (f"  [{next(iter(r.values()))['audible_s']} s of sound compared; onsets "
                     f"{next(iter(r.values()))['onset_lag']:+d} samples apart]" if r else ""))
    (OUTD / "audio" / "results.json").write_text(json.dumps(res, indent=1))
    sys.exit(0 if ok else 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--only", default="")
    ap.add_argument("--jobs", type=int, default=6)
    ap.add_argument("--frames", type=int, default=3000)
    ap.add_argument("--reuse", action="store_true", help="compare existing logs only")
    ap.add_argument("--audio", action="store_true", help="the audio comparison (levels, spectra)")
    ap.add_argument("--plain", action="store_true", help="VARISPEED, the plain build (see the docstring)")
    a = ap.parse_args()
    if a.audio:
        return main_audio(a.frames, a.jobs)
    import hashlib
    if not os.environ.get("VEM_IMG_ORACLE") and \
            hashlib.sha256(IMAGES["oracle"].read_bytes()).hexdigest() != ORACLE_SHA:
        sys.exit("the oracle image is not the shipped FINAL (sha256 90b4a1c1...)")
    results = []
    sc = plain_matrix(a.quick) if PLAIN else matrix(a.quick)
    if a.only:
        sc = {k: v for k, v in sc.items() if a.only in k}
    groups = plain_groups(sc) if PLAIN else [("eq", sc, ("new", "oracle"), {})]
    oor = oor_matrix()
    if not a.only or "oor" in a.only:
        groups.append(("oor", oor, ("new", "stock"), {}))
    for tag, scens, (ia, ib), only in groups:
        if not scens:
            continue
        logs = {}
        # VARISPEED, the VARI group: scenarios with AUTO tracks also run on stock, for the
        # tracks that turn out not to play as VARI (not_vari)
        auto = PLAIN and tag == "eq" and any(c["mode"] == "AUTO" for v in scens.values()
                                              for c in v["tracks"].values())
        for img in (ia, ib) + (("stock",) if auto else ()):
            st = {}
            for n, cfg in scens.items():
                # the stock reference of an out-of-range case: TSTR OFF, same values (the
                # VARI group's stock run: the same values, AUTO as AUTO)
                # (2026-10-15: this used to apply to EVERY stock run, so the VARISPEED stock
                # group's PICKUP tracks ran as FLEX on TSTR OFF on stock: only "oor" wants it)
                c = cfg if not (img == "stock" and tag == "oor") else \
                    dict(cfg, tracks={t: dict(v, mode="OFF") for t, v in cfg["tracks"].items()})
                st[n] = scenario_steps(c, img)
            if a.reuse:
                logs[img] = {n: OUTD / tag / img / f"{n}.log" for n in scens}
            else:
                print(f"[{tag}] running {img}: {len(scens)} scenarios ...", flush=True)
                logs[img] = run(img, st, a.frames, a.jobs, tag)
        pairs = []
        for n in scens:
            nv = not_vari(logs[ia][n], scens[n]) if auto else set()
            if nv:
                o = (only.get(n) if only.get(n) is not None else set(scens[n]["tracks"])) - nv
                pairs.append((n, ib, o, ""))
                pairs.append((n, "stock", nv, " -- not VARI (its voice plays another sample)"))
            else:
                pairs.append((n, ib, only.get(n), ""))
        for n, ref, o, why in pairs:
            la, lb = logs[ia][n], logs[ref][n]
            ok_run = all("run ended REACHED" in p.read_text() for p in (la, lb) if p.exists())
            r = compare(parse(str(la) + ".vem"), parse(str(lb) + ".vem"), scens[n],
                        f"{tag}:{n} {ia} vs {ref} [{PRJ['project']}]"
                        + (f" (tracks {','.join(f'T{t + 1}' for t in sorted(o))}{why})" if o else ""),
                        0xfffffc if tag == "oor" and not PLAIN else 0xffffff, o)
            r["reached"] = ok_run
            results.append(r)
            tr = " ".join(f"T{t + 1}:{s['n']}/{s['diff']}{'' if s['started'] else '(no trig)'}"
                          for t, s in sorted(r["tracks"].items()))
            print(f"  {'IDENTICAL' if r['ok'] and ok_run else 'DIFFER   '} {r['label']}  [{tr}]"
                  + ("" if ok_run else "  (a run did not reach its frame count)"))
            for t, s in sorted(r["tracks"].items()):
                if s["first"]:
                    print(f"      T{t + 1} first difference: {s['first']}")
            w = r.get("whole_run", [])
            if w:
                print(f"      whole run (transitions included): {len(w)} differing pass(es), first "
                      + ", ".join(f"frame {f} T{t} LC{lc} {a_}/{b_}" for f, t, lc, a_, b_ in w[:4]))
            if r["tagged"]:
                print(f"      {r['tagged']} passes of the new image carry an engine tag out of range")
            if PLAIN and ref == "stock":
                print(f"      stock's own engine bits (y:$40 bits 0-1) nonzero on {r['ref_tagged']} compared "
                      f"pass(es): {'carried through unmasked' if r['ok'] else 'see the differences'}")
            for nt in r.get("notes", []):
                print("     ", nt)
    OUTD.mkdir(parents=True, exist_ok=True)
    (OUTD / "results.json").write_text(json.dumps(results, indent=1, default=str))
    bad = [r for r in results if not (r["ok"] and r["reached"])]
    print(f"\n{len(results) - len(bad)}/{len(results)} scenarios identical")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
