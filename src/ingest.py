import hashlib
import json
import logging
from pathlib import Path

import pymupdf  # PyMuPDF — fast text-layer probe (docling already depends on it)
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import (
    PdfPipelineOptions,
    RapidOcrOptions,
)
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling_core.types.doc import ImageRefMode


ROOT = Path(__file__).resolve().parents[1]
INPUT_DIR = ROOT / "data" / "raw"
OUTPUT_DIR = ROOT / "data" / "extracted"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def provenance(item):
    return [entry.model_dump(mode="json") for entry in item.prov]


def pdf_needs_ocr(pdf_path: Path, min_chars_per_page: int = 40) -> bool:
    """Return True only if the PDF has essentially no extractable text layer."""
    try:
        with pymupdf.open(pdf_path) as doc:
            if doc.page_count == 0:
                return True
            total_chars = sum(
                len(page.get_text("text").strip()) for page in doc
            )
            avg = total_chars / doc.page_count
            return avg < min_chars_per_page
    except Exception:
        logger.warning("Could not probe %s; assuming OCR needed", pdf_path.name)
        return True


def make_converter(needs_ocr: bool):
    options = PdfPipelineOptions()

    options.do_table_structure = True
    options.table_structure_options.do_cell_matching = True

    if needs_ocr:
        options.do_ocr = True
        options.ocr_options = RapidOcrOptions(force_full_page_ocr=False)
        logger.info("OCR enabled (scanned PDF detected)")
    else:
        options.do_ocr = False
        logger.info("OCR disabled (digital PDF with text layer)")

    options.images_scale = 2.0
    options.generate_page_images = True
    options.generate_picture_images = True

    return DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=options)
        }
    )


def process_pdf(pdf_path):
    file_hash = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
    document_id = f"{pdf_path.stem}-{file_hash[:12]}"

    output = OUTPUT_DIR / document_id
    for name in ("pages", "tables", "figures"):
        (output / name).mkdir(parents=True, exist_ok=True)

    needs_ocr = pdf_needs_ocr(pdf_path)
    converter = make_converter(needs_ocr)

    result = converter.convert(pdf_path)

    status = getattr(result.status, "value", str(result.status))
    if status != "success":
        raise RuntimeError(
            f"Conversion did not complete successfully: {status}. "
            f"Details: {result.errors}"
        )

    document = result.document
    document.save_as_json(output / "document.json")
    document.save_as_markdown(
        output / "document.md",
        image_mode=ImageRefMode.REFERENCED,
    )

    manifest = {
        "document_id": document_id,
        "source_pdf": pdf_path.name,
        "sha256": file_hash,
        "status": status,
        "ocr_used": needs_ocr,
        "pages": [],
        "tables": [],
        "figures": [],
    }

    for page in document.pages.values():
        image_path = output / "pages" / f"page-{page.page_no:03d}.png"
        if page.image is not None:
            page.image.pil_image.save(image_path)
            manifest["pages"].append({
                "page": page.page_no,
                "image": image_path.relative_to(output).as_posix(),
            })

    for index, table in enumerate(document.tables, start=1):
        stem = f"table-{index:03d}"
        csv_path = output / "tables" / f"{stem}.csv"
        html_path = output / "tables" / f"{stem}.html"
        image_path = output / "tables" / f"{stem}.png"

        table.export_to_dataframe(doc=document).to_csv(csv_path, index=False)
        html_path.write_text(
            table.export_to_html(doc=document), encoding="utf-8"
        )

        image = table.get_image(document)
        if image is not None:
            image.save(image_path)

        manifest["tables"].append({
            "id": stem,
            "self_ref": table.self_ref,
            "caption": table.caption_text(document),
            "provenance": provenance(table),
            "csv": csv_path.relative_to(output).as_posix(),
            "html": html_path.relative_to(output).as_posix(),
            "image": (
                image_path.relative_to(output).as_posix()
                if image is not None else None
            ),
        })

    for index, picture in enumerate(document.pictures, start=1):
        stem = f"figure-{index:03d}"
        image_path = output / "figures" / f"{stem}.png"

        image = picture.get_image(document)
        if image is not None:
            image.save(image_path)

        manifest["figures"].append({
            "id": stem,
            "self_ref": picture.self_ref,
            "caption": picture.caption_text(document),
            "provenance": provenance(picture),
            "image": (
                image_path.relative_to(output).as_posix()
                if image is not None else None
            ),
        })

    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    logger.info(
        "%s [ocr=%s]: %d pages, %d tables, %d figures",
        pdf_path.name,
        needs_ocr,
        len(document.pages),
        len(document.tables),
        len(document.pictures),
    )


def main():
    pdfs = sorted(
        p for p in INPUT_DIR.iterdir()
        if p.is_file() and p.suffix.lower() == ".pdf"
    )
    if not pdfs:
        raise SystemExit(f"No PDFs found in {INPUT_DIR}")

    failures = []
    for pdf_path in pdfs:
        try:
            process_pdf(pdf_path)
        except Exception:
            logger.exception("Failed to process %s", pdf_path.name)
            failures.append(pdf_path.name)

    if failures:
        raise SystemExit(f"Failed PDFs: {', '.join(failures)}")


if __name__ == "__main__":
    main()