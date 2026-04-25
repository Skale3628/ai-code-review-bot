#  AI Code Review Bot

A production-grade, model-agnostic AI code review bot for **GitHub** and **GitLab**.
Automatically reviews Pull Requests and Merge Requests with structured feedback, inline comments, and severity-ranked issues.

---

## Features

- ✅ **GitHub + GitLab** webhook support
- ✅ **Model-agnostic** — OpenAI, Anthropic Claude, Azure OpenAI, or Ollama
- ✅ **Inline PR comments** at exact line numbers
- ✅ **Structured JSON reviews** — bugs, security, performance, readability
- ✅ **Severity filtering** — only post comments above a threshold
- ✅ **Smart file filtering** — skips lock files, generated code, minified assets
- ✅ **AST-aware diff parsing** — targets only changed lines
- ✅ **Docker-ready** with hot-reload dev setup

---

## Architecture

```
Webhook (GitHub / GitLab)
        │
        ▼
FastAPI (signature verified)
        │
        ▼
BackgroundTask
        │
   ┌────┴────┐
   │         │
GitHub    GitLab
Client    Client
   │         │
   └────┬────┘
        │  Fetch PR files + diffs
        ▼
  File Filter & Language Detector
        │
        ▼
  Prompt Builder
        │
        ▼
  LLM Client (model-agnostic)
  ┌─────────────────────────┐
  │ OpenAI / Anthropic /    │
  │ Azure OpenAI / Ollama   │
  └─────────────────────────┘
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

## Quick Start

### 1. Clone & Configure

```bash
git clone https://github.com/your-org/ai-code-review-bot
cd ai-code-review-bot
cp .env.example .env
```

Edit `.env` and set:
- Your chosen `LLM_PROVIDER` and `LLM_MODEL`
- The relevant API key (`OPENAI_API_KEY` or `ANTHROPIC_API_KEY`)
- `GITHUB_TOKEN` and/or `GITLAB_TOKEN`
- Webhook secrets

### 2. Run with Docker

```bash
docker compose up
```

### 3. Expose for Webhooks (local dev)

```bash
# Install ngrok, then:
NGROK_AUTHTOKEN=your-token docker compose --profile tunnel up
```

Your webhook URL will be: `https://xxxx.ngrok.io/webhook/github`

---

## LLM Provider Configuration

Switch providers by changing `.env` — no code changes needed.

| Provider | `LLM_PROVIDER` | `LLM_MODEL` example |
|---|---|---|
| OpenAI | `openai` | `gpt-4o` |
| Anthropic | `anthropic` | `claude-opus-4-6` |
| Azure OpenAI | `azure_openai` | set `AZURE_OPENAI_DEPLOYMENT` |
| Ollama (local) | `ollama` | `codellama` |

---

## GitHub Setup

1. Go to your repo → **Settings → Webhooks → Add webhook**
2. Payload URL: `https://your-domain/webhook/github`
3. Content type: `application/json`
4. Secret: match `GITHUB_WEBHOOK_SECRET` in `.env`
5. Events: select **Pull requests**

For a GitHub App (recommended for production): set `GITHUB_APP_ID` and `GITHUB_APP_PRIVATE_KEY_PATH`.

---

## GitLab Setup

1. Go to your project → **Settings → Webhooks**
2. URL: `https://your-domain/webhook/gitlab`
3. Secret token: match `GITLAB_WEBHOOK_SECRET` in `.env`
4. Trigger: **Merge request events**

---

## Running Tests

```bash
pip install -r requirements.txt
pytest tests/ -v
```

---

## Configuration Reference

| Variable | Default | Description |
|---|---|---|
| `LLM_PROVIDER` | `openai` | LLM backend to use |
| `LLM_MODEL` | `gpt-4o` | Model name |
| `MIN_SEVERITY_TO_COMMENT` | `medium` | Only post issues at this severity or above |
| `MAX_FILES_PER_REVIEW` | `20` | Cap files reviewed per PR |
| `POST_INLINE_COMMENTS` | `true` | Post inline comments at specific lines |
| `POST_SUMMARY_COMMENT` | `true` | Post overall summary comment |

---

## Project Structure

```
app/
├── main.py                  # FastAPI app + lifespan
├── api/
│   ├── github_webhook.py    # GitHub webhook + API client + comment posting
│   ├── gitlab_webhook.py    # GitLab webhook + API client + note posting
│   └── health.py            # Health check
├── core/
│   ├── config.py            # All settings via pydantic-settings
│   └── logging.py           # Structured logging setup
├── models/
│   └── review.py            # Pydantic models: PRContext, ReviewResult, etc.
├── services/
│   ├── llm_client.py        # Model-agnostic LLM abstraction
│   ├── prompts.py           # Prompt templates
│   └── review_engine.py     # Orchestration: filter → prompt → LLM → validate
└── utils/
    └── diff_utils.py        # Diff parsing, language detection, file filtering
tests/
└── test_review.py           # Unit tests (pytest + pytest-asyncio)
```
