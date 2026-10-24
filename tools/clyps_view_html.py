#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Zac Kyoti
"""Build a self-contained HTML page of emulator screen renders (crisp, pixel-scaled) and open it
in the default web browser.

  python3 tools/clyps_view_html.py TITLE "caption=path.png" ["caption=path.png" ...]
"""
import base64, html, pathlib, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
title, shots = sys.argv[1], [a.split("=", 1) for a in sys.argv[2:]]
cards = "".join(
    f'<figure><img src="data:image/png;base64,{base64.b64encode(pathlib.Path(p).read_bytes()).decode()}">'
    f"<figcaption>{html.escape(c)}</figcaption></figure>" for c, p in shots)
page = f"""<!doctype html><html><head><meta charset="utf-8"><title>{html.escape(title)}</title>
<style>
body{{background:#111;color:#ddd;font:14px -apple-system,system-ui,sans-serif;margin:24px}}
h1{{font-size:18px;font-weight:600}}
figure{{display:inline-block;margin:0 24px 24px 0}}
img{{width:768px;image-rendering:pixelated;image-rendering:crisp-edges;border:1px solid #333}}
figcaption{{margin-top:6px;color:#aaa}}
</style></head><body><h1>{html.escape(title)}</h1>{cards}</body></html>"""
out = ROOT / "out/clyps/view.html"
out.write_text(page)
subprocess.run(["open", str(out)], check=False)
print(out)
