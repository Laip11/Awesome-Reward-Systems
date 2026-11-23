#!/usr/bin/env python3
"""Build papers.yaml from the survey's references.bib and its LaTeX sections.

Each paper gets categories from where the survey cites it (see taxonomy.yaml).
If papers.yaml already exists, the script keeps the fields people edit by hand:
`code`, `note`, `categories_override`, and `primary_override`.

Usage:
    python scripts/bib2yaml.py --survey /path/to/survey [--out papers.yaml]
"""
from __future__ import annotations

import argparse
import re
from collections import Counter, OrderedDict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
MANUAL_FIELDS = ("code", "note", "categories_override", "primary_override")
# Broad categories (introduction, framework, overviews) cite many papers in passing.
# A paper gets one of these as its primary category only if it has nothing more specific.
GENERIC = {"background", "framework", "design-overview", "outlook", "notation"}


def tier(cat: str) -> int:
    if cat == "benchmarks":  # a benchmark is listed under Benchmarks wherever else it is cited
        return -1
    if cat in GENERIC:
        return 2
    return 1 if cat.endswith("-general") else 0

# ---------------------------------------------------------------- BibTeX parsing

ENTRY_RE = re.compile(r"@(\w+)\s*\{\s*([^,\s]+)\s*,", re.S)


def _read_braced(text: str, i: int) -> tuple[str, int]:
    """Read a value that starts at text[i] ('{' or '"'). Return (value, end index)."""
    if text[i] == '"':
        j = text.index('"', i + 1)
        return text[i + 1 : j], j + 1
    depth, j = 0, i
    while j < len(text):
        c = text[j]
        if c == "\\":
            j += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[i + 1 : j], j + 1
        j += 1
    raise ValueError(f"unbalanced braces near offset {i}")


def parse_bib(text: str) -> "OrderedDict[str, dict]":
    entries: "OrderedDict[str, dict]" = OrderedDict()
    for m in ENTRY_RE.finditer(text):
        etype, key = m.group(1).lower(), m.group(2)
        if etype in ("comment", "string", "preamble"):
            continue
        fields: dict[str, str] = {"_type": etype}
        i = m.end()
        while i < len(text):
            fm = re.compile(r"\s*(\w+)\s*=\s*").match(text, i)
            if not fm:
                break
            name, i = fm.group(1).lower(), fm.end()
            if text[i] in "{\"":
                value, i = _read_braced(text, i)
            else:  # bare value, e.g. year = 2024
                vm = re.compile(r"[^,}\s]+").match(text, i)
                value, i = vm.group(0), vm.end()
            fields[name] = value
            cm = re.compile(r"\s*,?").match(text, i)
            i = cm.end()
            if i < len(text) and text[i] == "}":
                break
        entries[key] = fields
    return entries


ACCENTS = {"'": "\u0301", "`": "\u0300", '"': "\u0308", "^": "\u0302", "~": "\u0303", "c": "\u0327", "v": "\u030c"}


def latex_to_text(s: str) -> str:
    import unicodedata

    s = re.sub(r"\\([\'`\"^~cv])\s*\{?\\?([A-Za-z])\}?", lambda m: unicodedata.normalize("NFC", m.group(2) + ACCENTS[m.group(1)]), s)
    s = re.sub(r"\\(?:emph|textit|textbf|textsc|mbox|texttt)\s*\{([^{}]*)\}", r"\1", s)
    s = s.replace("\\&", "&").replace("\\%", "%").replace("\\_", "_").replace("~", " ")
    s = s.replace("---", "\u2014").replace("--", "\u2013")
    s = re.sub(r"\\[a-zA-Z]+\s*", "", s)
    s = s.replace("{", "").replace("}", "")
    return re.sub(r"\s+", " ", s).strip()


ARXIV_RE = re.compile(r"(?:arxiv\.org/(?:abs|pdf)/|arXiv:)\s*(\d{4}\.\d{4,5})", re.I)


def venue_of(f: dict) -> str:
    raw = f.get("booktitle") or f.get("journal") or f.get("howpublished") or f.get("publisher") or ""
    raw = latex_to_text(raw)
    if re.match(r"arxiv", raw, re.I):
        return "arXiv"
    abbrev = [
        (r"Neural Information Processing Systems.*Datasets", "NeurIPS D&B"),
        (r"Neural Information Processing Systems", "NeurIPS"),
        (r"International Conference on Learning Representations", "ICLR"),
        (r"International Conference on Machine Learning", "ICML"),
        (r"Findings of the Association for Computational Linguistics", "ACL Findings"),
        (r"Empirical Methods in Natural Language Processing", "EMNLP"),
        (r"North American Chapter", "NAACL"),
        (r"Association for Computational Linguistics", "ACL"),
        (r"Conference on Language Modeling", "COLM"),
        (r"AAAI", "AAAI"),
        (r"Transactions on Machine Learning Research", "TMLR"),
        (r"^Nature$", "Nature"),
    ]
    for pat, short in abbrev:
        if re.search(pat, raw, re.I):
            return short
    return raw


def link_of(f: dict) -> tuple[str, str | None]:
    """Return (paper link, arXiv id or None)."""
    blob = " ".join(f.get(k, "") for k in ("url", "journal", "eprint", "note"))
    m = ARXIV_RE.search(blob)
    arxiv = m.group(1) if m else (f.get("eprint") if re.fullmatch(r"\d{4}\.\d{4,5}", f.get("eprint", "")) else None)
    if f.get("url"):
        return f["url"].strip(), arxiv
    if f.get("doi"):
        return "https://doi.org/" + f["doi"].strip(), arxiv
    if arxiv:
        return f"https://arxiv.org/abs/{arxiv}", arxiv
    return "", arxiv


# ---------------------------------------------------------------- LaTeX scanning

CITE_RE = re.compile(r"\\(?:no)?cite[a-zA-Z]*\*?(?:\s*\[[^\]]*\]){0,2}\s*\{([^}]*)\}")
HEAD_RE = re.compile(r"\\(section|subsection|subsubsection|paragraph)\*?\s*\{")
INPUT_RE = re.compile(r"\\input\s*\{([^}]+)\}")
LEVELS = {"section": 0, "subsection": 1, "subsubsection": 2}


def strip_comments(tex: str) -> str:
    return re.sub(r"(?<!\\)%.*", "", tex)


def expand_inputs(tex: str, survey: Path, depth: int = 0) -> str:
    if depth > 3:
        return tex

    def sub(m: re.Match) -> str:
        if m.group(1).startswith("sections/"):
            return ""  # section files are scanned on their own, under their own stem
        p = survey / m.group(1)
        if p.suffix != ".tex":
            p = p.with_suffix(".tex")
        if not p.exists() or "_palette" in p.name:
            return ""
        return expand_inputs(strip_comments(p.read_text(encoding="utf-8")), survey, depth + 1)

    return INPUT_RE.sub(sub, tex)


def heading_text(tex: str, start: int) -> str:
    value, _ = _read_braced(tex, start)
    value = re.sub(r"\\texorpdfstring\s*\{[^{}]*\}\s*\{([^{}]*)\}", r"\1", value)
    value = re.sub(r"\\comp[A-Z]~?", "", value)
    return latex_to_text(value)


def citations_by_location(section_file: Path, survey: Path) -> list[tuple[str, str]]:
    """Return (cite key, innermost heading) for each citation in the file."""
    tex = expand_inputs(strip_comments(section_file.read_text(encoding="utf-8")), survey)
    events: list[tuple[int, str, object]] = []
    for m in HEAD_RE.finditer(tex):
        if m.group(1) in LEVELS:
            events.append((m.start(), "head", (LEVELS[m.group(1)], heading_text(tex, m.end() - 1))))
    for m in CITE_RE.finditer(tex):
        for key in m.group(1).split(","):
            if key.strip():
                events.append((m.start(), "cite", key.strip()))
    events.sort(key=lambda e: e[0])
    path: list[str] = ["", "", ""]
    out = []
    for _, kind, payload in events:
        if kind == "head":
            level, title = payload
            path[level] = title
            for deeper in range(level + 1, 3):
                path[deeper] = ""
        else:
            innermost = next((h for h in reversed(path) if h), "")
            out.append((payload, innermost))
    return out


def classify(file_stem: str, heading: str, rules: list[dict]) -> str | None:
    for r in rules:
        if r["file"] != file_stem:
            continue
        if "heading" in r and not re.search(re.escape(r["heading"]), heading, re.I):
            continue
        return r["id"]
    return None


# ---------------------------------------------------------------- main


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--survey", type=Path, required=True, help="survey LaTeX root (holds references.bib and sections/)")
    ap.add_argument("--out", type=Path, default=ROOT / "papers.yaml")
    args = ap.parse_args()

    taxonomy = yaml.safe_load((ROOT / "taxonomy.yaml").read_text(encoding="utf-8"))
    rules = taxonomy["categories"]
    order = list(OrderedDict.fromkeys(r["id"] for r in rules))

    bib = parse_bib((args.survey / "references.bib").read_text(encoding="utf-8"))

    hits: dict[str, Counter] = {k: Counter() for k in bib}
    first_seen: dict[str, dict[str, int]] = {k: {} for k in bib}
    unknown_keys: Counter = Counter()
    unmatched_locations: Counter = Counter()
    seq = 0
    for sec in sorted((args.survey / "sections").glob("*.tex")):
        for key, heading in citations_by_location(sec, args.survey):
            seq += 1
            if key not in bib:
                unknown_keys[key] += 1
                continue
            cat = classify(sec.stem, heading, rules)
            if cat is None:
                unmatched_locations[(sec.stem, heading)] += 1
                continue
            hits[key][cat] += 1
            first_seen[key].setdefault(cat, seq)

    old: dict[str, dict] = {}
    if args.out.exists():
        for p in yaml.safe_load(args.out.read_text(encoding="utf-8")) or []:
            old[p["key"]] = p

    papers = []
    for key, f in bib.items():
        link, arxiv = link_of(f)
        cats = sorted(hits[key], key=lambda c: (tier(c), -hits[key][c], first_seen[key][c]))
        rec = {
            "key": key,
            "title": latex_to_text(f.get("title", "")),
            "venue": venue_of(f),
            "year": int(f["year"]) if f.get("year", "").isdigit() else f.get("year", ""),
            "link": link,
        }
        if arxiv:
            rec["arxiv"] = arxiv
        rec["categories"] = sorted(cats, key=order.index)
        rec["primary"] = cats[0] if cats else None
        for fld in MANUAL_FIELDS:
            if old.get(key, {}).get(fld) not in (None, "", []):
                rec[fld] = old[key][fld]
        papers.append(rec)
    # Papers added by hand (not in the survey's bibliography) are kept as they are.
    papers.extend(p for k, p in old.items() if k not in bib)

    args.out.write_text(
        "# Generated by scripts/bib2yaml.py. Edit only code, note, categories_override, primary_override;\n"
        "# other fields are regenerated from the survey.\n"
        + yaml.safe_dump(papers, sort_keys=False, allow_unicode=True, width=1000),
        encoding="utf-8",
    )

    uncited = [p["key"] for p in papers if not p["categories"] and not p.get("categories_override")]
    print(f"{len(papers)} papers written to {args.out}")
    print(f"{len(papers) - len(uncited)} classified, {len(uncited)} without a category")
    if uncited:
        print("  without a category (not cited in sections/, or cited only in unmatched places):")
        for k in uncited:
            print("   -", k)
    if unknown_keys:
        print(f"{len(unknown_keys)} cite keys not in references.bib: {', '.join(sorted(unknown_keys))}")
    if unmatched_locations:
        print("citations in locations no taxonomy rule matches:")
        for (stem, heading), n in unmatched_locations.most_common():
            print(f"   {n:4d}  {stem} :: {heading or '(no heading)'}")


if __name__ == "__main__":
    main()
