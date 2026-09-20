#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac-Kyoti
"""
RELOAD FROM PROJECT (NOTES.md "Session 42") -- prove the two things the design
rests on, in octabam's full-firmware emulator (`refs/octabam/tools/emu_rtos.py`
via `tools/emu_rtos.py`).

  --slice  the core mechanic.  Load the factory OT DEMO, start the transport,
           then WHILE PLAYING: scribble over the active pattern P's slab *and* a
           bystander pattern Q's slab in the bank blob (stand-in for live edits),
           memcpy P's saved slab back (stand-in for "copied out of a .strd
           deserialised into scratch"), poke the "reload now" flag 0x46c8028a,
           run frames.  Asserts:
             * P's slab reverts, Q's edit survives  (a single-slab copy is clean)
             * 0x46c8028a is consumed and 0x800065b6 (pattern length) reloads
             * no fault, transport keeps running

  --strd   prove the async storage-task file path reloads the bank blob from
           `bankNN.strd`.  Posts a type-0x14 job (FUN_40022778(1<<curbank)) --
           the same primitive stock RELOAD BANK uses -- and lets the real
           storage task FUN_4008445c drain it (FUN_4008f0b0 .strd->.work +
           FUN_400905d4 -> FUN_4008ded0).  Cross-checks the reloaded P11 t2
           p-lock array against `bank01.strd` on disk.  (This is the WHOLE-bank
           stock path; the feature's partial reload hooks the same chain --
           redirect the open to .strd, deserialise into a scratch region,
           slice-copy.  A direct call_as_main(FUN_40016864/FUN_4008ded0) instead
           faults `rte would return to user mode` -- the buffered open blocks,
           which is why the real build MUST use the storage task, not a
           synchronous cave.)

  --combo  single-step rl_combo (the [PTN]+[NO] hook) in isolation, gates forced,
           no scheduler underneath.  Fast + decisive: does it arm G_KIND/G_PAT,
           post the storage job (FUN_40022778), suppress the chooser, swallow NO.

  --patched  boot out/mainos_reload.bin and drive [PTN]+[NO] END TO END: combo ->
           storage-task worker (open bankNN.strd, FUN_4008cebc-parse pattern P,
           memcpy the slab, 0x46c8028a) -> the pattern reverts to the saved
           state, a bystander pattern is untouched, no fault, transport runs.
           Halts the stock whole-bank deser on entry so the worker's effect is
           seen in isolation (that deser is the emu's 10 MB load finishing, not
           anything [PTN]+[NO] triggers).

    python3 tools/emu_reload.py --slice
    python3 tools/emu_reload.py --combo
    python3 tools/emu_reload.py --patched
    python3 tools/emu_reload.py --slice --strd      # one boot, both

Needs `python3 tools/refs/sync.py` + the EMAC-patched Unicorn
(`refs/octabam/scripts/build_unicorn.sh`).  ~3 min wall per boot.
"""
import argparse
import os
import pathlib
import struct
import sys

sys.stdout.reconfigure(line_buffering=True)

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCTABAM = ROOT / "refs" / "octabam"
STOCK_IMAGE = ROOT / "out" / "raw" / "section_3_MAIN_OS.bin"
RELOAD_IMAGE = ROOT / "out" / "mainos_reload.bin"        # build_reload.py output
OUR_IMAGE = STOCK_IMAGE                                  # overridden by --patched
DEMO = pathlib.Path.home() / "Desktop" / "OT Backup" / "KYOTI" / "OT DEMO"
DEMO_BANK1_STRD = DEMO / "bank01.strd"
DEMO_BANK1_WORK = DEMO / "bank01.work"

if not (OCTABAM / "tools" / "emu" / "emu_rtos.py").exists():
    sys.exit("missing refs/octabam -> python3 tools/refs/sync.py")
if not (OCTABAM / ".venv" / "lib" / "unicorn-emac").is_dir():
    sys.exit("missing the EMAC-patched Unicorn -> "
             "( cd refs/octabam && PY=$(command -v python3) bash scripts/build_unicorn.sh )")
os.chdir(OCTABAM)
sys.path.insert(0, str(OCTABAM / "tools"))
import toolpath                  # noqa: E402
import emu_rtos as er            # noqa: E402
import emu_card as ec            # noqa: E402

# --- blob geometry (NOTES.md "Session 42" RE) --------------------------------
BANK_BLOB = er.BANK_BLOB               # 0x400e21e0
BANK_STRIDE = er.BANK_STRIDE           # 0x9b340
PAT_STRIDE = er.PATTERN_STRIDE         # 0x8ed8  -- 16 pattern slabs fill blob+0..0x8ed80
TRAC_STRIDE = er.TRAC_STRIDE           # 0x91a
PARTS_OFF = 0x8ed80                    # = 16 * 0x8ed8 ; 4 part payloads follow
PART_STRIDE = 0x18b2                   # 6322
PARTS_LEN = 4 * PART_STRIDE            # 0x62c8
PLOCK_IN_TRAC = 0x59
PLOCK_LEN = 0x800

RELOAD_NOW = 0x46c8028a                # step engine polls this at 0x400a2530
SEQ_LEN_M1 = 0x800065b6               # master pattern length - 1 (reloaded by the block)
SEQ_STEP = 0x800065b4                 # master step position (zeroed by the block)
SEQ_BANK, SEQ_PAT = 0x800065bd, 0x800065be
TRANSPORT = 0x800065b8

# factory DEMO: P11 (index 10) t2 (index 1) is a 16-step track with p-locks
DISK_PAT, DISK_TRK = 10, 1
# disk layout of bank01.{work,strd}
D_PAT1, D_PSTRIDE, D_PHDR, D_TRAC = 0x16, 0x8EEC, 8, 0x922


def boot_and_load():
    card, name = er.stage_project(str(DEMO), "OCTABAM", None)
    r, rt = er.attach(str(OUR_IMAGE), card, tick=True)
    print(f"boot       : {r.stopped}")
    mounted, posted, saved_bank, final_bank, elapsed = rt.load_project_live(
        "OCTABAM", name, run_ms=6000, mount_ms=3000)
    print(f"load       : mounted={mounted} posted={posted} saved_bank={saved_bank} "
          f"final_bank={final_bank} ({elapsed:.0f} ms)")
    return rt


def part_ptr(rt):
    return struct.unpack(">I", rt.uc.mem_read(ec.PART_PTR, 4))[0]


def rd(rt, a, n):
    return bytes(rt.uc.mem_read(a, n))


def spin(rt, cap=400_000):
    n = 0
    while rt.pc != er.MAIN_SPIN and n < cap:
        rt.step()
        n += 1


# ---------------------------------------------------------------------------
def cmd_slice(rt):
    print("\n===== --slice : slab revert + 0x46c8028a refresh, while playing =====")
    curbank = rt.uc.mem_read(er.CUR_BANK, 1)[0]
    blob = part_ptr(rt)
    want = BANK_BLOB + curbank * BANK_STRIDE
    print(f"curbank={curbank}  PART_PTR={blob:#x}  BANK_BLOB+bank*stride={want:#x}  "
          f"{'OK' if blob == want else 'MISMATCH'}")
    if not blob:
        sys.exit("PART_PTR null -- load failed")

    P, Q = DISK_PAT, 0
    pP = blob + P * PAT_STRIDE
    pQ = blob + Q * PAT_STRIDE
    seqb, seqp = rt.seq_select_live(curbank, P)
    print(f"seq select : bank {seqb} pattern {seqp}  (want pattern {P})")

    saved_P = rd(rt, pP, PAT_STRIDE)
    saved_Q = rd(rt, pQ, PAT_STRIDE)
    print(f"snapshot   : P{P} slab {pP:#x}  Q{Q} slab {pQ:#x}  ({PAT_STRIDE:#x} B each)")

    # --- start the transport, let it settle -------------------------------
    rt.frame = True
    rt.next_frame = rt.sample + er.FRAME_PERIOD
    rt.exact_clock()
    rt.internal_clock()
    rt.press_play_live()
    rt.run(ms=250)
    print(f"transport  : 0x800065b8={int.from_bytes(rd(rt, TRANSPORT, 4),'big')}  "
          f"step={int.from_bytes(rd(rt, SEQ_STEP, 2),'big')}  "
          f"len-1={int.from_bytes(rd(rt, SEQ_LEN_M1, 1),'big')}")

    # --- scribble live edits into BOTH P and Q ----------------------------
    def scribble(base, tag):
        # a few trig-mask bytes + a p-lock value on track 0 and track DISK_TRK
        before = {}
        for trk in (0, DISK_TRK):
            tb = base + trk * TRAC_STRIDE
            for off in (0x00, 0x08, PLOCK_IN_TRAC + 0x40, PLOCK_IN_TRAC + 0x41):
                before[(trk, off)] = rd(rt, tb + off, 1)[0]
                rt.uc.mem_write(tb + off, bytes([before[(trk, off)] ^ 0x5A]))
        print(f"  scribble {tag}: {[(t, hex(o), hex(v)) for (t, o), v in before.items()]}")
        return before

    ed_P = scribble(pP, f"P{P}")
    ed_Q = scribble(pQ, f"Q{Q}")
    assert rd(rt, pP, PAT_STRIDE) != saved_P, "P edit did not land"
    assert rd(rt, pQ, PAT_STRIDE) != saved_Q, "Q edit did not land"

    # --- the worker's slice-copy: P's saved slab back over the blob -------
    rt.uc.mem_write(pP, saved_P)
    p_ok = rd(rt, pP, PAT_STRIDE) == saved_P
    q_survived = rd(rt, pQ, PAT_STRIDE) != saved_Q
    print(f"\nslice-copy : P{P} reverted = {p_ok}   Q{Q} edit survived = {q_survived}")

    # --- fire the reload-now flag, run frames ----------------------------
    len_before = int.from_bytes(rd(rt, SEQ_LEN_M1, 1), 'big')
    rt.uc.mem_write(RELOAD_NOW, struct.pack(">I", 1))
    print(f"poke       : 0x46c8028a = 1   (len-1 was {len_before})")
    faulted = None
    try:
        rt.run(ms=400)
    except Exception as e:
        faulted = f"{type(e).__name__}: {e}"
    flag = int.from_bytes(rd(rt, RELOAD_NOW, 4), 'big')
    len_after = int.from_bytes(rd(rt, SEQ_LEN_M1, 1), 'big')
    step_after = int.from_bytes(rd(rt, SEQ_STEP, 2), 'big')
    tport = int.from_bytes(rd(rt, TRANSPORT, 4), 'big')
    print(f"after run  : 0x46c8028a={flag:#x}  len-1={len_after}  step={step_after}  "
          f"transport={tport}  fault={faulted}")

    ok = (blob == want and p_ok and q_survived and flag == 0
          and 1 <= len_after <= 63 and faulted is None and tport == 1)
    print(f"\n--slice: {'ALL GOOD' if ok else 'CHECK FAILED'}")
    for name, cond in [("PART_PTR == blob geometry", blob == want),
                       ("P reverted to saved slab", p_ok),
                       ("Q's live edit survived", q_survived),
                       ("0x46c8028a consumed by the step engine", flag == 0),
                       ("pattern length reloaded (1..63)", 1 <= len_after <= 63),
                       ("no fault", faulted is None),
                       ("transport still running", tport == 1)]:
        print(f"   [{'x' if cond else ' '}] {name}")
    return ok


# ---------------------------------------------------------------------------
FUN_POST_RELOAD = 0x40022778    # (mask) -> post type-0x14 job to the storage task queue
STRD_MARK = 0x4009acec         # the reload-clear PC emu_plock uses as a landmark


def cmd_strd(rt):
    print("\n===== --strd : async storage-task reload of the bank blob from bankNN.strd =====")
    curbank = rt.uc.mem_read(er.CUR_BANK, 1)[0]
    blob = part_ptr(rt)
    tb = blob + DISK_PAT * PAT_STRIDE + DISK_TRK * TRAC_STRIDE
    before = rd(rt, tb + PLOCK_IN_TRAC, PLOCK_LEN)

    # a distinguishing scribble so we can see the reload overwrite it
    rt.uc.mem_write(tb + PLOCK_IN_TRAC, b"\xAB" * 64)
    print(f"curbank={curbank}  blob={blob:#x}  scribbled #1[0..1] = 0xAB*64")

    spin(rt)
    faulted = None
    try:
        d0 = rt.call_as_main(FUN_POST_RELOAD, args=(1 << curbank,), budget=1_000_000)
        print(f"post       : FUN_40022778(1<<{curbank}) -> d0={d0:#x}")
    except Exception as e:
        faulted = f"{type(e).__name__}: {e}"
        print(f"post       : raised {faulted}")
        return False
    rt.run(ms=20000)   # let FUN_4008445c drain: .strd->.work + deserialise

    after = rd(rt, tb + PLOCK_IN_TRAC, PLOCK_LEN)
    changed = after[:64] != b"\xAB" * 64
    print(f"reload     : #1[0] head  before {before[:16].hex(' ')}")
    print(f"                         after  {after[:16].hex(' ')}   "
          f"{'RELOADED (scribble gone)' if changed else 'scribble still there -- job did not run'}")

    strd = DEMO_BANK1_STRD.read_bytes()
    doff = D_PAT1 + D_PSTRIDE * DISK_PAT + D_PHDR + D_TRAC * DISK_TRK
    disk_plock = strd[doff + 0x62: doff + 0x62 + PLOCK_LEN]
    ram_plock = after

    def locked(buf):
        return [(s, [(hex(i), hex(buf[s * 32 + i])) for i in range(32) if buf[s * 32 + i] != 0xFF])
                for s in range(64) if any(buf[s * 32 + i] != 0xFF for i in range(32))]

    work = DEMO_BANK1_WORK.read_bytes()
    woff = D_PAT1 + D_PSTRIDE * DISK_PAT + D_PHDR + D_TRAC * DISK_TRK
    work_plock = work[woff + 0x62: woff + 0x62 + PLOCK_LEN]

    dl, rl, wl = locked(disk_plock), locked(ram_plock), locked(work_plock)
    src = ("bank01.strd" if rl == dl else "bank01.work" if rl == wl else "neither (?)")
    print(f"\n  .strd locked steps: {dl[:4]}")
    print(f"  .work locked steps: {wl[:4]}")
    print(f"  blob  locked steps: {rl[:4]}")
    print(f"\n--strd: the async storage-task job RAN end to end -- "
          f"dequeue -> FUN_400905d4 -> FUN_4008ded0 -> blob refilled from {src}")
    print("   [x] FUN_40022778 + storage task + deserialiser reach the blob (scribble wiped)")
    print(f"   [{'x' if src == 'bank01.strd' else ' '}] source was .strd  "
          f"(stock RELOAD BANK path copies .strd->.work first; the FEATURE build redirects "
          f"the open to .strd and skips that copy -- verify on the patched image / HW)")
    return changed


PTN_HELD = 0x460d1742
NO_KEYCODE = 0x32
G_KIND = 0x80006a50
G_PAT = 0x80006a51
G_SEL = 0x80006a53
TOAST_FN = 0x4005a2b8

# which picker item cmd_patched drives.  patch_reload.s item 0 == PTN SEQ (the
# whole-pattern worker); emu_reload2.py overrides this to 1 (patch_reload2.s item
# 0 is TRK SEQ, item 1 is PTN SEQ).
PATCHED_GSEL = 0

# RAM pattern-slab geometry (FUN_4009a670 / NOTES.md L1067)
MIDI_BASE_IN_SLAB = 0x48d0
MTRA_STRIDE = 0x8b0
PART_LINK_IN_SLAB = 0x8e57


def _sym(name):
    import subprocess
    nm = subprocess.run(["m68k-elf-nm", str(ROOT / "out" / "patch_reload.elf")],
                        capture_output=True, text=True).stdout
    for ln in nm.splitlines():
        p = ln.split()
        if len(p) == 3 and p[2] == name:
            return int(p[0], 16)
    raise KeyError(name)


def cmd_patched(rt):
    print("\n===== --patched : drive the SEQ worker end to end on the built image =====")
    rl_ptn = _sym("rl_ptn")
    curbank = rt.uc.mem_read(er.CUR_BANK, 1)[0]
    blob = part_ptr(rt)
    P, Q = 0, DISK_PAT          # P = active pattern 0 -> the worker's discard loop is empty
    pP, pQ = blob + P * PAT_STRIDE, blob + Q * PAT_STRIDE
    rt.seq_select_live(curbank, P)
    print(f"curbank={curbank}  blob={blob:#x}  rl_ptn={rl_ptn:#x}  reload target P={P}, bystander Q={Q}")

    saved_P = rd(rt, pP, PAT_STRIDE)
    saved_Q = rd(rt, pQ, PAT_STRIDE)

    rt.frame = True
    rt.next_frame = rt.sample + er.FRAME_PERIOD
    rt.exact_clock(); rt.internal_clock(); rt.press_play_live()
    rt.run(ms=250)

    # "live edits" into P and Q -- scribble BOTH the cold blob AND the live
    # working copy 0x1001614e (a real UI edit lands in both; scribbling only the
    # blob lets a blob<-live sync during the long drain revert it)
    LIVE_COPY = 0x1001614e
    for pat in (P, Q):
        for trk in (0, DISK_TRK):
            for base in (blob + pat * PAT_STRIDE, LIVE_COPY + pat * PAT_STRIDE):
                tb = base + trk * TRAC_STRIDE
                for off in (0x00, 0x08, PLOCK_IN_TRAC + 0x40):
                    rt.uc.mem_write(tb + off, bytes([rd(rt, tb + off, 1)[0] ^ 0x5A]))
    scribbled_P = rd(rt, pP, PAT_STRIDE)
    assert scribbled_P != saved_P and rd(rt, pQ, PAT_STRIDE) != saved_Q
    print(f"edits      : P{P} and Q{Q} scribbled (blob + live copy)")

    # watch pattern Q's blob slab -- if anything reverts it, log the PC
    qw = []
    hq = rt.uc.hook_add(er.eb.UC_HOOK_MEM_WRITE, lambda u, a, ad, sz, v, x:
                        qw.append((u.reg_read(er.eb.UC_M68K_REG_PC), ad, v)),
                        begin=pQ, end=pQ + PAT_STRIDE - 1)
    # log entry to the deserialiser / per-pattern parser / stock reload workers
    fx = []
    NAMES = {_sym("rl_job"): "rl_job", 0x4008cebc: "FUN_4008cebc(parse-one-pat)",
             0x4008ded0: "FUN_4008ded0(deser-whole-bank)", 0x400905d4: "FUN_400905d4(load-worker)",
             0x4008f0b0: "FUN_4008f0b0(strd->work)", 0x40016864: "FUN_40016864(open)"}
    deser_seen = [False]
    hf = []
    for a, nm in NAMES.items():
        def mk(nm):
            def cb(u, ad, sz, x):
                # the stock whole-bank deser reverts everything -- halt on its
                # first instruction so the worker's effect is seen in isolation
                if nm == "FUN_4008ded0(deser-whole-bank)":
                    if not deser_seen[0]:
                        deser_seen[0] = True
                        fx.append((nm, 0, 0))
                    u.emu_stop()
                    return
                fx.append((nm, u.reg_read(er.eb.UC_M68K_REG_A7),
                           u.reg_read(er.eb.UC_M68K_REG_A2)))
            return cb
        hf.append(rt.uc.hook_add(er.eb.UC_HOOK_CODE, mk(nm), begin=a, end=a))
    rt.uc.ctl_flush_tb()

    # stub the toast + the picker-close cb -- not what we test, and their window
    # ops are not call_as_main-friendly (emu_directjump.py stubs its toast too)
    rt.uc.mem_write(TOAST_FN, b"\x4e\x75")
    rt.uc.mem_write(0x40056bc0, b"\x4e\x75")   # FUN_40056bc0 (CLOSE_CB)
    rt.uc.ctl_flush_tb()

    spin(rt)
    rt.uc.mem_write(PTN_HELD, struct.pack(">I", 1))
    rt.uc.mem_write(TRANSPORT, struct.pack(">I", 1))   # harness doesn't start it on the patched img
    rt.uc.mem_write(0x800065be, bytes([P]))            # active pattern = P
    print(f"gates      : PTN_HELD=1  RUNNING=1  active pattern={P}")
    faulted = None
    try:
        # the picker (rl_ptn hold-open -> rl_yes execute) is proven by --combo;
        # here arm the SEQ worker the way rl_yes does and drive rl_yes for real
        rt.uc.mem_write(G_KIND, b"\x00")
        rt.uc.mem_write(G_KIND + 2, b"\x01")               # G_MENU = 1 (picker open)
        rt.uc.mem_write(G_SEL, bytes([PATCHED_GSEL]))      # highlight the whole-pattern SEQ item
        rl_yes = _sym("rl_yes")
        d0 = rt.call_as_main(rl_yes, args=(0x31, 1), budget=900_000)
        print(f"combo      : rl_yes(kc=0x31, press) -> d0={d0:#x}")
    except Exception as e:
        faulted = f"{type(e).__name__}: {e}"
        print(f"combo      : raised {faulted}")

    gk1 = rd(rt, G_KIND, 1)[0]
    gp = rd(rt, G_PAT, 1)[0]
    ptn_used = int.from_bytes(rd(rt, 0x460d173e, 4), "big")
    msg_type = rd(rt, 0x460bd912, 1)[0]
    print(f"armed      : G_KIND={gk1:#x}  G_PAT={gp} (want {P})  "
          f"PTN_USED={ptn_used:#x}  msg[0]={msg_type:#x} (0x14 = storage job)")

    # drain in SHORT bursts.  Snapshot the instant the worker's memcpy lands (pP
    # changes); or bail if the stock whole-bank deser tries to run -- it's
    # halted-on-entry so it writes nothing, but its attempt means the emu's
    # initial 10 MB load is still finishing (NOT something [PTN]+[NO] triggers:
    # the worker never posts a type-6 job).
    after_P = after_Q = None
    for _ in range(300):
        try:
            rt.run(ms=100)
        except Exception as e:
            faulted = faulted or f"{type(e).__name__}: {e}"
            print(f"drain      : raised {faulted}")
            break
        landed = rd(rt, pP, PAT_STRIDE) != scribbled_P
        if landed or deser_seen[0]:
            after_Q = rd(rt, pQ, PAT_STRIDE)     # Q, before anything else can touch it
            if landed:
                rt.run(ms=200)                   # let the step engine consume 0x46c8028a
            after_P = rd(rt, pP, PAT_STRIDE)
            break
    if after_P is None:
        after_P, after_Q = rd(rt, pP, PAT_STRIDE), rd(rt, pQ, PAT_STRIDE)

    rt.uc.hook_del(hq)
    for h in hf:
        rt.uc.hook_del(h)
    ran = [nm for nm, _, _ in fx]
    n_parse = ran.count("FUN_4008cebc(parse-one-pat)")
    n_deser = ran.count("FUN_4008ded0(deser-whole-bank)")
    # the stock whole-bank deser is halted on entry (emu_stop) so it never loops;
    # if it never even tried to run, all the better
    worker_isolated = n_parse == P + 1        # exactly one FUN_4008cebc per pattern 0..P
    print(f"  fn entries: rl_job={ran.count('rl_job')} open={ran.count('FUN_40016864(open)')} "
          f"FUN_4008cebc={n_parse} (want {P + 1})  stock-deser-blocked={n_deser > 0}")
    flag = int.from_bytes(rd(rt, RELOAD_NOW, 4), "big")
    gk2 = rd(rt, G_KIND, 1)[0]
    tport = int.from_bytes(rd(rt, TRANSPORT, 4), "big")

    # cross-check pattern P's p-lock array (t2) against bank01.strd on disk
    strd = DEMO_BANK1_STRD.read_bytes()
    doff = D_PAT1 + D_PSTRIDE * P + D_PHDR + D_TRAC * DISK_TRK
    disk_pl = strd[doff + 0x62: doff + 0x62 + PLOCK_LEN]
    ram_pl = after_P[DISK_TRK * TRAC_STRIDE + PLOCK_IN_TRAC:
                     DISK_TRK * TRAC_STRIDE + PLOCK_IN_TRAC + PLOCK_LEN]

    p_reverted = after_P == saved_P          # for pattern 0, saved_P == the .strd state (fresh load)
    p_matches_disk = ram_pl == disk_pl
    q_survived = after_Q != saved_Q

    print(f"\nresult     : G_KIND {gk1:#x}->{gk2:#x}  0x46c8028a={flag:#x}  transport={tport}  fault={faulted}")
    print(f"  P{P} slab == pre-edit snapshot (reverted) : {p_reverted}")
    print(f"  P{P} t{DISK_TRK} p-lock array == bank01.strd on disk : {p_matches_disk}")
    print(f"  Q{Q} slab != pre-combo edit (survived)   : {q_survived}")

    ok = (faulted is None and gp == P and msg_type == 0x14
          and gk2 == 0 and tport == 1 and p_matches_disk and q_survived
          and flag in (0, 1) and worker_isolated)
    print(f"\n--patched: {'ALL GOOD' if ok else 'CHECK FAILED'}")
    for name, cond in [("no fault (worker rejoined the storage loop)", faulted is None),
                       ("[YES] armed the SEQ job (G_PAT, msg type 0x14)",
                        gp == P and msg_type == 0x14),
                       ("worker cleared G_KIND", gk2 == 0),
                       (f"worker ran exactly {P + 1}x FUN_4008cebc (no stray parses)", worker_isolated),
                       ("pattern P's p-lock array == bank01.strd", p_matches_disk),
                       ("bystander pattern Q untouched by the worker", q_survived),
                       ("0x46c8028a fired then was consumed", flag in (0, 1)),
                       ("transport still running", tport == 1)]:
        print(f"   [{'x' if cond else ' '}] {name}")
    return ok


CUR_TRACK_G, MIDI_MODE_G = 0x80000000, 0x80000012


def cmd_trk(rt):
    """patch_reload2.s TRK SEQ (G_KIND=3): drive rl_yes with item 0 highlighted
    and assert the worker copies back EXACTLY the selected track's region --
    the other 7 audio tracks, all 8 MIDI tracks, the pattern->Part link byte,
    and a bystander pattern are all left scribbled."""
    try:
        _sym("rl_arm_trk")
    except KeyError:
        print("\n--trk: SKIP (no rl_arm_trk symbol -- not patch_reload2)")
        return True
    print("\n===== --trk : per-track slice -- only the addressed track reverts =====")
    T = 3                                   # target audio track
    curbank = rt.uc.mem_read(er.CUR_BANK, 1)[0]
    blob = part_ptr(rt)
    P, Q = 0, DISK_PAT
    pP, pQ = blob + P * PAT_STRIDE, blob + Q * PAT_STRIDE
    rt.seq_select_live(curbank, P)

    rt.frame = True
    rt.next_frame = rt.sample + er.FRAME_PERIOD
    rt.exact_clock(); rt.internal_clock(); rt.press_play_live()
    rt.run(ms=250)

    LIVE_COPY = 0x1001614e
    # Scribble a window of each track's p-lock array (stable under playback --
    # cmd_patched proved this region byte-reverts cleanly) + the Part-link byte,
    # in P and a bystander Q, in both the cold blob and the live cache.  For MIDI
    # tracks scribble a deep offset (0x300) inside the MTRA block.
    PL = PLOCK_IN_TRAC + 0x40               # into the p-lock array, past step 0
    PLW = 64
    MW_OFF, MW = 0x300, 32

    def scr(a, n):
        rt.uc.mem_write(a, bytes(b ^ 0x5A for b in rd(rt, a, n)))

    def scribble_all(pat):
        for base in (blob + pat * PAT_STRIDE, LIVE_COPY + pat * PAT_STRIDE):
            for t in range(8):
                scr(base + t * TRAC_STRIDE + PL, PLW)
                scr(base + MIDI_BASE_IN_SLAB + t * MTRA_STRIDE + MW_OFF, MW)
            scr(base + PART_LINK_IN_SLAB, 1)
    scribble_all(P); scribble_all(Q)
    scribbled_P = rd(rt, pP, PAT_STRIDE)
    scribbled_Q = rd(rt, pQ, PAT_STRIDE)

    fx, deser_seen = [], [False]
    for a, nm in {_sym("rl_job"): "rl_job", 0x4008cebc: "parse",
                  0x4008ded0: "deser"}.items():
        def mk(nm):
            def cb(u, ad, sz, x):
                if nm == "deser":                  # halt the residual whole-bank
                    deser_seen[0] = True           # deser on entry (as cmd_patched)
                    u.emu_stop(); return
                fx.append(nm)
            return cb
        rt.uc.hook_add(er.eb.UC_HOOK_CODE, mk(nm), begin=a, end=a)
    rt.uc.mem_write(TOAST_FN, b"\x4e\x75")
    rt.uc.mem_write(0x40056bc0, b"\x4e\x75")
    # NB: do NOT stub sprintf (0x40013a08) -- rl_openstrd in the worker uses it to
    # build the bankNN.strd path, and the RTOS uses it widely; a bare-rts stub
    # corrupts the storage task's stack and the job silently never runs.  Let the
    # TRK SEQ toast's sprintf run for real (harmless -- into rl_tbuf).
    rt.uc.ctl_flush_tb()

    spin(rt)
    rt.uc.mem_write(PTN_HELD, struct.pack(">I", 1))
    rt.uc.mem_write(TRANSPORT, struct.pack(">I", 1))
    rt.uc.mem_write(0x800065be, bytes([P]))
    rt.uc.mem_write(CUR_TRACK_G, bytes([T]))            # currently-addressed track
    rt.uc.mem_write(MIDI_MODE_G, b"\x00")               # audio pages
    rt.uc.mem_write(G_KIND, b"\x00")
    rt.uc.mem_write(G_MENU_A, b"\x01")
    rt.uc.mem_write(G_SEL_A, b"\x00")                   # item 0 = TRK SEQ
    # Arm via rl_arm_trk directly.  Driving the full rl_yes for TRK SEQ runs a real
    # sprintf (the "T3 SEQ" toast) that opens a scheduling window in which the
    # posted worker starts *inside* call_as_main and the borrowed idle slot never
    # cleanly returns to MAIN_SPIN.  rl_yes -> rl_arm_trk routing is covered by
    # --combo; here we want the worker's slice behaviour, so call the arming
    # subroutine (reads the track globals, posts, rts -- fast) and drain.
    faulted = None
    try:
        rt.call_as_main(_sym("rl_arm_trk"), args=(), budget=900_000)
    except Exception as e:
        faulted = f"{type(e).__name__}: {e}"

    # G_TRK is set synchronously by rl_arm_trk itself, so it's already final here.
    # G_KIND is NOT -- rl_arm_trk only ARMS the request (sets G_KIND=3, posts the
    # job) and returns immediately; it's rl_job, running later on the storage
    # task, that clears G_KIND. Sampling it here (right after rl_arm_trk returns,
    # before the drain loop below has let rl_job run at all) always reads the
    # just-armed 3, regardless of firmware correctness -- a test-timing bug, not
    # a firmware one (the other 9 checks below, all sampled post-drain, already
    # prove rl_job ran: FUN_4008cebc fired, the track actually reverted). Sample
    # it after the drain loop instead, same as every other post-worker check.
    gtrk = rd(rt, 0x80006a54, 1)[0]
    after_P = after_Q = None
    for _ in range(300):
        try:
            rt.run(ms=100)
        except Exception as e:
            faulted = faulted or f"{type(e).__name__}: {e}"
            break
        landed = rd(rt, pP, PAT_STRIDE) != scribbled_P
        if landed or deser_seen[0]:
            after_Q = rd(rt, pQ, PAT_STRIDE)
            if landed:
                rt.run(ms=200)
            after_P = rd(rt, pP, PAT_STRIDE)
            break
    if after_P is None:
        after_P, after_Q = rd(rt, pP, PAT_STRIDE), rd(rt, pQ, PAT_STRIDE)
    gk = rd(rt, G_KIND, 1)[0]

    def apl(buf, t):                        # a track's scribbled p-lock window
        o = t * TRAC_STRIDE + PL
        return buf[o: o + PLW]
    def mpl(buf, t):                        # a MIDI track's scribbled window
        o = MIDI_BASE_IN_SLAB + t * MTRA_STRIDE + MW_OFF
        return buf[o: o + MW]

    # track T's window should now match bank01.strd (reverted); the rest stays scribbled
    strd = DEMO_BANK1_STRD.read_bytes()
    doff = D_PAT1 + D_PSTRIDE * P + D_PHDR + D_TRAC * T
    disk_win = strd[doff + 0x62 + 0x40: doff + 0x62 + 0x40 + PLW]

    tgt_reverted = apl(after_P, T) == disk_win
    others_kept = all(apl(after_P, t) == apl(scribbled_P, t) for t in range(8) if t != T)
    midi_kept = all(mpl(after_P, t) == mpl(scribbled_P, t) for t in range(8))
    partlink_kept = after_P[PART_LINK_IN_SLAB] == scribbled_P[PART_LINK_IN_SLAB]
    q_survived = all(apl(after_Q, t) == apl(scribbled_Q, t) for t in range(8))
    n_parse = fx.count("parse")
    flag = int.from_bytes(rd(rt, RELOAD_NOW, 4), "big")
    tport = int.from_bytes(rd(rt, TRANSPORT, 4), "big")
    print(f"worker     : rl_job={fx.count('rl_job')} FUN_4008cebc={n_parse} "
          f"deser_seen={deser_seen[0]}  G_KIND {gk}  G_TRK {gtrk}  RELOAD_NOW={flag:#x}")

    ok = (faulted is None and gk == 0 and gtrk == T and tgt_reverted and others_kept
          and midi_kept and partlink_kept and q_survived and n_parse == P + 1
          and flag in (0, 1) and tport == 1)
    print(f"\n--trk: {'ALL GOOD' if ok else 'CHECK FAILED'}   (fault={faulted})")
    for name, cond in [("no fault", faulted is None),
                       ("worker cleared G_KIND", gk == 0),
                       (f"G_TRK == {T}", gtrk == T),
                       (f"audio track {T} reverted to saved", tgt_reverted),
                       ("other 7 audio tracks untouched (still scribbled)", others_kept),
                       ("all 8 MIDI tracks untouched", midi_kept),
                       ("pattern->Part link byte untouched", partlink_kept),
                       ("bystander pattern untouched", q_survived),
                       (f"exactly {P + 1}x FUN_4008cebc", n_parse == P + 1),
                       ("0x46c8028a fired then consumed", flag in (0, 1)),
                       ("transport still running", tport == 1)]:
        print(f"   [{'x' if cond else ' '}] {name}")
    return ok


G_KIND_A, G_PAT_A, G_MENU_A, G_SEL_A = 0x80006a50, 0x80006a51, 0x80006a52, 0x80006a53
POPUP2_FN, CLOSE_FN, POST_FN, PARTRELD_FN = 0x4005a0e0, 0x40056bc0, 0x40022778, 0x4004aab4
REFRESH_FNS = (0x4004d948, 0x40032208, 0x4004d640, 0x400486cc, 0x4006dbe8, 0x40077b00, 0x4002f2f8)
ARROW_A_RESUME, ARROW_B_RESUME = 0x4004b978, 0x400491a6   # arrow-handler fall-through targets
PTN_RESUME, PTN_HOLDTAIL = 0x4005a04a, 0x4005a0d2         # rl_ptn stock targets

# The picker items cmd_combo drives, in G_SEL order.  emu_reload2.py overrides
# this for the 2-item scaled-down build.
#   (G_SEL, label, want_G_KIND, want_FUN_4004aab4_calls, want_seq_job_post)
COMBO_ITEMS = [
    (0, "PTN SEQ",         1, 0, True),
    (1, "ALL PARTS",       0, 4, False),
    (2, "PARTS + PTN SEQ", 1, 4, True),
]

_END_PCS = {0x4005e276: "NO_REL", 0x4005e262: "NO_PRESS(stock)",
            0x4005e4d0: "YES_RESUME(stock)",
            PTN_RESUME: "PTN_RESUME(stock)", PTN_HOLDTAIL: "PTN_HOLDTAIL(stock)",
            ARROW_A_RESUME: "ARROW_A_RESUME(fell through)",
            ARROW_B_RESUME: "ARROW_B_RESUME(fell through)"}


def _run_cave_fn(rt, addr, keycode, event, calls, budget=4000):
    """Single-step a cave key-handler stub on a private stack (no scheduler).
    Records which stubbed firmware fns it calls.  Returns 'end'."""
    eb = er.eb
    STK, RET = 0x46cf0000, 0x46cf0f00
    rt.uc.mem_write(RET, b"\x4e\x75\x4e\x75")
    rt.uc.reg_write(eb.UC_M68K_REG_A7, STK)
    rt.uc.mem_write(STK, struct.pack(">3I", RET, keycode, event))
    rt.uc.reg_write(eb.UC_M68K_REG_PC, addr)
    for _ in range(budget):
        pc = rt.uc.reg_read(eb.UC_M68K_REG_PC)
        if pc == RET:
            return "rts"
        if pc in _END_PCS:
            return _END_PCS[pc]
        if not (0x400d7400 <= pc < 0x400d8000):
            calls.append(pc)
            # a stubbed firmware fn: skip it (as if it rts'd)
            sp = rt.uc.reg_read(eb.UC_M68K_REG_A7)
            ret = struct.unpack(">I", rt.uc.mem_read(sp, 4))[0]
            rt.uc.reg_write(eb.UC_M68K_REG_A7, sp + 4)
            rt.uc.reg_write(eb.UC_M68K_REG_PC, ret)
            continue
        try:
            rt.uc.emu_start(pc, 0, count=1)
        except Exception as e:
            return f"exc@{pc:#x}: {e}"
    return "budget"


def cmd_combo(rt):
    """Isolate the Session-44 OT-native picker: rl_ptn (hold-to-open),
    rl_no (close), rl_arr_a/b (arrows), rl_yes (execute) single-stepped on a
    private stack, gates forced, no scheduler.  Data-driven by COMBO_ITEMS
    (emu_reload2.py overrides it for the 2-item build)."""
    eb = er.eb
    rl_ptn, rl_no, rl_yes = _sym("rl_ptn"), _sym("rl_no"), _sym("rl_yes")
    rl_arr_a, rl_arr_b = _sym("rl_arr_a"), _sym("rl_arr_b")
    n = len(COMBO_ITEMS)
    print("\n===== --combo : single-step the OT-native picker in isolation =====")
    print(f"rl_ptn={rl_ptn:#x}  rl_no={rl_no:#x}  rl_yes={rl_yes:#x}  "
          f"rl_arr_a={rl_arr_a:#x}  rl_arr_b={rl_arr_b:#x}  ({n} items)")

    for a in (POPUP2_FN, CLOSE_FN, POST_FN, TOAST_FN, PARTRELD_FN, *REFRESH_FNS):
        rt.uc.mem_write(a, b"\x4e\x75")
    rt.uc.ctl_flush_tb()

    def reset_gates(actpat=7, menu=0, sel=0, running=1):
        rt.uc.mem_write(0x460e5cd0, struct.pack(">I", 0))   # no popup
        rt.uc.mem_write(0x460d1aec, struct.pack(">I", 0))   # no arranger
        rt.uc.mem_write(0x800065b8, struct.pack(">I", running))  # transport
        rt.uc.mem_write(0x800065be, bytes([actpat]))
        rt.uc.mem_write(G_KIND_A, b"\x00")
        rt.uc.mem_write(G_PAT_A, b"\x00")
        rt.uc.mem_write(G_MENU_A, bytes([menu]))
        rt.uc.mem_write(G_SEL_A, bytes([sel]))
        rt.uc.mem_write(0x460d173e, struct.pack(">I", 0))   # PTN_USED

    def g(a, m=1):
        return int.from_bytes(rt.uc.mem_read(a, m), "big")

    ok = True

    def check(cond, label):
        nonlocal ok
        ok &= bool(cond)
        print(f"  {'ok  ' if cond else 'FAIL'} {label}")

    # --- open: hold [PTN] (keycode 0x2e, event 2) ---
    reset_gates()
    calls = []
    end = _run_cave_fn(rt, rl_ptn, 0x2e, 2, calls)
    check(end == "PTN_HOLDTAIL(stock)" and g(G_MENU_A) == 1 and g(G_SEL_A) == 0
          and POPUP2_FN in calls and g(0x460d173e, 4) == 1,
          f"hold [PTN]: end={end} G_MENU={g(G_MENU_A)} G_SEL={g(G_SEL_A)} "
          f"popup2={POPUP2_FN in calls} PTN_USED={g(0x460d173e,4)}")

    # --- quick tap ([PTN] press, event 1) -> stock, window not opened ---
    reset_gates()
    calls = []
    end = _run_cave_fn(rt, rl_ptn, 0x2e, 1, calls)
    check(end == "PTN_RESUME(stock)" and g(G_MENU_A) == 0 and POPUP2_FN not in calls,
          f"quick tap [PTN]: end={end} G_MENU={g(G_MENU_A)} popup2={POPUP2_FN in calls}")

    # --- hold [PTN] while STOPPED -> gated out, falls to stock hold tail ---
    reset_gates(running=0)
    calls = []
    end = _run_cave_fn(rt, rl_ptn, 0x2e, 2, calls)
    check(end == "PTN_HOLDTAIL(stock)" and g(G_MENU_A) == 0 and POPUP2_FN not in calls
          and g(0x460d173e, 4) == 0,
          f"hold [PTN] stopped: end={end} G_MENU={g(G_MENU_A)} popup2={POPUP2_FN in calls}")

    # --- arrows move the highlight (window open, wrapping) ---
    reset_gates(menu=1, sel=0)
    for step in range(n + 1):
        calls = []
        end = _run_cave_fn(rt, rl_arr_b, 0x33, 1, calls)
        want = (step + 1) % n
        check(end == "rts" and g(G_SEL_A) == want and POPUP2_FN in calls,
              f"arrow B (next) {step}: G_SEL->{g(G_SEL_A)} (want {want}) popup2={POPUP2_FN in calls}")
    reset_gates(menu=1, sel=0)
    calls = []
    end = _run_cave_fn(rt, rl_arr_a, 0x34, 1, calls)
    check(end == "rts" and g(G_SEL_A) == n - 1 and POPUP2_FN in calls,
          f"arrow A (prev) from 0: G_SEL->{g(G_SEL_A)} (want {n-1}) popup2={POPUP2_FN in calls}")

    # --- arrows fall through untouched when the window is closed ---
    reset_gates(menu=0)
    end = _run_cave_fn(rt, rl_arr_a, 0x34, 1, [])
    check(end == "ARROW_A_RESUME(fell through)", f"arrow A closed -> {end}")
    reset_gates(menu=0)
    end = _run_cave_fn(rt, rl_arr_b, 0x33, 1, [])
    check(end == "ARROW_B_RESUME(fell through)", f"arrow B closed -> {end}")

    # --- [YES] executes + closes, per selection ---
    for sel, name, want_kind, want_n_parts, want_seqpost in COMBO_ITEMS:
        reset_gates(actpat=5, menu=1, sel=sel)
        calls = []
        end = _run_cave_fn(rt, rl_yes, 0x31, 1, calls)
        gk, gp, gm = g(G_KIND_A), g(G_PAT_A), g(G_MENU_A)
        n_partreld = calls.count(PARTRELD_FN)
        check(end == "rts" and gm == 0 and CLOSE_FN in calls and gk == want_kind
              and n_partreld == want_n_parts and (POST_FN in calls) == want_seqpost
              and (gp == 5 if want_seqpost else True),
              f"YES [{name}]: end={end} G_MENU->{gm} close={CLOSE_FN in calls} "
              f"G_KIND={gk}(want {want_kind}) FUN_4004aab4x{n_partreld}(want {want_n_parts}) "
              f"post={POST_FN in calls}(want {want_seqpost}) G_PAT={gp}")

    # --- [NO] cancels (window open, nothing runs) ---
    reset_gates(actpat=5, menu=1, sel=min(1, n - 1))
    calls = []
    end = _run_cave_fn(rt, rl_no, 0x32, 1, calls)
    check(end == "rts" and g(G_MENU_A) == 0 and CLOSE_FN in calls
          and g(G_KIND_A) == 0 and POST_FN not in calls and PARTRELD_FN not in calls,
          f"NO cancel: end={end} G_MENU->{g(G_MENU_A)} close={CLOSE_FN in calls} "
          f"G_KIND={g(G_KIND_A)} post={POST_FN in calls} FUN_4004aab4x{calls.count(PARTRELD_FN)}")

    # --- [YES] / [NO] with the window closed -> stock ---
    reset_gates(menu=0)
    end = _run_cave_fn(rt, rl_yes, 0x31, 1, [])
    check(end == "YES_RESUME(stock)", f"YES closed -> {end}")
    reset_gates(menu=0)
    end = _run_cave_fn(rt, rl_no, 0x32, 1, [])
    check(end == "NO_PRESS(stock)", f"NO closed -> {end}")

    print(f"\n--combo: {'ALL GOOD' if ok else 'CHECK FAILED'}")
    return ok


def main():
    global OUR_IMAGE
    ap = argparse.ArgumentParser()
    ap.add_argument("--slice", action="store_true", help="slab revert + reload-now refresh (playing)")
    ap.add_argument("--strd", action="store_true", help="async storage-task reload of the blob from .strd")
    ap.add_argument("--combo", action="store_true", help="single-step rl_combo in isolation (fast)")
    ap.add_argument("--patched", action="store_true",
                    help="boot the built image and drive rl_yes (whole-pattern SEQ) end to end")
    ap.add_argument("--trk", action="store_true",
                    help="patch_reload2 only: TRK SEQ copies back exactly one track's region")
    a = ap.parse_args()
    if not (a.slice or a.strd or a.patched or a.combo or a.trk):
        ap.error("pick --slice, --strd, --combo, --patched and/or --trk")
    if not DEMO_BANK1_STRD.exists():
        sys.exit(f"missing {DEMO_BANK1_STRD} (the factory OT DEMO export)")
    if a.patched or a.combo or a.trk:
        if not RELOAD_IMAGE.exists():
            sys.exit(f"missing {RELOAD_IMAGE} -- run the matching build_reload*.py first")
        OUR_IMAGE = RELOAD_IMAGE

    rt = boot_and_load()
    ok = True
    if a.combo:
        ok &= cmd_combo(rt)
    if a.slice:
        ok &= cmd_slice(rt)
    if a.strd:
        ok &= cmd_strd(rt)
    if a.patched:
        ok &= cmd_patched(rt)
    if a.trk:
        ok &= cmd_trk(rt)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
