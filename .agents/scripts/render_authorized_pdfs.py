from pathlib import Path
import fitz

INPUTS = [
    Path('attached_assets/JobRequest-(1)_(1)_1789406011025.pdf'),
    Path('attached_assets/JobRequest-A_(2)_(3)_1789406011025.pdf'),
]
out = Path('.agents/outputs/authorized-pdfs')
out.mkdir(parents=True, exist_ok=True)
for source in INPUTS:
    doc = fitz.open(source)
    stem = source.stem
    print(f'{source}: pages={doc.page_count}, metadata={doc.metadata}')
    for index, page in enumerate(doc):
        pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
        path = out / f'{stem}-page-{index+1}.png'
        pix.save(path)
        text = page.get_text('text').strip()
        print(f'  page={index+1} text_chars={len(text)} image_blocks={sum(1 for b in page.get_text("dict").get("blocks", []) if b.get("type") == 1)}')
