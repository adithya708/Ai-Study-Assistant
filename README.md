# AI Study Assistant

A Streamlit-based AI study assistant that uploads PDF documents or photos, extracts text, and answers study questions using NVIDIA NIM APIs. The application is designed to run locally and also to be deployed on Streamlit Community Cloud without code changes.

## 1. Hosting platform and reason for choosing it

Platform: Streamlit Community Cloud

Reason:
- Native support for Python + Streamlit apps
- Free or low-cost hosting path for small projects
- Easy GitHub integration
- Supports secrets management for API keys
- Public HTTPS URL generation for deployed apps

## 2. Prerequisites and configuration

Before deployment, ensure you have:
- Python 3.11+
- A GitHub account
- A Streamlit Community Cloud account
- An NVIDIA API key from NVIDIA's developer platform
- A PDF document or study notes for testing

Install local dependencies:

```bash
pip install -r requirements.txt
```

Create a local environment file:

```bash
copy .env.example .env
```

Then set your key in the local environment or in secrets:

```env
NVIDIA_API_KEY=your_nvidia_api_key_here
NVIDIA_MODEL=nvidia/nemotron-3.5-lightning-30b-a3b
NVIDIA_VISION_MODEL=meta/llama-3.2-11b-vision-instruct
NVIDIA_API_BASE_URL=https://integrate.api.nvidia.com/v1
```

Do not commit real API keys to GitHub. Use secrets in production.

## 3. GitHub repository setup

1. Create a new GitHub repository.
2. Push the project folder to GitHub.
3. Ensure these files are included:
   - `requirements.txt`
   - `app.py`
   - `study_assistant.py`
   - `.env.example`
   - `README.md`
   - `.streamlit/secrets.toml.example`

## 4. Cloud deployment steps

### Streamlit Community Cloud

1. Sign in to Streamlit Community Cloud.
2. Click "New app".
3. Select the GitHub repository.
4. Choose the branch and set the main file to `app.py`.
5. Click deploy.
6. Wait for the app to build.
7. Once deployed, copy the public URL.

### Platform environment variables / secrets

For Streamlit Community Cloud, use the app secrets manager:

```toml
# .streamlit/secrets.toml
NVIDIA_API_KEY = "your_nvidia_api_key_here"
NVIDIA_MODEL = "nvidia/nemotron-3.5-lightning-30b-a3b"
NVIDIA_VISION_MODEL = "meta/llama-3.2-11b-vision-instruct"
NVIDIA_API_BASE_URL = "https://integrate.api.nvidia.com/v1"
```

Do not put the value in source code, notebooks, logs, or UI output.

## 5. Local execution

```bash
streamlit run app.py
```

## 6. Features

- Upload PDF files or photos of notes (JPG, JPEG, PNG, WebP, BMP, and TIFF)
- Extract readable text from PDFs and use local OCR to read text from photos, with contrast and resolution normalization before recognition
- EasyOCR uses only cached local models to avoid hanging on first-use downloads; if local photo OCR is unavailable or fails, the configured NVIDIA vision model is used. This sends the photo to NVIDIA and may incur API usage
- Ask questions about the uploaded content
- Stream AI answers as they are generated. By default, the AI receives up to 200,000 characters of document context and can generate up to 2,048 tokens per response for more complete study materials. Longer responses may take more time. Adjust `MAX_MODEL_CONTEXT_CHARS` and `MAX_OUTPUT_TOKENS` if needed.
- Generate a concise study summary
- Build flashcards
- Generate a quiz
- NVIDIA requests use the OpenAI-compatible NIM chat completions API; extracted text is cached to avoid repeating OCR or PDF parsing on reruns

## 7. Health and error handling

The app shows clear messages when:
- The API key is missing
- The NVIDIA API quota is exhausted
- The AI service is unavailable or rate-limited
- Local photo OCR fails and NVIDIA Vision fallback is unavailable
- The uploaded PDF or photo has no readable text

These messages are shown in the UI instead of exposing raw API errors or secrets.

## 8. Testing performed

Local verification completed:
- App imports successfully
- Python tests pass for helper logic
- PDF-related helpers work as expected

Deployed verification is pending actual hosting credentials and public approval. This environment does not provide a live Streamlit Community Cloud account or a production deployment token, so the live public URL must be tested by the owner after connecting the repository and secrets.

## 9. Deployment limitations, API costs, and security considerations

- NVIDIA API usage may be subject to model quotas and account limits.
- Cloud deployment depends on the platform and account approval.
- Rate limits and usage quotas can affect the app during high traffic.
- API keys must stay out of GitHub, logs, and UI code.
- Configure `NVIDIA_MODEL` and `NVIDIA_VISION_MODEL` with model IDs enabled for your NVIDIA API key.
- Always use a secrets manager or environment variables for production.

## 10. Deployment placeholders

- Actual deployed URL: https://your-app-url.streamlit.app
- GitHub repository URL: https://github.com/your-username/your-repo

## 11. Acceptance checklist

- [x] Application runs locally
- [ ] Application deploys successfully to the cloud
- [ ] Public URL opens on another device
- [ ] AI question answering works online
- [ ] PDF upload and study features work online
- [x] API keys remain private in secrets or environment variables
- [x] Errors are handled properly
- [x] README contains deployment instructions
- [ ] Actual screenshots of the deployed application are included in the report

> The public deployment steps are ready, but the production URL and screenshots cannot be completed without access to the deployment account and approval of the live hosting setup.
