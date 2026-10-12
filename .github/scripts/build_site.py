#!/usr/bin/env python3
"""
Build ONE indexable docs site from many repos (or a single repo).

- README.md / index.md in any folder -> <folder>/index.html
- other foo.md                       -> foo.html
- folders with no README get a generated listing page, so EVERY subdir has a URL
- relative .md links are rewritten to .html
- each page gets <title>, meta description, canonical URL, and a link to its GitHub source
- writes sitemap.xml (lastmod from git history), robots.txt, and CNAME (custom domain)

Env:
  SITE_URL     required, e.g. https://docs.proofprotocol.io
  SRC_DIR      folder to build from (default: .). In hub mode: src/, one subfolder per repo
  REPOS_JSON   hub mode: JSON file {"repo-folder": {"url": "...", "branch": "main", "description": "..."}}
  HOME_MD      optional markdown shown above the repo list on the home page
  REPO_URL     single-repo mode: source repo URL
  BRANCH       single-repo mode: default main
  OUT_DIR      default: _site
"""
import html
import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import markdown

ROOT = Path(os.environ.get("SRC_DIR", ".")).resolve()
SITE_URL = os.environ["SITE_URL"].rstrip("/")
BASE = re.sub(r"^https?://[^/]+", "", SITE_URL)   # "" or e.g. "/specs" when served under a path
REPO_URL = os.environ.get("REPO_URL", "").rstrip("/")
BRANCH = os.environ.get("BRANCH", "main")
OUT = Path(os.environ.get("OUT_DIR", "_site")).resolve()
REPOS = json.loads(Path(os.environ["REPOS_JSON"]).read_text()) if os.environ.get("REPOS_JSON") else {}
HOME_MD = os.environ.get("HOME_MD", "")
ORG_URL = os.environ.get("ORG_URL", "")

SKIP_DIRS = {".git", ".github", "node_modules", "_site", ".venv", "venv", "__pycache__"}
ASSET_EXT = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".pdf", ".json", ".yaml",
             ".yml", ".txt", ".csv", ".xml", ".jsonld", ".ico"}
INDEX_NAMES = {"readme.md", "index.md"}

# ---- Branding (matches proofprotocol.io) - edit here ----
BRAND_HOME = "https://proofprotocol.io"
NAV = [  # (label, url). Section anchors on proofprotocol.io: verify and adjust.
    ("How it works", "https://proofprotocol.io/#how-it-works"),
    ("Specifications", "__BASE__/"),
    ("Proof record", "https://proofprotocol.io/#proof-record"),
    ("NIST anchoring", "https://proofprotocol.io/#nist-anchoring"),
    ("GitHub", "__GITHUB__"),
]
NAV_CTA = ("ProofRegister", "https://proofprotocol.io/#proofregister")
FOOTER_LINE = "&copy; 2026 Nebulonium, Inc. Specifications licensed CC BY 4.0 / CC BY 4.0."

CSS = """
:root{--bg:#050505;--panel:#0c0c0c;--line:#1c1c1c;--text:#ededed;--body:#cccccc;--muted:#aaaaaa;--accent:#9ffe00;--cyan:#38c6d9}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--body);font:16px/1.7 Inter,"Helvetica Neue",Helvetica,Arial,sans-serif;
  background-image:linear-gradient(rgba(255,255,255,.025) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.025) 1px,transparent 1px);
  background-size:48px 48px}
.mono{font-family:"JetBrains Mono",ui-monospace,Menlo,monospace}
.topbar{border-bottom:1px solid var(--line);background:rgba(5,5,5,.92);position:sticky;top:0;z-index:5;backdrop-filter:blur(6px)}
.topbar .in{max-width:1200px;margin:0 auto;padding:14px 20px;display:flex;align-items:center;gap:28px;flex-wrap:wrap}
.wordmark{font-weight:700;font-size:18px;letter-spacing:-.01em;color:#fff;text-decoration:none;margin-right:auto}
.wordmark span{color:var(--accent)} .wordmark sup{font-size:9px;color:#fff;margin-left:1px}
.nav{display:flex;gap:24px;flex-wrap:wrap;align-items:center}
.nav a{color:var(--muted);text-decoration:none;font-size:12px;letter-spacing:.12em;text-transform:uppercase}
.nav a:hover{color:#fff}
.nav a.cta{color:var(--accent);border:1px solid var(--accent);padding:7px 16px;background:rgba(159,254,0,.06)}
main{max-width:880px;margin:0 auto;padding:56px 20px 72px}
.eyebrow{display:inline-block;font-family:"JetBrains Mono",ui-monospace,monospace;font-size:11px;letter-spacing:.22em;text-transform:uppercase;
  color:var(--accent);border:1px solid rgba(159,254,0,.35);background:rgba(159,254,0,.05);padding:6px 12px;margin-bottom:22px}
.eyebrow a{color:var(--accent);text-decoration:none}
h1,h2,h3,h4{color:#fff;letter-spacing:-.02em;line-height:1.15}
h1{font-size:clamp(34px,5vw,52px);margin:0 0 20px;font-weight:700}
h2{font-size:28px;margin-top:48px;font-weight:700}
h3{font-size:20px;margin-top:32px}
h1 em,h2 em{color:var(--accent);font-style:normal}
p,li{color:var(--body)}
a{color:var(--accent);text-underline-offset:3px}
strong{color:#fff}
ul{list-style:none;padding-left:0}
ul li{position:relative;padding-left:26px;margin:6px 0}
ul li::before{content:"\\2B21";position:absolute;left:0;color:var(--accent);font-size:13px;top:1px}
ol{padding-left:22px} ol li::marker{color:var(--accent);font-family:"JetBrains Mono",monospace}
code{font-family:"JetBrains Mono",ui-monospace,monospace;font-size:13.5px;color:var(--accent);background:var(--panel);border:1px solid var(--line);padding:2px 6px}
pre{background:var(--panel);border:1px solid var(--line);padding:18px;overflow-x:auto;position:relative}
pre code{border:0;padding:0;background:none;color:#e6e6e6}
table{border-collapse:collapse;width:100%;display:block;overflow-x:auto;margin:24px 0}
th{font-family:"JetBrains Mono",monospace;font-size:11px;letter-spacing:.16em;text-transform:uppercase;color:var(--muted);text-align:left;font-weight:500}
th,td{border-bottom:1px solid var(--line);padding:12px 14px}
td{color:var(--body)} td:first-child{white-space:nowrap}
blockquote{margin:24px 0;padding:14px 18px;border:1px solid rgba(56,198,217,.35);background:rgba(56,198,217,.05);color:var(--cyan)}
blockquote p{color:var(--cyan);margin:0}
hr{border:0;border-top:1px solid var(--line);margin:40px 0}
img{max-width:100%}
.listing a{color:#fff;text-decoration:none;font-weight:600} .listing a:hover{color:var(--accent)}
.listing .d{display:block;color:var(--muted);font-size:14px}
.src{margin-top:56px;padding-top:20px;border-top:1px solid var(--line)}
.src a{font-family:"JetBrains Mono",monospace;font-size:12px;letter-spacing:.16em;text-transform:uppercase;color:var(--muted);text-decoration:none;border:1px solid var(--line);padding:10px 16px;display:inline-block}
.src a:hover{color:#fff;border-color:#444}
footer{border-top:1px solid var(--line)}
footer .in{max-width:1200px;margin:0 auto;padding:28px 20px 36px;display:flex;gap:24px;flex-wrap:wrap;align-items:center}
footer .meta{width:100%;font-size:13px;color:var(--muted)}
@media(max-width:700px){.nav{gap:14px}.topbar .in{gap:12px}main{padding-top:36px}}
"""



def git_lastmod(path: Path) -> str:
    try:
        d = path if path.is_dir() else path.parent
        out = subprocess.run(["git", "-C", str(d), "log", "-1", "--format=%cI", "--", str(path)],
                             capture_output=True, text=True).stdout.strip()
        if out:
            return out
    except Exception:
        pass
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()


def out_rel_for(md: Path) -> str:
    """Repo-relative md path -> site-relative html path."""
    rel = md.relative_to(ROOT)
    if rel.name.lower() in INDEX_NAMES:
        return str(rel.parent / "index.html").lstrip("./") if str(rel.parent) != "." else "index.html"
    return str(rel.with_suffix(".html"))


def source_for(rel: Path, kind: str = "blob") -> str:
    """GitHub URL for a repo-relative path. Hub mode: first path part is the repo folder."""
    parts = rel.parts
    if REPOS:
        if not parts or parts[0] not in REPOS:
            return ORG_URL
        r = REPOS[parts[0]]
        rest = "/".join(parts[1:])
        return f"{r['url']}/{kind}/{r.get('branch', 'main')}/{rest}" if rest else r["url"]
    if not REPO_URL:
        return ""
    return f"{REPO_URL}/{kind}/{BRANCH}/{rel.as_posix()}" if parts else REPO_URL


def url_for(out_rel: str) -> str:
    if out_rel == "index.html":
        return SITE_URL + "/"
    if out_rel.endswith("/index.html"):
        return f"{SITE_URL}/{out_rel[:-len('index.html')]}"
    return f"{SITE_URL}/{out_rel}"


def rewrite_links(body: str) -> str:
    def fix(m):
        attr, href = m.group(1), m.group(2)
        if re.match(r"^[a-z]+:", href, re.I) or href.startswith("#"):
            return m.group(0)
        path, sep, frag = href.partition("#")
        low = path.lower()
        if low.endswith("readme.md") or low.endswith("index.md"):
            path = path[: path.rfind("/") + 1] or "./"
        elif low.endswith(".md"):
            path = path[:-3] + ".html"
        return f'{attr}="{path}{sep}{frag}"'
    return re.sub(r'(href)="([^"]+)"', fix, body)


def first_h1(text: str):
    m = re.search(r"^#\s+(.+)$", text, re.M)
    return m.group(1).strip() if m else None


def first_para(text: str) -> str:
    for block in re.split(r"\n\s*\n", text):
        b = block.strip()
        if b and not b.startswith(("#", "```", "|", "<", "!", "-", "*", ">")):
            b = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", b)
            b = re.sub(r"[*_`]", "", b)
            b = " ".join(b.split())
            return b if len(b) <= 160 else b[:157].rsplit(" ", 1)[0] + "..."
    return ""


def eyebrow(out_rel: str) -> str:
    parts = [p for p in out_rel.split("/")[:-1]]
    crumbs = [f'<a href="{BASE}/">Proof Protocol</a>']
    acc = ""
    for p in parts:
        acc += p + "/"
        crumbs.append(f'<a href="{BASE}/{acc}">{html.escape(p)}</a>')
    return '<div class="eyebrow">' + " / ".join(crumbs) + "</div>"


def nav_html() -> str:
    links = []
    for label, url in NAV:
        if url == "__GITHUB__":
            url = ORG_URL or REPO_URL
            if not url:
                continue
        url = url.replace("__BASE__", BASE)
        links.append(f'<a href="{url}">{html.escape(label)}</a>')
    links.append(f'<a class="cta" href="{NAV_CTA[1]}">{html.escape(NAV_CTA[0])}</a>')
    return "".join(links)


WORDMARK = '<a class="wordmark" href="' + BRAND_HOME + '">Proof<span>Protocol</span><sup>&trade;</sup></a>'


def page(title, desc, canonical, body, out_rel, source_url):
    src = f'<div class="src"><a href="{source_url}">View source on GitHub</a></div>' if source_url else ""
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)} | Proof Protocol</title>
<meta name="description" content="{html.escape(desc)}">
<link rel="canonical" href="{canonical}">
<meta property="og:title" content="{html.escape(title)} | Proof Protocol">
<meta property="og:description" content="{html.escape(desc)}">
<meta property="og:url" content="{canonical}">
<meta property="og:site_name" content="Proof Protocol">
<meta name="theme-color" content="#050505">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>{CSS}</style>
</head><body>
<div class="topbar"><div class="in">{WORDMARK}<nav class="nav">{nav_html()}</nav></div></div>
<main>{eyebrow(out_rel)}{body}{src}</main>
<footer><div class="in">{WORDMARK}<nav class="nav">{nav_html()}</nav><div class="meta">{FOOTER_LINE}</div></div></footer>
</body></html>
"""


def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)

    md_files, assets, dirs = [], [], set()
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith("."))
        d = Path(dirpath)
        for f in sorted(filenames):
            p = d / f
            if p.suffix.lower() == ".md":
                md_files.append(p)
                dirs.add(d)
            elif p.suffix.lower() in ASSET_EXT:
                assets.append(p)

    entries = []  # (url, lastmod)
    meta = {}     # md path -> (title, desc)
    has_index = set()

    for md in md_files:
        text = md.read_text(encoding="utf-8", errors="replace")
        rel = md.relative_to(ROOT)
        out_rel = out_rel_for(md)
        if out_rel.endswith("index.html"):
            has_index.add(md.parent)
        title = first_h1(text) or (rel.parent.name if rel.name.lower() in INDEX_NAMES and str(rel.parent) != "." else rel.stem)
        desc = first_para(text) or title
        meta[md] = (title, desc)
        body = markdown.markdown(text, extensions=["tables", "fenced_code", "toc", "sane_lists"])
        body = rewrite_links(body)
        source_url = source_for(rel, "blob")
        canonical = url_for(out_rel)
        dest = OUT / out_rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(page(title, desc, canonical, body, out_rel, source_url), encoding="utf-8")
        entries.append((canonical, git_lastmod(md)))

    # Listing pages for folders with no README, plus every ancestor folder
    all_dirs = set()
    for d in dirs:
        while True:
            all_dirs.add(d)
            if d == ROOT:
                break
            d = d.parent
    for d in sorted(all_dirs):
        if d in has_index:
            continue
        rel_dir = d.relative_to(ROOT)
        out_rel = "index.html" if str(rel_dir) == "." else f"{rel_dir.as_posix()}/index.html"
        items = []
        for child in sorted(all_dirs):
            if child != d and child.parent == d:
                readme = next((m for m in md_files if m.parent == child and m.name.lower() in INDEX_NAMES), None)
                t, dsc = meta.get(readme, (child.name, "")) if readme else (child.name, "")
                if REPOS and d == ROOT and child.name in REPOS:
                    dsc = dsc or REPOS[child.name].get("description", "")
                items.append(f'<li><a href="{child.name}/">{html.escape(t)}</a>'
                             f'<span class="d">{html.escape(dsc)}</span></li>')
        for md in md_files:
            if md.parent == d:
                t, dsc = meta.get(md, (md.stem, ""))
                items.append(f'<li><a href="{Path(out_rel_for(md)).name}">{html.escape(t)}</a>'
                             f'<span class="d">{html.escape(dsc)}</span></li>')
        name = rel_dir.name or ROOT.name
        intro = f"<h1>{html.escape(name)}</h1>"
        if str(rel_dir) == "." and HOME_MD and Path(HOME_MD).exists():
            htxt = Path(HOME_MD).read_text(encoding="utf-8")
            name = first_h1(htxt) or name
            intro = rewrite_links(markdown.markdown(htxt, extensions=["tables", "fenced_code", "sane_lists"]))
        body = f'{intro}<ul class="listing">{"".join(items)}</ul>'
        source_url = source_for(rel_dir, "tree") if str(rel_dir) != "." else (ORG_URL or REPO_URL)
        dest = OUT / out_rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(page(name, f"Contents of {name}", url_for(out_rel), body, out_rel, source_url), encoding="utf-8")
        entries.append((url_for(out_rel), git_lastmod(d)))

    for a in assets:
        dest = OUT / a.relative_to(ROOT)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(a, dest)

    entries.sort()
    sm = ['<?xml version="1.0" encoding="UTF-8"?>',
          '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for u, lm in entries:
        sm.append(f"  <url><loc>{html.escape(u)}</loc><lastmod>{lm}</lastmod></url>")
    sm.append("</urlset>")
    (OUT / "sitemap.xml").write_text("\n".join(sm) + "\n", encoding="utf-8")
    (OUT / ".nojekyll").write_text("", encoding="utf-8")
    host = re.sub(r"^https?://", "", SITE_URL).split("/")[0]
    if not BASE:
        # Own host: robots.txt and custom domain live here.
        (OUT / "robots.txt").write_text(f"User-agent: *\nAllow: /\n\nSitemap: {SITE_URL}/sitemap.xml\n", encoding="utf-8")
        if not host.endswith("github.io"):
            (OUT / "CNAME").write_text(host + "\n", encoding="utf-8")

    print(f"Built {len(entries)} pages, {len(assets)} assets -> {OUT}")
    print(f"Sitemap: {SITE_URL}/sitemap.xml")


if __name__ == "__main__":
    main()
