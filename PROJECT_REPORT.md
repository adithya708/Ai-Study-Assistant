# AI Study Assistant Deployment Report

## 1. Hosting platform and reason for choosing it

This project is designed for Streamlit Community Cloud because it is purpose-built for Python-based Streamlit applications, supports GitHub-based deployment, and offers simple secrets management for API keys and other runtime values.

## 2. Prerequisites and configuration

- Python 3.11+
- GitHub repository
- Streamlit Community Cloud account
- Gemini API key
- Internet access to deploy and test the app

## 3. GitHub repository setup

1. Create a GitHub repository.
2. Upload the project files.
3. Commit the source and configuration files.
4. Ensure the repository contains `requirements.txt`, `app.py`, `study_assistant.py`, `README.md`, and the secret example file.

## 4. Cloud deployment steps

1. Log in to Streamlit Community Cloud.
2. Choose "New app".
3. Select the GitHub repository.
4. Set the main file to `app.py`.
5. Click deploy.
6. Wait for the build to complete.
7. Copy the public HTTPS URL once the deployment finishes.

## 5. Secrets configuration

In Streamlit Community Cloud, add the following secret values in the dashboard:

```toml
GEMINI_API_KEY = "your_live_key"
MODEL_NAME = "gemini-3.8-flash"
```

Never place the key in the source code or UI.

## 6. Testing performed on the deployed application

The local project has been validated with a smoke test and targeted unit tests.

The required deployed verification steps are:
- Open the public URL on another device
- Verify PDF upload works
- Ask a live question using the public deployment
- Confirm the answer appears successfully
- Confirm secret values are not disclosed

This environment does not have live hosting credentials or deployment approval, so the production URL and live screenshots will be completed by the owner after connecting the repository and secrets.

## 7. Deployment limitations, API costs, and security considerations

- API usage may incur charges.
- Rate limits and quotas may temporarily block requests.
- Public deployment exposes an HTTPS URL, so all API interactions must remain secure.
- Keys must never be stored in the repository or logged.
- Application functionality depends on the cloud provider's runtime and service availability.

## 8. Deployment placeholders

- Deployed URL: https://your-app-url.streamlit.app
- GitHub repository URL: https://github.com/your-username/your-repo

## 9. Screenshot status

Actual screenshots of the live deployed page are pending the real hosting setup and deployment approval.
