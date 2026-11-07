#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
"""
Validate REC_TRIG_MUTE (out/mainos_rec_trig_mute.bin) in octabam's full-firmware emulator.

Boots the image, loads the factory OT DEMO, then drives:
  1. keys   -- the [REC] keymap handler (rtm_rec) with held tracks poked into 0x460fab40:
               the per-track toggle in RTM_MASK, the CC 80 sends (FUN_40033e3c args), the toast text,
               GRID REC / "REC held" untouched; with no track held, stock [REC] (GRID REC
               toggles); the [TRACK]-layer YES / NO records stock again (ARM / DISARM REC TRK)
  2. CC in  -- the stock CC handler FUN_4000e79c with a real 3-byte message: track channel,
               AUTO channel, value 0 / >0, AUDIO CC IN off, and that CCs we don't own still
               take stock's path (CC 100 ignored, CC 120 -> 0x8000000c bit 0)
  3. gate   -- REC1 poked on every step of T1 and T2 (a runtime RAM poke into the loaded
               pattern, not a project file), T1 muted: the step handler's recorder flag word
               0x46c7a6c0 must get T2's REC1 bit and never T1's; then unmute -> T1's appears
  4. dots   -- (the two tab renderers called directly, in the UI frame's order: route A
               barely runs the UI frame) LCD pixels: two dots stacked beside every muted
               track's machine letter on its inner side (x+4 on T1-4, x-2 on T5-8; rows = the
               letter's top row and two below), inverted on the active tab, a blank pixel
               between letter and dots, none on unmuted or PICKUP tracks; rendered as
               hardware does, the mark painter 0x40044804 last (its '!' column is T1-4's dot
               column): dots over a lit '!', stock '!' elsewhere; the status renderer's cache
               stays stock; LCD screenshots

Every result is printed as PASS / FAIL.  Logic only: route A has no real DSP/audio path, so
whether a recording really stops is a hardware question.

    python3 tools/emu_rec_trig_mute.py [--image out/mainos_rec_trig_mute.bin] [--frames 1500]
    python3 tools/emu_rec_trig_mute.py --image out/KYOTI/mainos_kyoti_v1.0.bin
        (RTM_MASK is then read from the map beside the image: KYOTI places it itself)
"""
import argparse, os, pathlib, struct, subprocess, sys
sys.stdout.reconfigure(line_buffering=True)

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
DEMO = pathlib.Path.home() / "Desktop" / "OT Backup" / "KYOTI" / "OT DEMO"
ELF = ROOT / "out" / "patch_rec_trig_mute.elf"

os.chdir(OCTABAM)
sys.path.insert(0, str(OCTABAM / "tools"))
import toolpath  # noqa: E402,F401
import emu_rtos as er
import emu_card as ec
import emu_bringup as eb
import lcd_view

RTM_MASK, HELD, CACHE = 0x400d7c3a, 0x460fab40, 0x400c0cb8
RENDER = 0x4004bd48                 # the status-icon renderer; on hardware FUN_40052200's
                                    # UI-frame path polls it (0x4005222e), which route A barely runs
LETTERS = 0x4003fed8                # the tab letter renderer, polled right after it (0x40052232)
MARKS = 0x40044804                  # the tab mark painter ('!'), polled last (0x40052238)
LCD = 0x46c7e0ea
REC_FIELDS = (0x400c003c, 0x400c0040, 0x400c0620, 0x400c0624)    # [REC] keymap press/release
TRK_YES_FIELD, TRK_NO_FIELD = 0x400d15e4, 0x400d15fe                # [TRACK]-layer YES / NO
GRID_REC, REC_HELD = 0x460d1736, 0x460d1726
TRK_RELEASE, NOTIFY_CLOSE, TRK_PRESSED = 0x40083e40, 0x40056bec, 0x460fab44
CC_SEND, NOTIFY, CC_HANDLER, BLIT = 0x40033e3c, 0x4005a2b8, 0x4000e79c, 0x400128a8
CC_IN, AUTO_CH, TRIG_CH, MIDI_TRK_FLAGS = 0x80000049, 0x80000047, 0x8000003f, 0x8000000c
FLAGWORD = 0x46c7a6c0
MSG = 0x4005a148                    # test buffer: the zero tail of our own .draw region,
                                    # unused in both the standalone and the KYOTI image
RTM_CC = 80

fails = []


def check(ok, what):
    print(f"  {'PASS' if ok else 'FAIL'}  {what}")
    if not ok:
        fails.append(what)


def syms():
    out = subprocess.run(["m68k-elf-nm", str(ELF)], capture_output=True, text=True).stdout
    return {f[2]: int(f[0], 16) for f in (l.split() for l in out.splitlines()) if len(f) == 3}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", default=str(ROOT / "out" / "mainos_rec_trig_mute.bin"))
    ap.add_argument("--frames", type=int, default=1500)
    ap.add_argument("--png", default=str(ROOT / "out" / "rec_trig_mute_lcd.png"))
    a = ap.parse_args()
    if not pathlib.Path(a.png).is_absolute():          # the module chdir'd into octabam: like --image,
        a.png = str(ROOT / a.png)                       # a relative path is the repo's
    image = pathlib.Path(a.image)
    if not image.is_absolute():
        image = ROOT / image
    global RTM_MASK
    own = image.parent / (image.stem.removeprefix("mainos_") + "_map.json")   # the image's own map,
    maps = [own] if own.exists() else []                                        # never a stale sibling
    if maps:
        import json
        RTM_MASK = int(json.loads(maps[0].read_text())["pieces"]["rtm_mask"]["at"], 16)
        print(f"RTM_MASK {RTM_MASK:#x} (from {maps[0].name})")
    S = syms()
    card, name = er.stage_project(str(DEMO), "OCTABAM", None)
    r, rt = er.attach(str(image), card, tick=True)
    mounted, posted, saved_bank, final_bank, elapsed = rt.load_project_live("OCTABAM", name, run_ms=6000,
                                                                             mount_ms=3000)
    print(f"=== {image.name}: loaded={mounted} ({elapsed:.0f} ms) ===")
    uc = rt.uc
    rd = lambda adr, n: bytes(uc.mem_read(adr, n))
    u8 = lambda adr: rd(adr, 1)[0]
    u32 = lambda adr: struct.unpack(">I", rd(adr, 4))[0]
    w8 = lambda adr, v: uc.mem_write(adr, bytes([v & 0xff]))
    w32 = lambda adr, v: uc.mem_write(adr, struct.pack(">I", v & 0xffffffff))

    def spin():
        rt.run(until=lambda s: s.pc == er.MAIN_SPIN)

    # hooks: CC sends and toasts
    sends, toasts, durs, closes = [], [], [], []

    def on_send(u, adr, size, x):
        sp = u.reg_read(eb.UC_M68K_REG_A7)
        sends.append(struct.unpack(">III", u.mem_read(sp + 4, 12)))

    def on_notify(u, adr, size, x):
        sp = u.reg_read(eb.UC_M68K_REG_A7)
        p = struct.unpack(">I", u.mem_read(sp + 4, 4))[0]
        toasts.append(bytes(u.mem_read(p, 24)).split(b"\0")[0].decode(errors="replace"))
        durs.append(struct.unpack(">I", u.mem_read(sp + 8, 4))[0])

    def on_close(u, adr, size, x):
        closes.append(adr)

    uc.hook_add(eb.UC_HOOK_CODE, on_send, begin=CC_SEND, end=CC_SEND)
    uc.hook_add(eb.UC_HOOK_CODE, on_notify, begin=NOTIFY, end=NOTIFY)
    uc.hook_add(eb.UC_HOOK_CODE, on_close, begin=NOTIFY_CLOSE, end=NOTIFY_CLOSE)
    uc.ctl_flush_tb()

    # ------------------------------------------------------------------ 1. keys
    print("\n1. keys")
    recs = [u32(f) for f in REC_FIELDS]
    check(recs == [S["rtm_rec"]] * 4, f"[REC] keymap fields -> rtm_rec: {[hex(v) for v in recs]}")
    ty, tn = u32(TRK_YES_FIELD), u32(TRK_NO_FIELD)
    check((ty, tn) == (0x400834d8, 0x40083488),
          f"[TRACK]-layer YES / NO records stock: {ty:#010x} / {tn:#010x}")
    check(u8(RTM_MASK) == 0, "RTM_MASK boots 0 (all unmuted)")
    rec = S["rtm_rec"]

    def key(entry, code, event, held):
        sends.clear(); toasts.clear(); durs.clear()
        w32(HELD, held)
        spin()
        rt.call_as_main(entry, args=(code, event))
        w32(HELD, 0)
        return u8(RTM_MASK), list(sends), list(toasts)

    grid0 = u32(GRID_REC)
    w32(REC_HELD, 0)
    m, s, t = key(rec, 0x29, 1, 0b101)
    check(m == 0b101, f"T1+T3 held, REC press -> mask {m:#04x} (muted)")
    check(s == [(0, RTM_CC, 1), (2, RTM_CC, 1)], f"CC sends {s}")
    check(t == ["REC TRIGS MUTED"], f"toast {t}")
    check(durs == [0x3c], f"toast length {[hex(x) for x in durs]} (0x3c = 1.0 s, QLREC's)")
    toast_flag = RTM_MASK + 1
    check(u8(toast_flag) == 1, f"RTM_TOAST set ({u8(toast_flag)})")
    check(u32(GRID_REC) == grid0 and u32(REC_HELD) == 0,
          f"GRID REC unchanged ({u32(GRID_REC)}), 'REC held' not set ({u32(REC_HELD)})")
    m, s, t = key(rec, 0x29, 0, 0b101)
    check(m == 0b101 and not s and not t, "REC release with tracks held -> no change, no send, no toast")
    check(u8(toast_flag) == 1 and u32(REC_HELD) == 0,
          "  ... our toast kept (no release hook runs: KYOTI's QLREC would close it), 'REC held' clear")

    def release(code, held):
        """the stock track-key release handler, with `held` the mask before the release"""
        closes.clear()
        w32(HELD, held)
        w32(TRK_PRESSED, 0)
        spin()
        rt.call_as_main(TRK_RELEASE, args=(code, 0))
        h = u32(HELD)
        w32(HELD, 0)
        return h, len(closes)
    h, c = release(0x10, 0b101)
    check(h == 0b100 and c == 0 and u8(toast_flag) == 1,
          f"T1 released, T3 still held -> toast stays (held {h:#04x}, closes {c}, flag {u8(toast_flag)})")
    h, c = release(0x12, 0b100)
    check(h == 0 and c == 1 and u8(toast_flag) == 0,
          f"T3 released, none held -> our toast closed (closes {c}, flag {u8(toast_flag)})")
    h, c = release(0x10, 0b1)
    check(h == 0 and c == 0, f"a later track release with no toast of ours -> nothing closed (closes {c})")
    m, s, t = key(rec, 0x29, 1, 0b1)
    check(m == 0b100, f"T1 held (muted), REC press -> mask {m:#04x} (T1 unmuted)")
    check(s == [(0, RTM_CC, 0)], f"CC sends {s}")
    check(t == ["REC TRIGS UNMUTED"], f"toast {t}")
    m, s, t = key(rec, 0x29, 1, 0b101)
    check(m == 0b001 and t == ["REC TRIGS TOGGLED"] and s == [(0, RTM_CC, 1), (2, RTM_CC, 0)],
          f"T1+T3 held, only T3 muted -> each flips (T1 muted, T3 unmuted): mask {m:#04x}, "
          f"sends {s}, toast {t}")
    m, s, t = key(rec, 0x29, 1, 0b100)
    check(m == 0b101 and t == ["REC TRIGS MUTED"] and s == [(2, RTM_CC, 1)],
          f"T3 held -> T3 muted, T1 untouched: mask {m:#04x}, sends {s}, toast {t}")
    m, s, t = key(rec, 0x29, 1, 0b101)
    check(m == 0 and t == ["REC TRIGS UNMUTED"] and s == [(0, RTM_CC, 0), (2, RTM_CC, 0)],
          f"T1+T3 held, both muted -> both unmuted: mask {m:#04x}, sends {s}, toast {t}")
    check(u32(GRID_REC) == grid0, "GRID REC still unchanged after five track-held presses")
    m, s, t = key(rec, 0x29, 1, 0)
    check(m == 0 and not s and "REC TRIGS MUTED" not in t and "REC TRIGS UNMUTED" not in t,
          "nothing held, REC press -> no mute change, no send")
    check(u32(GRID_REC) == (0 if grid0 else 1) and u32(REC_HELD) == 1,
          f"  ... and stock [REC] ran: GRID REC {grid0} -> {u32(GRID_REC)}, 'REC held' {u32(REC_HELD)}")
    key(rec, 0x29, 0, 0)
    check(u32(REC_HELD) == 0, f"nothing held, REC release -> stock clears 'REC held' ({u32(REC_HELD)})")
    key(rec, 0x29, 1, 0)                                    # GRID REC back as it was
    key(rec, 0x29, 0, 0)
    check(u32(GRID_REC) == grid0, f"GRID REC restored ({u32(GRID_REC)})")
    m, s, t = key(ty, 0x31, 1, 0b1)
    check(m == 0 and t == ["ARM REC TRK"], f"[TRACK]+[YES] -> stock: toast {t}, mask {m:#04x}")
    m, s, t = key(tn, 0x32, 1, 0b1)
    check(m == 0 and t == ["DISARM REC TRK"], f"[TRACK]+[NO] -> stock: toast {t}, mask {m:#04x}")
    w8(RTM_MASK, 0)

    # ------------------------------------------------------------------ 2. CC in
    print("\n2. CC receive")
    chans = [struct.unpack("b", rd(TRIG_CH + t, 1))[0] for t in range(8)]
    auto = struct.unpack("b", rd(AUTO_CH, 1))[0]
    cc_in = u8(CC_IN)
    print(f"  project: TRIG CH {chans}, AUTO {auto}, AUDIO CC IN {cc_in}, "
          f"active track {u8(0x80000000)}")

    def cc(ch, num, val):
        uc.mem_write(MSG, bytes([0xB0 | (ch & 15), num, val]))
        spin()
        rt.call_as_main(CC_HANDLER, args=(MSG,))
        return u8(RTM_MASK)

    w8(CC_IN, 1)
    t2 = 1
    ch2 = chans[t2]
    same = [t for t in range(8) if chans[t] == ch2]
    want = sum(1 << t for t in same)
    m = cc(ch2, RTM_CC, 100)
    check(m == want, f"CC 80=100 on T2's channel {ch2} -> mask {m:#04x} (tracks on it: {same})")
    m = cc(ch2, RTM_CC, 0)
    check(m == 0, f"CC 80=0 -> mask {m:#04x}")
    m = cc(ch2, RTM_CC, 1)
    check(m == want, f"CC 80=1 (the stock 'on' value) -> mask {m:#04x}")
    w8(RTM_MASK, 0)
    if auto >= 0 and auto not in chans:
        act = u8(0x80000000)
        m = cc(auto, RTM_CC, 127)
        check(m == 1 << act, f"CC 80=127 on AUTO channel {auto} -> active track {act}: {m:#04x}")
        w8(RTM_MASK, 0)
    else:
        print(f"  (AUTO channel {auto} unset or shared with a track channel -- skipped)")
    w8(CC_IN, 0)
    m = cc(ch2, RTM_CC, 100)
    check(m == 0, "AUDIO CC IN off -> ignored")
    w8(CC_IN, 1)
    m = cc(ch2, 100, 100)
    check(m == 0, "CC 100 (not ours, <= 119) -> ignored, as stock")
    before = u32(MIDI_TRK_FLAGS)
    cc(ch2, 120, 127)
    after = u32(MIDI_TRK_FLAGS)
    check(after == before | 1, f"CC 120=127 still reaches stock's 120-127 path: "
                               f"0x8000000c {before:#x} -> {after:#x}")
    w32(MIDI_TRK_FLAGS, before)
    w8(CC_IN, cc_in)
    w8(RTM_MASK, 0)

    # ------------------------------------------------------------------ 3. gate + 4. glyph
    print("\n3. step-handler gate")
    bank = saved_bank if saved_bank is not None else final_bank
    pattern = u8(er.CUR_PATTERN)
    rt.seq_select_live(final_bank, pattern)
    blob = u32(ec.PART_PTR)
    act_pat = u8(0x100b14d0)
    print(f"  pattern {pattern} (UI mirror {act_pat}), blob {blob:#x}")
    trac = lambda t: blob + act_pat * er.PATTERN_STRIDE + t * er.TRAC_STRIDE
    for t in (0, 1):
        uc.mem_write(trac(t) + 0x20, b"\xff" * 8)          # REC1 on every step, T1 and T2
    w8(RTM_MASK, 0b01)                                     # T1 muted

    flag_writes = []

    def on_flag(u, acc, adr, size, val, x):
        if size == 4:
            flag_writes.append(((adr - FLAGWORD) // 4, val))
    uc.hook_add(eb.UC_HOOK_MEM_WRITE, on_flag, begin=FLAGWORD, end=FLAGWORD + 31)
    uc.ctl_flush_tb()

    rt.frame = True
    rt.next_frame = rt.sample + er.FRAME_PERIOD
    rt.start_transport_live()

    def frames(n):
        target = rt.frame_count + n
        rt.run(ms=n * er.FRAME_PERIOD / er.SAMPLE_HZ * 1000.0 * 5 + 2000,
               until=lambda x: x.frame_count >= target)

    frames(a.frames)
    rec = lambda t: [v for tt, v in flag_writes if tt == t and v & 0x7000]
    print(f"  {len(flag_writes)} flag-word writes")
    check(len(rec(1)) > 0, f"T2 (unmuted) recorder trigs reach 0x46c7a6c0[1]: {len(rec(1))}")
    check(len(rec(0)) == 0, f"T1 (muted) recorder trigs never do: {len(rec(0))}")

    print("\n4. dots: two stacked dots beside a muted track's letter, on the inner side")

    def render():
        spin()
        rt.call_as_main(RENDER)
        rt.call_as_main(LETTERS)
        rt.call_as_main(MARKS)                           # last, as on hardware: it found the T1-4 bug
        return lcd_view.pixels(rd(LCD, 1024))
    act0 = u8(0x80000000)
    part = u32(0x46c82456) + u8(0x80000003) * 6322 + 585122        # the renderers' machine byte
    machine = [rd(part + t, 1)[0] for t in range(8)]
    print(f"  active track T{act0 + 1}, machines {machine} (4 = PICKUP)")

    def dots(px, t):
        """(dot column rows top-1..top+3, gap column rows top..top+3, background) for track t."""
        a = 1 if t == u8(0x80000000) else 0
        x = 2 + a + 4 if t < 4 else 123 - a - 2
        gx = x - 1 if t < 4 else x + 1
        top = 5 + 15 * (t & 3)                           # the letter's top row on screen
        return ([px[top + i][x] for i in range(-1, 4)], [px[top + i][gx] for i in range(4)], a)

    def check_tabs(mask, what, bang=(), act=None):
        """bang: tracks whose stock '!' (the mark painter's column: voice +0 and +3 set) is lit."""
        w8(RTM_MASK, mask)
        if act is not None:
            w8(0x80000000, act)
        saved = {t: rd(0x800049d8 + 168 * t, 4) for t in bang}
        for t in bang:
            w8(0x800049d8 + 168 * t, 0xff)
            w8(0x800049d8 + 168 * t + 3, 1)
        px = render()
        for t in range(8):
            col, gap, bg = dots(px, t)
            fg = 1 - bg
            if (mask >> t) & 1 and machine[t] != 4:
                want = [bg, fg, bg, fg, bg]              # the dots, over a lit '!' too
            elif t in bang and t < 4:
                want = [fg, fg, fg, bg, fg]              # stock's '!' (T5-8: at x = 127)
            else:
                want = [bg] * 5
            check(col == want and gap == [bg] * 4,
                  f"{what} T{t + 1}{' (active)' if bg else ''}{' (!)' if t in bang else ''}"
                  f"{' (PICKUP: none)' if machine[t] == 4 else ''}: column {col} want {want}, gap {gap}")
        for t, v in saved.items():
            uc.mem_write(0x800049d8 + 168 * t, v)
        if act is not None:
            w8(0x80000000, act0)
        return px
    check_tabs(0, "unmuted: no dots")
    px = check_tabs(0b00010001 | (1 << act0), "T1 + T5 + the active track muted")
    cache = [u32(CACHE + 4 * t) for t in range(8)]
    check(all(c < 8 for c in cache), f"status-icon cache holds stock states only (0-7): {cache}")
    pxb = check_tabs(0b00010001, "stock '!' lit on T1 (muted) and T2:", bang=(0, 1))
    pxa = check_tabs(0b00010001, "T1 active (filled tab):", act=0)
    for img, tag in ((pxb, "_bang"), (pxa, "_t1active")):
        lcd_view.png(img, a.png.replace(".png", f"{tag}.png"))
    uc.mem_write(trac(0) + 0x20, b"\0" * 8)                # T1: no recorder trigs at all
    check(dots(render(), 0)[0] == [0, 1, 0, 1, 0], "muted T1 with NO recorder trigs: still dots")
    lcd_view.png(px, a.png)
    print(f"  LCD -> {a.png}")
    uc.mem_write(trac(0) + 0x20, b"\xff" * 8)              # T1's REC1 back for the unmute test

    print("\n   unmute T1 -> its recorder trigs come back")
    w8(RTM_MASK, 0)
    n0 = len(flag_writes)
    frames(a.frames)
    later = [v for tt, v in flag_writes[n0:] if tt == 0 and v & 0x7000]
    check(len(later) > 0, f"T1 recorder trigs reach 0x46c7a6c0[0] again: {len(later)}")
    col, _, bg = dots(render(), 0)
    check(col == [bg] * 5, f"unmuted T1: dots gone {col}")

    print(f"\n{'ALL PASS' if not fails else f'{len(fails)} FAIL'}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
