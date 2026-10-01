import os

import streamlit as st

from study_assistant import (
    ask_gemini,
    explain_concept,
    extract_pdf_text,
    generate_exam_answer,
    generate_flashcards,
    generate_quiz,
    generate_summary,
    get_api_key_from_settings,
)


st.set_page_config(page_title="AI Study Assistant", page_icon="📚", layout="wide")


if "chat_history" not in st.session_state:
    st.session_state.chat_history = []


def get_api_key() -> str | None:
    """Return the configured API key stored in Streamlit secrets or environment variables."""
    api_key = get_api_key_from_settings()
    if not api_key:
        st.warning("Add GEMINI_API_KEY to a local .env file or Streamlit secrets before using the AI features.")
    return api_key


def main() -> None:
    st.title("📚 AI Study Assistant")
    st.caption("Upload a PDF and turn your notes into study material.")

    with st.sidebar:
        st.header("Settings")
        st.markdown(f"Model: `{os.getenv('MODEL_NAME', 'gemini-3.8-flash')}`")
        st.markdown(f"Max file size: `{os.getenv('MAX_FILE_SIZE_MB', '20')} MB`")
        st.markdown(f"Max pages: `{os.getenv('MAX_PAGES', '80')}`")

    uploaded_file = st.file_uploader("Upload a PDF", type=["pdf"])
    if uploaded_file is None:
        st.info("Upload a PDF file to begin. The app will extract the text and build study tools from it.")
        return

    try:
        max_file_size = int(os.getenv("MAX_FILE_SIZE_MB", "20")) * 1024 * 1024
    except ValueError:
        st.warning("Invalid MAX_FILE_SIZE_MB value. Falling back to the default limit.")
        max_file_size = 20 * 1024 * 1024

    if uploaded_file.size > max_file_size:
        st.error("The uploaded file is larger than the configured limit.")
        return

    max_pages = int(os.getenv("MAX_PAGES", "80"))
    document_key = (uploaded_file.file_id, uploaded_file.size, max_pages, uploaded_file.name)
    cached_document = st.session_state.get("document_cache")
    if cached_document and cached_document["key"] == document_key:
        status = cached_document["status"]
        text = cached_document["text"]
        extraction_error = cached_document["error"]
    else:
        file_bytes = uploaded_file.getvalue()
        status = "ok"
        text = ""
        extraction_error = ""
        if not file_bytes or not file_bytes.strip():
            status = "empty"
        elif not file_bytes.startswith(b"%PDF"):
            status = "invalid"
        else:
            try:
                with st.spinner("Extracting text from the PDF..."):
                    text = extract_pdf_text(uploaded_file, max_pages=max_pages)
            except ValueError as exc:
                status = "error"
                extraction_error = str(exc)
        st.session_state.document_cache = {
            "key": document_key,
            "status": status,
            "text": text,
            "error": extraction_error,
        }

    if status == "empty":
        st.error("The uploaded file is empty. Please upload a valid PDF.")
        return
    if status == "invalid":
        st.error("This file is not a valid PDF or it contains no pages. Please upload a real PDF file.")
        return
    if status == "error":
        st.error(extraction_error)
        return

    max_chars = int(os.getenv("MAX_TEXT_CHARS", "200000"))
    if len(text) > max_chars:
        st.warning(
            f"The document is large. The app will use the first {max_chars:,} characters for model input to keep processing stable. "
            "For very long PDFs, split the document into smaller files."
        )

    st.subheader("Document preview")
    preview = text[:max_chars]
    st.text_area("Extracted text", preview, height=260)

    chat_tab, qna_tab, concept_tab, exam_tab, summary_tab, flashcards_tab, quiz_tab = st.tabs(
        ["Chat", "Q&A", "Concept", "Exam", "Summary", "Flashcards", "Quiz"]
    )

    with chat_tab:
        st.caption("Ask follow-up questions about the document.")
        if st.button("Clear chat", key="clear_chat"):
            st.session_state.chat_history = []
        for message in st.session_state.chat_history:
            with st.chat_message(message["role"]):
                st.write(message["content"])

        user_input = st.chat_input("Ask a study question about this PDF")
        if user_input:
            api_key = get_api_key()
            if api_key:
                st.session_state.chat_history.append({"role": "user", "content": user_input})
                with st.spinner("Generating response..."):
                    answer = ask_gemini(user_input, text, api_key=api_key, model_name=os.getenv("MODEL_NAME", "gemini-3.8-flash"))
                st.session_state.chat_history.append({"role": "assistant", "content": answer})
                st.rerun()

    with qna_tab:
        question = st.text_input("Ask a question about this document")
        if st.button("Generate answer", key="answer_button"):
            if not question.strip():
                st.warning("Please enter a question before generating an answer.")
            else:
                api_key = get_api_key()
                if api_key:
                    with st.spinner("Thinking through the document..."):
                        answer = ask_gemini(question, text, api_key=api_key, model_name=os.getenv("MODEL_NAME", "gemini-3.8-flash"))
                    st.subheader("Answer")
                    st.write(answer)

    with concept_tab:
        concept = st.text_input("Concept to explain", key="concept_input")
        if st.button("Explain concept", key="concept_button"):
            if not concept.strip():
                st.warning("Please enter a concept to explain.")
            else:
                api_key = get_api_key()
                if api_key:
                    with st.spinner("Explaining the concept..."):
                        explanation = explain_concept(concept, text, api_key=api_key, model_name=os.getenv("MODEL_NAME", "gemini-3.8-flash"))
                    st.subheader("Concept explanation")
                    st.write(explanation)

    with exam_tab:
        exam_type = st.selectbox("Exam type", ["5-mark", "10-mark"], index=0)
        exam_question = st.text_area("Exam question or topic")
        if st.button("Generate exam answer", key="exam_button"):
            if not exam_question.strip():
                st.warning("Please enter the exam question or topic.")
            else:
                api_key = get_api_key()
                if api_key:
                    with st.spinner("Drafting the exam answer..."):
                        exam_answer = generate_exam_answer(
                            exam_type,
                            text,
                            api_key=api_key,
                            model_name=os.getenv("MODEL_NAME", "gemini-3.8-flash"),
                            question=exam_question,
                        )
                    st.subheader(f"{exam_type} answer")
                    st.write(exam_answer)

    with summary_tab:
        if st.button("Generate summary", key="summary_button"):
            api_key = get_api_key()
            if api_key:
                with st.spinner("Creating a study summary..."):
                    summary = generate_summary(text, api_key=api_key, model_name=os.getenv("MODEL_NAME", "gemini-3.8-flash"))
                st.subheader("Summary")
                st.write(summary)

    with flashcards_tab:
        if st.button("Generate flashcards", key="flashcards_button"):
            api_key = get_api_key()
            if api_key:
                with st.spinner("Creating flashcards..."):
                    flashcards = generate_flashcards(text, api_key=api_key, model_name=os.getenv("MODEL_NAME", "gemini-3.8-flash"))
                st.subheader("Flashcards")
                st.write(flashcards)

    with quiz_tab:
        if st.button("Generate quiz", key="quiz_button"):
            api_key = get_api_key()
            if api_key:
                with st.spinner("Formulating quiz questions..."):
                    quiz = generate_quiz(text, api_key=api_key, model_name=os.getenv("MODEL_NAME", "gemini-3.8-flash"))
                st.subheader("Quiz")
                st.write(quiz)


if __name__ == "__main__":
    main()
