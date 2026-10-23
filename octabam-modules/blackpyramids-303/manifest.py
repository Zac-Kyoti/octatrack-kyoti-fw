"""BLACKPYRAMIDS_303 -- a TB-303 voice as a track machine, shown as BLKPYRAMD: built on Robin Schmidt's
Open303 algorithm and recalibrated on the TB-303's own circuit, on the DSP56300 (24-bit fixed point, the filter
4x oversampled at 176.4 kHz), one voice per DSP core (T1-T4, T5-T8), played by the OT's own sequencer (trigs =
notes, p-locked PTCH = melody, ACC = accent, slide trigs = slides, trigless trigs/locks = ties), live from the
track key, chromatic keys and MIDI, upstream of stock AMP, FX1 and FX2.

CREDIT. The filter, oscillator and envelope algorithms are Open303's (Robin Schmidt, MIT); since 2026-10-21 the
voice is recalibrated on the TB-303's circuit (Roland's service notes, the x0xb0x schematics, Robin Whittle's
notes) and fitted against Din Sync's recordings of a real TB-303 (measurement only). The machine registration
follows repeat98's ANALOG BD for octabam (MIT): the same chooser and SRC SETUP seams, the FLEX-plus-signature
track, SPRING REV's P words with DARK REV's helper moved, the source seam. The design, the calibration and
voicing, the sequencer and live-play plumbing and the hardware testing are Zac Kyoti's. What is Open303's and what
is new, and full attribution: reference/BLACKPYRAMIDS_303.md in Zac-Kyoti/octatrack-kyoti-fw.

STORAGE. The track is a FLEX track with a signature ('O','T',1) in NEIGHBOR bytes stock never uses,
so a stock OS opens the project with the track as FLEX; FLEX's own values are kept in NEIGHBOR's
unused bytes while the track is a BLKPYRAMD and put back when it leaves, and the machine's own
knobs are kept there while the track is another machine, so it comes back as it was left.

COLDFIRE. One DRAM unit, bp_runtime (~39 KB): tools/ot303/cf/{machine.s,control.c,record.c,
params.c} with the voice's tables (body_tables.h) and Y table, generated into one GNU-as unit by
tools/ot303/octabam_module.py (the C as `m68k-elf-gcc -S` output, libgcc's __muldi3 as words). Its
`reference` is the standalone image's runtime: linked alone at 0x40a955e0 it is those bytes, sha256
a6c4efba..., for -mcpu=5407 and 54455 alike (the generator refuses to write it otherwise). The detours,
pokes and the FLEX renderer slot (0x400d6438 -> ot_render) are the standalone builder's
(tools/build_blackpyramids_303.py).

DSP. bp_image.py, octabam's DSP-source integrate step (Module.dsp_source): the voice over SPRING REV's
P words in both payloads, DARK REV's helper moved, the source seam -> jsr the host, SPRING's X
records, SPRING's dispatch -> the passthrough stub. The words (bp_dsp_data.py) are the standalone's,
generated with bp_dsp_A.asm / bp_dsp_B.asm (the source as assembled, for reading); the step writes
both payloads byte for byte as the standalone image does. The voice's Y ($7a5-$feb) is streamed from
the ColdFire record, never part of an upload.

A REMIX WITH THIS MODULE gives up SPRING REV (the voice is its code) and carries no other DSP
module and no ANALOG BD (each owns the source seam, SPRING's words or DSP memory the voice uses).

MEASURED. The standalone image of this voice (FINAL 23 Oct 2026, mainos 88d49307...: the 21 Oct voice,
mainos ecc85887..., plus the link clips CUT-RES and DEC-ACC on the SRC page) on the author's MKI: all good.
This octabam form: the runtime and both DSP payloads are the standalone's bytes; the 21 Oct form flashed on
the author's MKI, 21 Oct 2026 (remixes/test/blackpyramids-303): all good. The 23 Oct form (the clips) is
not flashed in octabam.
"""

import os

from remix.schema import Detour, Kind, Linked, Module, Poke, SymbolRef

# This module's own directory, relative to the build's cwd (octabam's repo root): checked out
# directly, or as octabam's submodule of Zac-Kyoti/octatrack-kyoti-fw. One manifest serves both.
_HERE = os.path.relpath(os.path.dirname(os.path.realpath(__file__)))

H = bytes.fromhex

RUNTIME_AT = 0x40A955E0        # the standalone image's DRAM reserve (tools/ot303/dram.py RESERVE)
RUNTIME_SHA256 = "a6c4efba4b65bcd101fd3e1a369e121dab3da1e3a1c769bbb4b587d8bff21f43"

DETOURS = (
    Detour(0x400334D8, H("2f02222f0008"), "bp_runtime", "ot_machine_name", "chooser row 5's name"),
    Detour(0x4003C928, H("4bf9400a78c8"), "bp_runtime", "ot_src_names", "SRC SETUP's six names", kind="lea"),
    Detour(0x4003D718, H("41f9400a78c8"), "bp_runtime", "ot_name_a", "main page name lookup"),
    Detour(0x4004C36A, H("41f9400a78c8"), "bp_runtime", "ot_name_b", "the second one"),
    Detour(0x4003C980, H("71104fef0018"), "bp_runtime", "ot_setup_row", "SRC SETUP row highlight"),
    Detour(0x400786C8, H("7110b480662e"), "bp_runtime", "ot_chooser_row", "chooser row highlight"),
    Detour(0x400585DC, H("161079034879400bb704"), "bp_runtime", "ot_setup_open", "SRC SETUP opens on row 5", pad_to=10),
    Detour(0x4005221E, H("4ebaff1c4eb94007e940"), "bp_runtime", "ot_tick_hook", "publish the page", pad_to=10),
    Detour(0x40078886, H("71102f004879460e7386"), "bp_runtime", "ot_chooser_open", "chooser opens on row 5", pad_to=10),
    Detour(0x40031E74, H("710541f9400d5f386050"), "bp_runtime", "ot_resolve_pb", "the track's page", pad_to=10),
    Detour(0x4007981C, H("77101084d081"), "bp_runtime", "ot_main_commit", "chooser commit"),
    Detour(0x4005A616, H("2239460d5c30"), "bp_runtime", "ot_src_commit", "SRC SETUP commit"),
    Detour(0x4005A850, H("2239460d5c30"), "bp_runtime", "ot_src_commit2", "its second path"),
    Detour(0x4003A52E, H("2002e788d4829082"), "bp_runtime", "ot_setup_edit6", "SETUP edits row 5 as FLEX", pad_to=8),
    Detour(0x4003CD98, H("2e06e78fdc869e86"), "bp_runtime", "ot_setup_draw6", "SETUP draws it so", pad_to=8),
    Detour(0x40002318, H("4fefffa048d77cfc"), "bp_runtime", "ot_validate", "the Part validator", pad_to=8),
    Detour(0x4003D552, H("4eb940031d18"), "bp_runtime", "ot_slot_rec", "the label builder's sample", kind="jsr"),
    Detour(0x4004C1C0, H("4eb940031d18"), "bp_runtime", "ot_slot_rec_ui", "the track box's sample name", kind="jsr"),
    Detour(0x4004012C, H("486a00012f034879400bf10a2f36cce8"), "bp_runtime", "ot_glyph", "side glyph 3", pad_to=16),
    Detour(0x4009D1E8, H("4fefff9848d77cfc"), "bp_runtime", "ot_step_hook", "the step handler's entry", pad_to=8),
    Detour(0x400788C4, H("71907401b480"), "bp_runtime", "ot_chooser_level", "double-tap opens the machine list"),
    Detour(0x4009D422, H("41f946c7a810741d21827c00"), "bp_runtime", "ot_note_hook", "a note the step handler schedules", pad_to=12),
    Detour(0x4003CE02, H("207946c82456d1ced1c3d1c7d1fc0008ef5a1c10"), "bp_runtime", "ot_setup_value_hook", "SETUP preview values", pad_to=20),
    Detour(0x4003B33C, H("d3fc0008ef5b1011"), "bp_runtime", "ot_slic_a", "LEN's label reads the machine's SLIC", pad_to=8),
    Detour(0x40044DBE, H("d1fc0008ef5b4a10"), "bp_runtime", "ot_slic_b", "a slice check reads it", pad_to=8),
    Detour(0x4004FEE2, H("d1fc0008ef5b1c10"), "bp_runtime", "ot_slic_c", "another slice check", pad_to=8),
    Detour(0x4003BFF0, H("711041f9400d5f38605a"), "bp_runtime", "ot_pmtr_pb", "the LFO PMTR names", pad_to=10),
    Detour(0x40005030, H("4fefffe848d7047c"), "bp_runtime", "ot_live_req_hook", "live notes: the voice request", pad_to=8),
    Detour(0x4000E746, H("721d2b812c00"), "bp_runtime", "ot_live_midi_hook", "a MIDI chromatic note"),
    Detour(0x4004FC84, H("2002eb8841f946c7dfda320a11810800"), "bp_runtime", "ot_live_chrom_hook", "a chromatic key", pad_to=16),
    Detour(0x4000B4F6, H("1839800018281f440076"), "bp_runtime", "ot_live_rel_hook", "a live release", pad_to=10),
    Detour(0x4009D4A8, H("743d21827c00"), "bp_runtime", "ot_oneshot_hook", "a one-shot trig"),
    Detour(0x4004FD0C, H("2f3946c7e9562f002f0a42a72f024eb940042158"), "bp_runtime", "ot_rec_chrom_hook", "a chromatic key recorded", pad_to=20),
    Detour(0x40062604, H("712a0002204041f00c004868fe9c"), "bp_runtime", "ot_rec_midi_hook", "a MIDI note recorded", pad_to=14),
    Detour(0x400047F0, H("2f02222f0014"), "bp_runtime", "ot_idle_hook", "an idle track feeds the DSP's tables"),
    Detour(0x40044006, H("2039460d16f0"), "bp_runtime", "ot_led_hook", "SLOTS / SLICES LEDs dark"),
    Detour(0x4004F8DC, H("4feffff448d7001c"), "bp_runtime", "ot_slices_hook", "SLICES keys inert", pad_to=8),
    Detour(0x4004FA54, H("2f032f02242f000c"), "bp_runtime", "ot_slots_hook", "SLOTS keys inert", pad_to=8),
    Detour(0x40045918, H("7401b5b9460d16fc"), "bp_runtime", "ot_oct_hook", "CHROMATIC octaves 0..3", pad_to=8),
    Detour(0x40050254, H("2039460d16fc"), "bp_runtime", "ot_chrom_key_hook", "other tracks keep 0 / 1"),
    Detour(0x4004FBA8, H("7218b28a650001ba6d0001b6"), "bp_runtime", "ot_chrom_limit_hook", "idx up to 52", pad_to=12),
    Detour(0x40044968, H("7201b2b9460d16fc6616"), "bp_runtime", "ot_chrom_img_hook", "the full keyboard image", pad_to=10),
    Detour(0x4004FDE4, H("4ab9460d16fc660001aa"), "bp_runtime", "ot_page_key_hook", "the PAGE key: a 17th note on every octave", pad_to=10),
    Detour(0x40050CE2, H("72ffb280660000a6"), "bp_runtime", "ot_plock_hook", "MT31: held trigs' PTCH locks", pad_to=8),
)

POKES = (
    Poke(0x40079248, H("48780005"), H("48780006"), "machine chooser has six rows, BLKPYRAMD the last"),
    Poke(0x400585FA, H("48780005"), H("48780006"), "SRC SETUP selector has six rows"),
    Poke(0x400585FE, H("48780005"), H("48780006"), "SRC SETUP shows all six rows"),
    Poke(0x4003C950, H("7204"), H("7205"), "SRC SETUP name lookup admits row 5"),
    Poke(0x40078678, H("7004"), H("7005"), "machine chooser draws row 5"),
    Poke(0x400786CE, H("7004"), H("7005"), "machine chooser highlights row 5"),
    Poke(0x40079904, H("7604"), H("7605"), "machine chooser persists row 5"),
)

MODULE = Module(
    name="blackpyramids-303",
    key="BLACKPYRAMIDS_303",
    kind=Kind.HYBRID,
    doc="BLKPYRAMD: a TB-303 voice (built on Open303, recalibrated on the TB-303 circuit) as a track machine, one per DSP core, played by the "
        "sequencer, the chromatic keys and MIDI.",
    pressure_blocker="a DSP source engine, outside the FX pressure pricer (cycles: the author's "
                     "reference/BLACKPYRAMIDS_303.md section 4)",
    dsp_source=os.path.join(_HERE, "bp_image.py"),
    conflicts=(
        ("ANALOG BD", "both are DSP source machines: the same source seam, SPRING REV's words and the "
                      "machine chooser's sixth row"),
        ("SPRING REV", "the voice is SPRING REV's code"),
        ("SYNTH MACHINE", "the same FLEX renderer slot (0x400d6438) and MIDI note site (0x4000e746)"),
        ("TAPE ECHO", "it replaces SPRING REV, whose words are the voice"),
        ("SCALE QUANTIZER", "the same MIDI note site (0x4000e746)"),
        ("SIDECHAIN_COMPRESSOR", "in the author's images both take SPRING REV's program words, and "
                                 "octabam does not yet place a DSP section beside a source machine; "
                                 "in octabam its key bus is also in the voice's Y (Y:$7f0-$9ff)"),
    ),
    linked=(
        Linked("bp_runtime", os.path.join(_HERE, "bp_runtime.s"), dram=True,
               reference=(RUNTIME_AT, RUNTIME_SHA256)),
    ),
    detours=DETOURS,
    pokes=POKES,
    symbol_refs=(
        SymbolRef(0x400D6438, 0x40004008, "bp_runtime", "ot_render",
                  note="FLEX renderer: a signed track renders the voice's control record"),
    ),
)
