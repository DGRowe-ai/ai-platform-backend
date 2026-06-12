import json
import math
import re
from io import BytesIO
from pathlib import Path

from fastapi import HTTPException, UploadFile
from openai import OpenAI
from sqlalchemy.orm import Session

from models import Business, KnowledgeEmbedding, KnowledgeFile

EMBEDDING_MODEL = "text-embedding-3-small"
MAX_FILE_SIZE = 10 * 1024 * 1024
ALLOWED_EXTENSIONS = {".pdf", ".txt", ".doc", ".docx", ".csv", ".md", ".json"}
CHUNK_SIZE = 800
CHUNK_OVERLAP = 100
TOP_K = 5

KNOWLEDGE_ROOT = Path(__file__).resolve().parent / "businesses"


def get_openai_client() -> OpenAI:
    import os

    return OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def sanitize_filename(filename: str) -> str:
    name = Path(filename).name
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name)
    name = name.strip("._")
    if not name or name.startswith("."):
        raise HTTPException(status_code=400, detail="Invalid filename")
    return name[:180]


def validate_upload(file: UploadFile, contents: bytes) -> str:
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is required")

    extension = Path(file.filename).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File exceeds the 10 MB limit")

    return extension


def extract_text_from_file(contents: bytes, filename: str, file_type: str) -> str:
    if file_type in {".txt", ".md", ".csv", ".json"}:
        return contents.decode("utf-8", errors="ignore").strip()

    if file_type == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(BytesIO(contents))
        pages = [page.extract_text() or "" for page in reader.pages]
        text = "\n".join(pages).strip()
        if not text:
            raise HTTPException(status_code=400, detail="Could not extract text from PDF")
        return text

    if file_type == ".docx":
        from docx import Document

        document = Document(BytesIO(contents))
        text = "\n".join(paragraph.text for paragraph in document.paragraphs).strip()
        if not text:
            raise HTTPException(status_code=400, detail="Could not extract text from DOCX")
        return text

    if file_type == ".doc":
        raise HTTPException(
            status_code=400,
            detail="Legacy .doc files are not supported. Please upload a .docx file instead.",
        )

    raise HTTPException(status_code=400, detail="Unsupported file type")


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if not cleaned:
        return []

    chunks = []
    start = 0
    while start < len(cleaned):
        end = start + chunk_size
        chunk = cleaned[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(cleaned):
            break
        start = max(end - overlap, start + 1)

    return chunks


def generate_embeddings(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []

    client = get_openai_client()
    response = client.embeddings.create(model=EMBEDDING_MODEL, input=texts)
    return [item.embedding for item in response.data]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def get_business_upload_dir(business: Business) -> Path:
    directory = KNOWLEDGE_ROOT / business.folder_name / "knowledge_uploads"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def serialize_knowledge_file(record: KnowledgeFile) -> dict:
    return {
        "id": record.id,
        "client_id": record.client_id,
        "file_name": record.file_name,
        "file_type": record.file_type,
        "file_size": record.file_size,
        "uploaded_at": record.uploaded_at.isoformat() if record.uploaded_at else None,
    }


def list_knowledge_files(db: Session, client_id: int) -> list[dict]:
    records = (
        db.query(KnowledgeFile)
        .filter(KnowledgeFile.client_id == client_id)
        .order_by(KnowledgeFile.uploaded_at.desc())
        .all()
    )
    return [serialize_knowledge_file(record) for record in records]


async def ingest_knowledge_file(
    db: Session,
    business: Business,
    upload: UploadFile,
) -> dict:
    contents = await upload.read()
    file_type = validate_upload(upload, contents)
    safe_name = sanitize_filename(upload.filename)
    text = extract_text_from_file(contents, safe_name, file_type)
    chunks = chunk_text(text)

    if not chunks:
        raise HTTPException(status_code=400, detail="No readable text found in file")

    upload_dir = get_business_upload_dir(business)
    stored_path = upload_dir / safe_name
    if stored_path.exists():
        stem = stored_path.stem
        suffix = stored_path.suffix
        counter = 1
        while stored_path.exists():
            stored_path = upload_dir / f"{stem}_{counter}{suffix}"
            counter += 1

    stored_path.write_bytes(contents)
    embeddings = generate_embeddings(chunks)

    record = KnowledgeFile(
        client_id=business.id,
        file_name=safe_name,
        file_path=str(stored_path),
        file_type=file_type,
        file_size=len(contents),
    )
    db.add(record)
    db.flush()

    for chunk, vector in zip(chunks, embeddings):
        db.add(
            KnowledgeEmbedding(
                client_id=business.id,
                file_id=record.id,
                chunk_text=chunk,
                embedding_vector=json.dumps(vector),
            )
        )

    db.commit()
    db.refresh(record)
    return serialize_knowledge_file(record)


def delete_knowledge_file(db: Session, business: Business, file_id: int) -> dict:
    record = (
        db.query(KnowledgeFile)
        .filter(
            KnowledgeFile.id == file_id,
            KnowledgeFile.client_id == business.id,
        )
        .first()
    )
    if not record:
        raise HTTPException(status_code=404, detail="Knowledge file not found")

    file_path = Path(record.file_path)
    if file_path.exists() and file_path.is_file():
        file_path.unlink()

    db.delete(record)
    db.commit()
    return {"message": "Knowledge file deleted", "id": file_id}


def retrieve_knowledge_context(db: Session, client_id: int, query: str, top_k: int = TOP_K) -> str:
    rows = (
        db.query(KnowledgeEmbedding)
        .filter(KnowledgeEmbedding.client_id == client_id)
        .all()
    )
    if not rows:
        return ""

    client = get_openai_client()
    query_embedding = client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=query,
    ).data[0].embedding

    scored = []
    for row in rows:
        try:
            vector = json.loads(row.embedding_vector)
        except (TypeError, json.JSONDecodeError):
            continue
        score = cosine_similarity(query_embedding, vector)
        scored.append((score, row.chunk_text))

    if not scored:
        return ""

    scored.sort(key=lambda item: item[0], reverse=True)
    selected = [chunk for _, chunk in scored[:top_k] if chunk]
    return "\n\n".join(selected)
