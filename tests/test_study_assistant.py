from io import BytesIO
import subprocess
import sys
from pathlib import Path

from pypdf import PdfWriter

import study_assistant
from study_assistant import (
    build_activity_prompt,
    build_concept_prompt,
    build_exam_prompt,
    clean_text,
    extract_pdf_text,
    resolve_model_name,
    validate_pdf_bytes,
    truncate_text,
)


def test_clean_text_collapses_whitespace() -> None:
    sample = "Hello\n   world\t again\r\n  final\n"
    assert clean_text(sample) == "Hello\nworld again\nfinal"


def test_truncate_text_respects_limit() -> None:
    sample = "This is a long study note with many words."
    assert truncate_text(sample, 12) == "This is a lo"


def test_build_activity_prompt_contains_activity_and_document() -> None:
    prompt = build_activity_prompt("summary", "This is a study note.", "Keep it brief.")
    assert "summary" in prompt.lower()
    assert "This is a study note." in prompt
    assert "Keep it brief." in prompt


def test_validate_pdf_bytes_rejects_empty_or_invalid_files() -> None:
    assert validate_pdf_bytes(b"") == "empty"
    assert validate_pdf_bytes(b"not a pdf") == "invalid"


def test_build_concept_and_exam_prompts_include_requirements() -> None:
    concept_prompt = build_concept_prompt("photosynthesis", "Photosynthesis converts light into energy.")
    exam_prompt = build_exam_prompt("5-mark", "This is the document text.")
    assert "photosynthesis" in concept_prompt.lower()
    assert "5-mark" in exam_prompt.lower()
    assert "document" in exam_prompt.lower()


def test_resolve_model_name_uses_supported_gemini_model() -> None:
    assert resolve_model_name("gemini-1.5-flash") == "gemini-3.8-flash"
    assert resolve_model_name("gemini-2.5-flash") == "gemini-3.8-flash"
    assert resolve_model_name(None).startswith("gemini-")


def test_ocr_dependencies_are_not_imported_during_normal_startup() -> None:
    script = (
        "import sys, study_assistant; "
        "assert not any(name in sys.modules for name in "
        "('easyocr', 'fitz', 'numpy', 'pytesseract', 'pdf2image', "
        "'google.genai', 'google.generativeai'))"
    )
    subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[1],
        check=True,
    )


def test_extract_pdf_text_uses_ocr_fallback_for_textless_pdf(monkeypatch) -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    pdf_buffer = BytesIO()
    writer.write(pdf_buffer)
    pdf_buffer.seek(0)

    monkeypatch.setattr(study_assistant, "ocr_pdf_bytes", lambda file_bytes, max_pages=80: "Handwritten note transcription")
    result = extract_pdf_text(pdf_buffer, max_pages=1)
    assert "Handwritten note transcription" in result


def test_extract_pdf_text_ignores_page_number_noise_before_ocr(monkeypatch) -> None:
    class FakePage:
        def extract_text(self):
            return "1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23"

    class FakeReader:
        is_encrypted = False
        pages = [FakePage()]

    monkeypatch.setattr(study_assistant, "PdfReader", lambda _buffer: FakeReader())
    monkeypatch.setattr(study_assistant, "ocr_is_available", lambda: True)
    monkeypatch.setattr(study_assistant, "ocr_pdf_bytes", lambda file_bytes, max_pages=80: "Actual handwritten title and notes")

    result = extract_pdf_text(BytesIO(b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF"), max_pages=1)
    assert "Actual handwritten title and notes" in result


def test_generate_model_response_retries_on_transient_unavailable(monkeypatch) -> None:
    class FakeResponse:
        text = "Retry succeeded"

    call_count = {"value": 0}

    class FakeClient:
        def __init__(self, api_key):
            self.api_key = api_key

        @property
        def models(self):
            return self

        def generate_content(self, model, contents):
            call_count["value"] += 1
            if call_count["value"] < 3:
                raise Exception("503 UNAVAILABLE: high demand. Please try again later.")
            return FakeResponse()

    monkeypatch.setattr(study_assistant, "google_genai", type("FakeGoogleGenAI", (), {"Client": FakeClient}))
    monkeypatch.setattr(study_assistant.time, "sleep", lambda _seconds: None)

    result = study_assistant.generate_model_response("Say hello")
    assert result == "Retry succeeded"
    assert call_count["value"] == 3
