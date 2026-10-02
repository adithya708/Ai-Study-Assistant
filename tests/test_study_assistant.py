from io import BytesIO
import subprocess
import sys
from pathlib import Path

from PIL import Image
from pypdf import PdfWriter
import pytest

import study_assistant
from study_assistant import (
    build_activity_prompt,
    build_concept_prompt,
    build_exam_prompt,
    clean_text,
    extract_image_text,
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


def test_build_study_prompt_includes_documents_larger_than_previous_limit(monkeypatch) -> None:
    monkeypatch.delenv("MAX_TEXT_CHARS", raising=False)
    monkeypatch.delenv("MAX_MODEL_CONTEXT_CHARS", raising=False)
    document = "x" * 70000 + "DOCUMENT END"
    prompt = study_assistant.build_study_prompt("Question?", document)

    assert "DOCUMENT END" in prompt
    assert "Question?" in prompt


def test_stream_model_response_yields_chunks_as_received(monkeypatch) -> None:
    response = study_assistant.generate_model_response_stream("hello", api_key="test-key")
    monkeypatch.setattr(
        study_assistant,
        "_nvidia_chat_completion_stream",
        lambda *_args, **_kwargs: iter(["first ", "second"]),
    )

    assert list(response) == ["first ", "second"]


def test_validate_pdf_bytes_rejects_empty_or_invalid_files() -> None:
    assert validate_pdf_bytes(b"") == "empty"
    assert validate_pdf_bytes(b"not a pdf") == "invalid"


def test_build_concept_and_exam_prompts_include_requirements() -> None:
    concept_prompt = build_concept_prompt("photosynthesis", "Photosynthesis converts light into energy.")
    exam_prompt = build_exam_prompt("5-mark", "This is the document text.")
    assert "photosynthesis" in concept_prompt.lower()
    assert "5-mark" in exam_prompt.lower()
    assert "document" in exam_prompt.lower()


def test_resolve_model_name_uses_nvidia_model(monkeypatch) -> None:
    monkeypatch.delenv("NVIDIA_MODEL", raising=False)
    assert resolve_model_name("meta/custom-model") == "meta/custom-model"
    assert resolve_model_name(None) == "nvidia/nemotron-3.5-lightning-30b-a3b"


def test_default_output_token_budget_supports_complete_study_materials() -> None:
    assert study_assistant.DEFAULT_MAX_OUTPUT_TOKENS == 2048


def test_api_key_lookup_uses_nvidia_key_not_gemini_key(monkeypatch) -> None:
    monkeypatch.setenv("NVIDIA_API_KEY", "nvidia-test-key")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-test-key")

    assert study_assistant.get_api_key_from_settings() == "nvidia-test-key"


def test_generate_model_response_uses_nvidia_chat_completions(monkeypatch) -> None:
    import requests

    captured = {}

    class FakeResponse:
        status_code = 200
        ok = True

        @staticmethod
        def iter_lines(chunk_size=512, decode_unicode=True):
            assert chunk_size == 512
            return [
                'data: {"choices":[{"delta":{"content":"NVIDIA "}}]}',
                'data: {"choices":[{"delta":{"content":"response"}}]}',
                "data: [DONE]",
            ]

        @staticmethod
        def close():
            return None

    def fake_post(url, headers, json, timeout, **kwargs):
        captured.update(url=url, headers=headers, payload=json, timeout=timeout, **kwargs)
        return FakeResponse()

    monkeypatch.setattr(requests, "post", fake_post)

    result = study_assistant.generate_model_response("Say hello", api_key="test-key")

    assert result == "NVIDIA response"
    assert captured["url"] == study_assistant.DEFAULT_NVIDIA_API_URL
    assert captured["headers"]["Authorization"] == "Bearer test-key"
    assert captured["payload"]["model"] == "nvidia/nemotron-3.5-lightning-30b-a3b"
    assert captured["payload"]["messages"] == [{"role": "user", "content": "Say hello"}]
    assert captured["payload"]["stream"] is True
    assert captured["payload"]["max_tokens"] == study_assistant.DEFAULT_MAX_OUTPUT_TOKENS
    assert captured["stream"] is True


def test_nvidia_stream_retries_once_if_connection_fails_before_answer(monkeypatch) -> None:
    import requests

    class InterruptedResponse:
        ok = True
        status_code = 200

        @staticmethod
        def iter_lines(chunk_size, decode_unicode):
            raise requests.ConnectionError("connection reset")

        @staticmethod
        def close():
            return None

    class SuccessfulResponse:
        ok = True
        status_code = 200

        @staticmethod
        def iter_lines(chunk_size, decode_unicode):
            return [
                'data: {"choices":[{"delta":{"content":"Recovered answer"}}]}',
                "data: [DONE]",
            ]

        @staticmethod
        def close():
            return None

    responses = [InterruptedResponse(), SuccessfulResponse()]
    calls = []

    def fake_post(*args, **kwargs):
        calls.append((args, kwargs))
        return responses.pop(0)

    monkeypatch.setattr(requests, "post", fake_post)

    chunks = list(
        study_assistant._nvidia_chat_completion_stream(
            [{"role": "user", "content": "hello"}],
            "test-key",
            "nvidia/test-model",
        )
    )

    assert chunks == ["Recovered answer"]
    assert len(calls) == 2


def test_nvidia_stream_does_not_replay_after_partial_answer(monkeypatch) -> None:
    import requests

    class PartialResponse:
        ok = True
        status_code = 200

        @staticmethod
        def iter_lines(chunk_size, decode_unicode):
            yield 'data: {"choices":[{"delta":{"content":"Partial"}}]}'
            raise requests.ConnectionError("connection reset")

        @staticmethod
        def close():
            return None

    calls = []

    def fake_post(*args, **kwargs):
        calls.append((args, kwargs))
        return PartialResponse()

    monkeypatch.setattr(requests, "post", fake_post)

    chunks = list(
        study_assistant.generate_model_response_stream(
            "hello",
            api_key="test-key",
            model_name="nvidia/test-model",
        )
    )

    assert chunks[0] == "Partial"
    assert "partial answer" in chunks[1]
    assert len(calls) == 1


def test_ocr_dependencies_are_not_imported_during_normal_startup() -> None:
    script = (
        "import sys, study_assistant; "
        "assert not any(name in sys.modules for name in "
        "('easyocr', 'fitz', 'numpy', 'pytesseract', 'pdf2image', 'requests'))"
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

    monkeypatch.setattr(study_assistant, "ocr_is_available", lambda: True)
    monkeypatch.setattr(study_assistant, "ocr_pdf_bytes", lambda file_bytes, max_pages=80: "Handwritten note transcription")
    result = extract_pdf_text(pdf_buffer, max_pages=1)
    assert "Handwritten note transcription" in result


def test_extract_image_text_returns_recognized_photo_text(monkeypatch) -> None:
    image_buffer = BytesIO()
    Image.new("RGB", (20, 20), color="white").save(image_buffer, format="PNG")
    image_buffer.seek(0)
    monkeypatch.setattr(study_assistant, "_recognize_image", lambda _image: "Photo notes\n\nfrom class")
    study_assistant._extract_image_text_cached.cache_clear()

    result = extract_image_text(image_buffer)

    assert result == "Photo notes\n\nfrom class"


def test_extract_image_text_uses_nvidia_when_local_ocr_fails(monkeypatch) -> None:
    image_buffer = BytesIO()
    Image.new("RGB", (30, 30), color="white").save(image_buffer, format="PNG")
    image_buffer.seek(0)
    fallback_calls = []

    def fail_local_ocr(_image):
        raise ValueError("EasyOCR model download timed out")

    monkeypatch.setattr(
        study_assistant,
        "_recognize_image",
        fail_local_ocr,
    )
    monkeypatch.setattr(
        study_assistant,
        "_extract_image_text_with_nvidia",
        lambda image: fallback_calls.append(image.size) or "Recovered photo text",
    )

    result = extract_image_text(image_buffer)

    assert result == "Recovered photo text"
    assert len(fallback_calls) == 1


def test_nvidia_image_fallback_requires_api_key(monkeypatch) -> None:
    monkeypatch.setattr(study_assistant, "get_api_key_from_settings", lambda: None)

    with pytest.raises(ValueError, match="NVIDIA_API_KEY"):
        study_assistant._extract_image_text_with_nvidia(Image.new("RGB", (20, 20)))


def test_nvidia_vision_fallback_sends_image_to_openai_compatible_api(monkeypatch) -> None:
    import requests

    captured = {}

    class FakeResponse:
        status_code = 200
        ok = True

        @staticmethod
        def json():
            return {"choices": [{"message": {"content": "Transcribed NVIDIA notes"}}]}

    def fake_post(url, headers, json, timeout):
        captured.update(url=url, headers=headers, payload=json, timeout=timeout)
        return FakeResponse()

    monkeypatch.setattr(requests, "post", fake_post)
    monkeypatch.setattr(study_assistant, "get_api_key_from_settings", lambda: "nvidia-test-key")

    result = study_assistant._extract_image_text_with_nvidia(Image.new("RGB", (20, 20)))

    assert result == "Transcribed NVIDIA notes"
    assert captured["payload"]["model"] == study_assistant.DEFAULT_NVIDIA_VISION_MODEL
    content = captured["payload"]["messages"][0]["content"]
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_easyocr_reader_does_not_download_models_automatically(monkeypatch) -> None:
    import sys
    from types import SimpleNamespace

    calls = []

    class FakeReader:
        def __init__(self, languages, gpu, download_enabled):
            calls.append((languages, gpu, download_enabled))

    monkeypatch.setitem(sys.modules, "easyocr", SimpleNamespace(Reader=FakeReader))
    study_assistant._get_easyocr_reader.cache_clear()

    study_assistant._get_easyocr_reader()

    assert calls == [(["en"], False, False)]


def test_prepare_ocr_image_enhances_and_scales_small_photo() -> None:
    from PIL import Image

    prepared = study_assistant._prepare_ocr_image(Image.new("RGB", (400, 300), color=(180, 180, 180)))

    assert prepared.mode == "L"
    assert prepared.size == (800, 600)


def test_extract_image_text_rejects_invalid_image() -> None:
    with pytest.raises(ValueError, match="invalid"):
        extract_image_text(BytesIO(b"not an image"))


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


def test_nvidia_api_error_messages_do_not_expose_credentials(monkeypatch) -> None:
    import requests

    class FakeResponse:
        status_code = 401
        ok = False

        @staticmethod
        def close():
            return None

    monkeypatch.setattr(requests, "post", lambda *_args, **_kwargs: FakeResponse())

    with pytest.raises(ValueError, match="NVIDIA rejected") as exc_info:
        study_assistant._nvidia_chat_completion(
            [{"role": "user", "content": "hello"}],
            "sensitive-test-key",
            "meta/test-model",
        )

    assert "sensitive-test-key" not in str(exc_info.value)


def test_generate_model_response_reports_nvidia_auth_errors(monkeypatch) -> None:
    import requests

    class FakeResponse:
        status_code = 401
        ok = False

        @staticmethod
        def close():
            return None

    monkeypatch.setattr(requests, "post", lambda *_args, **_kwargs: FakeResponse())

    result = study_assistant.generate_model_response("Say hello", api_key="test-key")

    assert "NVIDIA rejected" in result


def test_generate_model_response_explains_retired_nvidia_model(monkeypatch) -> None:
    import requests

    class FakeResponse:
        status_code = 410
        ok = False

        @staticmethod
        def close():
            return None

    monkeypatch.setattr(requests, "post", lambda *_args, **_kwargs: FakeResponse())

    result = study_assistant.generate_model_response(
        "Say hello",
        api_key="test-key",
        model_name="retired/model",
    )

    assert "retired/model" in result
    assert "retired" in result
    assert "NVIDIA_MODEL" in result
