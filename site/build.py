#!/usr/bin/env python3
"""Build the raindrop-notes static site.

Reads notes/**/*.md (YAML front matter written by scripts/sync.mjs, possibly
edited in Obsidian) and screenshots/*.jpg, writes a static site to _site/.

    pip install -r site/requirements.txt
    python site/build.py                  # base path /raindrop-notes/
    SITE_BASE=/ python site/build.py      # serve from a domain root

Env:
    SITE_URL   absolute site URL, used in the Atom feed and canonical links
               (default https://frostmute.github.io/raindrop-notes)
    SITE_BASE  path prefix for links (default: path part of SITE_URL)
    SITE_TZ    timezone for displayed dates (default America/Chicago)
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
import shutil
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import markdown
import yaml
from jinja2 import Environment, FileSystemLoader, select_autoescape
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SITE_SRC = ROOT / "site"
OUT = ROOT / "_site"
NOTES = ROOT / "notes"
SHOTS = ROOT / "screenshots"

SITE_URL = os.environ.get("SITE_URL", "https://frostmute.github.io/raindrop-notes").rstrip("/")
BASE = os.environ.get("SITE_BASE", urlparse(SITE_URL).path or "/")
BASE = "/" + BASE.strip("/") + "/" if BASE.strip("/") else "/"
TZ = ZoneInfo(os.environ.get("SITE_TZ", "America/Chicago"))
SITE_TITLE = "~/bookmarks"
THUMB_WIDTH = 640

FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.S)
SECTION_RE = re.compile(r"^##\s+(.+?)\s*$", re.M)


@dataclass
class Note:
    slug: str
    title: str
    url: str
    domain: str
    rid: str
    created: datetime
    tags: list[str]
    summary_html: str
    summary_text: str
    excerpt: str
    extra_html: str
    shot: str | None  # filename in screenshots/
    related: list["Note"] = field(default_factory=list)
    related_kind: str = "shared tags / same site"

    @property
    def date(self) -> str:
        return self.created.astimezone(TZ).strftime("%Y-%m-%d")

    @property
    def datetime_local(self) -> str:
        return self.created.astimezone(TZ).strftime("%Y-%m-%d %H:%M %Z")

    @property
    def iso(self) -> str:
        return self.created.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_date(v, fallback: Path) -> datetime:
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if v:
        s = str(v).strip().strip('"')
        try:
            d = datetime.fromisoformat(s.replace("Z", "+00:00"))
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        except ValueError:
            m = re.search(r"(\d{4})-(\d{2})-(\d{2})", s)
            if m:
                return datetime(*map(int, m.groups()), tzinfo=timezone.utc)
    return datetime.fromtimestamp(fallback.stat().st_mtime, tz=timezone.utc)


def norm_tags(v) -> list[str]:
    if not v:
        return []
    if isinstance(v, str):
        v = re.split(r"[,\s]+", v)
    out = []
    for t in v:
        t = str(t).strip().lstrip("#").strip().lower()
        if t and t not in out:
            out.append(t)
    return out


def tag_slug(t: str) -> str:
    s = re.sub(r"[^a-z0-9_-]+", "-", t.lower()).strip("-")
    return s or "tag-" + hashlib.md5(t.encode()).hexdigest()[:6]


def split_sections(body: str) -> dict[str, str]:
    """Return {'_pre': text before first ##, 'Summary': ..., ...}."""
    parts = SECTION_RE.split(body)
    out = {"_pre": parts[0]}
    for i in range(1, len(parts), 2):
        out[parts[i].strip()] = parts[i + 1].strip()
    return out


def md(text: str) -> str:
    text = re.sub(r"\[\[([^\]|]+)\|([^\]]+)\]\]", r"\2", text)  # Obsidian [[a|b]]
    text = re.sub(r"\[\[([^\]]+)\]\]", r"\1", text)
    return markdown.markdown(text, extensions=["extra", "sane_lists"], output_format="html")


def load_note(path: Path) -> Note | None:
    raw = path.read_text(encoding="utf-8")
    m = FM_RE.match(raw)
    if not m:
        print(f"skip (no front matter): {path}", file=sys.stderr)
        return None
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as e:
        print(f"skip (bad yaml): {path}: {e}", file=sys.stderr)
        return None
    body = raw[m.end():]
    sec = split_sections(body)

    stem_id = re.search(r"(\d+)$", path.stem)
    rid = str(fm.get("raindrop_id") or (stem_id.group(1) if stem_id else path.stem))
    url = str(fm.get("url") or "")
    domain = str(fm.get("domain") or urlparse(url).netloc.removeprefix("www."))
    title = str(fm.get("title") or path.stem)

    summary = sec.get("Summary", "").strip()
    if summary.startswith("_No summary available"):
        summary = ""
    excerpt = sec.get("Excerpt", "").strip()
    excerpt = re.sub(r"^>\s?", "", excerpt, flags=re.M).strip()
    if excerpt and re.sub(r"\s+", " ", excerpt) == re.sub(r"\s+", " ", summary):
        excerpt = ""  # sync.mjs falls back to the excerpt when Gemini has no summary

    # Anything else Frost writes in the note (extra sections or text) is kept.
    extra = []
    pre = sec["_pre"]
    pre = re.sub(r"^#\s+.*$", "", pre, count=1, flags=re.M)              # H1 title
    pre = re.sub(r"^\[https?://[^\]]*\]\([^)]*\)\s*$", "", pre, flags=re.M)  # link line
    pre = re.sub(r"^!\[[^\]]*\]\([^)]*screenshots/[^)]*\)\s*$", "", pre, flags=re.M)
    if pre.strip():
        extra.append(pre.strip())
    for k, v in sec.items():
        if k in ("_pre", "Summary", "Excerpt") or not v.strip():
            continue
        extra.append(f"## {k}\n\n{v}")

    shot = None
    for ext in ("jpg", "jpeg", "png", "webp"):
        if (SHOTS / f"{rid}.{ext}").exists():
            shot = f"{rid}.{ext}"
            break

    return Note(
        slug=re.sub(r"[^a-z0-9-]+", "-", path.stem.lower()).strip("-"),
        title=title,
        url=url,
        domain=domain,
        rid=rid,
        created=parse_date(fm.get("created"), path),
        tags=norm_tags(fm.get("tags")),
        summary_html=md(summary) if summary else "",
        summary_text=re.sub(r"\s+", " ", summary).strip(),
        excerpt=excerpt,
        extra_html=md("\n\n".join(extra)) if extra else "",
        shot=shot,
    )


def compute_related(notes: list[Note], n: int = 6) -> None:
    for a in notes:
        scored = []
        for b in notes:
            if b is a:
                continue
            shared = len(set(a.tags) & set(b.tags))
            same_dom = a.domain and a.domain == b.domain
            if shared or same_dom:
                gap = abs((a.created - b.created).total_seconds())
                scored.append((-(shared * 10 + (3 if same_dom else 0)), gap, b))
        scored.sort(key=lambda x: (x[0], x[1]))
        a.related = [b for *_, b in scored[:n]]
        if not a.related:  # nothing shares a tag yet: fall back to neighbours in time
            near = sorted((b for b in notes if b is not a), key=lambda b: abs((a.created - b.created).total_seconds()))
            a.related = near[:3]
            a.related_kind = "saved around the same time"


def make_thumb(src: Path, dst: Path) -> tuple[int, int]:
    dst.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(src) as im:
        im = im.convert("RGB")
        if im.width > THUMB_WIDTH:
            h = round(im.height * THUMB_WIDTH / im.width)
            im = im.resize((THUMB_WIDTH, h), Image.LANCZOS)
        if not dst.exists() or dst.stat().st_mtime < src.stat().st_mtime:
            im.save(dst, "WEBP", quality=76, method=5)
        return im.size


def atom(notes: list[Note]) -> str:
    updated = notes[0].iso if notes else datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    e = html.escape
    items = []
    for n in notes[:50]:
        link = f"{SITE_URL}/b/{n.slug}/"
        img = f'<p><img src="{SITE_URL}/screenshots/{n.shot}" alt="" /></p>' if n.shot else ""
        content = f'{img}<p><a href="{e(n.url)}">{e(n.url)}</a></p>{n.summary_html}'
        cats = "".join(f'<category term="{e(t)}"/>' for t in n.tags)
        items.append(
            f"<entry><title>{e(n.title)}</title><link href=\"{link}\"/>"
            f"<link rel=\"related\" href=\"{e(n.url)}\"/><id>{link}</id>"
            f"<updated>{n.iso}</updated><published>{n.iso}</published>{cats}"
            f"<content type=\"html\">{e(content)}</content></entry>"
        )
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<feed xmlns="http://www.w3.org/2005/Atom">'
        f"<title>{e(SITE_TITLE)}</title><subtitle>Frost's bookmarks, screenshotted and summarized</subtitle>"
        f'<link href="{SITE_URL}/feed.xml" rel="self"/><link href="{SITE_URL}/"/>'
        f"<id>{SITE_URL}/</id><updated>{updated}</updated>"
        "<author><name>frostmute</name></author>" + "".join(items) + "</feed>\n"
    )


def main() -> int:
    notes = [n for p in sorted(NOTES.rglob("*.md")) if (n := load_note(p))]
    # de-dup slugs
    seen: dict[str, int] = {}
    for n in notes:
        if n.slug in seen:
            seen[n.slug] += 1
            n.slug = f"{n.slug}-{seen[n.slug]}"
        else:
            seen[n.slug] = 0
    notes.sort(key=lambda n: n.created, reverse=True)
    compute_related(notes)

    tags: dict[str, list[Note]] = {}
    for n in notes:
        for t in n.tags:
            tags.setdefault(t, []).append(n)
    tag_list = sorted(tags.items(), key=lambda kv: (-len(kv[1]), kv[0]))

    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir()
    shutil.copytree(SITE_SRC / "static", OUT / "static")

    thumbs = {}
    if SHOTS.exists():
        shutil.copytree(SHOTS, OUT / "screenshots")
        for n in notes:
            if n.shot:
                w, h = make_thumb(SHOTS / n.shot, OUT / "thumbs" / f"{n.rid}.webp")
                thumbs[n.rid] = (f"{n.rid}.webp", w, h)

    # cache-bust static assets by content hash
    def asset_hash(name: str) -> str:
        return hashlib.sha1((SITE_SRC / "static" / name).read_bytes()).hexdigest()[:8]

    env = Environment(
        loader=FileSystemLoader(SITE_SRC / "templates"),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.globals.update(
        base=BASE,
        site_url=SITE_URL,
        site_title=SITE_TITLE,
        tag_slug=tag_slug,
        thumbs=thumbs,
        css_v=asset_hash("style.css"),
        js_v=asset_hash("app.js"),
        total=len(notes),
        tag_count=len(tags),
        built=datetime.now(TZ).strftime("%Y-%m-%d %H:%M %Z"),
    )

    def write(rel: str, tpl: str, **ctx) -> None:
        p = OUT / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(env.get_template(tpl).render(**ctx), encoding="utf-8")

    write("index.html", "index.html", notes=notes, tags=tag_list[:24], page="index")
    for n in notes:
        write(f"b/{n.slug}/index.html", "note.html", n=n, page="note")
    write("tags/index.html", "tags.html", tags=tag_list, untagged=[n for n in notes if not n.tags], page="tags")
    for t, ns in tags.items():
        write(f"tags/{tag_slug(t)}/index.html", "tag.html", tag=t, notes=ns, page="tag")
    write("404.html", "404.html", page="404")

    index = [
        {
            "t": n.title,
            "u": f"{BASE}b/{n.slug}/",
            "d": n.domain,
            "g": n.tags,
            "s": n.summary_text[:400],
            "x": n.excerpt[:200],
            "date": n.date,
            "th": f"{BASE}thumbs/{thumbs[n.rid][0]}" if n.rid in thumbs else "",
        }
        for n in notes
    ]
    (OUT / "search.json").write_text(json.dumps(index, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    (OUT / "feed.xml").write_text(atom(notes), encoding="utf-8")
    (OUT / ".nojekyll").write_text("")
    print(f"built {len(notes)} notes, {len(tags)} tags -> {OUT} (base {BASE})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
