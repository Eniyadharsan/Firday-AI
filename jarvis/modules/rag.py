"""
RAG Module — Retrieval Augmented Generation

Allows JARVIS to answer questions about uploaded PDFs and documents.
Uses simple chunking + cosine similarity (no external vector DB needed).
"""

import os
import re
import hashlib
from jarvis.db import get_db
from pathlib import Path
from loguru import logger
from jarvis.config import DB_PATH, DATA_DIR

UPLOAD_DIR = DATA_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


# DB tables initialized by jarvis.db


def extract_text_from_pdf(file_bytes: bytes) -> str:
    """Extract text from PDF bytes. Uses PyPDF2 if available, else basic extraction."""
    try:
        import PyPDF2
        import io
        reader = PyPDF2.PdfReader(io.BytesIO(file_bytes))
        text = ""
        for page in reader.pages:
            text += page.extract_text() or ""
        return text.strip()
    except ImportError:
        # Fallback: extract readable text between parentheses (basic PDF text)
        text = file_bytes.decode("latin-1", errors="ignore")
        segments = re.findall(r"\(([^)]+)\)", text)
        return " ".join(s for s in segments if len(s) > 2)
    except Exception as e:
        logger.error(f"PDF extraction error: {e}")
        return ""


def extract_text(file_bytes: bytes, filename: str) -> str:
    """Extract text from various file types."""
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        return extract_text_from_pdf(file_bytes)
    elif ext in (".txt", ".md", ".csv", ".log"):
        return file_bytes.decode("utf-8", errors="ignore")
    elif ext in (".html", ".htm"):
        text = file_bytes.decode("utf-8", errors="ignore")
        text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        return re.sub(r"\s+", " ", text).strip()
    else:
        return file_bytes.decode("utf-8", errors="ignore")


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
    """Split text into overlapping chunks by words."""
    words = text.split()
    if len(words) <= chunk_size:
        return [text] if text.strip() else []

    chunks: list[str] = []
    start = 0
    while start < len(words):
        end = start + chunk_size
        chunk = " ".join(words[start:end])
        chunks.append(chunk)
        start = end - overlap
    return chunks


def upload_document(user_id: str, filename: str, file_bytes: bytes) -> dict:
    """Upload and index a document for RAG."""
    text = extract_text(file_bytes, filename)
    if not text.strip():
        return {"error": "Could not extract text from document."}

    doc_id = hashlib.sha256(f"{user_id}:{filename}:{len(file_bytes)}".encode()).hexdigest()[:16]
    chunks = chunk_text(text)

    conn = get_db()
    try:
        # Delete existing doc if re-uploading
        conn.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))
        conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))

        import time
        conn.execute(
            "INSERT INTO documents (id, user_id, filename, content, chunks_count, uploaded_at) VALUES (?, ?, ?, ?, ?, ?)",
            (doc_id, user_id, filename, text[:5000], len(chunks), time.strftime("%Y-%m-%dT%H:%M:%SZ")),
        )

        for i, chunk in enumerate(chunks):
            conn.execute(
                "INSERT INTO chunks (doc_id, user_id, chunk_index, content) VALUES (?, ?, ?, ?)",
                (doc_id, user_id, i, chunk),
            )
        conn.commit()
        logger.info(f"Indexed document '{filename}' with {len(chunks)} chunks")
        return {"success": True, "doc_id": doc_id, "filename": filename, "chunks": len(chunks)}
    except Exception as e:
        logger.error(f"Upload error: {e}")
        return {"error": str(e)}
    finally:
        conn.close()


def search_documents(user_id: str, query: str, top_k: int = 5) -> list[dict]:
    """Search indexed documents using keyword matching (simple TF approach)."""
    query_words = set(query.lower().split())
    if not query_words:
        return []

    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT doc_id, chunk_index, content FROM chunks WHERE user_id = ?",
            (user_id,),
        ).fetchall()

        scored: list[tuple[float, dict]] = []
        for doc_id, chunk_idx, content in rows:
            content_words = set(content.lower().split())
            overlap = len(query_words & content_words)
            if overlap > 0:
                score = overlap / len(query_words)
                scored.append((score, {"doc_id": doc_id, "chunk_index": chunk_idx, "content": content, "score": score}))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [item for _, item in scored[:top_k]]
    except Exception as e:
        logger.error(f"Search error: {e}")
        return []
    finally:
        conn.close()


def get_rag_context(user_id: str, query: str) -> str:
    """Get relevant document context for a query."""
    results = search_documents(user_id, query)
    if not results:
        return ""
    context_parts = [f"[Document excerpt]: {r['content']}" for r in results[:3]]
    return "\n\n".join(context_parts)


def list_documents(user_id: str) -> list[dict]:
    """List all uploaded documents for a user."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT id, filename, chunks_count, uploaded_at FROM documents WHERE user_id = ? ORDER BY uploaded_at DESC",
            (user_id,),
        ).fetchall()
        return [{"id": r[0], "filename": r[1], "chunks": r[2], "uploaded_at": r[3]} for r in rows]
    except Exception:
        return []
    finally:
        conn.close()


def delete_document(user_id: str, doc_id: str) -> bool:
    """Delete a document and its chunks."""
    conn = get_db()
    try:
        conn.execute("DELETE FROM chunks WHERE doc_id = ? AND user_id = ?", (doc_id, user_id))
        conn.execute("DELETE FROM documents WHERE id = ? AND user_id = ?", (doc_id, user_id))
        conn.commit()
        return True
    except Exception:
        return False
    finally:
        conn.close()
