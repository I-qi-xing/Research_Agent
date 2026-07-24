import json
import os
import pdfplumber
import fitz

papers_dir = "./papers"
analysis_dir = "./analysis"

os.makedirs(analysis_dir, exist_ok=True)

report = {}

for fname in os.listdir(papers_dir):
    if not fname.lower().endswith(".pdf"):
        continue

    pdf_path = os.path.join(papers_dir, fname)
    raw_name = os.path.splitext(fname)[0]
    out_path = os.path.join(analysis_dir, f"{raw_name}_raw.txt")

    text = None
    method = None

    try:
        with pdfplumber.open(pdf_path) as pdf:
            pages = [p.extract_text() for p in pdf.pages if p.extract_text()]
            text = "\n".join(pages)
        method = "pdfplumber"
    except Exception as e1:
        try:
            doc = fitz.open(pdf_path)
            pages = [doc[i].get_text() for i in range(len(doc))]
            text = "\n".join(pages)
            doc.close()
            method = "pymupdf_fallback"
        except Exception as e2:
            report[fname] = {
                "status": "failed",
                "method": None,
                "char_count": 0,
                "error": f"pdfplumber: {e1}; pymupdf: {e2}"
            }
            continue

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(text)

    report[fname] = {
        "status": "ok",
        "method": method,
        "char_count": len(text)
    }

report_path = os.path.join(analysis_dir, "extraction_report.json")
with open(report_path, "w", encoding="utf-8") as f:
    json.dump(report, f, ensure_ascii=False, indent=2)

print(f"Done. Processed {len(report)} PDF(s). Report saved to {report_path}")
