import hashlib
import os
import re
from pathlib import Path

import chromadb
from chromadb.config import Settings
from pypdf import PdfReader
from dotenv import load_dotenv

from database import register_document

load_dotenv()
ROOT = Path(__file__).resolve().parent
DOCS_DIR = ROOT / "documents"
CHROMA_DIR = ROOT / "chroma_db"
DOCS_DIR.mkdir(exist_ok=True)
CHROMA_DIR.mkdir(exist_ok=True)

_client = None
def get_collection():
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(path=str(CHROMA_DIR), settings=Settings(anonymized_telemetry=False))
    return _client.get_or_create_collection(
        name="student_course_documents",
        metadata={"hnsw:space": "cosine"}
    )

def split_text(text, chunk_size=900, overlap=150):
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    chunks = []
    start = 0
    while start < len(text):
        end = min(len(text), start + chunk_size)
        if end < len(text):
            boundary = text.rfind(" ", start + int(chunk_size * 0.65), end)
            if boundary > start:
                end = boundary
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks

def process_pdf(original_filename, pdf_bytes):
    digest = hashlib.sha256(pdf_bytes).hexdigest()
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(original_filename).name).strip("._")
    if not safe_name.lower().endswith(".pdf"):
        safe_name += ".pdf"
    stored_filename = f"{digest[:12]}_{safe_name}"
    path = DOCS_DIR / stored_filename

    collection = get_collection()
    # Check SQLite first for duplicates before writing new data.
    from database import get_connection
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT document_id FROM documents WHERE sha256_hash = ?", (digest,))
        duplicate = cur.fetchone()
        cur.close()
        if duplicate:
            raise ValueError("This exact PDF has already been uploaded.")
    finally:
        conn.close()

    path.write_bytes(pdf_bytes)
    try:
        reader = PdfReader(str(path))
        page_count = len(reader.pages)
        ids, texts, metadatas, embeddings = [], [], [], []
        # Local embeddings; download the model the first time the app indexes a PDF.
        from sentence_transformers import SentenceTransformer
        model_name = os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
        model = SentenceTransformer(model_name)

        for page_num, page in enumerate(reader.pages, start=1):
            page_text = page.extract_text() or ""
            for chunk_num, chunk in enumerate(split_text(page_text)):
                chunk_id = f"{digest[:12]}_p{page_num}_c{chunk_num}"
                ids.append(chunk_id)
                texts.append(chunk)
                metadatas.append({
                    "filename": Path(original_filename).name,
                    "stored_filename": stored_filename,
                    "page": page_num,
                    "chunk": chunk_num,
                    "sha256": digest,
                })

        if not texts:
            raise ValueError("No selectable text was found. If this is a scanned PDF, run OCR first.")

        batch_size = 64
        for offset in range(0, len(texts), batch_size):
            batch_texts = texts[offset:offset + batch_size]
            batch_embeddings = model.encode(batch_texts, normalize_embeddings=True).tolist()
            collection.add(
                ids=ids[offset:offset + batch_size],
                documents=batch_texts,
                metadatas=metadatas[offset:offset + batch_size],
                embeddings=batch_embeddings,
            )

        register_document(
            Path(original_filename).name, stored_filename, digest,
            page_count, len(texts), os.getenv("TRAINER_USERNAME", "trainer")
        )
        return {"pages": page_count, "chunks": len(texts), "filename": stored_filename}
    except Exception:
        # The uploaded file is retained for troubleshooting; remove it manually if needed.
        raise

def list_indexed_documents():
    collection = get_collection()
    result = collection.get(include=["metadatas"])
    unique = {}
    for meta in result.get("metadatas") or []:
        if meta:
            unique[meta.get("sha256", meta.get("filename", "unknown"))] = {
                "filename": meta.get("filename", "unknown"),
                "chunks_indexed": sum(
                    1 for m in (result.get("metadatas") or [])
                    if m and m.get("sha256") == meta.get("sha256")
                ),
            }
    return list(unique.values())
