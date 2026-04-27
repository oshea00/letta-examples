from letta_client import Letta

client = Letta(base_url="http://localhost:8283")

agent_state = client.agents.create(
    model="openai/gpt-5.1",
    embedding="openai/text-embedding-3-small",
    memory_blocks=[
        {
            "label": "human",
            "value": "The human's name is Chad. They like vibe coding."
        },
        {
            "label": "persona",
            "value": "My name is Sam, a helpful assistant."
        }
    ],
    tools=["web_search", "run_code"]
)

print(agent_state.id)
# agent-d9be...0846

response = client.agents.messages.create(
    agent_id=agent_state.id,
    messages=[
        {
            "role": "user",
            "content": "Hey, nice to meet you, my name is Brad."
        }
    ]
)

# the agent will think, then edit its memory using a tool
for message in response.messages:
    print(message)

# The content of this memory block will be something like
# "The human's name is Brad. They like vibe coding."
# Fetch this block's content with:
human_block = client.agents.blocks.retrieve(agent_id=agent_state.id, block_label="human")
print(human_block.value)
