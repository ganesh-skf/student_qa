import os
import json
import hashlib
import hmac
import secrets
import sqlite3
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent


def get_connection():
    """Open the local SQLite database and enable foreign-key checks."""
    db_setting = os.getenv("SQLITE_DB_PATH", "data/student_assistant.db")
    db_path = Path(db_setting).expanduser()
    if not db_path.is_absolute():
        db_path = BASE_DIR / db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def _dict_rows(rows):
    return [dict(row) for row in rows]


def hash_password(password: str) -> str:
    # PBKDF2 is included with Python; no separate password-hashing package is needed.
    salt = secrets.token_bytes(16)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 310_000)
    return f"pbkdf2_sha256${salt.hex()}${derived.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt_hex, digest_hex = stored.split("$", 2)
        if scheme != "pbkdf2_sha256":
            return False
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), 310_000
        ).hex()
        return hmac.compare_digest(actual, digest_hex)
    except (ValueError, TypeError):
        return False


def init_db():
    conn = get_connection()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS students (
                student_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS documents (
                document_id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL,
                stored_filename TEXT NOT NULL,
                sha256_hash TEXT NOT NULL UNIQUE,
                page_count INTEGER NOT NULL DEFAULT 0,
                chunk_count INTEGER NOT NULL DEFAULT 0,
                uploaded_by TEXT NOT NULL,
                uploaded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS chat_history (
                chat_id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                question TEXT NOT NULL,
                answer TEXT,
                source_documents TEXT,
                asked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (student_id) REFERENCES students(student_id)
            );

            CREATE INDEX IF NOT EXISTS idx_chat_history_student_asked
                ON chat_history(student_id, asked_at);
        """)
        conn.commit()
    finally:
        conn.close()


def create_student(name, email, password):
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO students (name, email, password_hash) VALUES (?, ?, ?)",
            (name, email, hash_password(password)),
        )
        conn.commit()
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        if "students.email" in str(exc).lower() or "unique constraint failed: students.email" in str(exc).lower():
            raise ValueError("That email address is already registered.") from exc
        raise
    finally:
        conn.close()


def authenticate_student(email, password):
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM students WHERE email = ?", (email,)).fetchone()
        if row and verify_password(password, row["password_hash"]):
            return {"id": row["student_id"], "name": row["name"], "role": "student"}
        return None
    finally:
        conn.close()


def authenticate_trainer(username, password):
    expected_user = os.getenv("TRAINER_USERNAME", "trainer")
    expected_password = os.getenv("TRAINER_PASSWORD", "")
    if expected_password and hmac.compare_digest(username, expected_user) and hmac.compare_digest(password, expected_password):
        return {"id": None, "name": expected_user, "role": "trainer"}
    return None


def save_question(student_id, question, answer, sources):
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO chat_history (student_id, question, answer, source_documents)
               VALUES (?, ?, ?, ?)""",
            (student_id, question, answer, json.dumps(sources, ensure_ascii=False)),
        )
        conn.commit()
    finally:
        conn.close()


def get_student_history(student_id, limit=30):
    conn = get_connection()
    try:
        rows = _dict_rows(conn.execute(
            """SELECT chat_id, question, answer, source_documents, asked_at
               FROM chat_history WHERE student_id = ?
               ORDER BY asked_at DESC, chat_id DESC LIMIT ?""",
            (student_id, int(limit)),
        ).fetchall())
        for row in rows:
            if isinstance(row.get("source_documents"), str):
                try:
                    row["source_documents"] = json.loads(row["source_documents"])
                except json.JSONDecodeError:
                    row["source_documents"] = []
        return rows
    finally:
        conn.close()


def get_all_questions(limit=500):
    conn = get_connection()
    try:
        rows = _dict_rows(conn.execute(
            """SELECT h.chat_id, s.name AS student_name, s.email,
                      h.question, h.answer, h.source_documents, h.asked_at
               FROM chat_history h
               JOIN students s ON s.student_id = h.student_id
               ORDER BY h.asked_at DESC, h.chat_id DESC LIMIT ?""",
            (int(limit),),
        ).fetchall())
        for row in rows:
            if isinstance(row.get("source_documents"), str):
                try:
                    row["source_documents"] = json.loads(row["source_documents"])
                except json.JSONDecodeError:
                    row["source_documents"] = []
            row["source_documents"] = ", ".join(row.get("source_documents") or [])
        return rows
    finally:
        conn.close()


def get_documents():
    conn = get_connection()
    try:
        return _dict_rows(conn.execute(
            """SELECT filename, page_count, chunk_count, uploaded_by, uploaded_at
               FROM documents ORDER BY uploaded_at DESC, document_id DESC"""
        ).fetchall())
    finally:
        conn.close()


def register_document(filename, stored_filename, sha256_hash, page_count, chunk_count, uploaded_by):
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO documents
               (filename, stored_filename, sha256_hash, page_count, chunk_count, uploaded_by)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (filename, stored_filename, sha256_hash, page_count, chunk_count, uploaded_by),
        )
        conn.commit()
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        if "documents.sha256_hash" in str(exc).lower() or "unique constraint failed: documents.sha256_hash" in str(exc).lower():
            raise ValueError("This exact PDF has already been uploaded.") from exc
        raise
    finally:
        conn.close()
