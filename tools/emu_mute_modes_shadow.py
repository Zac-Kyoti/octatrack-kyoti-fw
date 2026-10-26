#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
"""
MUTE_MODES' SHADOW byte in octabam's full-firmware emulator (route A, logic only).

SHADOW is hook 1's (`pre`) per-frame "silenced" set; OTFX reads it back to find each
newly muted track (the 0->1 edge that calls the note-off FUN_40008f84 once). It used to
be SRAM 0x80006c66, inside the stock timestretch task's work area: that task (prio 1,
entry 0x40098a5c) fills 0x80006964.. with audio on every grain, so on hardware SHADOW
could read back audio bytes. Route A does not stream samples, so the task never writes
there -- this script plays its part by poking an audio-like byte into 0x80006c66 right
before a mute.

Boots the image, loads the factory OT DEMO, starts the transport, then:
  1. OT mode: `pre` keeps SHADOW at 0; counts `pre`'s writes to 0x80006c66
     (the old build: every frame; the fixed build: none)
  2. OTFX, T2 muted: SHADOW == 0x02 and exactly one note-off, for T2
  3. OTFX, 0x80006c66 = 0xff poked (what the timestretch task leaves), then T3 muted:
     the note-off for T3 must still fire (the old build misses it -- the bug)
Every result is printed as PASS / FAIL.

    python3 tools/emu_mute_modes_shadow.py [--image out/mainos_mute_modes.bin]
                                           [--shadow 0xADDR] [--frames 300]
    --shadow defaults to SHADOW from out/patch_softmute_dt.elf (the standalone build);
    pass 0x80006c66 for an image built from the old source.
"""
import argparse, os, pathlib, struct, subprocess, sys
sys.stdout.reconfigure(line_buffering=True)
ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
DEMO = pathlib.Path.home() / "Desktop" / "OT Backup" / "KYOTI" / "OT DEMO"
ELF = ROOT / "out" / "patch_softmute_dt.elf"
os.chdir(OCTABAM)
sys.path.insert(0, str(OCTABAM / "tools"))
import toolpath  # noqa: E402,F401
import emu_rtos as er
import emu_bringup as eb

OLD_SHADOW = 0x80006c66
GATE, MUTE_STATE, REL_STATE = 0x800000dc, 0x80000008, 0x8000184a
F_NOTEOFF = 0x40008f84
CAVE_LO, CAVE_HI = 0x400d6500, 0x400d8000     # where every build places `pre`

fails = []


def check(ok, what):
    print(f"  {'PASS' if ok else 'FAIL'}  {what}")
    if not ok:
        fails.append(what)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", default=str(ROOT / "out" / "mainos_mute_modes.bin"))
    ap.add_argument("--shadow", type=lambda s: int(s, 0), default=None)
    ap.add_argument("--frames", type=int, default=300)
    a = ap.parse_args()
    image = pathlib.Path(a.image)
    if not image.is_absolute():
        image = ROOT / image
    shadow = a.shadow
    if shadow is None:
        out = subprocess.run(["m68k-elf-nm", str(ELF)], capture_output=True, text=True).stdout
        shadow = next(int(f[0], 16) for f in (l.split() for l in out.splitlines())
                      if len(f) == 3 and f[2] == "SHADOW")
    print(f"SHADOW {shadow:#x}{'  (the old SRAM address)' if shadow == OLD_SHADOW else ''}")

    card, name = er.stage_project(str(DEMO), "OCTABAM", None)
    r, rt = er.attach(str(image), card, tick=True)
    mounted, posted, saved_bank, final_bank, elapsed = rt.load_project_live("OCTABAM", name, run_ms=6000,
                                                                             mount_ms=3000)
    print(f"=== {image.name}: loaded={mounted} ({elapsed:.0f} ms) ===")
    uc = rt.uc
    u8 = lambda adr: bytes(uc.mem_read(adr, 1))[0]
    u32 = lambda adr: struct.unpack(">I", bytes(uc.mem_read(adr, 4)))[0]
    w8 = lambda adr, v: uc.mem_write(adr, bytes([v & 0xff]))
    w32 = lambda adr, v: uc.mem_write(adr, struct.pack(">I", v & 0xffffffff))

    old_writes = []                     # writes to 0x80006c66 from code in the cave
    noteoffs = []

    def on_old(u, acc, adr, size, val, x):
        pc = u.reg_read(eb.UC_M68K_REG_PC)
        if CAVE_LO <= pc < CAVE_HI:
            old_writes.append(pc)

    def on_noteoff(u, adr, size, x):
        sp = u.reg_read(eb.UC_M68K_REG_A7)
        noteoffs.append(struct.unpack(">I", bytes(u.mem_read(sp + 4, 4)))[0])

    uc.hook_add(eb.UC_HOOK_MEM_WRITE, on_old, begin=OLD_SHADOW, end=OLD_SHADOW)
    uc.hook_add(eb.UC_HOOK_CODE, on_noteoff, begin=F_NOTEOFF, end=F_NOTEOFF)
    uc.ctl_flush_tb()

    rt.frame = True
    rt.next_frame = rt.sample + er.FRAME_PERIOD
    rt.start_transport_live()

    def frames(n):
        target = rt.frame_count + n
        rt.run(ms=n * er.FRAME_PERIOD / er.SAMPLE_HZ * 1000.0 * 5 + 2000,
               until=lambda x: x.frame_count >= target)

    print("\n1. OT mode")
    w32(GATE, 0)
    w32(MUTE_STATE, u32(MUTE_STATE) & ~0xffff)          # nothing muted or soloed
    frames(a.frames)
    old_writes.clear()
    frames(a.frames)
    check(u8(shadow) == 0, f"SHADOW stays 0: {u8(shadow):#04x}")
    if shadow == OLD_SHADOW:
        print(f"  (old build: `pre` wrote 0x80006c66 {len(old_writes)} times in {a.frames} frames)")
    else:
        check(not old_writes, f"`pre` never writes 0x80006c66: {len(old_writes)} writes")

    print("\n2. OTFX, T2 muted")
    w32(GATE, 1)
    frames(a.frames)
    noteoffs.clear()
    w32(MUTE_STATE, u32(MUTE_STATE) | 1 << (8 + 1))
    frames(a.frames)
    check(u8(shadow) == 0x02, f"SHADOW = T2: {u8(shadow):#04x}")
    check(noteoffs == [1], f"one note-off, for T2: {noteoffs}")
    check(u8(REL_STATE) & 0x02, f"REL_STATE holds T2: {u8(REL_STATE):#04x}")

    print("\n3. OTFX, 0x80006c66 = 0xff (what the timestretch task can leave), then T3 muted")
    noteoffs.clear()
    w8(OLD_SHADOW, 0xff)
    w32(MUTE_STATE, u32(MUTE_STATE) | 1 << (8 + 2))
    frames(a.frames)
    check(2 in noteoffs, f"T3's note-off fires: {noteoffs}")
    check(u8(shadow) == 0x06, f"SHADOW = T2+T3: {u8(shadow):#04x}")

    w32(MUTE_STATE, u32(MUTE_STATE) & ~0xffff)
    w32(GATE, 0)
    print(f"\n{'ALL PASS' if not fails else f'{len(fails)} FAIL'}")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
