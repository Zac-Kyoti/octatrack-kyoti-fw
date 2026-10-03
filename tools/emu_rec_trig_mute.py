#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
Validate REC_TRIG_MUTE (out/mainos_rec_trig_mute.bin) in octabam's full-firmware emulator.

Boots the image, loads the factory OT DEMO, then drives:
  1. keys   -- the [TRK]-layer NO / YES handlers with held tracks poked into 0x460fab40:
               RTM_MASK, the CC 80 sends (FUN_40033e3c args) and the toast text
  2. CC in  -- the stock CC handler FUN_4000e79c with a real 3-byte message: track channel,
               AUTO channel, value 0 / >0, AUDIO CC IN off, and that CCs we don't own still
               take stock's path (CC 100 ignored, CC 120 -> 0x8000000c bit 0)
  3. gate   -- REC1 poked on every step of T1 and T2 (a runtime RAM poke into the loaded
               pattern, not a project file), T1 muted: the step handler's recorder flag word
               0x46c7a6c0 must get T2's REC1 bit and never T1's; then unmute -> T1's appears
  4. glyph  -- (renderer 0x4004bd48 called directly: route A barely runs the UI frame)
               the edge renderer's cache 0x400c0cb8[t] = 8|playing ("..[]" / "..>") for
               muted T1 with and without recorder trigs, stock for unmuted T2, stock "+" for
               a muted track mid-recording; the blit gets our descriptors; LCD screenshot

Every result is printed as PASS / FAIL.  Logic only: route A has no real DSP/audio path, so
whether a recording really stops is a hardware question.

    python3 tools/emu_rec_trig_mute.py [--image out/mainos_rec_trig_mute.bin] [--frames 1500]
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
RENDER = 0x4004bd48                 # the edge renderer; on hardware FUN_40052200's UI-frame
                                    # path polls it (0x4005222e), which route A barely runs
NO_ENTRY, YES_FIELD = 0x40083488, 0x400d15e4
CC_SEND, NOTIFY, CC_HANDLER, BLIT = 0x40033e3c, 0x4005a2b8, 0x4000e79c, 0x400128a8
CC_IN, AUTO_CH, TRIG_CH, MIDI_TRK_FLAGS = 0x80000049, 0x80000047, 0x8000003f, 0x8000000c
FLAGWORD = 0x46c7a6c0
MSG = 0x400d6600                    # test buffer: classic-cave zeros, unused on this image
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
    image = pathlib.Path(a.image)
    if not image.is_absolute():
        image = ROOT / image
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
    sends, toasts, blits = [], [], []

    def on_send(u, adr, size, x):
        sp = u.reg_read(eb.UC_M68K_REG_A7)
        sends.append(struct.unpack(">III", u.mem_read(sp + 4, 12)))

    def on_notify(u, adr, size, x):
        sp = u.reg_read(eb.UC_M68K_REG_A7)
        p = struct.unpack(">I", u.mem_read(sp + 4, 4))[0]
        toasts.append(bytes(u.mem_read(p, 24)).split(b"\0")[0].decode(errors="replace"))

    def on_blit(u, adr, size, x):
        sp = u.reg_read(eb.UC_M68K_REG_A7)
        ret, desc, plane, xx, yy = struct.unpack(">IIIII", u.mem_read(sp, 20))
        if desc in (S["D_DOTSS"], S["D_DOTSP"]):
            blits.append((desc, xx, yy))
    uc.hook_add(eb.UC_HOOK_CODE, on_send, begin=CC_SEND, end=CC_SEND)
    uc.hook_add(eb.UC_HOOK_CODE, on_notify, begin=NOTIFY, end=NOTIFY)
    uc.hook_add(eb.UC_HOOK_CODE, on_blit, begin=BLIT, end=BLIT)
    uc.ctl_flush_tb()

    # ------------------------------------------------------------------ 1. keys
    print("\n1. keys")
    yes_entry = u32(YES_FIELD)
    check(yes_entry == S["rtm_yes"], f"[TRK]-layer YES record -> rtm_yes 0x{yes_entry:08x}")
    check(u8(RTM_MASK) == 0, "RTM_MASK boots 0 (all unmuted)")

    def key(entry, code, event, held):
        sends.clear(); toasts.clear()
        w32(HELD, held)
        spin()
        rt.call_as_main(entry, args=(code, event))
        w32(HELD, 0)
        return u8(RTM_MASK), list(sends), list(toasts)

    m, s, t = key(NO_ENTRY, 0x32, 1, 0b101)
    check(m == 0b101, f"T1+T3 held, NO press -> mask {m:#04x}")
    check(s == [(0, RTM_CC, 1), (2, RTM_CC, 1)], f"CC sends {s}")
    check(t == ["REC TRIGS MUTED"], f"toast {t}")
    m, s, t = key(NO_ENTRY, 0x32, 0, 0b10)
    check(m == 0b101 and not s and not t, "NO release event -> no change, no send, no toast")
    m, s, t = key(yes_entry, 0x31, 1, 0b1)
    check(m == 0b100, f"T1 held, YES press -> mask {m:#04x}")
    check(s == [(0, RTM_CC, 0)], f"CC sends {s}")
    check(t == ["REC TRIGS UNMUTED"], f"toast {t}")
    m, s, t = key(yes_entry, 0x31, 1, 0)
    check(m == 0b100 and not s and not t, "nothing held -> no change")
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

    print("\n4. glyph: a muted track shows dots + its play state, recorder trigs or not")

    def render():
        spin()
        rt.call_as_main(RENDER)
    DOTS = (S["D_DOTSS"], S["D_DOTSP"])
    render()
    c0, c1 = u32(CACHE), u32(CACHE + 4)
    check(c0 in (8, 9), f"muted T1 (has recorder trigs): cache {c0} (8 = ..[], 9 = ..>)")
    check(c1 < 8, f"unmuted T2: cache {c1} (stock)")
    check(any(d in DOTS for d, _, _ in blits),
          f"blit called with our glyphs: {[(hex(d), x, y) for d, x, y in blits[:4]]}")
    uc.mem_write(trac(0) + 0x20, b"\0" * 8)                # T1: no recorder trigs at all
    render()
    c0 = u32(CACHE)
    check(c0 in (8, 9), f"muted T1 with NO recorder trigs: cache {c0} (still dots)")
    plane = rd(0x46c7e0ea, 1024)
    lcd_view.png(lcd_view.pixels(plane), a.png)
    print(f"  LCD -> {a.png}")
    if c1 in (2, 3):                                       # T2 is mid-recording: "+" wins
        w8(RTM_MASK, 0b11)
        render()
        c1m = u32(CACHE + 4)
        check(c1m in (2, 3), f"T2 muted while its recording runs: cache {c1m} (stock '+')")
        w8(RTM_MASK, 0b01)
    else:
        print(f"  (T2 not recording at this moment, cache {c1} -- '+' precedence not exercised)")
    uc.mem_write(trac(0) + 0x20, b"\xff" * 8)              # T1's REC1 back for the unmute test

    print("\n   unmute T1 -> its recorder trigs come back")
    w8(RTM_MASK, 0)
    n0 = len(flag_writes)
    frames(a.frames)
    later = [v for tt, v in flag_writes[n0:] if tt == 0 and v & 0x7000]
    check(len(later) > 0, f"T1 recorder trigs reach 0x46c7a6c0[0] again: {len(later)}")
    render()
    check(u32(CACHE) < 8, f"renderer cache T1 = {u32(CACHE)} (stock)")

    print(f"\n{'ALL PASS' if not fails else f'{len(fails)} FAIL'}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
