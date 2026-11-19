#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
"""
VARISPEED / VARISPEED_EMUS -- QUAN on entering VARI (VARIG2), through the REAL panel in ot_emu.

The author's rule (2026-11-19): QUAN is ALWAYS 1/1 when a track goes to VARI, unless that track
had QUAN set to something else, left VARI and came back (then it shows that value). PTCH comes
back unchanged when the track leaves VARI.

Every case boots a real hardware export (OTDEMO: T1-T7 FLEX, part 1; MMTESTDT: T1-T8 STATIC,
part 0), sets its starting bytes by runtime pokes after the load, then drives the panel with a
live script (SRC SETUP opened with [SRC] twice, TSTR turned with encoder E, QUAN with encoder
A, the page closed with [SRC]), and reads the Part block, the live bytes and the screen at the
end. Nothing is written to a project file but by the firmware itself (the SAVE / RELOAD case
saves through the PROJECT menu onto a copy of the card).

    python3 tools/varispeed_quan_entry_test.py IMAGE [--only a,b] [--jobs N] [--out DIR]

IMAGE: a VARISPEED or VARISPEED_EMUS unit / feature image, or a KYOTI image (rp_prev is found
from the unit's ratio table). The emulator: VEM_EMU, else out/emu/octabam/out/emu/ot_emu.

Cases (T1 unless said; PTCH raw 64 = 0, 76 = +12, 59 = -5; QUAN 64 = 1/1, 79 = 5/4, 109 = 3/2):
  ptch0       PTCH 0 -> VARI: QUAN 1/1; PTCH parked (64)
  p12         PTCH +12 -> VARI: QUAN 1/1, PTCH parked (76); back to BEAT: PTCH +12, QUAN 1/1
              remembered (0x80 | 64)
  m5          PTCH -5 -> VARI: QUAN 1/1; back to BEAT: PTCH -5
  mem32       PTCH +12 -> VARI -> QUAN 3/2 -> BEAT -> VARI: QUAN 3/2 again, PTCH +12 parked; the
              switch drawn on 3/2
  legacy      a park an older build left off VARI (76, no bit 7: the 5/4 the author saw) -> VARI:
              QUAN 1/1
  forgot      SRC SETUP open, rp_prev forgotten (as a Part apply / reload / another Part does)
              before TSTR goes to VARI: QUAN 1/1 (FINAL: the PTCH value read as QUAN, 5/4)
  stale       a track already on VARI (QUAN 1/1, PTCH +12 parked) whose rp_prev says off VARI
              (a poll missed): the rule holds, QUAN 1/1 (FINAL: 5/4)
  auto        TSTR AUTO, the sample's TIMESTRETCH set to VARI (the gate opens without a TSTR
              edit), rp_prev forgotten first: QUAN 1/1, PTCH parked
  partsw      Part 1 (the playing one) T1 not VARI (PTCH +12); Part 0 T1 TSTR VARI over PTCH +12
              (a Part whose bytes never entered VARI): pattern 1 (Part 0) brings T1 onto VARI:
              QUAN 1/1 there, PTCH +12 parked; back to pattern 5: PTCH +12, not VARI
  st_p12      STATIC (MMTESTDT, part 0): as p12
  st_mem32    STATIC: as mem32
  reload      mem32's end state, SAVE PROJECT, RELOAD PROJECT: QUAN 3/2, PTCH +12 parked
  power       mem32's end state, then a power cycle (CS1 kept): QUAN 3/2, PTCH +12 parked
  midi        p12 on T1, then the MIDI page and a MIDI track key: every Part byte but T1's three
              (PTCH slot, its park, TSTR; VARISPEED_EMUS: + TSNS and its park) as loaded -- the MIDI
              tracks' and the other tracks'
"""
import argparse, concurrent.futures as cf, json, os, pathlib, shutil, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
EMU = pathlib.Path(os.environ.get("VEM_EMU", ROOT / "out/emu/octabam/out/emu/ot_emu"))
CARDS = ROOT / "out/vem/img"
sys.path.insert(0, str(ROOT / "out/emu/octabam/tools/emu"))
DB, PSTRIDE, SHADOW = 0x400e21e0, 0x18b2, 0x100a4ece
O_P1, O_P2, O_MACH, O_SLOT5 = 0x2a, 0x1da, 0x22, 0x2ca
LIVE_P1, BASE_W = 0x80000810, 0x80000a50
SET_STATIC, SET_FLEX, SET_STRIDE = 0x100d5b30, 0x100b14f0, 0x448
PARK1 = {0: 18, 1: 23}
PROJ = {"otdemo": ("otdemo.img", "KYOTI", "OTDEMO", 1, 1), "mmtestdt": ("mmtestdt.img", "MMTESTDT", "test", 0, 0)}
K = dict(DOWN=0x20, UP=0x33, YES=0x31, NO=0x32, SRC=0x22, FUNC=0x2d, MIX=0x30, RIGHT=0x21, PTN=0x2e,
         MIDI=0x35, T1=0x10, T2=0x11, TR1=0x00, TR5=0x04)
RAT = bytes([1, 2, 2, 3, 3, 4, 4, 5, 1, 1, 5, 4, 4, 3, 3, 2, 2, 1])
LAB = ["1/2", "2/3", "3/4", "4/5", "1/1", "5/4", "4/3", "3/2", "2/1"]


def bucket(v):
    return min(8, (v + 3) // 15)


def rp_prev_of(img):
    """rp_prev: behind the ratio table (VARISPEED_EMUS: and its two 3-byte tables), 4-aligned."""
    d = img.read_bytes()
    o = 0x400d6500 - 0x40000400
    i = d.find(RAT, o, o + 0x2000)
    if i < 0:
        sys.exit(f"{img}: no VARISPEED ratio table in the classic cave")
    vem = d.find(b"SP12\0", o, o + 0x2000) >= 0
    a = 0x40000400 + i + 18 + (6 if vem else 0)
    return (a + 3) & ~3, vem


def b(a, v):
    return f"{a:#x}={v & 0xff:#x}"


class Flow:
    def __init__(self):
        self.t, self.lines = 300, []
        self.tap("NO")                   # the SET DATE/TIME dialog the emulator boots with

    def tap(self, k, dt=200):
        self.lines += [f"{self.t} key {K[k]:#x} down", f"{self.t + 80} key {K[k]:#x} up"]
        self.t += dt

    def chord(self, a, k):
        self.lines += [f"{self.t} key {K[a]:#x} down", f"{self.t + 50} key {K[k]:#x} down",
                       f"{self.t + 130} key {K[k]:#x} up", f"{self.t + 180} key {K[a]:#x} up"]
        self.t += 400

    def enc(self, n, d, cnt):
        for _ in range(cnt):
            self.lines.append(f"{self.t} enc {n} {d}")
            self.t += 100
        self.t += 200

    def wait(self, ms):
        self.t += ms

    def poke(self, items):
        self.lines.append(f"{self.t} poke {';'.join(items)}")
        self.t += 50

    def text(self):
        return "\n".join(self.lines + [f"{self.t + 800} quit"]) + "\n"

    # the page moves: SRC SETUP opens with [SRC] tapped twice (as on the unit), a third tap closes it
    def setup(self, trk):
        self.tap(trk); self.wait(300); self.tap("SRC"); self.tap("SRC")

    def close(self):
        self.tap("SRC"); self.wait(400)

    def vari(self, trk="T1"):            # select, SRC SETUP, TSTR AUTO -> VARI (four stops), close
        self.setup(trk); self.enc(4, 1, 16); self.close()

    def beat(self, trk="T1"):            # SRC SETUP, TSTR VARI -> BEAT, close
        self.setup(trk); self.enc(4, -1, 6); self.close()       # 6 detents: one stop down after the turn up

    def quan(self, steps):               # three single detents per ratio
        self.enc(0, 1 if steps > 0 else -1, 3 * abs(steps)); self.wait(300)


def part_pokes(part, t, m, ptch=None, park=None, tstr=None, live=True):
    pb, sh = DB + 0x8ed80 + part * PSTRIDE, SHADOW + part * PSTRIDE
    out = []
    for off, v in ((O_P1 + 30 * t + 6 * m, ptch), (O_P1 + 30 * t + PARK1[m], park), (O_P2 + 30 * t + 6 * m + 4, tstr)):
        if v is not None:
            out += [b(pb + off, v), b(sh + off, v)]
    if live and ptch is not None:
        out += [b(LIVE_P1 + 72 * t, ptch), b(BASE_W + 64 * t, ptch), b(BASE_W + 64 * t + 1, 0)]
    return out


def run(case, img, rpp, d, proj, flow, pokes, extra=(), card=None, dump_parts=(1,), more_dump=""):
    cardf, st, pr, _, _ = PROJ[proj]
    d.mkdir(parents=True, exist_ok=True)
    (d / "panel.script").write_text(flow.text())
    dumps = ";".join(f"{DB + 0x8ed80 + p * PSTRIDE:#x},{PSTRIDE:#x}={d / f'p{p}.part'}" for p in dump_parts)
    cmd = [str(EMU), "--image", str(img), "--card", str(card or CARDS / cardf), "--set", st, "--project", pr,
           "--load-ms", "20000", "--live-script", str(d / "panel.script"), "--lcd", str(d / "lcd.bin"),
           "--mem-dump", f"{dumps};{LIVE_P1:#x},0x240={d / 'live.bin'};{rpp:#x},16={d / 'prev.bin'}{more_dump}"] + list(extra)
    if pokes:
        cmd += ["--poke", ";".join(pokes)]
    (d / "cmd.json").write_text(json.dumps(cmd, indent=1))
    with open(d / "log.txt", "w") as f:
        subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, timeout=4 * 3600)
    import lcd_view as L
    rows = L.screen((d / "lcd.bin").read_bytes())
    L.png(rows, str(d / "end.png"))
    parts = {p: (d / f"p{p}.part").read_bytes() for p in dump_parts}
    return parts, (d / "live.bin").read_bytes(), (d / "prev.bin").read_bytes(), rows


def knob(rows):
    """the PTCH / QUAN dial's cell on the PLAYBACK page (screen x 62..92, y 12..34)"""
    return tuple(tuple(r[62:93]) for r in rows[12:35])


class Res:
    def __init__(self, name):
        self.name, self.fails, self.notes = name, [], []

    def eq(self, what, got, want):
        (self.notes if got == want else self.fails).append(f"{what}: got {got!r}" + ("" if got == want else f", want {want!r}"))


def t1(parts, part, t=0, m=1):
    p = parts[part]
    return dict(slot=p[O_P1 + 30 * t + 6 * m], park=p[O_P1 + 30 * t + PARK1[m]], tstr=p[O_P2 + 30 * t + 6 * m + 4])


def case_run(name, img, rpp, vem, outd):
    d = outd / name
    r = Res(name)
    if name in ("ptch0", "p12", "m5", "mem32", "legacy", "forgot", "stale", "auto", "midi"):
        proj, part, m = "otdemo", 1, 1
        ptch = {"ptch0": 64, "m5": 59, "legacy": 64}.get(name, 76)   # legacy: the PTCH such a swap lost
        f = Flow()
        pokes = part_pokes(part, 0, m, ptch=ptch, park=76 if name == "legacy" else 0)
        if name == "auto":
            slot = 20                        # T1's FLEX slot in OTDEMO's part 1
            pokes += [b(SET_FLEX + SET_STRIDE * slot + 0x110 + 3, 4)]   # its TIMESTRETCH: VARI (TSTR stays AUTO)
            f.tap("T1"); f.tap("SRC"); f.wait(300)
            f.poke([b(rpp + 1, 0xff)])                                   # forgotten, as after a Part apply
            f.tap("T2"); f.tap("T1"); f.wait(500)
        elif name == "forgot":
            f.tap("T1"); f.tap("SRC"); f.tap("SRC"); f.wait(300)        # SETUP open: T1 polled (off VARI)
            f.poke([b(rpp + 1, 0xff)])                                   # then forgotten
            f.enc(4, 1, 16); f.tap("SRC"); f.wait(400)
        elif name == "stale":
            f.vari()                                                     # on VARI: QUAN 1/1, PTCH +12 parked
            f.poke([b(rpp + 1, 0)])                                      # a missed poll: rp_prev says off VARI
            f.tap("T2"); f.tap("T1"); f.wait(500)
        else:
            f.vari()
            if name in ("p12", "m5"):
                f.beat()
            if name == "mem32":
                f.quan(3); f.beat(); f.vari()
            if name == "midi":
                f.tap("MIDI"); f.tap("T2"); f.wait(300); f.tap("T1"); f.wait(300)
        parts, live, prev, rows = run(name, img, rpp, d, proj, f, pokes)
        x = t1(parts, part, 0, m)
        if name == "ptch0":
            r.eq("T1 TSTR / QUAN / park", (x["tstr"], x["slot"], x["park"]), (4, 64, 64))
        elif name in ("p12", "m5"):
            r.eq("after BEAT: TSTR / PTCH / park (QUAN 1/1 remembered)", (x["tstr"], x["slot"], x["park"]), (3, ptch, 0x80 | 64))
            r.eq("live PTCH byte", live[0], ptch)
        elif name == "mem32":
            r.eq("back on VARI: TSTR / QUAN / park (PTCH +12)", (x["tstr"], x["slot"], x["park"]), (4, 109, 76))
            r.eq("QUAN reads", LAB[bucket(x["slot"])], "3/2")
            r.eq("live QUAN byte", live[0], 109)
        elif name in ("legacy", "forgot", "auto"):
            r.eq("TSTR / QUAN / park", (x["tstr"], x["slot"], x["park"]), (1 if name == "auto" else 4, 64, 76 if name != "legacy" else 64))
            r.eq("QUAN reads", LAB[bucket(x["slot"])], "1/1")
            r.eq("live QUAN byte", live[0], 64)
        elif name == "stale":
            r.eq("QUAN reads (the rule)", LAB[bucket(x["slot"])], "1/1")
            r.notes.append(f"stale: QUAN {x['slot']}, park {x['park']} (the parked PTCH a missed poll loses)")
        elif name == "midi":
            base = (outd / "_base_otdemo" / "p1.part")
            if not base.exists():
                g = Flow()
                run("_base_otdemo", img, rpp, outd / "_base_otdemo", proj, g, part_pokes(part, 0, m, ptch=76, park=0))
            b0 = base.read_bytes()
            own = {O_P1 + 6 * m, O_P1 + PARK1[m], O_P2 + 6 * m + 4}
            if vem:                          # VARISPEED_EMUS: the TSNS / EMUS pair swaps with it
                own |= {O_P2 + 6 * m + 5, O_P2 + {0: 23, 1: 21}[m]}
            diff = [hex(i) for i in range(PSTRIDE) if b0[i] != parts[part][i] and i not in own]
            r.eq("Part bytes changed besides T1's PTCH slot / park / TSTR", diff, [])
            r.eq("T1", (x["tstr"], x["slot"], x["park"]), (4, 64, 76))
        if name in ("ptch0", "legacy", "forgot", "mem32"):
            (d / "knob.json").write_text(json.dumps(knob(rows)))
    elif name == "partsw":
        f = Flow()
        pokes = part_pokes(1, 0, 1, ptch=76, park=0) + part_pokes(0, 0, 1, ptch=76, park=0, tstr=4, live=False)
        f.tap("T1"); f.tap("SRC"); f.wait(300)
        f.chord("PTN", "TR1"); f.wait(1500); f.tap("T2"); f.tap("T1"); f.wait(500)
        parts, live, prev, rows = run(name + "_a", img, rpp, d / "a", "otdemo", f, pokes, dump_parts=(0, 1))
        x0, x1 = t1(parts, 0), t1(parts, 1)
        r.eq("pattern 1 (Part 0): T1 TSTR / QUAN / park", (x0["tstr"], x0["slot"], x0["park"]), (4, 64, 76))
        r.eq("Part 1 untouched", (x1["tstr"], x1["slot"], x1["park"]), (1, 76, 0))
        f.chord("PTN", "TR5"); f.wait(1500); f.tap("T2"); f.tap("T1"); f.wait(500)
        parts, live, prev, rows = run(name + "_b", img, rpp, d / "b", "otdemo", f, pokes, dump_parts=(0, 1))
        x0, x1 = t1(parts, 0), t1(parts, 1)
        r.eq("back to pattern 5 (Part 1): T1 PTCH +12, off VARI; live PTCH", (x1["tstr"], x1["slot"], x1["park"], live[0]), (1, 76, 0, 76))
        r.eq("Part 0 keeps its entry", (x0["tstr"], x0["slot"], x0["park"]), (4, 64, 76))
    elif name in ("st_p12", "st_mem32"):
        f = Flow()
        f.vari()
        if name == "st_p12":
            f.beat()
        else:
            f.quan(3); f.beat(); f.vari()
        parts, live, prev, rows = run(name, img, rpp, d, "mmtestdt", f, part_pokes(0, 0, 0, ptch=76, park=0), dump_parts=(0,))
        x = t1(parts, 0, 0, 0)
        if name == "st_p12":
            r.eq("STATIC after BEAT: TSTR / PTCH / park", (x["tstr"], x["slot"], x["park"]), (3, 76, 0x80 | 64))
        else:
            r.eq("STATIC back on VARI: TSTR / QUAN / park", (x["tstr"], x["slot"], x["park"]), (4, 109, 76))
    elif name in ("reload", "power"):
        f = Flow()
        f.vari(); f.quan(3); f.beat(); f.vari()
        pokes = part_pokes(1, 0, 1, ptch=76, park=0)
        d.mkdir(parents=True, exist_ok=True)
        if name == "reload":
            card = d / "card.img"
            shutil.copy(CARDS / PROJ["otdemo"][0], card)
            f.chord("FUNC", "MIX"); f.wait(500); f.tap("RIGHT"); f.tap("DOWN"); f.tap("YES"); f.wait(500); f.tap("YES")
            f.wait(20000)                                                # SAVE PROJECT
            f.chord("FUNC", "MIX"); f.wait(500); f.tap("RIGHT"); f.tap("DOWN"); f.tap("YES"); f.wait(500); f.tap("YES")
            f.wait(25000); f.tap("T1"); f.tap("SRC"); f.wait(500)        # RELOAD PROJECT
            parts, live, prev, rows = run(name, img, rpp, d, "otdemo", f, pokes, extra=["--card-rw"], card=card)
        else:
            cs1 = d / "cs1.bin"
            run(name + "_a", img, rpp, d / "a", "otdemo", f, pokes, more_dump=f";0x10000000,0x100000={cs1}")
            g = Flow(); g.wait(2000); g.tap("T1"); g.tap("SRC"); g.wait(800)
            parts, live, prev, rows = run(name + "_b", img, rpp, d / "b", "otdemo", g, [],
                                          extra=["--cs1-in", str(cs1), "--no-post"])
        x = t1(parts, 1)
        r.eq("after the " + ("RELOAD" if name == "reload" else "power cycle") + ": TSTR / QUAN / park", (x["tstr"], x["slot"], x["park"]), (4, 109, 76))
        r.eq("QUAN reads", LAB[bucket(x["slot"])], "3/2")
    return r


CASES = ["ptch0", "p12", "m5", "mem32", "legacy", "forgot", "stale", "auto", "partsw", "st_p12", "st_mem32",
         "reload", "power", "midi"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("--only", default="")
    ap.add_argument("--jobs", type=int, default=6)
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    img = pathlib.Path(a.image).resolve()
    rpp, vem = rp_prev_of(img)
    outd = pathlib.Path(a.out or ROOT / "out/quan_entry" / img.stem).resolve()
    outd.mkdir(parents=True, exist_ok=True)
    names = [c for c in CASES if not a.only or c in a.only.split(",")]
    print(f"{img}  rp_prev {rpp:#x}  ({'VARISPEED_EMUS' if vem else 'VARISPEED'})  -> {outd}", flush=True)
    with cf.ThreadPoolExecutor(a.jobs) as ex:
        res = dict(zip(names, ex.map(lambda n: case_run(n, img, rpp, vem, outd), names)))
    # the switch: the same dial for the same stop on every page drawn (1/1: ptch0, legacy, forgot; 3/2: mem32)
    kn = {n: json.loads((outd / n / "knob.json").read_text()) for n in ("ptch0", "legacy", "forgot", "mem32")
          if (outd / n / "knob.json").exists()}
    ok = 0
    for n in names:
        r = res[n]
        print(("PASS  " if not r.fails else "FAIL  ") + n)
        for x in r.fails:
            print("      FAIL " + x)
        for x in r.notes:
            print("      ok   " + x)
        ok += not r.fails
    if "ptch0" in kn:
        same = all(kn[n] == kn["ptch0"] for n in ("legacy", "forgot") if n in kn)
        diff = "mem32" not in kn or kn["mem32"] != kn["ptch0"]
        print(("PASS  " if same and diff else "FAIL  ") + "switch: the 1/1 dial drawn the same in ptch0 / legacy / forgot, "
              "and another for 3/2 (mem32)")
        ok += same and diff
        names = names + ["switch"]
    print(f"\n{ok}/{len(names)} pass")
    return 0 if ok == len(names) else 1


if __name__ == "__main__":
    sys.exit(main())
