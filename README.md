# Letta examples

## Setup

### Pre-requisites

* Postgres >= v15 with pgvector extension running locally.
* LETTA_PG_URI=postgresql://user:userpass@host-gateway:5432/letta
* ```uv sync```

For WSL-hosted Ollama:
```bash
export OLLAMA_WSL_IP=$(ip addr show eth0 | grep 'inet ' | awk '{print $2}' | cut -d/ -f1)
export OLLAMA_BASE_URL="http://${OLLAMA_WSL_IP}:11434"
```

Start Letta API
```bash
docker compose -f local-compose.yaml up 
```
