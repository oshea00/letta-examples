# Letta examples

## Setup

### Pre-requisites

* Postgres >= v15 with pgvector extension running locally.
* LETTA_PG_URI=postgresql://user:userpass@host-gateway:5432/letta
* ```uv sync```

Start Letta API
```bash
docker compose -f local-compose.yaml up 
```

## Documents

* [Letta API](https://docs.letta.com/api-overview/introduction/)
* [lettactl](https://docs.letta.com/guides/community/lettactl/)
* [lettactl GitHub](https://github.com/nouamanecodes/lettactl)
* [lettactl Docs](https://lettactl.dev/quickstart)

## Examples

| Script | Description |
|--------|-------------|
| example.py | Basic chat with agent |
| example-mcp.py | Basic chat with agent using mcp tool|
| chat_ui.py | Web chat UI (OpenWebUI-style) for local Letta — `uv run python chat_ui.py` |
