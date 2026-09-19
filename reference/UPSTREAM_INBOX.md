# Upstream inbox — external changes not yet distilled

`tools/refs/whatsnew.py` output, triaged. Newest first. When a line is fully
folded into `reference/kb/`, move it to the "Distilled" section with the target
file noted. This file is the hand-off point for the (optional) weekly scheduled
agent that fetches the refs and appends new commits here.

## Format

```
- YYYY-MM-DD  <repo>@<short-hash>  <one-line summary>   [ TODO | kb/<file> ]
```

## Pending

- 2026-09-16  octabam@0ad97b9  178 new commits since our 2026-09-14 pin (2 days).
              Not triaged individually — this repo is now moving too fast to
              read commit-by-commit; next octabam sync should skim
              `docs/RTOS_FORK.md` / `CLAUDE.md` "Traps" section deltas rather
              than the raw log.                                    [ TODO — skim before next octabam sync ]
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
- 2026-09-12  ems-octakit@8ded517  6 commits since ec70dda: mostly Octakit's own
              256-Kits-runtime bugfixes (stale popup/descriptor ownership at a
              Kit/Pattern handoff) + a crash-report refactor, not stock-firmware
              content. Five new named addresses distilled into kb/octakit-abi.md
              "Recording Setup menu / LOAD KIT". Also shipped a LICENSE (MIT) —
              CREDITS.md updated.                                  [ kb/octakit-abi.md ]

## Distilled

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
