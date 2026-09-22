# External Octatrack RE research — index

Prior art we mine so we don't rebuild the wheel. See also [`CREDITS.md`](../CREDITS.md)
(lineage + legal) and [`COVERAGE.md`](../COVERAGE.md) (what this repo has vs hasn't mapped).

## How this works

```
refs/MANIFEST.toml      the six repos + one line each on what to mine
refs/MANIFEST.lock      the exact commit last synced (tracked)
refs/<name>/            local clone — GITIGNORED, disposable cache, never committed
tools/refs/sync.py      clone/fetch all to the pinned commit, rewrite the lock
tools/refs/whatsnew.py  list upstream commits newer than the lock -> what to re-distil
tools/refs/refresh.sh   run whatsnew, save refs/.whatsnew-report.md, notify (macOS)
reference/kb/*.md       the durable asset: distilled, address-keyed, attributed
reference/UPSTREAM_INBOX.md   dated triage list of upstream changes not yet distilled
```

`reference/KB_REFRESH.md` (local, gitignored) is the operator's step-by-step for
this loop — the commands to check upstream, pull a repo, and fold it in. If it's
not in your checkout, that's expected; the "Session workflow" below is the same
thing in brief. **`.claude/skills/pull-research/`** is the one-command version —
ask to "pull what's new from the contributors" and it runs the check, pull,
read, distill and log steps in one pass instead of you doing them by hand.

**Never commit anything under `refs/` except the two manifest files** — mixed and
absent licenses, and this project redistributes no third-party material.

### Session workflow

1. Doing cross-repo work? `python3 tools/refs/whatsnew.py` — anything listed is a
   candidate to re-distil.
2. Need a repo's detail? It's already checked out under `refs/<name>/` at the
   locked commit — `rg` it directly.
3. Found something reusable? Add it to the right `reference/kb/*.md` with
   **source repo + file + commit hash (from `MANIFEST.lock`) + date**. Same
   attribution discipline as the memory files.
4. First sync on a new machine: `python3 tools/refs/sync.py`.

Forum threads (Elektronauts etc.) can't be synced — `WebFetch` the specific
thread on demand and distil the finding into `kb/` with the URL + retrieval date.

## The repos

| Repo | Side | Mine it for |
|---|---|---|
| [mxldyn/octamax](https://github.com/mxldyn/octamax) | ColdFire | Upstream of this fork. Container/update-chain analysis, the patch/build pipeline, PERSONALIZE-menu map, first behaviour mods. **2026-09: OCTAMAX 2.x** — `c78ff70` the `'ANDY'` battery-SRAM persistence mechanism (→ our Session 19), `emu_check.py` pre-flash gate, dual-256 sample slots (`DUAL256.md`, not adopted), **`DESIGN_SLICEVIEW.md` SLICE PLAYHEAD** — voice-struct field map + screen primitives + the periodic-repaint tick distilled 2026-09-08 → [`kb/memory-map.md`](kb/memory-map.md). |
| [mischa85/elektron-firmware-tool](https://github.com/mischa85/elektron-firmware-tool) | tooling | ELEK container pack/unpack, aPLib, `.bin`/`.syx` transports. Vendored separately in `vendor/`; kb needs the format notes + any format fixes. **2026-09-08 (`a5bce9a`):** ELEK version field is a fixed 10-byte right-justified field at `0x08` (not `0x0D`); aPLib offset-bias underflow is deliberate; `--emit-container`. → [`kb/container-format.md`](kb/container-format.md) |
| [snugsound/OctaLib](https://github.com/snugsound/OctaLib) | file-format | on-CF project/bank/part/arrangement struct layouts. Directly feeds the unmapped per-step trig / p-lock / sample-lock model (NOTES Session 13 backlog). → [`kb/file-format.md`](kb/file-format.md) |
| [emuyia/ems-octakit](https://github.com/emuyia/ems-octakit) | file-format + ColdFire | Swaps 4 Parts/Bank for 256 Kits/Project. **Open-sourced 2026-09** (commit `ca3b527`): `runtime/abi.inc` = ~500 named stock addresses (`GK_STOCK_*`); `runtime/firmware.json` = 598 SHA-guarded patch sites + 411 relocate ops; 62 `.S` modules + a Rust patcher. **`link.ld` + `loader.S` = the append-a-runtime architecture** (reclaim flex-pool RAM, append an aPLib-packed ~128 KB ColdFire runtime, boot-hook it in) — the way past the ~4 KB code-cave limit. **`8ded517` (2026-09-12):** MIT-licensed now; five more named addresses around the Recording Setup menu / LOAD KIT handoff (own-runtime bugfixes, not stock bugs). → [`kb/octakit-abi.md`](kb/octakit-abi.md), [`kb/file-format.md`](kb/file-format.md), [`kb/techniques.md`](kb/techniques.md) |
| [bryantysinger/octa-bt-pt](https://github.com/bryantysinger/octa-bt-pt) | ColdFire + DSP | Parameter-default patch tool (OS 1.40C, Python/Streamlit). **Distilled 2026-09-02:** full FX/machine descriptor table (`0x400d2fe4`–`0x400d5e04`), effect id codes, DSP module-map parser + AMF `mpysu`→`mpyuu` bug fix, ELUP cipher constants. → [`kb/memory-map.md`](kb/memory-map.md), [`kb/dsp56300.md`](kb/dsp56300.md), [`kb/container-format.md`](kb/container-format.md). **Repo is static** (4 commits, last 2026-08-22); Bryan T's *live* RE (recorder / delay / timestretch / EMAC) is shared on **Discord** and reaches us folded into octabam's `docs/EXTERNAL.md` — sync octabam, not this repo, for new Bryan findings. |
| [sambanks/octabam](https://github.com/sambanks/octabam) | DSP + ColdFire | Adds DSP56300 effects to the MKII. The DSP effect-tuning work is out of scope here — but the **RTOS fork** (`RTOS_FORK.md`) is ColdFire-side and increasingly overlaps our own threads: `emu_rtos.py` full-firmware emulator, kernel/scheduler decode, the per-step **TRAC mask map** (recorder trigs HW-confirmed), `ot_project.py` `pattern-trig`/`pattern-diff`, `PARAM_PAGES.md` full descriptor-table decode, `FAILURE_MODES.md`, `midi_flash.py`. RTOS 10.13–10.16 (`47f6cc5`): EMAC-patched Unicorn, machine-type values `0=STATIC/1=FLEX/4=PICKUP`, 5-byte per-track slot record. `04b8512`: `docs/COLDFIRE_PORT.md` — `tools/ot_emu`, a headless **C++ ColdFire V4e + both DSP cores + ESAI audio + CF load** (O1–O12); `docs/midi_re_cc.md` §7 — the **page-2 param → engine publish path**, HW-verified over 12 flashes. **RTOS 10.19–10.59 (→ `0ec42f3`, 2026-09-12):** a long recorder-click chase (FLEX self-loop, non-golden tempo) through the arm/frame-builder path — arm-caller `0x40006238`, a corrected read on `0x4000672c`/`0x40006a2c` as "a PICKUP-only follow-up mechanism, not the FLEX arm path", independent confirmation of our own `FUN_400068e4` (16 hits/frame), unmapped lane-table fill `0x4000aece..0x4000af22`. Directly adjacent to Session 49's Part-carryover / PICKUP-follow-up bug family — see `reference/UPSTREAM_INBOX.md` for the specific cross-check TODO. **Extremely active** (178 new commits in the 2 days between our 2026-09-14 and 2026-09-16 syncs) — expect the pin to fall behind fast; re-sync deliberately, don't assume it's current. → [`kb/memory-map.md`](kb/memory-map.md), [`kb/file-format.md`](kb/file-format.md), [`kb/techniques.md`](kb/techniques.md), [`kb/dsp56300.md`](kb/dsp56300.md) |
| [bkkbrls-del/midisc](https://github.com/bkkbrls-del/midisc) | ColdFire | **Added 2026-09-16.** MIDI-track scene A/B locks + XF morph for OS **1.40C** — same base OS as this project. Small, focused, HW-confirmed (`docs/TECH.md` + `tools/midisc/memory_map.py`, full address map). Already vendored by octabam as a submodule (`modules/midi-scenes`). Distilled 2026-09-16: MIDI page/flat resolver, live scene bank layout, the part-save freeze-twin persistence pattern (reusable for any new per-part persistent state), the XF-over-step-lock morph engine, a bank-register-clobber fix, and the "hook the caller, not the shared entry point" composition pattern it uses to coexist with Octakit on `STOCK_APPLY`. → [`kb/memory-map.md`](kb/memory-map.md), [`kb/techniques.md`](kb/techniques.md) |
| [dsp56300/dsp56300](https://github.com/dsp56300/dsp56300) | dsp | **Added 2026-09-16.** The canonical, actively-developed DSP56300 CPU/DSP core emulator (GPLv3) — octabam vendors a hand-pinned commit of this into `vendor/dsp56300` rather than tracking tip. **Track branch `dsp56300`, not `main`** (`main` is stale since 2026-05-25; `dsp56300` is where all current work lands). Distilled 2026-09-16: octabam's vendored pin (`c051afad`, 2026-07-28) is 132 commits behind current tip — recent work includes instruction-semantics fixes (`CMPU`, CCR overflow flags, `ADC`/`SBC`, `MOVEP`, absolute-short `MOVE(M)`) worth checking against any DSP56300 behaviour question we hit ourselves. `dsp56300/gearmulator` (same org, the flagship VST-emulator project) pulls this exact repo in as a submodule and was reviewed 2026-09-16 but not added separately — nothing in the rest of its tree (JUCE plugin UI, unrelated synth emulations) bears on an Octatrack-shaped machine. → [`kb/dsp56300.md`](kb/dsp56300.md) |

## Licence posture

Each repo keeps its own terms. octamax **and ems-octakit** ship no `LICENSE`
(this fork exists under GitHub's ToS, educational use only, per `CREDITS.md`;
ems-octakit takes the same "provide your own official OS, contains no official
code or assets" stance). octabam / octa-bt-pt each carry their own — check
`refs/<name>/LICENSE` before quoting more than a fact. We store **findings and
small factual excerpts** in `kb/`, never wholesale copies of their source — for
ems-octakit that means distilled address facts, not its `.S` or `abi.inc` in bulk.
