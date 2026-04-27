"""
Local Letta + MCP example.

Requires WSL2 mirrored networking (networkingMode=mirrored in .wslconfig) so
that localhost is the same inside the Letta container and on the WSL2 host.

Override MCP_HOST if your MCP servers are on a different host.
"""

import os

from letta_client import Letta

MCP_HOST = os.environ.get("MCP_HOST", "host-gateway")

client = Letta(base_url="http://localhost:8283")

# ── MCP server registration (idempotent — safe to run multiple times) ────────
pricing_server = client.mcp_servers.create(
    server_name="pricing-server",
    config={
        "mcp_server_type": "streamable_http",
        "server_url": f"http://{MCP_HOST}:5000/mcp",
    },
)
print(f"MCP server: {pricing_server.id}  url=http://{MCP_HOST}:5000/mcp")

# ── Agent ────────────────────────────────────────────────────────────────────
agent_state = client.agents.create(
    model="openai/gpt-4.1",
    embedding="openai/text-embedding-3-small",
    memory_blocks=[
        {
            "label": "human",
            "value": "The human's name is Chad. They like vibe coding.",
        },
        {
            "label": "persona",
            "value": "My name is Sam, a helpful assistant.",
        },
    ],
    tools=["web_search", "run_code"],
)
print(f"Agent: {agent_state.id}")

response = client.agents.messages.create(
    agent_id=agent_state.id,
    messages=[
        {
            "role": "user",
            "content": "Hey, nice to meet you, my name is Brad.",
        }
    ],
)

for message in response.messages:
    print(message)

human_block = client.agents.blocks.retrieve(
    agent_id=agent_state.id, block_label="human"
)
print(human_block.value)
