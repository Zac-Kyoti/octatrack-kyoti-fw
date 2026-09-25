# reference/kb/ — the distilled knowledge base

First-class project data, same status as `NOTES.md` / `COVERAGE.md`. Read the
relevant file here **before** starting a new patch — it's where prior art from
the external repos (`reference/EXTERNAL_RESEARCH.md`) and our own cross-session
findings are merged into one address-keyed picture.

## Files

| File | Scope |
|---|---|
| [`memory-map.md`](memory-map.md) | THE merge point — every function / RAM word / MMIO reg by address, ours + theirs |
| [`container-format.md`](container-format.md) | ELUP/ELEK container, aPLib, checksum, `.bin` vs `.syx` transport, the update chain |
| [`file-format.md`](file-format.md) | on-CF Set/Project/Bank/Part/Pattern/Arrangement layout; the per-step trig / p-lock model |
| [`dsp56300.md`](dsp56300.md) | the DSP program: location, upload path, and octabam's findings. Out of scope to *patch* here |
| [`techniques.md`](techniques.md) | code-cave/detour patterns, PERSONALIZE-menu recipe, pre-flash emulation, build-pipeline ideas worth stealing |
| [`caves.md`](caves.md) | **code caves** — the ecosystem's free-space ledger, who owns which bytes of the contested 6 KB cave, the regions **proven live at runtime on hardware**, and the canary test a region must pass. **Read before choosing an address for any new hook.** |
| [`octakit-abi.md`](octakit-abi.md) | ems-octakit's `abi.inc` — ~500 named stock addresses for the Part/Kit/Bank/scene/LFO/sequencer subsystems + guarded patch-site facts |

## Rules for entries

- **Attribute everything imported.** `source: <repo>/<path> @ <commit>` (commit from
  `refs/MANIFEST.lock`) `· fetched <date>`. For our own findings: `source: NOTES Session N`.
- **Normalise on the address namespace already in `NOTES.md`:**
  `0x40xxxxxx` = MAIN OS code (base `0x40000400`), `0x800xxxxx` = work RAM,
  `0x46cxxxxx` = MMIO / driver structs, `FUN_`/`DAT_`/`_DAT_` = Ghidra auto-names.
- **Flag confidence.** `confirmed` (HW or decompiled), `likely` (emu / inference),
  `claim` (someone else's, unverified here).
- **Contradictions stay visible.** If an external repo disagrees with our finding,
  record both and mark which we trust and why — don't silently overwrite.
- Keep excerpts factual and small. No wholesale source copies (licence posture).
- **Verify a load-bearing borrowed claim against our own image.** Every upstream we
  track cites the same MAIN OS (sha256 `164f3122…`), so their addresses are directly
  comparable — and they are sometimes wrong. Marking a claim **C** on the strength of
  someone else's label is how a wrong function signature propagates; a 30-second
  `m68k-elf-objdump` is the difference. See `.claude/skills/pull-research/SKILL.md`
  step 4b for the recipe.
