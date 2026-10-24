# Modwerk modules

The source of Zac Kyoti's modules as [Modwerk](https://github.com/repeat98/modwerk) ships them, one folder per module. Modwerk imports these files into `sdk/octabam/modules/<id>/`.

They are their own copies. Nothing in this repository builds from them: the standalone builders, the Bugbuilds and KYOTI use `tools/`, and octabam uses `octabam-modules/`. A change made for Modwerk lands here and nowhere else.

| Folder | On Modwerk | Status (23 October 2026) |
|---|---|---|
| [quantize-live-rec-toggle](quantize-live-rec-toggle/) | Quant Live Rec | 0.1.0 live; 0.1.1 (this source) in repeat98/modwerk#846 |
| [mute-modes](mute-modes/) | Mute Modes | 0.2.1 live; mirrored from Modwerk `main` `c8fcb805` |
| [sidechain-compressor](sidechain-compressor/) | Sidechain Compressor | 0.1.2 live; 0.2.0 (this source) not submitted yet |

Each folder holds the module's MIT sources and its Modwerk-form `manifest.py`. Modwerk's own files for these modules (its test gates and measurement tools under GPL-3.0-or-later, its documentation, thumbnails and LCD captures) stay on Modwerk and are not copied here.

In a Modwerk-form manifest `author` is the GitHub login (`Zac-Kyoti`), which Modwerk checks against the module's catalogue entry; the site shows the name from `author.name` there ("Zac Kyoti"). Modwerk-form manifests also differ from octabam's: every stock expectation is an address/length/SHA-256 guard read from the builder's own OS file, so no stock bytes are carried, and Modwerk's remix schema has no build settings or stores.
