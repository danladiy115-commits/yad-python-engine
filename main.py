
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from docx import Document
from calculations import calculate_rsa
from mapper import analyze_docx_mapping
import fitz
import io
import zipfile
import base64
import binascii

app = FastAPI(
    title="YAD Documents Corrector Python Engine",
    version="0.3.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

MAX_FILE_SIZE = 25 * 1024 * 1024
MAX_BATCH_FILES = 30


@app.get("/")
def root():
    return {
        "service": "YAD Python Engine",
        "status": "running",
        "version": app.version
    }


@app.get("/health")
def health():
    return {
        "ok": True,
        "service": "yad-python-engine",
        "version": app.version
    }


async def read_upload(upload):

    data = await upload.read()

    if not data:
        raise HTTPException(
            400,
            "Uploaded file is empty."
        )

    if len(data) > MAX_FILE_SIZE:
        raise HTTPException(
            413,
            "File exceeds 25 MB."
        )

    return data


@app.post("/api/analyze")
async def analyze_document(
    file: UploadFile = File(...)
):

    filename = (file.filename or "").lower()
    data = await read_upload(file)

    try:

        if filename.endswith(".docx"):

            doc = Document(io.BytesIO(data))

            paragraphs = [
                p.text
                for p in doc.paragraphs
                if p.text.strip()
            ]

            tables = [
                [
                    cell.text
                    for cell in row.cells
                ]
                for table in doc.tables
                for row in table.rows
            ]

            return {
                "filename": file.filename,
                "file_type": "docx",
                "paragraph_count": len(paragraphs),
                "table_count": len(doc.tables),
                "text": "\n".join(paragraphs),
                "tables": tables
            }

        if filename.endswith(".pdf"):

            pdf = fitz.open(
                stream=data,
                filetype="pdf"
            )

            pages = [
                page.get_text("text")
                for page in pdf
            ]

            return {
                "filename": file.filename,
                "file_type": "pdf",
                "page_count": len(pdf),
                "text": "\n".join(pages)
            }

        raise HTTPException(
            415,
            "Only DOCX and PDF files are supported."
        )

    except HTTPException:
        raise

    except Exception:
        raise HTTPException(
            400,
            "Could not read this document."
        )


@app.post("/api/zip/check")
async def check_zip(
    file: UploadFile = File(...)
):

    if not (file.filename or "").lower().endswith(".zip"):
        raise HTTPException(
            415,
            "Please upload a ZIP file."
        )

    data = await read_upload(file)

    try:

        with zipfile.ZipFile(
            io.BytesIO(data)
        ) as archive:

            names = [
                item.filename
                for item in archive.infolist()
                if not item.is_dir()
                and item.filename.lower().endswith(
                    (".pdf", ".docx")
                )
            ]

        return {
            "filename": file.filename,
            "document_count": len(names),
            "documents": names
        }

    except zipfile.BadZipFile:
        raise HTTPException(
            400,
            "Invalid ZIP file."
        )


class CalculationRequest(BaseModel):
    rsa_balance: str
    dob: str
    calculation_year: int = 2026


@app.post("/api/calculate")
def calculate_documents(
    request: CalculationRequest
):

    try:

        return calculate_rsa(
            balance=request.rsa_balance,
            dob=request.dob,
            calculation_year=request.calculation_year
        )

    except ValueError as error:

        raise HTTPException(
            400,
            detail=str(error)
        )


class BatchDocument(BaseModel):
    name: str
    base64: str


class BatchAnalysisRequest(BaseModel):
    documents: list[BatchDocument]


def decode_batch_documents(documents):

    if not documents:
        raise HTTPException(
            400,
            "Upload at least one document."
        )

    if len(documents) > MAX_BATCH_FILES:
        raise HTTPException(
            413,
            "Maximum 30 documents per batch."
        )

    total_size = 0
    decoded = []

    for item in documents:

        try:

            raw = base64.b64decode(
                item.base64,
                validate=True
            )

        except (ValueError, binascii.Error):

            raise HTTPException(
                400,
                f"Invalid file data: {item.name}"
            )

        if not raw:
            raise HTTPException(
                400,
                f"Empty file: {item.name}"
            )

        total_size += len(raw)

        if total_size > MAX_FILE_SIZE:
            raise HTTPException(
                413,
                "Combined files exceed 25 MB."
            )

        decoded.append(
            (item.name, raw)
        )

    return decoded


@app.post("/api/analyze/batch")
def analyze_batch(
    request: BatchAnalysisRequest
):

    decoded = decode_batch_documents(
        request.documents
    )

    results = []

    for name, raw in decoded:

        try:

            if name.lower().endswith(".docx"):

                report = analyze_docx_mapping(
                    raw,
                    name
                )

                results.append({
                    "filename": name,
                    "file_type": "docx",
                    "word_count": sum(
                        len(x["contexts"][0].split())
                        for x in report["candidates"]
                        if x["contexts"]
                    ),
                    "text_preview": "",
                    "status": report["status"],
                    "mapping_report": report
                })

            elif name.lower().endswith(".pdf"):

                pdf = fitz.open(
                    stream=raw,
                    filetype="pdf"
                )

                text_content = "\n".join(
                    page.get_text("text")
                    for page in pdf
                )

                results.append({
                    "filename": name,
                    "file_type": "pdf",
                    "page_count": len(pdf),
                    "word_count": len(
                        text_content.split()
                    ),
                    "text_preview": text_content[:2500],
                    "status": (
                        "text_extracted"
                        if text_content.strip()
                        else "needs_ocr"
                    ),
                    "message": (
                        "PDF text extraction only; "
                        "OCR for scanned pages is not yet enabled."
                    )
                })

            else:

                results.append({
                    "filename": name,
                    "status": "unsupported"
                })

        except Exception as error:

            results.append({
                "filename": name,
                "status": "failed",
                "message": str(error)
            })

    return {
        "service": "yad-python-engine",
        "analysis_engine": "contextual-python-mapper",
        "document_count": len(results),
        "results": results
    }


@app.post("/api/map/batch")
def map_batch(
    request: BatchAnalysisRequest
):

    decoded = decode_batch_documents(
        request.documents
    )

    results = []

    for name, raw in decoded:

        if not name.lower().endswith(".docx"):

            results.append({
                "filename": name,
                "status": "unsupported",
                "message": (
                    "Contextual mapping currently "
                    "supports DOCX only."
                )
            })

            continue

        try:

            results.append(
                analyze_docx_mapping(
                    raw,
                    name
                )
            )

        except Exception as error:

            results.append({
                "filename": name,
                "status": "failed",
                "message": str(error)
            })

    return {
        "service": "yad-python-engine",
        "operation": "contextual_mapping_only",
        "documents_modified": False,
        "document_count": len(results),
        "results": results
    }


# Correction is intentionally not wired to the mapping stage yet.
# We will enable replacement only after mapping is validated.
