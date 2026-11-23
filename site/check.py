#!/usr/bin/env python3
"""Sanity-check _site/: every internal href/src resolves, feed and search index parse."""
import json, os, re, sys
from pathlib import Path
from urllib.parse import urlparse
from xml.dom import minidom

OUT = Path(__file__).resolve().parent.parent / "_site"
site_url = os.environ.get("SITE_URL", "https://frostmute.github.io/raindrop-notes").rstrip("/")
base = os.environ.get("SITE_BASE", urlparse(site_url).path or "/")
base = "/" + base.strip("/") + "/" if base.strip("/") else "/"

errors = []
pages = list(OUT.rglob("*.html"))
for page in pages:
    for ref in re.findall(r'(?:href|src)="([^"]+)"', page.read_text(encoding="utf-8")):
        if not ref.startswith("/") or ref.startswith("//"):
            continue
        path = ref.split("#")[0].split("?")[0]
        if not path.startswith(base):
            errors.append(f"{page.relative_to(OUT)}: link outside base {base}: {ref}")
            continue
        target = OUT / path[len(base):]
        if path.endswith("/"):
            target = target / "index.html"
        if not target.exists():
            errors.append(f"{page.relative_to(OUT)}: broken link {ref}")
minidom.parse(str(OUT / "feed.xml"))
idx = json.loads((OUT / "search.json").read_text())
if not (OUT / "index.html").exists():
    errors.append("missing index.html")
for e in errors:
    print("ERROR", e)
print(f"checked {len(pages)} pages, {len(idx)} search entries, {len(errors)} errors")
sys.exit(1 if errors else 0)
