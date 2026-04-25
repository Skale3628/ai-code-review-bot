# 🤖 AI Code Review Bot

> **Automated, AI-powered code reviews for GitHub and GitLab — drop it in, configure once, and never miss a bug again.**

[![Python](https://img.shields.io/badge/Python-3.11+-blue?logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111+-green?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Docker](https://img.shields.io/badge/Docker-ready-2496ED?logo=docker&logoColor=white)](https://docker.com)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

---

## 📌 What Is This?

**AI Code Review Bot** is a self-hosted webhook service that automatically reviews Pull Requests (GitHub) and Merge Requests (GitLab) using large language models. It posts structured, actionable feedback — inline comments at exact line numbers, severity-ranked issues, and a summary — without any manual intervention.

You connect it once via webhook. After that, every PR/MR gets reviewed automatically.

---

## ✨ Key Features

| Feature | Details |
|---|---|
| 🔗 **GitHub + GitLab** | Full webhook support for both platforms |
| 🧠 **Model-Agnostic** | Works with OpenAI, Anthropic Claude, Azure OpenAI, or local Ollama |
| 💬 **Inline Comments** | Posts comments at exact changed line numbers |
| 🏷️ **Severity Ranking** | Issues ranked as `low`, `medium`, `high`, `critical` |
| 🔍 **Smart File Filtering** | Skips lock files, minified assets, generated code, migrations |
| 🧩 **AST-Aware Diff Parsing** | Only reviews lines that actually changed |
| 📦 **Docker-Ready** | Single command to run anywhere |
| 🔌 **RAG Support** | Optional repo-level context retrieval for smarter reviews |

---

## 🏗️ Architecture

```
Webhook (GitHub / GitLab)
        │
        ▼
  FastAPI  ──── Signature Verified
        │
        ▼
  Background Task
        │
   ┌────┴────┐
   │         │
GitHub     GitLab
Client     Client
   │         │
   └────┬────┘
        │  Fetch PR diffs + file contents
        ▼
  File Filter & Language Detector
        │
        ▼
  Prompt Builder
        │
        ▼
  LLM Client (model-agnostic)
  ┌──────────────────────────┐
  │ OpenAI / Anthropic /     │
  │ Azure OpenAI / Ollama    │
  └──────────────────────────┘
        │  Structured JSON output
        ▼
  Output Validator & Parser
        │
        ▼
  Comment Formatter
        │
   ┌────┴────┐
   │         │
Summary   Inline
Comment   Comments
```

---

## 🚀 Quick Start

### Prerequisites

- Docker & Docker Compose
- A GitHub or GitLab account
- An API key for your chosen LLM provider

### 1. Clone the repository

```bash
git clone https://github.com/your-username/ai-code-review-bot.git
cd ai-code-review-bot
```

### 2. Configure environment

```bash
cp .env.example .env
```

Open `.env` and fill in:

```env
# Choose your LLM provider
LLM_PROVIDER=anthropic          # openai | anthropic | azure_openai | ollama
LLM_MODEL=claude-opus-4-6       # or gpt-4o, codellama, etc.
ANTHROPIC_API_KEY=your-key-here # only the key for your chosen provider

# GitHub
GITHUB_TOKEN=your-github-token
GITHUB_WEBHOOK_SECRET=your-webhook-secret

# GitLab (if using GitLab)
GITLAB_TOKEN=your-gitlab-token
GITLAB_WEBHOOK_SECRET=your-webhook-secret
```

### 3. Start the service

```bash
docker compose up
```

### 4. Expose for webhooks (local dev)

```bash
# Uses ngrok tunnel built into docker-compose
NGROK_AUTHTOKEN=your-token docker compose --profile tunnel up
```

Your webhook URL will be: `https://xxxx.ngrok.io/webhook/github`

---

## ⚙️ LLM Provider Setup

Switch providers with a single `.env` change — no code modifications needed.

| Provider | `LLM_PROVIDER` | `LLM_MODEL` Example | API Key Variable |
|---|---|---|---|
| OpenAI | `openai` | `gpt-4o` | `OPENAI_API_KEY` |
| Anthropic | `anthropic` | `claude-opus-4-6` | `ANTHROPIC_API_KEY` |
| Azure OpenAI | `azure_openai` | set `AZURE_OPENAI_DEPLOYMENT` | `AZURE_OPENAI_API_KEY` |
| Ollama (local) | `ollama` | `codellama` | *(none needed)* |

---

## 🔧 GitHub Webhook Setup

1. Go to your repo → **Settings → Webhooks → Add webhook**
2. Set **Payload URL** to `https://your-domain/webhook/github`
3. Set **Content type** to `application/json`
4. Set **Secret** to match `GITHUB_WEBHOOK_SECRET` in your `.env`
5. Under events, select **Pull requests**
6. Click **Add webhook**

> **For production**, use a GitHub App instead of a PAT. Set `GITHUB_APP_ID` and `GITHUB_APP_PRIVATE_KEY_PATH` in `.env`.

---

## 🔧 GitLab Webhook Setup

1. Go to your project → **Settings → Webhooks**
2. Set **URL** to `https://your-domain/webhook/gitlab`
3. Set **Secret token** to match `GITLAB_WEBHOOK_SECRET` in your `.env`
4. Enable **Merge request events**
5. Click **Add webhook**

---

## 📋 Configuration Reference

| Variable | Default | Description |
|---|---|---|
| `LLM_PROVIDER` | `openai` | LLM backend to use |
| `LLM_MODEL` | `gpt-4o` | Model name |
| `LLM_TEMPERATURE` | `0.2` | Lower = more consistent reviews |
| `LLM_MAX_TOKENS` | `4096` | Max tokens per review |
| `MIN_SEVERITY_TO_COMMENT` | `medium` | Only post issues at or above this level |
| `MAX_FILES_PER_REVIEW` | `20` | Max files reviewed per PR |
| `MAX_DIFF_SIZE_KB` | `500` | Skip review if diff exceeds this size |
| `POST_INLINE_COMMENTS` | `true` | Post inline comments at specific lines |
| `POST_SUMMARY_COMMENT` | `true` | Post an overall summary comment |
| `RAG_ENABLED` | `false` | Enable repo-level context retrieval |

---

## 🧪 Running Tests

```bash
pip install -r requirements.txt
pytest tests/ -v
```

---

## 📁 Project Structure

```
ai-code-review-bot/
├── app/
│   ├── main.py                      # FastAPI app entry point
│   ├── api/
│   │   ├── github_webhook.py        # GitHub webhook handler + API client
│   │   ├── gitlab_webhook.py        # GitLab webhook handler + API client
│   │   └── health.py                # Health check endpoint
│   ├── core/
│   │   ├── config.py                # All settings via pydantic-settings
│   │   └── logging.py               # Structured logging
│   ├── models/
│   │   └── review.py                # Pydantic models (PRContext, ReviewResult)
│   ├── services/
│   │   ├── llm_client.py            # Model-agnostic LLM abstraction
│   │   ├── prompts.py               # Prompt templates
│   │   ├── review_engine.py         # Core orchestration logic
│   │   └── rag/                     # RAG pipeline (embeddings, chunking, retrieval)
│   └── utils/
│       └── diff_utils.py            # Diff parsing, language detection, filtering
├── tests/
│   └── test_review.py               # Unit tests
├── .github/workflows/               # CI/CD pipelines
├── .env.example                     # Environment variable template
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

---

## 🛡️ Security Notes

- Webhook signatures are **verified on every request** using HMAC-SHA256
- **Never commit your `.env` file** — use `.env.example` as a template
- For production, prefer **GitHub Apps** over Personal Access Tokens
- All API keys are loaded via environment variables — no hardcoding

---

## 🤝 Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch: `git checkout -b feat/your-feature`
3. Commit your changes: `git commit -m "Feat: add your feature"`
4. Push and open a Pull Request

---

## 📄 License

This project is licensed under the **MIT License** — see the [LICENSE](LICENSE) file for details.

---

<p align="center">Built with ❤️ using FastAPI, Python, and your favorite LLM</p>
