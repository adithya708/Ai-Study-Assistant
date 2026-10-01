import io
import importlib.util
import os
import re
import shutil
import time
from functools import lru_cache
from typing import BinaryIO

from dotenv import load_dotenv
from pypdf import PdfReader

google_genai = None
genai = None
_gemini_sdk_checked = False


load_dotenv()


def resolve_model_name(model_name: str | None) -> str:
    """Return a supported Gemini model name while tolerating older defaults."""
    preferred = (model_name or os.getenv("MODEL_NAME") or "gemini-1.5-flash").strip()
    normalized = preferred.lower()

    aliases = {
        "gemini-1.5-flash": "gemini-1.5-flash",
        "gemini-1.5-flash-latest": "gemini-1.5-flash",
        "gemini-1.5-pro": "gemini-1.5-flash",
        "gemini-2.0-flash": "gemini-1.5-flash",
        "gemini-2.0-flash-lite": "gemini-1.5-flash",
        "gemini-2.5-flash": "gemini-1.5-flash",
        "gemini-3.8-flash": "gemini-1.5-flash",
    }

    if normalized in aliases:
        return aliases[normalized]
    if normalized:
        return normalized
    return "gemini-1.5-flash"


def _load_gemini_sdk() -> None:
    global google_genai, genai, _gemini_sdk_checked
    if google_genai is not None or genai is not None or _gemini_sdk_checked:
        return

    _gemini_sdk_checked = True
    try:
        from google import genai as google_genai_module

        google_genai = google_genai_module
    except ImportError:
        try:
            import google.generativeai as legacy_genai

            genai = legacy_genai
        except ImportError:
            return


def get_api_key_from_settings() -> str | None:
    """Read the API key from secrets or the environment without exposing it in the app."""
    for key_name in ("GEMINI_API_KEY", "OPENAI_API_KEY", "API_KEY"):
        value = os.getenv(key_name)
        if value and value.strip():
            return value.strip()

    try:
        import streamlit as st  # pragma: no cover

        for key_name in ("GEMINI_API_KEY", "OPENAI_API_KEY", "API_KEY"):
            if "secrets" in dir(st) and key_name in st.secrets:
                value = st.secrets[key_name]
                if value:
                    return str(value).strip()
    except Exception:  # pragma: no cover
        pass

    return None


def validate_pdf_bytes(file_bytes: bytes) -> str:
    """Validate a PDF byte stream and return a simple status code."""
    if not file_bytes or not file_bytes.strip():
        return "empty"

    if not file_bytes.startswith(b"%PDF"):
        return "invalid"

    try:
        reader = PdfReader(io.BytesIO(file_bytes))
        if reader.is_encrypted:
            return "encrypted"
        if len(reader.pages) == 0:
            return "no_pages"
        return "ok"
    except Exception:
        return "invalid"


def clean_text(text: str) -> str:
    """Normalize whitespace in extracted PDF content."""
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n +", "\n", text)
    text = re.sub(r" +\n", "\n", text)
    return text.strip()


def is_probably_page_noise(text: str) -> bool:
    """Detect low-value page-number artifacts that should not count as readable document content."""
    cleaned = clean_text(text)
    if not cleaned:
        return True

    compact = re.sub(r"[^0-9A-Za-z]", "", cleaned)
    if not compact:
        return True

    letters = sum(ch.isalpha() for ch in compact)
    digits = sum(ch.isdigit() for ch in compact)
    if letters == 0 and digits > 0:
        return True

    if re.fullmatch(r"(?i)(page|index)\s*[:\- ]*\d+(\s*[-/]\s*\d+)?", cleaned):
        return True

    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
    if not lines:
        return True

    page_like_lines = 0
    for line in lines:
        if re.fullmatch(r"\d+(\s*[-/\.]\s*\d+)*", line) or re.fullmatch(r"(?i)(page|index)\s*[:\- ]*\d+", line):
            page_like_lines += 1

    if lines and page_like_lines / len(lines) >= 0.8:
        return True

    if len(cleaned) < 40 and digits > 0 and (digits / max(len(compact), 1)) > 0.6:
        return True

    return False


def filter_noise_from_text(text: str) -> str:
    """Discard page labels and index-number fragments while preserving actual notes."""
    if not text:
        return ""

    kept: list[str] = []
    for line in text.splitlines():
        cleaned = clean_text(line)
        if not cleaned or is_probably_page_noise(cleaned):
            continue
        kept.append(cleaned)

    return "\n\n".join(kept)


def truncate_text(text: str, max_chars: int) -> str:
    """Return the first max_chars characters for preview safely."""
    if max_chars <= 0:
        return ""
    if not text:
        return ""
    return text[:max_chars]


def ocr_is_available() -> bool:
    """Return True when the app has the OCR stack needed for scanned handwritten notes."""
    if importlib.util.find_spec("fitz") is None:
        return False
    if shutil.which("tesseract") and importlib.util.find_spec("pytesseract") is not None:
        return True
    return (
        importlib.util.find_spec("easyocr") is not None
        and importlib.util.find_spec("numpy") is not None
    )


def ocr_pdf_bytes(file_bytes: bytes, max_pages: int = 80) -> str:
    """Attempt OCR for scanned or handwritten PDFs when text extraction produces nothing."""
    if not file_bytes or not file_bytes.strip():
        return ""

    if shutil.which("tesseract") and importlib.util.find_spec("pytesseract") is not None:
        try:
            import fitz
            import pytesseract
            from PIL import Image

            doc = fitz.open(stream=file_bytes, filetype="pdf")
            try:
                chunks: list[str] = []
                for page_number in range(min(len(doc), max_pages)):
                    page = doc[page_number]
                    image = page.get_pixmap(matrix=fitz.Matrix(2, 2))
                    pil_image = Image.frombytes("RGB", [image.width, image.height], image.samples)
                    text = pytesseract.image_to_string(pil_image, config="--psm 6")
                    clean = clean_text(text)
                    if clean:
                        chunks.append(clean)
            finally:
                doc.close()
            combined = "\n\n".join(chunks)
            if combined.strip():
                return filter_noise_from_text(combined)
        except Exception:
            pass

    if importlib.util.find_spec("easyocr") is not None and importlib.util.find_spec("numpy") is not None:
        try:
            import easyocr
            import fitz
            import numpy as np
            from PIL import Image

            doc = fitz.open(stream=file_bytes, filetype="pdf")
            try:
                reader = easyocr.Reader(["en"], gpu=False)
                chunks = []
                for page_number in range(min(len(doc), max_pages)):
                    page = doc[page_number]
                    image = page.get_pixmap(matrix=fitz.Matrix(2, 2))
                    pil_image = Image.frombytes("RGB", [image.width, image.height], image.samples)
                    results = reader.readtext(np.asarray(pil_image), detail=0, paragraph=True)
                    if results:
                        chunks.append("\n".join(str(item).strip() for item in results if str(item).strip()))
            finally:
                doc.close()
            combined = "\n\n".join(chunks)
            if combined.strip():
                return filter_noise_from_text(combined)
        except Exception:
            pass

    return ""


@lru_cache(maxsize=8)
def _extract_pdf_text_cached(file_bytes: bytes, max_pages: int) -> str:
    """Read a PDF from bytes and reuse the result for identical uploads."""
    try:
        reader = PdfReader(io.BytesIO(file_bytes))
    except Exception as exc:  # pragma: no cover
        raise ValueError("The uploaded file is not a valid PDF or could not be read.") from exc

    if reader.is_encrypted:
        raise ValueError("This PDF is password-protected. Please remove the password and upload it again.")

    pages = list(reader.pages[:max_pages])
    if not pages:
        raise ValueError("The PDF is valid but contains no readable pages.")

    chunks: list[str] = []
    for page in pages:
        try:
            page_text = page.extract_text() or ""
        except Exception:
            page_text = ""
        cleaned_page_text = clean_text(page_text)
        if cleaned_page_text and not is_probably_page_noise(cleaned_page_text):
            chunks.append(cleaned_page_text)

    if not chunks:
        if not ocr_is_available():
            raise ValueError(
                "No readable text could be extracted from this PDF because it appears to be a scanned or handwritten image-based PDF. "
                "Install the project dependencies with 'pip install -r requirements.txt' and install Tesseract OCR on your machine, then upload a clearer scan."
            )
        ocr_text = ocr_pdf_bytes(file_bytes, max_pages=max_pages)
        if ocr_text.strip():
            return clean_text(filter_noise_from_text(ocr_text))
        raise ValueError(
            "No readable text could be extracted from this PDF. Scanned or handwritten notes may need a clearer upload or stronger OCR processing. "
            "Try a higher-quality scan and make sure Tesseract is installed."
        )

    return "\n\n".join(chunks)


def extract_pdf_text(file_obj: BinaryIO, max_pages: int = 80) -> str:
    """Read a PDF file and return cleaned text from the first pages, with OCR fallback for scanned notes."""
    try:
        file_obj.seek(0)
        file_bytes = file_obj.read()
    except Exception as exc:  # pragma: no cover
        raise ValueError("The uploaded file is not a valid PDF or could not be read.") from exc
    return _extract_pdf_text_cached(file_bytes, max_pages)


def build_study_prompt(question: str, document_text: str) -> str:
    """Build a prompt instructing the model to answer from the provided document."""
    document_excerpt = truncate_text(document_text, int(os.getenv("MAX_TEXT_CHARS", "200000")))
    return (
        "You are an AI study assistant. Use the uploaded document to answer the user question. "
        "Answer using only the information available in the document. If the answer is not present, "
        "say that the information is not in the provided material.\n\n"
        f"Document excerpt:\n{document_excerpt}\n\n"
        f"User question: {question}"
    )


def build_activity_prompt(activity: str, document_text: str, instructions: str = "", max_chars: int | None = None) -> str:
    """Build a prompt for a document-based study activity such as summary or flashcards."""
    limit = max_chars if max_chars is not None else int(os.getenv("MAX_TEXT_CHARS", "200000"))
    document_excerpt = truncate_text(document_text, limit)
    instruction_block = f"Additional instructions: {instructions}\n\n" if instructions.strip() else ""
    return (
        "You are an AI study assistant. Use only the uploaded document to complete this activity. "
        "Do not invent information that is not explicitly present in the material.\n\n"
        f"Activity: {activity}\n\n"
        f"{instruction_block}"
        f"Document excerpt:\n{document_excerpt}"
    )


def build_concept_prompt(concept: str, document_text: str, max_chars: int | None = None) -> str:
    """Build a prompt asking for a simple concept explanation using the document text."""
    limit = max_chars if max_chars is not None else int(os.getenv("MAX_TEXT_CHARS", "200000"))
    document_excerpt = truncate_text(document_text, limit)
    return (
        "Explain the following concept in a simple, student-friendly way. "
        "Use only the provided document material and say clearly if the concept is not described in the document.\n\n"
        f"Concept: {concept}\n\n"
        f"Document excerpt:\n{document_excerpt}"
    )


def build_exam_prompt(exam_type: str, document_text: str, question: str | None = None, max_chars: int | None = None) -> str:
    """Build a prompt for 5-mark or 10-mark exam answers based on the uploaded document."""
    limit = max_chars if max_chars is not None else int(os.getenv("MAX_TEXT_CHARS", "200000"))
    document_excerpt = truncate_text(document_text, limit)
    question_type = exam_type.lower().strip()
    if "10" in question_type or "ten" in question_type:
        instruction = "Write a well-structured 10-mark answer with a clear introduction, main points, and conclusion."
    else:
        instruction = "Write a clear 5-mark answer with 3 to 5 short, relevant points."

    question_text = question.strip() if question else "Describe the topic based on the document."
    return (
        "You are answering an academic exam question using the uploaded document only. "
        "Do not invent facts. Keep the answer direct and relevant.\n\n"
        f"Question type: {exam_type}\n"
        f"Question: {question_text}\n"
        f"Instruction: {instruction}\n\n"
        f"Document excerpt:\n{document_excerpt}"
    )


def generate_model_response(prompt: str, api_key: str | None = None, model_name: str | None = None) -> str:
    """Send a prompt to Gemini and return the model text."""
    resolved_key = api_key or get_api_key_from_settings()

    resolved_model = resolve_model_name(model_name)

    if not resolved_key:
        return "Missing API key: configure GEMINI_API_KEY in Streamlit secrets or a hosting environment variable before using the AI features."

    _load_gemini_sdk()
    if google_genai is None and genai is None:
        return "The Gemini SDK is not installed. Please install the project dependencies."

    for attempt in range(3):
        try:
            if google_genai is not None:
                client = google_genai.Client(api_key=resolved_key)
                response = client.models.generate_content(
                    model=resolved_model,
                    contents=prompt,
                )
                return getattr(response, "text", str(response))

            genai.configure(api_key=resolved_key)
            model = genai.GenerativeModel(resolved_model)
            response = model.generate_content(prompt)
            return getattr(response, "text", str(response))
        except Exception as exc:  # pragma: no cover - cloud/runtime safety
            message = str(exc).lower()

            if "quota" in message or "limit" in message:
                return "The API quota is exhausted or rate-limited for this key. Please try again later or increase your quota."

            if "invalid api key" in message or "api key" in message:
                return "The provided API key is invalid or expired. Update the key in Streamlit secrets or the hosting environment."

            if "unavailable" in message or "timeout" in message or "service" in message or "503" in message or "high demand" in message or "busy" in message:
                if attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
                return "Gemini is currently busy or unavailable. Please try again in a few moments."

            return f"The AI request failed while generating a response: {exc}. Please check your API configuration and try again."

    return "The Gemini service could not generate a response with the configured model. Please update the model name or API key."


def ask_gemini(question: str, document_text: str, api_key: str | None = None, model_name: str | None = None) -> str:
    """Query Gemini with the user's study material as context."""
    prompt = build_study_prompt(question, document_text)
    return generate_model_response(prompt, api_key=api_key, model_name=model_name)


def generate_summary(document_text: str, api_key: str | None = None, model_name: str | None = None) -> str:
    """Create a concise study summary from the uploaded document."""
    prompt = build_activity_prompt(
        "summary",
        document_text,
        "Return a concise summary in 5 bullet points or 4-6 sentences. Focus on the main ideas, key terms, and conclusions.",
    )
    return generate_model_response(prompt, api_key=api_key, model_name=model_name)


def generate_flashcards(document_text: str, api_key: str | None = None, model_name: str | None = None) -> str:
    """Create flashcards from the uploaded document."""
    prompt = build_activity_prompt(
        "flashcards",
        document_text,
        "Return 8-12 flashcards in this format exactly: Q: ... A: ... Use one question and answer per line.",
    )
    return generate_model_response(prompt, api_key=api_key, model_name=model_name)


def generate_quiz(document_text: str, api_key: str | None = None, model_name: str | None = None) -> str:
    """Create quiz questions from the uploaded document."""
    prompt = build_activity_prompt(
        "quiz",
        document_text,
        "Generate 5 multiple-choice questions with 4 options each and clearly mark the correct answer.",
    )
    return generate_model_response(prompt, api_key=api_key, model_name=model_name)


def explain_concept(concept: str, document_text: str, api_key: str | None = None, model_name: str | None = None) -> str:
    """Explain a concept in simple language using the document as context."""
    prompt = build_concept_prompt(concept, document_text)
    return generate_model_response(prompt, api_key=api_key, model_name=model_name)


def generate_exam_answer(
    exam_type: str,
    document_text: str,
    api_key: str | None = None,
    model_name: str | None = None,
    question: str | None = None,
) -> str:
    """Generate a 5-mark or 10-mark answer using the uploaded document."""
    prompt = build_exam_prompt(exam_type, document_text, question=question)
    return generate_model_response(prompt, api_key=api_key, model_name=model_name)
