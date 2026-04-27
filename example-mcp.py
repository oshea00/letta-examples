"""
Local Letta + MCP example.

MCP server URLs must use host-gateway so the Letta container can reach
services running in WSL2. Override with MCP_HOST env var if needed.

MCP server registration is idempotent — safe to run multiple times.
"""

import os

from letta_client import Letta

MCP_HOST = os.environ.get("MCP_HOST", "host-gateway")

client = Letta(base_url="http://localhost:8283")

# ── MCP server registration (idempotent) ─────────────────────────────────────
pricing_server = client.mcp_servers.create(
    server_name="pricing-server",
    config={
        "mcp_server_type": "streamable_http",
        "server_url": f"http://{MCP_HOST}:5000/mcp",
    },
)
print(f"MCP server: {pricing_server.id}")

# ── Fetch tools registered for this MCP server ───────────────────────────────
mcp_tools = client.mcp_servers.tools.list(mcp_server_id=pricing_server.id)
mcp_tool_ids = [tool.id for tool in mcp_tools]
print(f"MCP tools: {[tool.name for tool in mcp_tools]}")

# ── Agent ─────────────────────────────────────────────────────────────────────
agent_state = client.agents.create(
    model="openai/gpt-4.1",
    embedding="openai/text-embedding-3-small",
    tool_ids=mcp_tool_ids,
    memory_blocks=[
        {"label": "human", "value": "The human's name is Chad. They like vibe coding."},
        {"label": "persona", "value": "My name is Sam, a helpful assistant."},
    ],
    tools=["web_search", "run_code"],
)
print(f"Agent: {agent_state.id}")

response = client.agents.messages.create(
    agent_id=agent_state.id,
    messages=[
        {"role": "user", "content": "Hey, what pricing categories do you know about?"}
    ],
)

for message in response.messages:
    print(message)

human_block = client.agents.blocks.retrieve(
    agent_id=agent_state.id, block_label="human"
)
print(human_block.value)
