# Sidechain Compressor (Modwerk)

Stock COMPRESSOR with a side-chain KEY from any track. Page 2: RMS, MON, KEY, KGN, KBAS (the key's high-pass, in Hz) and KWID (its low-pass, in octaves above KBAS).

- `patch_sc_dsp3.asm`, `patch_sidechain.s`, `ui_switch.s`, `sc_tables.py`, `sc_keyfilt.py`: the final SIDECHAIN_COMPRESSOR sources, unchanged.
- `manifest.py`: the Modwerk form of `octabam-modules/sidechain-compressor/manifest.py`, with its sources beside it in this folder.

Version 0.2.0 for Modwerk, replacing 0.1.2 (KFLT gave way to KBAS and KWID; a COMPRESSOR saved with 0.1.x keeps its KEY, and its other page-2 values land on different knobs). Submitted as repeat98/modwerk#971 (26 October 2026) with the beta base changes it needs, for the owner's review.

Also in 0.2.0 (25 October 2026): MON shows OFF on the left and ON on the right, and a COMPRESSOR saved with any earlier version comes up with MON OFF; KEY moves one position per detent when the encoder is pressed and turned; switching MON, or changing KEY while MON is on, fades over 256 samples.

The first Modwerk image (MW_SC020, 24 October 2026) broke KBAS and KWID on the author's MKI: the key-filter table address was taken from a register the gain store had already moved. The table is now its own `ptable2` (Modwerk's resident engine needs `ptable2` support for that), fixed and confirmed on hardware in the octabam form (OCTABAM32, 25 October 2026). Modwerk's native image of this form (MW_SC021, MAIN OS `131142e1…`) ran on the author's MKI on 26 October 2026: all good.

0.2.1 for Modwerk (30 October 2026): the key bus moves to Y:$7e00..$7fff (the first internal FX2 slot's tail, past every +$3DFD ring) and the MON words to Y:$ff0..$fff, so Y:$7f0..$9ff is free for a DSP machine's voice (BlackPyramids, repeat98/modwerk#1064). DSP code and sound unchanged; only the addresses. Modwerk's native image of this version alone (MAIN OS `fb7c5e31…`, OS VERSION MW_SC021) and beside BBD (`c234d13c…`, MW_BBDSC) ran on the author's MKI on 30 October 2026: all good.
