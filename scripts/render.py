#!/usr/bin/env python3
"""Render papers.yaml into the paper list in README.md.

Only the text between the BEGIN/END PAPERS markers is replaced, so the
hand-written parts of the README are kept.

Usage:
    python scripts/render.py [--check]

With --check, the script exits with status 1 if README.md is out of date. CI uses this.
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import OrderedDict, defaultdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
BEGIN, END = "<!-- BEGIN PAPERS -->", "<!-- END PAPERS -->"


def slug(heading: str) -> str:
    """GitHub's anchor for a heading."""
    s = heading.strip().lower()
    s = re.sub(r"[^\w\- ]", "", s, flags=re.UNICODE)
    return s.replace(" ", "-")


def entry(p: dict) -> str:
    venue = " ".join(str(x) for x in (p.get("venue"), p.get("year")) if x)
    parts = [f"- **{p['title']}**"]
    if venue:
        parts.append(f"*{venue}*")
    links = []
    if p.get("link"):
        links.append(f"[[paper]]({p['link']})")
    if p.get("code"):
        links.append(f"[[code]]({p['code']})")
    line = " · ".join(parts) + (" " + " ".join(links) if links else "")
    if p.get("note"):
        line += f" — {p['note']}"
    return line


def sort_key(p: dict):
    year = p.get("year") if isinstance(p.get("year"), int) else 0
    return (-year, p["title"].lower())


def build(papers: list[dict], taxonomy: dict) -> str:
    cat_title: "OrderedDict[str, str]" = OrderedDict()
    cat_group: dict[str, str] = {}
    for r in taxonomy["categories"]:
        cat_title.setdefault(r["id"], r["title"])
        cat_group.setdefault(r["id"], r["group"])

    by_cat: dict[str, list[dict]] = defaultdict(list)
    extra: list[dict] = []
    for p in papers:
        primary = p.get("primary_override") or p.get("primary")
        if primary and primary not in cat_title:
            sys.exit(f"{p['key']}: unknown category {primary!r}")
        (by_cat[primary] if primary else extra).append(p)

    out: list[str] = []
    n_listed = sum(len(v) for v in by_cat.values())
    out.append(f"*{n_listed + len(extra)} papers. Each one appears once, under the section of the survey that discusses it most specifically.*\n")

    # GitHub adds -1, -2, ... to repeated heading anchors, in document order.
    seen: dict[str, int] = {"contents": 1}
    anchors: dict[str, str] = {}

    def anchor(kind: str, ident: str, title: str) -> None:
        base = slug(title)
        n = seen.get(base, 0)
        seen[base] = n + 1
        anchors[f"{kind}:{ident}"] = base if n == 0 else f"{base}-{n}"

    for g in taxonomy["groups"]:
        cats = [c for c in cat_title if cat_group[c] == g["id"] and by_cat.get(c)]
        if cats:
            anchor("g", g["id"], g["title"])
            if len(cats) > 1:  # a group with one category gets no subheading
                for c in cats:
                    anchor("c", c, cat_title[c])

    # Table of contents
    out.append("## Contents\n")
    for g in taxonomy["groups"]:
        cats = [c for c in cat_title if cat_group[c] == g["id"] and by_cat.get(c)]
        if not cats:
            continue
        gh = f"{g['title']}"
        n = sum(len(by_cat[c]) for c in cats)
        out.append(f"- [{gh}](#{anchors['g:' + g['id']]}) ({n})")
        for c in cats if len(cats) > 1 else []:
            out.append(f"  - [{cat_title[c]}](#{anchors['c:' + c]}) ({len(by_cat[c])})")
    if extra:
        out.append(f"- [Additional References](#additional-references) ({len(extra)})")
    out.append("")

    for g in taxonomy["groups"]:
        cats = [c for c in cat_title if cat_group[c] == g["id"] and by_cat.get(c)]
        if not cats:
            continue
        out.append(f"## {g['title']}\n")
        out.append(f"> Survey {g['survey']}\n")
        for c in cats:
            if len(cats) > 1:
                out.append(f"### {cat_title[c]}\n")
            out.extend(entry(p) for p in sorted(by_cat[c], key=sort_key))
            out.append("")
        out.append("<p align=\"right\"><a href=\"#contents\">back to top</a></p>\n")

    if extra:
        out.append("## Additional References\n")
        out.append("Papers in the survey's bibliography that are not tied to a single section.\n")
        out.extend(entry(p) for p in sorted(extra, key=sort_key))
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="fail if README.md is not up to date")
    args = ap.parse_args()

    papers = yaml.safe_load((ROOT / "papers.yaml").read_text(encoding="utf-8"))
    taxonomy = yaml.safe_load((ROOT / "taxonomy.yaml").read_text(encoding="utf-8"))
    readme_path = ROOT / "README.md"
    readme = readme_path.read_text(encoding="utf-8")
    if BEGIN not in readme or END not in readme:
        sys.exit(f"README.md must contain {BEGIN} and {END}")
    head, rest = readme.split(BEGIN, 1)
    _, tail = rest.split(END, 1)
    new = f"{head}{BEGIN}\n\n{build(papers, taxonomy)}\n{END}{tail}"

    if args.check:
        if new != readme:
            sys.exit("README.md is out of date. Run: python scripts/render.py")
        print("README.md is up to date")
        return
    readme_path.write_text(new, encoding="utf-8")
    print(f"README.md updated ({len(papers)} papers)")


if __name__ == "__main__":
    main()
