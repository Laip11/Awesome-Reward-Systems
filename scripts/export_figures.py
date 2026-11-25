"""Export the survey's illustration SVGs to JPEGs for the README.

The SVGs embed a base image plus text labels in an embedded web font, so they
are rendered with headless Chromium (as the survey's PDFs are) and saved as
high-quality JPEG (4:4:4 chroma, so labels stay sharp), about 1/5 the size.

    python scripts/export_figures.py --survey /path/to/survey-latex [--quality 90]

Needs a Chromium or Chrome binary on PATH (or --chrome) and Pillow.
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIGURES = ["reward-system-illustration", "coevolution-illustration", "rsi-illustration"]


def size_of(svg: Path) -> tuple[int, int]:
    head = svg.read_text(encoding="utf-8", errors="ignore")[:2000]
    m = re.search(r'viewBox="\s*[\d.]+\s+[\d.]+\s+([\d.]+)\s+([\d.]+)"', head)
    if not m:
        sys.exit(f"{svg}: no viewBox")
    return round(float(m.group(1))), round(float(m.group(2)))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--survey", required=True, help="path to the survey LaTeX project")
    ap.add_argument("--quality", type=int, default=90)
    ap.add_argument("--chrome", help="Chromium/Chrome binary")
    args = ap.parse_args()

    from PIL import Image

    chrome = args.chrome or next((c for c in ("chromium", "chromium-browser", "google-chrome", "chrome")
                                  if shutil.which(c)), None)
    if not chrome:
        sys.exit("no Chromium/Chrome found; pass --chrome")
    out_dir = ROOT / "figures"
    out_dir.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        for name in FIGURES:
            svg = Path(args.survey) / "figures" / f"{name}.svg"
            if not svg.exists():
                print(f"skip {name}: {svg} not found")
                continue
            w, h = size_of(svg)
            local = Path(tmp) / svg.name
            shutil.copy(svg, local)
            png = Path(tmp) / f"{name}.png"
            subprocess.run([chrome, "--headless=new", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
                            "--force-device-scale-factor=1", f"--window-size={w},{h}", "--virtual-time-budget=5000",
                            f"--screenshot={png}", local.as_uri()],
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
            dst = out_dir / f"{name}.jpg"
            Image.open(png).convert("RGB").save(dst, quality=args.quality, subsampling=0, optimize=True,
                                                progressive=True)
            print(f"{dst.relative_to(ROOT)}  {w}x{h}  {dst.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
