import base64
import io
import importlib.util
import json
import os
import re
import shutil
from functools import lru_cache
from pathlib import Path
from typing import BinaryIO, Iterator

from dotenv import load_dotenv
from pypdf import PdfReader


load_dotenv()


DEFAULT_NVIDIA_MODEL = "nvidia/nemotron-3.5-lightning-30b-a3b"
DEFAULT_NVIDIA_VISION_MODEL = "meta/llama-3.2-11b-vision-instruct"
DEFAULT_NVIDIA_API_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
DEFAULT_MAX_OUTPUT_TOKENS = 2048
DEFAULT_MAX_MODEL_CONTEXT_CHARS = 200000


def get_model_context_limit() -> int:
    configured = int(os.getenv("MAX_TEXT_CHARS", "200000"))
    performance_limit = int(os.getenv("MAX_MODEL_CONTEXT_CHARS", str(DEFAULT_MAX_MODEL_CONTEXT_CHARS)))
    return min(configured, performance_limit)


def resolve_model_name(model_name: str | None) -> str:
<<<<<<< HEAD
    """Return the configured NVIDIA NIM model name."""
    return (model_name or os.getenv("NVIDIA_MODEL") or DEFAULT_NVIDIA_MODEL).strip()
=======
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
>>>>>>> dd187cf11852d1c6c01330b0365291867ae37c32


def get_api_key_from_settings() -> str | None:
    """Read the NVIDIA API key from secrets or the environment."""
    for key_name in ("NVIDIA_API_KEY", "NGC_API_KEY"):
        value = os.getenv(key_name)
        if value and value.strip():
            return value.strip()

    try:
        import streamlit as st  # pragma: no cover

        for key_name in ("NVIDIA_API_KEY", "NGC_API_KEY"):
            if "secrets" in dir(st) and key_name in st.secrets:
                value = st.secrets[key_name]
                if value:
                    return str(value).strip()
    except Exception:  # pragma: no cover
        pass

    return None


def _nvidia_http_error(status_code: int, model_name: str) -> str:
    if status_code in (401, 403):
        return "NVIDIA rejected the API key or its permissions. Check NVIDIA_API_KEY and your NVIDIA API access."
    if status_code == 404:
        return f"NVIDIA model '{model_name}' or endpoint was not found. Check NVIDIA_MODEL."
    if status_code == 410:
        return (
            f"NVIDIA model '{model_name}' has been retired or is no longer available. "
            "Update NVIDIA_MODEL to an active model in NVIDIA NIM."
        )
    if status_code == 429:
        return "NVIDIA API quota is exhausted or rate-limited. Check your NVIDIA API account and retry later."
    if status_code >= 500:
        return "The NVIDIA AI service is temporarily unavailable. Please retry in a few moments."
    return f"NVIDIA API request failed with HTTP {status_code}. Check the model and API configuration."


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
    return image_ocr_is_available()


def image_ocr_is_available() -> bool:
    """Return True when an OCR engine is available for uploaded photos."""
    if shutil.which("tesseract") and importlib.util.find_spec("pytesseract") is not None:
        return True
    return (
        importlib.util.find_spec("easyocr") is not None
        and importlib.util.find_spec("numpy") is not None
    )


def _nvidia_chat_completion(
    messages: list[dict],
    api_key: str,
    model_name: str,
    *,
    timeout: int = 60,
) -> str:
    import requests

    endpoint = os.getenv("NVIDIA_API_BASE_URL", DEFAULT_NVIDIA_API_URL).rstrip("/")
    if not endpoint.endswith("/chat/completions"):
        endpoint = f"{endpoint}/chat/completions"

    try:
        response = requests.post(
            endpoint,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model_name,
                "messages": messages,
                "temperature": 0.2,
                "max_tokens": int(os.getenv("MAX_OUTPUT_TOKENS", str(DEFAULT_MAX_OUTPUT_TOKENS))),
            },
            timeout=timeout,
        )
    except requests.Timeout:
        raise ValueError("The NVIDIA API request timed out. Please retry.") from None
    except requests.RequestException:
        raise ValueError("Could not connect to the NVIDIA API. Check your network and API endpoint.") from None

    if not response.ok:
        raise ValueError(_nvidia_http_error(response.status_code, model_name))

    try:
        result = response.json()["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError, ValueError):
        raise ValueError("NVIDIA API returned an unexpected response. Check that the selected model supports chat completions.") from None
    if isinstance(result, list):
        result = "\n".join(part.get("text", "") for part in result if isinstance(part, dict))
    return str(result).strip()


def _nvidia_chat_completion_stream(
    messages: list[dict],
    api_key: str,
    model_name: str,
    *,
    timeout: int = 60,
) -> Iterator[str]:
    import requests

    endpoint = os.getenv("NVIDIA_API_BASE_URL", DEFAULT_NVIDIA_API_URL).rstrip("/")
    if not endpoint.endswith("/chat/completions"):
        endpoint = f"{endpoint}/chat/completions"

    try:
        response = requests.post(
            endpoint,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model_name,
                "messages": messages,
                "temperature": 0.2,
                "max_tokens": int(os.getenv("MAX_OUTPUT_TOKENS", str(DEFAULT_MAX_OUTPUT_TOKENS))),
                "stream": True,
            },
            timeout=(10, timeout),
            stream=True,
        )
    except requests.Timeout:
        raise ValueError("The NVIDIA API request timed out. Please retry.") from None
    except requests.RequestException:
        raise ValueError("Could not connect to the NVIDIA API. Check your network and API endpoint.") from None

    try:
        if not response.ok:
            raise ValueError(_nvidia_http_error(response.status_code, model_name))

        for line in response.iter_lines(chunk_size=1, decode_unicode=True):
            if not line:
                continue
            if isinstance(line, bytes):
                line = line.decode("utf-8")
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                event = json.loads(data)
                delta = event["choices"][0].get("delta", {}).get("content")
            except (json.JSONDecodeError, KeyError, IndexError, TypeError):
                continue
            if isinstance(delta, str) and delta:
                yield delta
            elif isinstance(delta, list):
                for part in delta:
                    if isinstance(part, dict) and part.get("text"):
                        yield part["text"]
    except requests.Timeout:
        raise ValueError("The NVIDIA API response timed out. Please retry.") from None
    except requests.RequestException:
        raise ValueError("The NVIDIA API stream was interrupted. Please retry.") from None
    finally:
        response.close()


@lru_cache(maxsize=1)
def _get_easyocr_reader():
    import easyocr

    return easyocr.Reader(["en"], gpu=False, download_enabled=False)


def _easyocr_models_available() -> bool:
    model_dir = Path.home() / ".EasyOCR" / "model"
    return (model_dir / "craft_mlt_25k.pth").is_file() and (model_dir / "english_g2.pth").is_file()


def _prepare_ocr_image(image):
    """Normalize contrast and scale text to improve local OCR reliability."""
    from PIL import Image, ImageEnhance, ImageOps

    image = ImageOps.autocontrast(ImageOps.grayscale(image), cutoff=1)
    longest_edge = max(image.size)
    if longest_edge < 1600:
        scale = min(2.0, 1600 / longest_edge)
    elif longest_edge > 3000:
        scale = 3000 / longest_edge
    else:
        scale = 1
    if scale > 1 or longest_edge > 3000:
        size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
        image = image.resize(size, Image.Resampling.LANCZOS)
    image = ImageEnhance.Contrast(image).enhance(1.5)
    return ImageEnhance.Sharpness(image).enhance(1.4)


def _recognize_image(image) -> str:
    """Extract text from a Pillow image using the available local OCR engine."""
    failures: list[str] = []
    if shutil.which("tesseract") and importlib.util.find_spec("pytesseract") is not None:
        try:
            import pytesseract

            text = clean_text(pytesseract.image_to_string(image, config="--psm 6"))
            if text:
                return text
        except Exception as exc:
            failures.append(f"Tesseract OCR failed: {exc}")

    easyocr_installed = importlib.util.find_spec("easyocr") is not None
    numpy_installed = importlib.util.find_spec("numpy") is not None
    if easyocr_installed and numpy_installed and _easyocr_models_available():
        try:
            import numpy as np

            results = _get_easyocr_reader().readtext(np.asarray(image), detail=0, paragraph=True)
            text = clean_text("\n".join(str(item).strip() for item in results if str(item).strip()))
            if text:
                return text
        except Exception as exc:
            failures.append(f"EasyOCR failed: {exc}")
    elif easyocr_installed and numpy_installed:
        failures.append("EasyOCR models are not cached locally.")
    elif easyocr_installed:
        failures.append("NumPy is not installed for EasyOCR.")

    if failures:
        raise ValueError("Could not read text from this photo. " + " ".join(failures)) from None
    raise ValueError("Photo text recognition is unavailable locally.")


def _extract_image_text_with_nvidia(image) -> str:
    """Use NVIDIA vision only after local OCR fails."""
    api_key = get_api_key_from_settings()
    if not api_key:
        raise ValueError("Configure NVIDIA_API_KEY to use NVIDIA photo OCR fallback.")

    image_buffer = io.BytesIO()
    image.convert("RGB").save(image_buffer, format="JPEG", quality=90, optimize=True)
    image_data = base64.b64encode(image_buffer.getvalue()).decode("ascii")
    prompt = (
        "Transcribe all clearly visible text in this study-notes photo. "
        "Preserve the original wording and line breaks. Do not summarize or add text. "
        "Return only the transcription, or an empty response if there is no readable text."
    )
    model_name = os.getenv("NVIDIA_VISION_MODEL", DEFAULT_NVIDIA_VISION_MODEL).strip()
    return _nvidia_chat_completion(
        [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_data}"}},
                ],
            }
        ],
        api_key,
        model_name,
    )


@lru_cache(maxsize=8)
def _extract_image_text_cached(file_bytes: bytes) -> str:
    try:
        from PIL import Image, ImageOps, UnidentifiedImageError

        with Image.open(io.BytesIO(file_bytes)) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
        image = _prepare_ocr_image(image)
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ValueError("The uploaded photo is invalid or uses an unsupported image format.") from exc

    local_error = ""
    try:
        text = filter_noise_from_text(_recognize_image(image))
    except ValueError as exc:
        local_error = str(exc)
        text = ""

    if not text:
        try:
            text = filter_noise_from_text(_extract_image_text_with_nvidia(image))
        except ValueError as exc:
            if local_error:
                raise ValueError(f"{local_error} NVIDIA fallback: {exc}") from None
            raise ValueError(f"No readable text was found locally. NVIDIA fallback: {exc}") from None
    if not text:
        if local_error:
            raise ValueError(f"{local_error} NVIDIA fallback found no readable text.") from None
        raise ValueError("No readable text was found in this photo. Try a clearer, well-lit image.")
    return text


def extract_image_text(file_obj: BinaryIO) -> str:
    """Read text from an uploaded photo and cache extraction for identical image data."""
    try:
        file_obj.seek(0)
        file_bytes = file_obj.read()
    except Exception as exc:
        raise ValueError("The uploaded photo could not be read.") from exc
    if not file_bytes:
        raise ValueError("The uploaded photo is empty.")
    return _extract_image_text_cached(file_bytes)


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
    document_excerpt = truncate_text(document_text, get_model_context_limit())
    return (
        "You are an AI study assistant. Use the uploaded document to answer the user question. "
        "Answer using only the information available in the document. If the answer is not present, "
        "say that the information is not in the provided material.\n\n"
        f"Document excerpt:\n{document_excerpt}\n\n"
        f"User question: {question}"
    )


def build_activity_prompt(activity: str, document_text: str, instructions: str = "", max_chars: int | None = None) -> str:
    """Build a prompt for a document-based study activity such as summary or flashcards."""
    limit = max_chars if max_chars is not None else get_model_context_limit()
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
    limit = max_chars if max_chars is not None else get_model_context_limit()
    document_excerpt = truncate_text(document_text, limit)
    return (
        "Explain the following concept in a simple, student-friendly way. "
        "Use only the provided document material and say clearly if the concept is not described in the document.\n\n"
        f"Concept: {concept}\n\n"
        f"Document excerpt:\n{document_excerpt}"
    )


def build_exam_prompt(exam_type: str, document_text: str, question: str | None = None, max_chars: int | None = None) -> str:
    """Build a prompt for 5-mark or 10-mark exam answers based on the uploaded document."""
    limit = max_chars if max_chars is not None else get_model_context_limit()
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
    """Return the complete response from NVIDIA NIM."""
    return "".join(generate_model_response_stream(prompt, api_key=api_key, model_name=model_name))


def generate_model_response_stream(
    prompt: str,
    api_key: str | None = None,
    model_name: str | None = None,
) -> Iterator[str]:
    """Yield response chunks from NVIDIA NIM as they arrive."""
    resolved_key = api_key or get_api_key_from_settings()
<<<<<<< HEAD
=======

    resolved_model = resolve_model_name(model_name)

>>>>>>> dd187cf11852d1c6c01330b0365291867ae37c32
    if not resolved_key:
        yield "Missing NVIDIA API key: configure NVIDIA_API_KEY in Streamlit secrets or a hosting environment variable."
        return

<<<<<<< HEAD
    selected_model = resolve_model_name(model_name)
    try:
        yield from _nvidia_chat_completion_stream(
            [{"role": "user", "content": prompt}],
            resolved_key,
            selected_model,
        )
    except ValueError as exc:
        yield str(exc)
=======
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
>>>>>>> dd187cf11852d1c6c01330b0365291867ae37c32


def stream_ask_ai(
    question: str,
    document_text: str,
    api_key: str | None = None,
    model_name: str | None = None,
) -> Iterator[str]:
    return generate_model_response_stream(
        build_study_prompt(question, document_text),
        api_key=api_key,
        model_name=model_name,
    )


def stream_summary(document_text: str, api_key: str | None = None, model_name: str | None = None) -> Iterator[str]:
    prompt = build_activity_prompt(
        "summary",
        document_text,
        "Return a concise summary in 5 bullet points or 4-6 sentences. Focus on the main ideas, key terms, and conclusions.",
    )
    return generate_model_response_stream(prompt, api_key=api_key, model_name=model_name)


def stream_flashcards(document_text: str, api_key: str | None = None, model_name: str | None = None) -> Iterator[str]:
    prompt = build_activity_prompt(
        "flashcards",
        document_text,
        "Return 8-12 flashcards in this format exactly: Q: ... A: ... Use one question and answer per line.",
    )
    return generate_model_response_stream(prompt, api_key=api_key, model_name=model_name)


def stream_quiz(document_text: str, api_key: str | None = None, model_name: str | None = None) -> Iterator[str]:
    prompt = build_activity_prompt(
        "quiz",
        document_text,
        "Generate 5 multiple-choice questions with 4 options each and clearly mark the correct answer.",
    )
    return generate_model_response_stream(prompt, api_key=api_key, model_name=model_name)


def stream_concept_explanation(
    concept: str,
    document_text: str,
    api_key: str | None = None,
    model_name: str | None = None,
) -> Iterator[str]:
    return generate_model_response_stream(
        build_concept_prompt(concept, document_text),
        api_key=api_key,
        model_name=model_name,
    )


def stream_exam_answer(
    exam_type: str,
    document_text: str,
    api_key: str | None = None,
    model_name: str | None = None,
    question: str | None = None,
) -> Iterator[str]:
    return generate_model_response_stream(
        build_exam_prompt(exam_type, document_text, question=question),
        api_key=api_key,
        model_name=model_name,
    )


def ask_ai(question: str, document_text: str, api_key: str | None = None, model_name: str | None = None) -> str:
    """Query the configured NVIDIA model with the user's study material as context."""
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
