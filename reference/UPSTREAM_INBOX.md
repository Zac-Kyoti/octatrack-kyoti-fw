# Upstream inbox — external changes not yet distilled

`tools/refs/whatsnew.py` output, triaged. Newest first. When a line is fully
folded into `reference/kb/`, move it to the "Distilled" section with the target
file noted. This file is the hand-off point for the (optional) weekly scheduled
agent that fetches the refs and appends new commits here.

## ⚠️ Two entries below are stamped "out of scope per COVERAGE.md". That stamp is stale.

DSP work is **in scope** for this project — it ships DSP56300 assembly (SIDECHAIN3),
and `CLAUDE.md` "Scope of this project" is now the policy (`COVERAGE.md` is the
descriptive map, not the gate). The affected entries are octabam's 2026-09-12
DSP-effect pass and the 2026-09-24 `dsp56300` core commits. **Re-triage either before
treating it as settled**; anything marked out of scope for being DSP is worth a second
look.

## Format

```
- YYYY-MM-DD  <repo>@<short-hash>  <one-line summary>   [ TODO | kb/<file> ]
```

## Pending

- 2026-09-16  octabam@0ad97b9  178 new commits since our 2026-09-14 pin (2 days).
              **CLOSED 2026-09-24** — done as part of the 397-commit skim below;
              the doc set it told us to skim has since been reorganised (see that
              entry).                                              [ closed — see 2026-09-24 octabam ]
- 2026-09-06  octamax@7d9debc  OCTAMAX 2.x — dual-256 static-pool reclaim (DDR
              relocation), OCTAMAX_2 combined release. Techniques noted in
              kb/techniques.md; not adopted.                          [ noted, not adopted ]
- 2026-09-12  octabam@0ec42f3  DSP-effect "ear pass" continuation (BusVerb/BusDelay,
              Character, Modulation, Spectrum tuning + one-aux bus work) —
              out of scope per COVERAGE.md.                             [ out of scope ]
- 2026-09-12  octabam@0ec42f3  RTOS_FORK 10.19–10.59 supersedes the 09-08 "not ours"
              triage below — the recorder-click chase (route A / emu_rtos.py +
              a new C++ "port" doing real DSP+ColdFire audio render, `tools/ot_emu`
              --mem-dump/--dsp-stopwatch) runs straight through the arm/frame-builder
              path our Session 49 Part-carryover fix sits next to. Cross-checks worth
              doing against `patch_partreapply`: (1) their arm-caller address
              `0x40006238`, corrected off an earlier wrong guess of
              `0x4000672c`/`0x40006a2c` which they now call "a different,
              PICKUP-only follow-up mechanism, not the FLEX arm path" — worth a look
              since report #1 is exactly a PICKUP follow-up bug; (2) their
              independent confirmation that the per-frame per-track dispatcher
              `0x400068e4` runs at 16/frame matches our own `FUN_400068e4` reading
              (NOTES Session 49, "control-rate voice updater") — corroborates our
              calling-convention re-derivation, not a contradiction; (3) lane-table
              fill `0x4000aece..0x4000af22` (trig-word composition) — unmapped by us,
              could refine the sequencer trig model later.        [ TODO — cross-check
              against S49 before next patch_partreapply revision, then fold the
              confirmed pieces into kb/memory-map.md ]
              **PARTIALLY RESOLVED 2026-09-24.** (2) their `0x400068e4` confirmation was
              already folded. (3) the sequencer/recorder model is now much better mapped —
              `RECORDER.md` gives the recorder **arm caller as `0x40005ff0`** (note: a
              *different* address from the `0x40006238` this entry chased, and from the
              retracted `0x4000672c`/`0x40006a2c`), plus the three storage tiers and the QREC
              scheduler `0x40005178`. (1) the PICKUP-follow-up cross-check itself is
              **superseded in framing**: S49's root cause is no longer "a missing call" but an
              enumerated delta between three part-apply variants, and `patch_partreapply` was
              audited against it (`reference/MERGE.md`) with **no change needed**. What is
              still genuinely open: the lane-table fill `0x4000aece..0x4000af22`, and
              upstream's own ❓ on why the PICKUP arm reads the FOUT slot — which is plausibly
              the same PICKUP-specific oddity report #1 describes.
                                          [ TODO — narrowed: the PICKUP/FOUT-slot question ]
- 2026-09-12  ems-octakit@8ded517  6 commits since ec70dda: mostly Octakit's own
              256-Kits-runtime bugfixes (stale popup/descriptor ownership at a
              Kit/Pattern handoff) + a crash-report refactor, not stock-firmware
              content. Five new named addresses distilled into kb/octakit-abi.md
              "Recording Setup menu / LOAD KIT". Also shipped a LICENSE (MIT) —
              CREDITS.md updated.                                  [ kb/octakit-abi.md ]

## Distilled

- 2026-09-24  **PENDING ITEMS FROM THIS MORNING'S SYNC — ALL CLEARED.** Second pass the same
              day. (a) **octabam's unread firmware docs**: `PARAM_PAGES.md` §5g distilled
              (step-record parameter semantics PLAYBACK/LFO/AMP/FX1/FX2 by byte, the **trig
              word** `TRAC+0x89a+(s-1)*2` with its count/micro-timing/condition bitfields and
              its **RAM-vs-FILE one-byte skew**, sample-lock store `0x40040ee0`, p-lock store
              `0x4004f5f8` and its trig-key-down precondition, part payload offsets,
              `fx1_disallowed_effects`); `RECORDER.md` distilled (**the three recorder storage
              tiers** — bank / SRAM / per-frame-published `0x80000cf4` — which is the
              mechanism behind S49's recorder carry-over report; the **tempo chain**
              `0x4000ca94..cabc` that explains why `FUN_40009094` writes four tempo words;
              QREC scheduler `0x40005178`; recorder buffers as arena ids 128-135 armed by
              opcode `0x25`; and the reconciliation that octabam's `0x400d80e0` ladder and
              octemu's `seq_quant_length_table 0x400d80dc` are **one table read from opposite
              ends**, shared by QREC/QPL and chain-quantise). Remaining octabam docs
              (`PANEL`, `MAINMENU`, `LFO`, `LEVEL_LAW`, `STORAGE`, `CHIP`, `TABLES`,
              `REPITCH`, `COLDFIRE_DELAY`, `tools/hw/*`) reviewed for scope and carry nothing
              bearing on a current thread — logged as reviewed, not unread.
              (b) **octemu's remaining symbols**: swept in the most useful direction — every
              address our 8 shipped/WIP patches touch, cross-referenced against all 768
              symbols. Yield: `bank_reload_gate_read` corroborates `patch_qlrec`'s detour
              site; `0x4000d49e` confirms `patch_softmute` sits inside the frame ISR
              (supporting the MACSR closure); **`sample_heap_base 0x40a955e0` with an
              arithmetic proof it is exactly where the 16 bank blobs end**; and the
              **`0x400e21e0` dual identity** (DSP bootstrap in the image file, bank blob at
              runtime — patching the image there corrupts the DSP loader).
              (c) **octemu's USB-Audio CF-card-payload trick**: distilled as a second route
              past the cave ceiling, with a better failure mode than append-a-runtime (no
              card file = stock behaviour; recovery is hold-NO-at-boot or delete the file),
              plus its **hardware-measured SDRAM scratch verdicts** (`0x48001000` wrong —
              writes past ~`0x48003000` destroy image code; `0x48010000` corrupts the
              exception screen itself; `0x49000000` clean for 256 KB).
              (d) **octamachine**: read `BOOT_FEASIBILITY.md` + `COMPATIBILITY_MATRIX.md` —
              **confirmed out of scope on reading**. It is MCF5206E / Machinedrum territory
              (Gearmulator's MD memory map, MAME's `elektronmono.cpp`); the only
              Octatrack-side sentence just restates octemu's board setup. Nothing for us.
              (e) **midisc-patcher**: `patch.json` read — `{stockSha256 164f3122…,
              patchedSha256, mainOsSize 1112560, spans[549] {offset,data}}`. Distilled as a
              **distribution pattern**: we could publish a redistributable single-file span
              diff and, more cheaply, a `patchedSha256` **rebuild-reproducibility gate** our
              builds do not currently give the user.
              [ kb/memory-map.md, kb/caves.md, kb/techniques.md, kb/file-format.md ]
- 2026-09-24  **AUDIT: the seven finished mods vs everything ingested today. No mod needs
              rebuilding or reflashing.** Recorded per-mod in `reference/MERGE.md` "Audit of
              the finished set". Highlights: **PARTREAPPLY validated** — its transport gate on
              `FUN_40009094` turns out to be exactly right, because that is the only variant
              that re-arms the audio eDMA chain and republishes tempo (a hunch in its comment
              is now a mechanism), and its `(bank, part)` convention is confirmed while
              octemu's label is wrong. **MUTE MODE validated** — the MACSR preemption hazard
              it was designed around is impossible (level 5 vs level 1), which shrinks its
              risk surface to the two level-6 sources. **Bug-2 pattern-LED root cause
              sharpened** — verified by disassembly that stock's predicate skips exactly
              `+0x10..0x17`, the trigless-lock mask; a cheaper fix exists and is deliberately
              **not** adopted (the mask's label is disputed 🟡/✅ upstream, the MIDI side is
              unmapped, and our array scan is correct either way). **QLREC no bug** — it only
              replays the gate `jsr`, so the "wider than a byte" warning does not apply.
              **`0x800000d4` does not affect any shipped mod** — proven by assembling the
              shipping `DT_MODE=1` softmute (970 B, no reference; only the 986 B diagnostic
              build has it). Cave overlaps with octalab/octabam/midisc documented — they rule
              out naive merged images, nothing else.       [ reference/MERGE.md, kb/caves.md ]
- 2026-09-24  **CORRECTION to this morning's own entry.** The first pass recorded
              `0x800000d4` as "NOT free" on midisc's + MERGE.md's word. Swept the image
              myself afterwards: **zero absolute-long references to any word in
              `0x800000d4..df`** — including `0x800000dc`, which MUTE MODE ships on. That is
              the tell that `0x80000070` is a block base reached by **displacement**, so no
              absolute scan (ours or Session 20's) proves anything either way — exactly what
              MERGE.md's own B1 text says about `0x800000f8`. What does settle the
              PERSONALIZE question: stock's boot restore is `memcpy` length `0x64`, ending
              one byte short of `0xd4`. **MERGE.md's "referenced once in stock" is
              unsubstantiated — do not propagate it.** `kb/memory-map.md` now records all
              four sources, the method artefact, and the emulator-watchpoint test that would
              actually settle it.                          [ kb/memory-map.md, NOTES.md ]

- 2026-09-24  octalab@e0dc56d  **NEW repo, new contributor (nordseele; MIT, findings
              only — renamed from `octalab-notes`, which still redirects).** The single
              most valuable ingest of this sync: creative helpers on stock OS 1.40C
              **built and tested on an Octatrack MKI** — the same hardware and OS as
              this project, which no other upstream can say. Distilled:
              **the cave ledger + the hardware-proven verdict that the image tail
              (`0x401087e4`/`0x4010cdd1`, 27 KB of zeros with ZERO static refs) is
              live at runtime and bricked a unit into MIDI-only recovery** (→ new
              `kb/caves.md`); the canary protocol; the classic cave's five-way
              ownership; **"a Part lives three times"** and the bank-only-write-is-lost
              trap, with `0x40029a4c` → `0x40009094(bank, part)` — which independently
              corroborates our own disassembly of the part-apply family; input maps as
              **layers** (`0x40031494`, keys `0x46c7d8de+code*0x18`, encoders
              `0x46c7dede+enc*0x14`, last-map-wins, `-1` passes through, null encoder
              handler swallows) + the stuck-held-trig hazard (`0x460d174a`); the
              callable SETUP-window draw primitives; trig step records (64 x 32 B from
              `TRAC+0x59`, sample lock = byte 31) + store `0x40040ee0`; master length is
              a **u16 at `+0x8e50` with `-1` = INF**; the FS vtable `0x46c823fa` + walker
              `0x40090a14` and its last-entry trap; slot-load needs the dispatcher's two
              refreshes; WAV writer `0x40024168` needs `0x460be9e8`/`ec` set;
              recorder reserve 460 x 0x1800 = 16.0 s; the CRLF regex trap; and
              **octabam's DRAM loader booting on a MKI** (the append-a-runtime route is
              MKI-proven, with the FREE MEM / MEMORY-page total artefact).
              [ kb/caves.md (new), kb/memory-map.md, kb/file-format.md, kb/techniques.md ]
- 2026-09-24  (our RE, prompted by octemu + octalab)  **The part-apply family — the
              Session 49 answer.** Disassembled `0x40009094` / `0x40009848` /
              `0x40009e00` and diffed their absolute-write and `jsr` sets mechanically:
              three variants share a prologue, but **only `0x40009094` (`STOCK_APPLY`)
              republishes tempo (`0x80001814/18/1c`, `0x80001824`), re-arms the audio
              eDMA TCD0/TCD1 chain (`0xfc04501e`/`0xfc04503e` + TCD6/7) and
              re-unmasks INTC0, and posts a kernel queue message**. Verified that
              `seq_goto_pattern` (`0x400a0570`) reads the pattern->Part link at slab
              `+0x8e57` (`0x400a05e8`) and calls the **light** `0x40009e00` — so the S49
              hypothesis "the pattern-change path never runs `FUN_40009094`" is
              **confirmed literally true**, and the carry-over is explained by an
              enumerated delta rather than a missing call. Argument order is
              **`(bank, part)`**, verified three ways; octemu's `apply_part(part,
              pattern)` label is wrong.        [ kb/memory-map.md "The part-apply family" ]
- 2026-09-24  (our RE, prompted by octamad)  **The MACSR/EMAC preemption worry is
              retired, and the interrupt-level table is now complete.** Verified against
              our own image: the frame ISR spans `0x4000aad0..0x4000d9b0` (`0x4000d9ae`
              is the `rte`) and **every** MACSR site in our KB is inside it — so there is
              no "calling task"; it is interrupt context. INTC0 ICR1 = **5** (frame ISR,
              `0x4001fc30`); INTC1 ICR43 = **1** (PIT0, `0x400005e2`). Level 1 cannot
              preempt level 5, so **the scheduler provably cannot land inside the
              MACSR=0x60 window** — the documented open question is closed, and the
              residual surface is narrowed to the two level-6 sources (MIDI IN
              `0x400106ec`, serial link `0x400109bc`). Also scanned every ICR write in
              the image to produce the full 11-row level table, which neither octabam nor
              octemu carries.                  [ kb/memory-map.md "Interrupt levels" ]
- 2026-09-24  octamad@0980fb5 / ccb11fb  **NEW repo (repeat98 / Jannik Assfalg).** An
              octabam fork tracked because octabam's own `CONTRIBUTIONS.md` records that
              his `STOCK_PROFILE.md`, `stock-analysis-fast` module and `--work-profile`
              counter **"were not sent"** upstream. Found them on branch
              `origin/poly-machine` at `ccb11fb` (not on `main`) and read them from the
              object store. Distilled: the stock-firmware instruction profile (frame ISR
              26.21 %, delay 18.74 %, sample analysis 13.80 %, voice renderer 13.70 %),
              the verified frame-ISR and voice-renderer extents, that
              **`FUN_4000c8a4` is not a function boundary** (our
              `tools/patch_partreapply.s` names it), and the methodology caveats that
              stop the numbers being misquoted as headroom.
                                          [ kb/techniques.md, kb/memory-map.md ]
- 2026-09-24  midisc@63ca127  6 commits: **1.40MIDISC8.1 / 8.2**. Distilled: **two new
              safe D-region pads** (`0x400D347E..CF` 81 B, `0x400D352D..6F` 66 B) and
              **three more addresses that are NEVER safe for code** (`0x400C14D5`
              alongside our known `0x400C1153`; table zero-gaps `0x400EC8BC`,
              `0x400E6E5B`) -> `kb/caves.md`; **project-file persistence** as an
              alternative to our battery-block shadow (packed byte `0x460CA680`, key
              `MIDISC_CC_FILT`, load/save trampolines) with its "PERSONALIZE A8/D8/DC
              did not survive on HW" negative result and its bricked-Project-Save
              history; and the two shipped bug classes worth grepping our own patches
              for (a **missing `track*32` stride** that made track 1's locks cross-talk;
              **clobbering the live encoder `d2`** on a write path). Also
              **corroborates independently that `0x800000D4` is NOT free** — which
              contradicted our own `memory-map.md` and is now fixed there.
                                          [ kb/caves.md, kb/techniques.md, kb/memory-map.md ]
- 2026-09-24  dsp56300@2afc1c4  31 commits, **out of scope** per COVERAGE.md (ESAI/DMA/
              HDI08/SHI peripheral timing + JIT-only fixes). Logged with the three
              instruction-semantics items that could ever matter to a DSP patch, and two
              invariants that transfer to our **own** ColdFire harness (update
              peripherals before an instruction that reads one; one peripheral's deadline
              must not postpone another's).              [ kb/dsp56300.md ]
- 2026-09-24  ems-octakit@c6d3f39  2 commits: "reset live Kit workspace when loading
              empty slots" + feature descriptions. Checked `runtime/abi.inc` — **no new
              stock addresses**; the change calls the already-mapped
              `GK_STOCK_PART_PAYLOAD_INITIALIZE` (`0x40005638`). Their own 256-Kit
              runtime, not stock-firmware content.        [ noted, not adopted ]
- 2026-09-24  octamax / OctaLib / elektron-firmware-tool / octa-bt-pt  **up to date**,
              no new commits since the 2026-09-16 pin.   [ nothing to do ]


- 2026-09-16  dsp56300@46aa691  132 commits ahead of octabam's vendored pin
              (`c051afad`, 2026-07-28) — cross-checked against SIDECHAIN3
              (NOTES.md Session 71), the first of our own threads to actually
              touch DSP56300 semantics. Instruction-by-instruction audit of
              `patch_sc_dsp3.asm` against every relevant fix (ASL/ASR carry
              on AArch64/x64, CCR overflow-flag pass, mpyi/maci sign-extend,
              multiplier product-scale fold): all either flag-only bugs our
              branch-free, C/V-blind code never reads, or x64-only/immediate-
              operand-only paths our register-register `mpy`, arm64 host
              never hits. Does not explain the bug via our own patch code;
              the STOCK compressor module's own disassembly was not
              cross-checked the same way (not on hand this session).
                                          [ kb/dsp56300.md "Checked against SIDECHAIN3" ]
- 2026-09-16  octabam@f77d5d7  pulled specifically to root-cause the hook-12
              (`levelchain_mute`) hardware silence regression (NOTES.md "Session 58
              continued yet again, part 3/4"): the RTOS's saved task context
              (`0x400005fc` TCB builder) has no MACSR/EMAC-accumulator slot — only
              d0-d7/a0-a7 — and different frame-builder call sites run the EMAC in
              different MACSR modes (our exact hook site, the level chain at
              `0x4000ccae`, runs fractional `0x60`; two other sites run `0x20`).
              octabam's own ColdFire port independently hit "every voice rendered
              silent" from mismodeling this exact function's MACSR S/U bit (O9b,
              8 Sep 2026) — same failure signature, different cause (their emulator
              vs our detour), but confirms this code is uniquely easy to get wrong.
              Also pulled their general "a lock-step/short-scenario emulator run
              cannot show you a cross-task race; when local says clean and hardware
              says broken, believe the hardware" rule (`CLAUDE.md`), which matches
              our own standing methodology gap for this exact incident.
              [ kb/memory-map.md "Kernel / RTOS scheduler" ]
- 2026-09-16  midisc@eb8b4bc  first sync — new contributor, added to MANIFEST.toml.
              Full 1.40C MIDI-scene address map + XF morph engine + part-save
              freeze-twin persistence pattern + bank-register-clobber fix +
              the "hook the caller, not the shared entry point" Octakit
              composition pattern.
              [ kb/memory-map.md "MIDI track scenes", kb/techniques.md "midisc" ]
- 2026-09-09  ems-octakit@ec70dda  the append-a-runtime architecture — reclaim a flex-pool
              slice (4 constant patches @0x40096f80–0x40097130; cost 18.4 s / 3.6 %),
              append an aPLib-packed ~128 KB ColdFire runtime at 0x45d0dde0, ~10 boot
              splices (0x4000050c / 0x40020870 / 0x4000f97c / 0x40013304 / …). ColdFire
              space only — nothing for the DSP. From link.ld + loader.S + firmware.json.
              [ kb/octakit-abi.md "The append-a-runtime architecture", kb/techniques.md,
                kb/memory-map.md ]
- 2026-09-08  octamax@7d9debc  DESIGN_SLICEVIEW.md — SLICE PLAYHEAD RE (octamax's own
              feature, not ported): voice-struct field map @0x800049d8 (+8/+23/+32/+36/
              +48/+52/+68), FUN_40007960 position engine, slice table SETTINGS+312+n*12
              / count +1092, screen primitives + surface 0x400bf10a, the 0x40056c92
              periodic-repaint hole (event 78 → 0x40062d04)
              [ kb/memory-map.md "Voices" + "Screen drawing primitives" ]
- 2026-09-08  octabam@04b8512  midi_re_cc.md §7 (HW, 12 flashes) — page-2 param → engine
              publish path: P2EDIT 0x4003a474, store DB+part*6322+0x8ef5a+track*30+page*6+slot2
              (page=0 for FX2), bookkeeping flags mandatory, live lane 0x80000830+track*72+slot2,
              NO DSP post (rides copier 0x4000cae8 only); page-1 posts kind-0x0f to 0x460d17ee.
              Generic writer FUN_40054cd8. Supersedes NOTES S17 "verify".
              [ kb/memory-map.md "Parameter value → the engine" ]
- 2026-09-08  octabam@04b8512  COLDFIRE_PORT.md O9d — per-voice DSP record 0x80000110/0x310
              (core1) / 0x210/0x410 (core0), 32 halfwords/track (+0..5 AMP, +6..11 FX1 pg1,
              +12..17 FX2 pg1, page-2 in low byte, +27/+28 ids); copier 0x4000cae8; FILTER
              coeff X:0x2c0 (FX2) / X:0x3a0 (FX1)
              [ kb/memory-map.md, kb/dsp56300.md ]
- 2026-09-08  octabam@04b8512  COLDFIRE_PORT.md O1–O12 — tools/ot_emu, headless C++ ColdFire
              V4e + both DSP cores + ESAI audio + CF load; O11 r7-×3-per-track; "load part ≠
              play part"; "dsp_host pokes r6 → a slot can publish nothing"
              [ kb/techniques.md "the ColdFire PORT", kb/dsp56300.md ]
- 2026-09-08  efw-tool@a5bce9a  ELEK version field = fixed 10 B @ 0x08, right-justified
              (was 0x0D); container_header_end(); aPLib offset-bias underflow is deliberate;
              --emit-container; section 2 DSP→bootstrap
              [ kb/container-format.md ]

- 2026-09-07  octabam@47f6cc5  RTOS 10.16 — stock Unicorn halves the ColdFire fractional
              EMAC; unicorn_emac_fractional.patch + build_unicorn.sh; MAC/MSAC ext-bit-8
              [ kb/techniques.md ; patched Unicorn built into refs/octabam/.venv/ ]
- 2026-09-07  octabam@47f6cc5  RTOS 10.13 — machine types 0=STATIC/1=FLEX/4=PICKUP;
              5-byte per-track slot record (+0x2d3+5*track+type); 0x80004f1c recorder
              state record (16x84B, double-buffered); block-table reciprocals 0x80003c20
              [ kb/memory-map.md, kb/file-format.md ]
- 2026-09-02  OctaLib@6e2438e  bank/pattern/part file offsets            [ kb/file-format.md ]
- 2026-09-02  (our RE, DEMO bank01.work)  full TRAC layout + p-lock array (64x32B @+0x62)
              + PART FX-id bytes; tools/inspect_bank.py                   [ kb/file-format.md ]
- 2026-09-02  octabam@e1dcfa9  SETTINGS-tree menu cluster (FUN_40064908/64c18/5578c,
              24B row struct) + FUN_4006d57c signature; 27-fn name diff   [ kb/memory-map.md, kb/techniques.md ]
- 2026-09-02  octabam@e1dcfa9  DSP56721 chip model + boot/upload map     [ kb/dsp56300.md ]
- 2026-09-02  octa-bt-pt@e970dd0  FX/machine descriptor table (0x400d2fe4-0x400d5e04),
              effect id codes, DSP module-map parser, AMF mpysu->mpyuu, ELUP cipher
              [ kb/memory-map.md, kb/dsp56300.md, kb/container-format.md ]
- 2026-09-02  ems-octakit@1817ffb  closed-source, nothing to import; behavioural note only
              [ kb/file-format.md ]
- 2026-09-06  ems-octakit@ca3b527  OPEN-SOURCED — runtime/abi.inc (~500 named stock
              addrs) + firmware.json (598 guarded patch sites + 411 relocate ops) +
              62 .S + Rust patcher; no LICENSE
              [ kb/octakit-abi.md (new), kb/file-format.md, kb/memory-map.md,
                kb/container-format.md, kb/techniques.md ]
- 2026-09-06  octamax@c78ff70  'ANDY' battery-SRAM persistence — 0x800000xx is volatile,
              real store 0x100fff00 (checksum FUN_4001f23c, restore memcpy 0x64 @ 3 sites)
              [ kb/memory-map.md, kb/techniques.md; ported in Session 19 ]
- 2026-09-06  octamax@ec510e1  emu_check.py Unicorn pre-flash gate (diff patched vs stock)
              [ kb/techniques.md ]
- 2026-09-06  octabam@2f241e1  RTOS fork: emu_rtos.py full-firmware emulator + kernel decode
              (scheduler 0x40000550, 11 tasks, TCB layout, INTC0/1)
              [ kb/memory-map.md "Kernel / RTOS", kb/techniques.md ]
- 2026-09-06  octabam@2f241e1  TRAC step-mask map — masks 0x00..0x38 → offsets +0x09..+0x41,
              recorder trigs REC1/2/3 = masks 0x20/0x28/0x30 (HW-confirmed via pattern-diff),
              RAM strides 0x8ed8 / 0x91a, step handler 0x4009d1e8
              [ kb/file-format.md, kb/memory-map.md ]
- 2026-09-06  octabam@2f241e1  PARAM_PAGES.md — full descriptor-table decode: bounds
              0x400d2e52..0x400d5f00, entry layout, MULTIBCOMP id 0x19 @ 0x400d5bdc,
              recorder-page 3-tier storage (Bryan T)
              [ kb/memory-map.md ]
- 2026-09-06  octabam@2f241e1  FAILURE_MODES.md — cave ceiling 0x400d8000 (OS .bss tail
              is not free), power-cycle-after-upgrade warm-up tag
              [ kb/techniques.md, kb/dsp56300.md, FLASHING.md ]
- 2026-09-06  octabam@2f241e1  MAINMENU.md §9a — menu-state table 0x400cbdac (16 entries,
              stride 0x14), relocate-and-repoint to add a whole screen
              [ kb/techniques.md ]
