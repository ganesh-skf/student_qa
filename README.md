# AI Student Assistant (Streamlit + SQLite + RAG + Groq)

A starter project where trainers upload PDFs and students ask questions. The app retrieves relevant passages from PDFs using ChromaDB and local Sentence Transformers embeddings, then asks a Groq-hosted language model to answer from that context. Student accounts, uploaded-document metadata, and student questions/answers are stored in a local SQLite database.

## Architecture

- **Streamlit:** student/trainer interface
- **SQLite:** student accounts, document metadata, and question history (no separate database server required)
- **PyPDF:** extracts text and page numbers from PDFs
- **Sentence Transformers:** creates local embeddings
- **ChromaDB:** persistent vector search index
- **Groq API:** generates answers from retrieved context

This version intentionally does not use LangChain, reducing the chance of import/API mismatches between LangChain versions. SQLite is accessed using Python's built-in `sqlite3` module, so no database-driver installation is needed.

## Requirements

- Windows 10/11
- Python 3.10 or 3.11 recommended
- A Groq API key
- Internet access for package installation, first model download, and Groq calls

## 1. Create a Groq API key

Create an API key through the Groq developer console. Keep it private; do not put it in Python source code or commit `.env` to Git.

## 2. Create the Python environment

Open PowerShell in this project folder:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

If PowerShell blocks activation, run this for the current terminal only:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

If `py -3.11` is not available, use a supported installed Python version, for example `py -3.10`.

## 3. Configure `.env`

Copy the example file and open it:

```powershell
Copy-Item .env.example .env
notepad .env
```

Fill in these values:

- `GROQ_API_KEY`
- `TRAINER_PASSWORD`
- Optionally change `TRAINER_USERNAME`

Use a long, unique trainer password. Do not share `.env` or upload it to GitHub. The default model is `llama-3.3-70b-versatile`. If Groq reports that the model is unavailable for your account, select a currently supported chat model from the Groq console and update `GROQ_MODEL`.

`SQLITE_DB_PATH` defaults to `data/student_assistant.db`. The app creates the database folder and tables automatically when it starts. You do not need to install or start MySQL, and you do not need to create tables manually.

## 4. Start the application

```powershell
streamlit run app.py
```

Streamlit usually opens `http://localhost:8501`.

## 5. Test the flow

1. Open the Trainer login tab.
2. Log in using `TRAINER_USERNAME` and `TRAINER_PASSWORD` from `.env`.
3. Upload a text-based PDF and click **Process and index PDF**.
4. Log out.
5. Register a student account and log in.
6. Ask a question whose answer is in the uploaded PDF.
7. Log out and sign back in as the trainer.
8. Open **Student questions** to inspect saved records.

The first PDF processing may take a few minutes because Sentence Transformers downloads the embedding model. The model is reused locally afterward.

## 6. Where information is stored

- `data/student_assistant.db`: student accounts, password hashes, uploaded-document metadata, and student question/answer history
- `documents/`: uploaded PDF files
- `chroma_db/`: persistent vector index

Back up the SQLite database file and the `documents/` and `chroma_db/` folders together. Do not delete `chroma_db/` unless you intend to rebuild the index.

## 7. Hosting and persistence

SQLite is convenient for local use and small deployments. It stores data in a file, so when hosting the app, configure a **persistent disk/volume** and set `SQLITE_DB_PATH` to a path on that disk. If the hosting platform has ephemeral storage, your database can be lost when the app restarts or redeploys. Keep the app and its database on a persistent storage location, and back up the file regularly. If many students will write to the database at the same time or the app will run across multiple instances, consider a managed server database such as PostgreSQL or MySQL instead.

For deployment, also ensure `documents/` and `chroma_db/` are stored persistently or move them to suitable managed storage.

## 8. Limitations and production hardening

- Scanned/image-only PDFs need OCR before indexing. This starter detects PDFs with no extractable text and reports an error.
- The starter limits uploads to 25 MB.
- Trainer credentials are configured in `.env`; there is one trainer account in this starter.
- The trainer dashboard shows up to the latest 500 questions.
- Students can see their own recent history; the trainer can review all question history.
- For production, add HTTPS, rate limiting, login lockout, password reset, audit logs, and automated backups.
- The current PDF indexing flow is suitable for a starter project. For production, implement transactional re-indexing/rollback and safe document deletion.

## Troubleshooting

### Database file or permission error
- Confirm the application has permission to create/write the folder configured in `SQLITE_DB_PATH`.
- Use an absolute path on a persistent disk when deploying.
- Stop the app before manually moving or replacing the database file.

### Groq authentication or model error
Check `GROQ_API_KEY`. If the model name is unavailable, update `GROQ_MODEL` to one currently enabled for your Groq account.

### PDF returns no text
It may be scanned. OCR it first, or use a text-based PDF.

### `pip install` errors
Use Python 3.10 or 3.11 in a fresh virtual environment, then upgrade pip and reinstall the requirements.

## SQL to inspect saved questions

You can open `data/student_assistant.db` with a SQLite viewer such as DB Browser for SQLite. Or run the following Python script from the project folder:

```python
import sqlite3

connection = sqlite3.connect("data/student_assistant.db")
connection.row_factory = sqlite3.Row
rows = connection.execute("""
    SELECT s.name, s.email, h.question, h.answer,
           h.source_documents, h.asked_at
    FROM chat_history AS h
    JOIN students AS s ON s.student_id = h.student_id
    ORDER BY h.asked_at DESC
""").fetchall()

for row in rows:
    print(dict(row))

connection.close()
```
  
  