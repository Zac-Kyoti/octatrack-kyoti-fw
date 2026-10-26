# Sidechain Compressor (Modwerk)

Stock COMPRESSOR with a side-chain KEY from any track. Page 2: RMS, MON, KEY, KGN, KBAS (the key's high-pass, in Hz) and KWID (its low-pass, in octaves above KBAS).

- `patch_sc_dsp3.asm`, `patch_sidechain.s`, `ui_switch.s`, `sc_tables.py`, `sc_keyfilt.py`: the final SIDECHAIN_COMPRESSOR sources, unchanged.
- `manifest.py`: the Modwerk form of `octabam-modules/sidechain-compressor/manifest.py`, with its sources beside it in this folder.

Version 0.2.0 for Modwerk, replacing 0.1.2 (KFLT gave way to KBAS and KWID; a COMPRESSOR saved with 0.1.x keeps its KEY, and its other page-2 values land on different knobs). Not submitted yet: Modwerk's beta USB base builds Sidechain Compressor into its resident DSP engine (`resident_dsp.py`, `stock_hook_controllers.py`), so this version needs that base updated as well.

Also in 0.2.0 (25 October 2026): MON shows OFF on the left and ON on the right, and a COMPRESSOR saved with any earlier version comes up with MON OFF; KEY moves one position per detent when the encoder is pressed and turned; switching MON, or changing KEY while MON is on, fades over 256 samples.

The first Modwerk image (MW_SC020, 24 October 2026) broke KBAS and KWID on the author's MKI: the key-filter table address was taken from a register the gain store had already moved. The table is now its own `ptable2` (Modwerk's resident engine needs `ptable2` support for that), fixed and confirmed on hardware in the octabam form (OCTABAM32, 25 October 2026). This Modwerk form has not been rebuilt or flashed since.
