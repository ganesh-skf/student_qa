import os
from datetime import datetime

import streamlit as st
from dotenv import load_dotenv

from database import (
    init_db, create_student, authenticate_student, authenticate_trainer,
    save_question, get_student_history, get_all_questions, get_documents,
)
from pdf_processor import process_pdf, list_indexed_documents
from rag_pipeline import answer_question

load_dotenv()
st.set_page_config(page_title="AI Student Assistant", page_icon="🎓", layout="wide")
init_db()

st.title("🎓 AI Student Assistant")
st.caption("Ask questions about your course materials and get answers grounded in uploaded PDFs.")

if "user" not in st.session_state:
    st.session_state.user = None
if "messages" not in st.session_state:
    st.session_state.messages = []

def logout():
    st.session_state.user = None
    st.session_state.messages = []
    st.rerun()

def login_screen():
    tab_student, tab_trainer, tab_register = st.tabs(
        ["Student login", "Trainer login", "Student registration"]
    )

    with tab_student:
        with st.form("student_login"):
            email = st.text_input("Email", key="student_email_login")
            password = st.text_input("Password", type="password", key="student_password_login")
            submitted = st.form_submit_button("Log in", use_container_width=True)
        if submitted:
            user = authenticate_student(email.strip().lower(), password)
            if user:
                st.session_state.user = user
                st.session_state.messages = []
                st.rerun()
            else:
                st.error("Invalid email or password.")

    with tab_trainer:
        st.info("Trainer credentials are configured in your .env file.")
        with st.form("trainer_login"):
            username = st.text_input("Trainer username", key="trainer_username")
            password = st.text_input("Trainer password", type="password", key="trainer_password")
            submitted = st.form_submit_button("Log in as trainer", use_container_width=True)
        if submitted:
            user = authenticate_trainer(username.strip(), password)
            if user:
                st.session_state.user = user
                st.rerun()
            else:
                st.error("Invalid trainer credentials. Check your .env settings.")

    with tab_register:
        with st.form("student_register"):
            name = st.text_input("Full name")
            email = st.text_input("Email address")
            password = st.text_input("Create password", type="password")
            confirm = st.text_input("Confirm password", type="password")
            submitted = st.form_submit_button("Create student account", use_container_width=True)
        if submitted:
            if not name.strip() or not email.strip() or not password:
                st.error("Please fill in every field.")
            elif password != confirm:
                st.error("Passwords do not match.")
            elif len(password) < 8:
                st.error("Use a password with at least 8 characters.")
            else:
                try:
                    create_student(name.strip(), email.strip().lower(), password)
                    st.success("Account created. You can now log in from the Student login tab.")
                except ValueError as exc:
                    st.error(str(exc))
                except Exception:
                    st.error("Could not create the account. Check the database connection and email address.")

user = st.session_state.user
if not user:
    login_screen()
    st.stop()

with st.sidebar:
    st.write(f"**Signed in:** {user['name']}")
    st.write(f"**Role:** {user['role'].title()}")
    st.divider()
    if st.button("Log out", use_container_width=True):
        logout()

if user["role"] == "trainer":
    st.subheader("Trainer dashboard")
    tab_upload, tab_docs, tab_questions = st.tabs(["Upload PDF", "Indexed documents", "Student questions"])

    with tab_upload:
        st.write("Upload course notes or reference documents in PDF format. Only trainers can access this page.")
        uploaded = st.file_uploader("Choose a PDF", type=["pdf"], accept_multiple_files=False)
        if uploaded is not None:
            st.caption(f"Selected: {uploaded.name} ({uploaded.size:,} bytes)")
            if st.button("Process and index PDF", type="primary"):
                if uploaded.size > 25 * 1024 * 1024:
                    st.error("For this starter version, PDFs must be 25 MB or smaller.")
                else:
                    with st.spinner("Extracting text and creating the searchable index..."):
                        try:
                            result = process_pdf(uploaded.name, uploaded.getvalue())
                            st.success(
                                f"Indexed **{result['chunks']} text chunks** from "
                                f"**{result['pages']} pages**."
                            )
                            st.info("Students can now ask questions about this document.")
                        except Exception as exc:
                            st.error(f"PDF processing failed: {exc}")

    with tab_docs:
        st.write("Documents currently recorded in MySQL:")
        docs = get_documents()
        if docs:
            st.dataframe(docs, use_container_width=True, hide_index=True)
        else:
            st.info("No documents have been uploaded yet.")
        st.write("Files in the vector index:")
        indexed = list_indexed_documents()
        if indexed:
            st.dataframe(indexed, use_container_width=True, hide_index=True)
        else:
            st.info("The vector index is empty.")

    with tab_questions:
        st.write("Student question and answer history")
        questions = get_all_questions(limit=500)
        if questions:
            st.dataframe(questions, use_container_width=True, hide_index=True)
            st.caption("Showing up to the most recent 500 records.")
        else:
            st.info("No questions have been recorded yet.")

else:
    st.subheader("Ask your course assistant")
    st.caption("The assistant uses trainer-uploaded PDFs. If the answer is not in the documents, it should say No.")

    history = get_student_history(user["id"], limit=30)
    if history and not st.session_state.messages:
        with st.expander("Recent saved questions"):
            for item in history:
                st.markdown(f"**You:** {item['question']}")
                st.markdown(f"**Assistant:** {item['answer'] or 'No answer was saved.'}")
                st.caption(str(item["asked_at"]))
                st.divider()

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg.get("sources"):
                st.caption("Sources: " + "; ".join(msg["sources"]))

    question = st.chat_input("Ask a question about your course PDFs...")
    if question:
        st.session_state.messages.append({"role": "user", "content": question})
        with st.chat_message("user"):
            st.markdown(question)

        with st.chat_message("assistant"):
            with st.spinner("Searching course documents and preparing an answer..."):
                try:
                    result = answer_question(question)
                    answer = result["answer"]
                    sources = result["sources"]
                    st.markdown(answer)
                    if sources:
                        st.caption("Sources: " + "; ".join(sources))
                    elif not result.get("has_context"):
                        st.caption("No relevant source passages were found.")
                    save_question(user["id"], question, answer, sources)
                    st.session_state.messages.append(
                        {"role": "assistant", "content": answer, "sources": sources}
                    )
                except Exception as exc:
                    error_message = f"I couldn't process that question. Please try again. Details: {exc}"
                    st.error(error_message)
                    # Keep a record of the failure as well, so attempted questions are not lost.
                    try:
                        save_question(user["id"], question, error_message, [])
                    except Exception:
                        pass
                    st.session_state.messages.append(
                        {"role": "assistant", "content": error_message, "sources": []}
                    )
