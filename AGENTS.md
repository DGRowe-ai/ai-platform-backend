# AGENTS.md

## Project overview

LokiAI backend API (`ai-platform-backend`) — a FastAPI service for multi-tenant AI customer-support chatbots. The frontend lives in a separate repo: [DGRowe-ai/ai-platform-frontend](https://github.com/DGRowe-ai/ai-platform-frontend).

This `main` branch is a slim API-only checkout. Business file data is expected at `../businesses/` relative to the server working directory (`/businesses` when running from `/workspace`).

## Cursor Cloud specific instructions

### Services

| Service | Port | Required |
|---------|------|----------|
| FastAPI (Uvicorn) | 8000 | Yes |
| SQLite (`platform.db`) | — | Yes (embedded, auto-created) |
| `businesses/` filesystem | — | Yes (not in `main` branch; see below) |
| OpenAI API | — | Yes for `/chat` |
| Frontend (separate repo) | 3000 | Optional for UI E2E |

### Python dependencies

Dependencies install to user site-packages (`pip install --user`). Ensure `~/.local/bin` is on `PATH` so `uvicorn` is found:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

`python3-venv` is not available in this VM image; use `pip3 install --user -r requirements.txt` rather than a virtualenv.

### Businesses directory (one-time setup)

Several routes read/write `../businesses/{folder_name}/` (profile, settings, knowledge). This directory is **not** committed on `main`; it exists on the `backend` branch.

If `/businesses` is missing, bootstrap from the `backend` branch:

```bash
sudo mkdir -p /businesses/template /businesses/test_business /businesses/my_biz
cd /workspace
for f in businesses/template/knowledge.txt businesses/template/profile.json businesses/template/settings.json \
         businesses/my_biz/knowledge.txt businesses/my_biz/profile.json businesses/my_biz/settings.json; do
  git show "origin/backend:$f" | sudo tee "/$f" > /dev/null
done
sudo cp /businesses/template/* /businesses/test_business/
sudo sed -i 's/Example Business/Test Business/' /businesses/test_business/profile.json
sudo chown -R "$(whoami):$(whoami)" /businesses
```

The committed `platform.db` references `test_business`; new signups create folders under `/businesses/` from `template/`.

### Running the API

```bash
export PATH="$HOME/.local/bin:$PATH"
cd /workspace
./start.sh
# or: uvicorn main:app --host 0.0.0.0 --port 8000
```

Interactive API docs: http://localhost:8000/docs

### Environment variables

| Variable | Required | Notes |
|----------|----------|-------|
| `OPENAI_API_KEY` | For `/chat` | Returns 503 if unset |
| `SECRET_KEY` | Dev optional | JWT signing; has insecure dev default |
| `DATABASE_URL` | Optional | Defaults to `sqlite:///./platform.db` |
| `CORS_ALLOWED_ORIGINS` | Optional | Comma-separated; sensible localhost defaults exist |

### Lint / test

No linter config or automated test suite is present on `main`. Verify changes by starting the server and hitting `/ping`, `/login`, `/signup`, and `/chat`.

### Gotchas

- Run Uvicorn from `/workspace` so `../businesses` resolves to `/businesses`.
- `/chat` requires a valid `business_id` matching a folder under `/businesses/`.
- Signup and `create-business` copy from `/businesses/template/`; signup fails if template is missing.
