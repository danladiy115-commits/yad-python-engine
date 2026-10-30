from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from docx import Document
from calculations import calculate_rsa
import fitz
import io
import zipfile

app = FastAPI(
    title="YAD Documents Corrector Python Engine",
    version="0.2.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

MAX_FILE_SIZE = 25 * 1024 * 1024


# -----------------------------
# ROOT AND HEALTH CHECK
# -----------------------------

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
        "service": "yad-python-engine"
    }


# -----------------------------
# UPLOAD VALIDATION
# -----------------------------

async def read_upload(upload):
    data = await upload.read()

    if not data:
        raise HTTPException(400, "Uploaded file is empty.")

    if len(data) > MAX_FILE_SIZE:
        raise HTTPException(413, "File exceeds 25 MB.")

    return data


# -----------------------------
# DOCUMENT ANALYSIS
# -----------------------------

@app.post("/api/analyze")
async def analyze_document(file: UploadFile = File(...)):
    filename = (file.filename or "").lower()
    data = await read_upload(file)

    try:
        if filename.endswith(".docx"):
            doc = Document(io.BytesIO(data))

            paragraphs = [
                p.text for p in doc.paragraphs
                if p.text.strip()
            ]

            tables = []

            for table in doc.tables:
                for row in table.rows:
                    tables.append([
                        cell.text for cell in row.cells
                    ])

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


# -----------------------------
# ZIP INSPECTION
# -----------------------------

@app.post("/api/zip/check")
async def check_zip(file: UploadFile = File(...)):
    if not (file.filename or "").lower().endswith(".zip"):
        raise HTTPException(415, "Please upload a ZIP file.")

    data = await read_upload(file)

    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
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
        raise HTTPException(400, "Invalid ZIP file.")


# -----------------------------
# RSA AND MORTGAGE CALCULATIONS
# -----------------------------

class CalculationRequest(BaseModel):
    rsa_balance: str
    dob: str
    calculation_year: int = 2026


@app.post("/api/calculate")
def calculate_documents(request: CalculationRequest):
    try:
        return calculate_rsa(
            balance=request.rsa_balance,
            dob=request.dob,
            calculation_year=request.calculation_year
        )

    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error)
        )
        
