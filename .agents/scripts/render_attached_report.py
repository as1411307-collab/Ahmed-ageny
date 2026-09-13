from __future__ import annotations

import sys
from pathlib import Path

import fitz


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: render_attached_report.py <pdf>")

    pdf_path = Path(sys.argv[1])
    output_dir = Path(".agents/outputs/attached-report-pages")
    output_dir.mkdir(parents=True, exist_ok=True)

    document = fitz.open(pdf_path)
    print(f"pages={document.page_count}")
    print(f"metadata={document.metadata}")
    for page_number, page in enumerate(document, start=1):
        pixmap = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
        output_path = output_dir / f"page-{page_number:02d}.png"
        pixmap.save(output_path)
        print(f"rendered={output_path}")


if __name__ == "__main__":
    main()