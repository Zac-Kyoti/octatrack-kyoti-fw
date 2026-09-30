# tools/ghidra/

Helper scripts for the Ghidra headless analysis of the decompressed MAIN OS
(`out/raw/section_3_MAIN_OS.bin`, load base `0x40000400`, ColdFire / m68k
big-endian).

## Reusable

| script | run | purpose |
|---|---|---|
| `ghidra_import.py` | inside Ghidra (Script Manager) or via `analyzeHeadless` | verify/annotate the load base, then define strings + pointers from `pointers_to_strings.csv` so cross-references show in the disassembly |
| `ghidra_decompile.py` | inside Ghidra | batch-decompile a named function list to text |

## One-shot probe scripts

The ~350 one-shot `Ghidra*.java` probes — each written to answer a single question in a
single session — were removed on 2026-09-29. They are in this repo's history
(`git show 69949ce:tools/ghidra/attic/<name>.java`), next to the `NOTES.md` session that
spawned each one. The findings themselves live in `NOTES.md`, `ARCHITECTURE.md` and
`COVERAGE.md`.
