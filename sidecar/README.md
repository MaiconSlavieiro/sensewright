# Sensewright Sidecar

Local FastAPI companion for the **Sensewright v2** mod (The Sims 4 AI Companion & World Director). Serves the `/v1/*` REST API and the Sensewright Web Studio at `/ui`.

## Run

```bash
# From the sidecar directory:
cp config.example.toml config.toml   # (config.example.toml lives in this directory)
python main.py
# or:
python -m sensewright_sidecar
```

- REST API: `http://127.0.0.1:8765/v1/...`
- Web Studio: `http://127.0.0.1:8765/ui`
- Health: `http://127.0.0.1:8765/v1/health`

## Install

```bash
pip install -r requirements.txt
```

## Test

```bash
python -m pytest
```

## Configuration

Two-layer `config.toml` (see `config.example.toml` in this directory):

- **Layer 1** (`[llm.providers.*]`): credentials + technical rate limits (RPM/RPD/TPM).
- **Layer 2** (`[llm.routes.*]`, `[llm.tiers.*]`): routing by purpose + generation budgets.

With no provider enabled, every one of the 33 purposes answers with a deterministic localized fallback (fully offline).

## Layout

- `sensewright_sidecar/` — application package (routers, LLM layer, SaveVault, i18n engine, Web Studio).
- `locales/` — official locale bundle (manifest + ui/content JSON).
- `data/` — runtime data (`saves/` Shadow DB, `panel.toml`, `logs/`).
- `tests/` — pytest suite.

See the repository root `README.md` and [`docs/architecture.md`](../docs/architecture.md) for the full architecture. The documentation hub is [`docs/README.md`](../docs/README.md).
