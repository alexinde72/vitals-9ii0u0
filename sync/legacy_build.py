#!/usr/bin/env python3
"""Rewrite web/index.html's inline script for old browsers (e.g. a TV's Chrome 74 WebView).

Usage: python sync/legacy_build.py web/index.html
Needs Node (npx). Optional chaining (?.) and ?? become plain ES2018 so older WebViews can run the app.
"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

html_path = Path(sys.argv[1])
html = html_path.read_text()
m = re.search(r"<script>\n(\"use strict\";.*?)</script>", html, re.S)
if not m:
    sys.exit("inline <script> not found")
with tempfile.TemporaryDirectory() as d:
    src = Path(d) / "app.js"
    out = Path(d) / "app.out.js"
    src.write_text(m.group(1))
    subprocess.run(["npx", "--yes", "esbuild@0.24.2", str(src), "--target=chrome69", "--outfile=" + str(out), "--log-level=warning"], check=True)
    js = out.read_text()
html = html[: m.start(1)] + js + html[m.end(1):]
html_path.write_text(html)
left = len(re.findall(r"\?\.[a-zA-Z_$\[(]|\?\?", js))
print(f"Legacy build done: {len(js)} bytes of JS, {left} modern operators left")
