#!/usr/bin/env python3
"""Simple chat UI for a local Letta instance. Run with: uv run python chat_ui.py"""

import os

from flask import Flask, jsonify, request, render_template_string
from letta_client import Letta

app = Flask(__name__)
LETTA_URL = os.environ.get("LETTA_BASE_URL", "http://localhost:8283")
client = Letta(base_url=LETTA_URL)

# ── Serialisers ───────────────────────────────────────────────────────────────


def message_to_dict(msg):
    d = (
        msg.model_dump()
        if hasattr(msg, "model_dump")
        else dict(getattr(msg, "__dict__", {}))
    )
    msg_type = d.get("message_type", type(msg).__name__)
    result = {"type": msg_type}
    if d.get("content") is not None:
        result["content"] = str(d["content"])
    if d.get("reasoning") is not None:
        result["content"] = str(d["reasoning"])
    tc = d.get("tool_call")
    if tc:
        result["tool_name"] = (
            tc.get("name", "") if isinstance(tc, dict) else getattr(tc, "name", "")
        )
        result["tool_args"] = (
            tc.get("arguments", "")
            if isinstance(tc, dict)
            else getattr(tc, "arguments", "")
        )
    if d.get("tool_return") is not None:
        result["tool_return"] = str(d["tool_return"])
    return result


def server_to_dict(s):
    return {
        "id": s.id,
        "name": getattr(s, "server_name", s.id),
        "type": getattr(s, "mcp_server_type", "unknown"),
        "url": getattr(s, "server_url", None),
    }


def tool_to_dict(t):
    return {
        "id": t.id,
        "name": t.name,
        "description": getattr(t, "description", "") or "",
    }


# ── Routes ────────────────────────────────────────────────────────────────────


@app.route("/")
def index():
    return render_template_string(HTML)


# Agents
@app.route("/api/agents")
def list_agents():
    try:
        agents = client.agents.list()
        return jsonify(
            [{"id": a.id, "name": getattr(a, "name", None) or a.id} for a in agents]
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/models")
def list_models():
    try:
        models = client.models.list()
        llms = [
            {"handle": m.handle, "display_name": m.display_name, "provider": m.provider_name}
            for m in models
            if getattr(m, "model_type", "") == "llm"
        ]
        llms.sort(key=lambda m: (m["provider"], m["display_name"]))
        return jsonify(llms)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/agents", methods=["POST"])
def create_agent():
    data = request.json or {}
    try:
        kwargs = dict(
            name=data.get("name", "Chat Agent"),
            model=data.get("model", "openai/gpt-4.1"),
            embedding="openai/text-embedding-3-small",
            memory_blocks=[
                {"label": "human", "value": "The user is a person I am chatting with."},
                {
                    "label": "persona",
                    "value": data.get("persona", "I am a helpful AI assistant."),
                },
            ],
        )
        if data.get("tool_ids"):
            kwargs["tool_ids"] = data["tool_ids"]
        if data.get("tools"):
            kwargs["tools"] = data["tools"]
        agent = client.agents.create(**kwargs)
        return jsonify(
            {"id": agent.id, "name": getattr(agent, "name", None) or agent.id}
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/agents/<agent_id>/messages")
def get_messages(agent_id):
    try:
        msgs = client.agents.messages.list(agent_id=agent_id, limit=200)
        return jsonify([message_to_dict(m) for m in msgs])
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/agents/<agent_id>/messages", methods=["POST"])
def send_message(agent_id):
    data = request.json or {}
    content = (data.get("content") or "").strip()
    if not content:
        return jsonify({"error": "Empty message"}), 400
    try:
        response = client.agents.messages.create(
            agent_id=agent_id,
            messages=[{"role": "user", "content": content}],
        )
        return jsonify({"messages": [message_to_dict(m) for m in response.messages]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/agents/<agent_id>", methods=["DELETE"])
def delete_agent(agent_id):
    try:
        client.agents.delete(agent_id=agent_id)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/agents/<agent_id>/conversations")
def list_conversations(agent_id):
    try:
        convs = client.conversations.list(
            agent_id=agent_id, order="desc", order_by="last_message_at", limit=50
        )
        return jsonify([
            {
                "id": c.id,
                "summary": c.summary or "New conversation",
                "created_at": c.created_at.isoformat() if c.created_at else "",
                "last_message_at": c.last_message_at.isoformat() if c.last_message_at else None,
            }
            for c in convs
        ])
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/agents/<agent_id>/conversations", methods=["POST"])
def new_conversation(agent_id):
    data = request.json or {}
    current_conv_id = data.get("current_conv_id")
    try:
        # Stamp the closing conversation with its first user message as summary
        if current_conv_id:
            msgs = client.conversations.messages.list(current_conv_id, limit=10, order="asc")
            for m in msgs:
                d = message_to_dict(m)
                if d.get("type") == "user_message" and d.get("content"):
                    text = d["content"].strip()
                    summary = text[:80] + ("…" if len(text) > 80 else "")
                    client.conversations.update(current_conv_id, summary=summary)
                    break
        new_conv = client.conversations.create(agent_id=agent_id)
        return jsonify({
            "id": new_conv.id,
            "summary": new_conv.summary or "New conversation",
            "created_at": new_conv.created_at.isoformat() if new_conv.created_at else "",
        }), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500


_SKIP_MSG_TYPES = {"ping", "stop_reason", "usage_statistics", "error_message"}


@app.route("/api/conversations/<conv_id>/messages")
def get_conversation_messages(conv_id):
    try:
        msgs = client.conversations.messages.list(conv_id, limit=200, order="asc")
        return jsonify([message_to_dict(m) for m in msgs])
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/conversations/<conv_id>/messages", methods=["POST"])
def send_conversation_message(conv_id):
    data = request.json or {}
    content = (data.get("content") or "").strip()
    if not content:
        return jsonify({"error": "Empty message"}), 400
    try:
        stream = client.conversations.messages.create(
            conv_id,
            messages=[{"role": "user", "content": content}],
        )
        messages = []
        for event in stream:
            d = event.model_dump() if hasattr(event, "model_dump") else {}
            if d.get("message_type") not in _SKIP_MSG_TYPES:
                messages.append(message_to_dict(event))
        return jsonify({"messages": messages})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# MCP Servers
@app.route("/api/mcp-servers")
def list_mcp_servers():
    try:
        servers = client.mcp_servers.list()
        return jsonify([server_to_dict(s) for s in servers])
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/mcp-servers", methods=["POST"])
def create_mcp_server():
    data = request.json or {}
    server_type = data.get("type", "streamable_http")
    try:
        if server_type in ("streamable_http", "sse"):
            config = {"mcp_server_type": server_type, "server_url": data["url"]}
            if data.get("auth_token"):
                config["auth_token"] = data["auth_token"]
            if data.get("auth_header"):
                config["auth_header"] = data["auth_header"]
        else:  # stdio
            config = {
                "mcp_server_type": "stdio",
                "command": data["command"],
                "args": data.get("args", []),
            }
            if data.get("env"):
                config["env"] = data["env"]
        server = client.mcp_servers.create(server_name=data["name"], config=config)
        return jsonify(server_to_dict(server))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/mcp-servers/<server_id>", methods=["DELETE"])
def delete_mcp_server(server_id):
    try:
        client.mcp_servers.delete(mcp_server_id=server_id)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/mcp-servers/<server_id>/tools")
def list_mcp_tools(server_id):
    try:
        tools = client.mcp_servers.tools.list(mcp_server_id=server_id)
        return jsonify([tool_to_dict(t) for t in tools])
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/mcp-servers/<server_id>/refresh", methods=["POST"])
def refresh_mcp_server(server_id):
    try:
        client.mcp_servers.refresh_mcp_server_tools(mcp_server_id=server_id)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── HTML ──────────────────────────────────────────────────────────────────────

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Letta Chat</title>
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/themes/prism-dark.min.css">
<script src="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/prism.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/components/prism-python.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/components/prism-javascript.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/components/prism-json.min.js"></script>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0f172a; color: #e2e8f0; height: 100vh; display: flex; overflow: hidden; }

/* ── Sidebar ── */
#sidebar { width: 260px; background: #1e293b; border-right: 1px solid #2d3f55; display: flex; flex-direction: column; flex-shrink: 0; }
#sidebar-top { padding: 14px 14px 10px; border-bottom: 1px solid #2d3f55; flex-shrink: 0; }
#sidebar-top h1 { font-size: 16px; font-weight: 600; color: #f1f5f9; }
#sidebar-top p  { font-size: 11px; color: #475569; margin-top: 1px; }
#sidebar-scroll { flex: 1; overflow-y: auto; }

.sec-hdr { display: flex; align-items: center; justify-content: space-between; padding: 10px 10px 4px; }
.sec-hdr-label { font-size: 10px; font-weight: 700; color: #475569; text-transform: uppercase; letter-spacing: .06em; }
.sec-hdr-btn { width: 20px; height: 20px; border: none; background: transparent; color: #475569; cursor: pointer; border-radius: 4px; font-size: 16px; line-height: 1; display: flex; align-items: center; justify-content: center; }
.sec-hdr-btn:hover { background: #273344; color: #94a3b8; }
.sec-divider { height: 1px; background: #2d3f55; margin: 4px 0; }

/* Agent items */
.agent-item { padding: 8px 10px; border-radius: 6px; cursor: pointer; font-size: 13px; color: #94a3b8; margin: 1px 6px; display: flex; align-items: center; gap: 8px; }
.agent-item:hover { background: #273344; color: #e2e8f0; }
.agent-item.active { background: #1d4ed8; color: #fff; }
.agent-avatar { width: 24px; height: 24px; border-radius: 50%; background: #334155; display: flex; align-items: center; justify-content: center; font-size: 9px; font-weight: 700; flex-shrink: 0; color: #94a3b8; }
.agent-item.active .agent-avatar { background: rgba(255,255,255,.2); color: #fff; }
.agent-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.agent-actions { flex-shrink: 0; }
.agent-btn { padding: 2px 5px; border: none; background: transparent; color: #475569; cursor: pointer; border-radius: 3px; font-size: 11px; }
.agent-btn:hover { background: #334155; color: #94a3b8; }

/* MCP server items */
.mcp-item { margin: 1px 6px; border-radius: 6px; font-size: 13px; color: #94a3b8; }
.mcp-item-row { display: flex; align-items: center; gap: 7px; padding: 7px 10px; cursor: pointer; border-radius: 6px; }
.mcp-item-row:hover { background: #273344; color: #e2e8f0; }
.mcp-icon { font-size: 12px; flex-shrink: 0; }
.mcp-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.type-tag { font-size: 9px; padding: 1px 4px; border-radius: 3px; background: #1a2740; color: #475569; flex-shrink: 0; }
.mcp-actions { display: none; gap: 2px; flex-shrink: 0; }
.mcp-item-row:hover .mcp-actions { display: flex; }
.mcp-btn { padding: 2px 5px; border: none; background: transparent; color: #475569; cursor: pointer; border-radius: 3px; font-size: 11px; }
.mcp-btn:hover { background: #334155; color: #94a3b8; }
.mcp-tools-panel { padding: 0 10px 4px 26px; display: none; }
.mcp-tools-panel.open { display: block; }
.mcp-tool-row { font-size: 11px; color: #475569; padding: 2px 0; display: flex; align-items: baseline; gap: 4px; }
.mcp-tool-row::before { content: "–"; flex-shrink: 0; }
.mcp-tool-name-text { color: #64748b; }
.mcp-tool-desc { color: #334155; margin-left: 2px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.mcp-loading { font-size: 11px; color: #334155; padding: 4px 0; }
.mcp-empty { font-size: 11px; color: #334155; padding: 4px 0; font-style: italic; }
.chevron { font-size: 9px; transition: transform .15s; flex-shrink: 0; }
.chevron.open { transform: rotate(90deg); }

/* ── Main area ── */
#main { flex: 1; display: flex; flex-direction: column; min-width: 0; }
#chat-header { padding: 12px 20px; border-bottom: 1px solid #2d3f55; background: #1e293b; font-size: 14px; font-weight: 500; color: #64748b; flex-shrink: 0; }
#messages { flex: 1; overflow-y: auto; padding: 24px 20px; display: flex; flex-direction: column; gap: 10px; }

/* Empty state */
#empty-state { display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100%; gap: 10px; pointer-events: none; }
#empty-state svg { opacity: 0.25; }
#empty-state p { font-size: 13px; color: #334155; }

/* Message rows */
.msg-row { display: flex; flex-direction: column; max-width: 760px; }
.msg-row.user { align-self: flex-end; align-items: flex-end; }
.msg-row.assistant { align-self: flex-start; align-items: flex-start; }
.msg-label { font-size: 11px; color: #475569; margin-bottom: 4px; padding: 0 4px; }
.msg-bubble { padding: 11px 15px; border-radius: 14px; font-size: 14px; line-height: 1.65; }
.msg-row.user .msg-bubble { background: #1d4ed8; color: #fff; border-bottom-right-radius: 4px; }
.msg-row.assistant .msg-bubble { background: #1e293b; color: #e2e8f0; border-bottom-left-radius: 4px; border: 1px solid #2d3f55; }

/* Markdown */
.msg-bubble p { margin-bottom: 8px; }
.msg-bubble p:last-child { margin-bottom: 0; }
.msg-bubble code:not(pre code) { background: rgba(0,0,0,.25); padding: 1px 5px; border-radius: 3px; font-size: 12.5px; font-family: monospace; }
.msg-bubble pre { background: #090e1a; border: 1px solid #2d3f55; border-radius: 8px; padding: 12px 14px; overflow-x: auto; margin: 8px 0; }
.msg-bubble pre code { font-size: 12.5px; background: none; padding: 0; }
.msg-bubble ul,.msg-bubble ol { padding-left: 20px; margin: 6px 0; }
.msg-bubble li { margin-bottom: 3px; }
.msg-bubble h1,.msg-bubble h2,.msg-bubble h3 { margin: 10px 0 6px; color: #f1f5f9; font-size: 1em; font-weight: 600; }
.msg-bubble blockquote { border-left: 3px solid #334155; padding-left: 12px; color: #94a3b8; margin: 8px 0; }
.msg-bubble a { color: #60a5fa; }
.msg-bubble table { border-collapse: collapse; width: 100%; margin: 8px 0; font-size: 13px; }
.msg-bubble th,.msg-bubble td { border: 1px solid #334155; padding: 6px 10px; }
.msg-bubble th { background: #273344; }

/* Tool cards */
.tool-group { max-width: 760px; align-self: flex-start; width: 100%; }
.tool-card { border: 1px solid #2d3f55; border-radius: 8px; overflow: hidden; margin-bottom: 5px; font-size: 12px; }
.tool-card-hdr { padding: 6px 10px; background: #1a2740; cursor: pointer; display: flex; align-items: center; gap: 7px; color: #64748b; user-select: none; }
.tool-card-hdr:hover { background: #1e2f4a; color: #94a3b8; }
.tool-card-title { flex: 1; font-weight: 500; }
.tool-card-chev { font-size: 9px; transition: transform .15s; }
.tool-card-copy { padding: 2px 6px; border: none; background: transparent; color: #475569; cursor: pointer; border-radius: 3px; font-size: 11px; opacity: 0; transition: opacity .15s; }
.tool-card-hdr:hover .tool-card-copy { opacity: 1; }
.tool-card-copy:hover { background: #334155; color: #94a3b8; }
.tool-card-body { padding: 8px 10px; background: #090e1a; color: #64748b; font-family: monospace; font-size: 11.5px; white-space: pre-wrap; word-break: break-all; display: none; }
.tool-card-body.open { display: block; }
.tool-card-hdr.expanded .tool-card-chev { transform: rotate(180deg); }

/* Typing */
.typing-wrap { max-width: 760px; align-self: flex-start; }
.typing-label { font-size: 11px; color: #475569; margin-bottom: 4px; padding: 0 4px; }
.typing-bubble { display: inline-flex; gap: 4px; padding: 13px 15px; background: #1e293b; border: 1px solid #2d3f55; border-radius: 14px; border-bottom-left-radius: 4px; }
.dot { width: 6px; height: 6px; background: #475569; border-radius: 50%; animation: blink 1.3s infinite; }
.dot:nth-child(2) { animation-delay: .2s; }
.dot:nth-child(3) { animation-delay: .4s; }
@keyframes blink { 0%,60%,100% { opacity:.3; transform:translateY(0); } 30% { opacity:1; transform:translateY(-4px); } }

/* Input */
#input-area { padding: 14px 20px; border-top: 1px solid #2d3f55; background: #1e293b; flex-shrink: 0; }
#input-form { display: flex; gap: 8px; align-items: flex-end; max-width: 820px; margin: 0 auto; }
#msg-input { flex: 1; background: #0f172a; border: 1px solid #2d3f55; border-radius: 10px; padding: 10px 14px; color: #e2e8f0; font-size: 14px; resize: none; min-height: 44px; max-height: 180px; outline: none; font-family: inherit; line-height: 1.5; transition: border-color .15s; }
#msg-input:focus { border-color: #2563eb; }
#msg-input::placeholder { color: #334155; }
#msg-input:disabled { opacity: .4; cursor: not-allowed; }
#send-btn { background: #2563eb; color: white; border: none; border-radius: 8px; padding: 0 16px; cursor: pointer; font-size: 13px; height: 44px; display: flex; align-items: center; gap: 5px; white-space: nowrap; transition: background .15s; font-weight: 500; }
#send-btn:hover:not(:disabled) { background: #1d4ed8; }
#send-btn:disabled { background: #1e293b; border: 1px solid #2d3f55; color: #334155; cursor: not-allowed; }

/* ── Modals ── */
.overlay { position: fixed; inset: 0; background: rgba(0,0,0,.65); display: flex; align-items: center; justify-content: center; z-index: 50; }
.modal { background: #1e293b; border: 1px solid #2d3f55; border-radius: 12px; padding: 22px 24px 20px; width: min(640px, calc(100vw - 24px)); max-height: 88vh; overflow-y: auto; }
.modal h3 { font-size: 15px; margin-bottom: 16px; color: #f1f5f9; font-weight: 600; }
.field-label { font-size: 11px; color: #64748b; margin-bottom: 4px; display: block; font-weight: 500; }
.modal input, .modal select, .modal textarea { width: 100%; background: #0f172a; border: 1px solid #2d3f55; border-radius: 6px; padding: 8px 11px; color: #e2e8f0; font-size: 13px; margin-bottom: 12px; outline: none; font-family: inherit; }
.modal input:focus, .modal select:focus, .modal textarea:focus { border-color: #2563eb; }
.modal select option { background: #1e293b; }
.modal textarea { resize: vertical; min-height: 60px; }
.modal-btns { display: flex; gap: 8px; justify-content: flex-end; margin-top: 8px; }
.modal-btns button { padding: 8px 16px; border-radius: 6px; border: none; cursor: pointer; font-size: 13px; font-weight: 500; }
.btn-cancel { background: #273344; color: #94a3b8; }
.btn-cancel:hover { background: #334155; }
.btn-primary { background: #2563eb; color: #fff; }
.btn-primary:hover:not(:disabled) { background: #1d4ed8; }
.btn-primary:disabled { background: #334155; color: #475569; cursor: not-allowed; }

/* Tool selection in modal */
.tools-section { border-top: 1px solid #2d3f55; margin-top: 4px; padding-top: 14px; }
.tools-section h4 { font-size: 11px; font-weight: 700; color: #475569; text-transform: uppercase; letter-spacing: .06em; margin-bottom: 10px; }
.tool-checks { display: flex; flex-wrap: wrap; gap: 6px 16px; margin-bottom: 12px; }
.tool-check { display: flex; align-items: center; gap: 6px; cursor: pointer; font-size: 13px; color: #94a3b8; }
.tool-check input { accent-color: #2563eb; cursor: pointer; }
.tool-check:hover { color: #e2e8f0; }
.mcp-tool-group { margin-bottom: 10px; }
.mcp-tool-group-hdr { display: flex; align-items: center; gap: 6px; cursor: pointer; margin-bottom: 5px; user-select: none; min-width: 0; }
.mcp-tool-group-hdr:hover { color: #e2e8f0; }
.mcp-tg-name { font-size: 12px; color: #64748b; font-weight: 500; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.mcp-tg-badge { font-size: 9px; padding: 1px 4px; border-radius: 3px; background: #1a2740; color: #475569; }
.mcp-tg-chev { font-size: 9px; color: #475569; transition: transform .15s; }
.mcp-tg-chev.open { transform: rotate(90deg); }
.mcp-tool-list { padding-left: 8px; display: none; }
.mcp-tool-list.open { display: block; }
.mcp-tool-check { display: grid; grid-template-columns: 16px minmax(0, 1fr); align-items: flex-start; column-gap: 7px; padding: 4px 0; cursor: pointer; width: 100%; }
.mcp-tool-check input { accent-color: #2563eb; cursor: pointer; margin-top: 2px; flex-shrink: 0; }
.mcp-tool-check-info { font-size: 12px; color: #94a3b8; min-width: 0; overflow-wrap: anywhere; word-break: break-word; }
.mcp-tool-check-desc { font-size: 11px; color: #475569; margin-top: 1px; overflow-wrap: anywhere; word-break: break-word; }
.mcp-loading-msg { font-size: 12px; color: #334155; font-style: italic; padding: 4px 0; }

/* Scrollbar */
::-webkit-scrollbar { width: 5px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: #2d3f55; border-radius: 3px; }

/* ── Conversations panel ── */
#conv-panel { width: 220px; background: #172032; border-right: 1px solid #2d3f55; display: none; flex-direction: column; flex-shrink: 0; }
#conv-panel-header { padding: 10px; border-bottom: 1px solid #2d3f55; flex-shrink: 0; }
#new-chat-btn { width: 100%; padding: 7px 10px; background: #2563eb; color: #fff; border: none; border-radius: 6px; font-size: 12px; font-weight: 500; cursor: pointer; text-align: left; }
#new-chat-btn:hover { background: #1d4ed8; }
#new-chat-btn:disabled { background: #273344; color: #475569; cursor: not-allowed; }
#conv-list { flex: 1; overflow-y: auto; padding: 6px 0; }
.conv-card { margin: 2px 6px; padding: 8px 10px; border-radius: 6px; cursor: pointer; border: 1px solid transparent; }
.conv-card:hover { background: #1e293b; }
.conv-card.active { background: #1e3a5f; border-color: #2563eb; }
.conv-summary { font-size: 12px; color: #94a3b8; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; margin-bottom: 3px; }
.conv-card.active .conv-summary { color: #e2e8f0; }
.conv-date { font-size: 10px; color: #475569; }
.conv-live-dot { display: inline-block; width: 6px; height: 6px; border-radius: 50%; background: #22c55e; margin-right: 4px; vertical-align: middle; }
</style>
</head>
<body>

<div id="sidebar">
  <div id="sidebar-top">
    <h1>Letta Chat</h1>
    <p>Local instance</p>
  </div>
  <div id="sidebar-scroll">
    <!-- Agents -->
    <div class="sec-hdr">
      <span class="sec-hdr-label">Agents</span>
      <button class="sec-hdr-btn" onclick="showCreateModal()" title="New agent">+</button>
    </div>
    <div id="agents-list"></div>

    <div class="sec-divider"></div>

    <!-- MCP Servers -->
    <div class="sec-hdr">
      <span class="sec-hdr-label">MCP Servers</span>
      <button class="sec-hdr-btn" onclick="showRegisterModal()" title="Register server">+</button>
    </div>
    <div id="mcp-list"></div>
  </div>
</div>

<div id="conv-panel">
  <div id="conv-panel-header">
    <button id="new-chat-btn" onclick="newChat()">+ New Chat</button>
  </div>
  <div id="conv-list"></div>
</div>

<div id="main">
  <div id="chat-header">Select an agent</div>
  <div id="messages">
    <div id="empty-state">
      <svg width="44" height="44" viewBox="0 0 24 24" fill="none" stroke="#475569" stroke-width="1.5">
        <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
      </svg>
      <p>Select an agent or create a new one</p>
    </div>
  </div>
  <div id="input-area">
    <div id="input-form">
      <textarea id="msg-input" placeholder="Message…" rows="1" disabled></textarea>
      <button id="send-btn" disabled>
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
          <line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/>
        </svg>
        Send
      </button>
    </div>
  </div>
</div>

<script>
marked.setOptions({
  breaks: true, 
  gfm: true,
  highlight: (code, lang) => {
    if (lang) return `<code class="language-${lang}">${code}</code>`;
    return `<code>${code}</code>`;
  }
});

// ── State ─────────────────────────────────────────────────────────────────────
let agentId = null;
let busy    = false;
let convId  = null;   // null = agent-direct; "conv-<uuid>" = explicit Letta conversation

// ── Agents ────────────────────────────────────────────────────────────────────

async function loadAgents() {
  try {
    const agents = await api('/api/agents');
    const el = document.getElementById('agents-list');
    el.innerHTML = '';
    if (agents.error) { el.innerHTML = err(agents.error); return; }
    if (!agents.length) { el.innerHTML = '<div style="padding:6px 10px;font-size:12px;color:#334155;">No agents yet</div>'; return; }
    agents.forEach(a => {
      const div = document.createElement('div');
      div.className = 'agent-item' + (a.id === agentId ? ' active' : '');
      div.dataset.id = a.id;
      div.innerHTML = `
        <div class="agent-avatar">${esc(a.name||'A').slice(0,2).toUpperCase()}</div>
        <span class="agent-name">${esc(a.name||a.id)}</span>
        <div class="agent-actions" style="display:none;gap:4px;margin-left:auto;flex-shrink:0;">
          <button class="agent-btn" title="Delete agent" onclick="event.stopPropagation();deleteAgent('${a.id}','${esc(a.name||a.id)}')">✕</button>
        </div>
      `;
      div.onmouseover = () => { if (a.id !== agentId) div.querySelector('.agent-actions').style.display = 'flex'; };
      div.onmouseout = () => { div.querySelector('.agent-actions').style.display = 'none'; };
      div.onclick = () => selectAgent(a.id, a.name);
      el.appendChild(div);
    });
  } catch(e) { console.error(e); }
}

async function selectAgent(id, name) {
  agentId = id;
  convId = null;
  document.getElementById('chat-header').textContent = name || id;
  document.querySelectorAll('.agent-item').forEach(el => el.classList.toggle('active', el.dataset.id === id));
  document.getElementById('conv-panel').style.display = 'flex';
  document.getElementById('msg-input').disabled = false;
  document.getElementById('send-btn').disabled = false;

  await loadConversations(id);

  // If no explicit conversations exist, show agent-direct messages
  if (!convId) {
    const msgs = document.getElementById('messages');
    msgs.innerHTML = '<div style="color:#334155;font-size:13px;text-align:center;padding:20px;">Loading…</div>';
    try {
      const data = await api(`/api/agents/${id}/messages`);
      msgs.innerHTML = '';
      if (data.error) { msgs.innerHTML = err(data.error); return; }
      if (!data.length) { msgs.innerHTML = '<div id="empty-state"><p>No messages yet — say hello!</p></div>'; return; }
      renderMessages(data);
      scrollBottom();
    } catch(e) { msgs.innerHTML = err(e.message); }
  }
}

async function loadConversations(aid) {
  const list = document.getElementById('conv-list');
  list.innerHTML = '<div style="padding:6px 10px;font-size:11px;color:#334155;">Loading…</div>';
  try {
    const convs = await api(`/api/agents/${aid}/conversations`);
    list.innerHTML = '';
    if (convs.error || !convs.length) {
      list.innerHTML = '<div style="padding:6px 10px;font-size:11px;color:#334155;font-style:italic;">No past conversations</div>';
      return;
    }
    // Server returns desc by last_message_at — most recent first
    convs.forEach(c => renderConvCard(c, list));
    // Auto-select the most recently active conversation
    await selectConversation(convs[0].id);
  } catch(e) { list.innerHTML = ''; }
}

function renderConvCard(conv, container) {
  const card = document.createElement('div');
  card.className = 'conv-card';
  card.dataset.convId = conv.id;
  const ts = conv.last_message_at || conv.created_at;
  const d = ts ? new Date(ts) : new Date();
  const dateStr = d.toLocaleDateString([], {month:'short', day:'numeric'})
                + ' ' + d.toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'});
  card.innerHTML = `<div class="conv-summary">${esc(conv.summary || 'New conversation')}</div><div class="conv-date">${esc(dateStr)}</div>`;
  card.onclick = () => selectConversation(conv.id);
  container.appendChild(card);
}

async function selectConversation(id) {
  if (busy) return;
  convId = id;
  document.querySelectorAll('.conv-card').forEach(el =>
    el.classList.toggle('active', el.dataset.convId === id));

  const msgs = document.getElementById('messages');
  msgs.innerHTML = '<div style="color:#334155;font-size:13px;text-align:center;padding:20px;">Loading…</div>';

  try {
    const data = await api(`/api/conversations/${id}/messages`);
    msgs.innerHTML = '';
    if (data.error) { msgs.innerHTML = err(data.error); return; }
    if (!data.length) {
      msgs.innerHTML = '<div id="empty-state"><p>New conversation — say hello!</p></div>';
      return;
    }
    renderMessages(data);
    scrollBottom();
  } catch(e) { msgs.innerHTML = err(e.message); }
}

async function newChat() {
  if (busy || !agentId) return;
  const btn = document.getElementById('new-chat-btn');
  btn.disabled = true;
  try {
    const newConv = await api(`/api/agents/${agentId}/conversations`, {method:'POST', json:{current_conv_id: convId}});
    if (newConv.error) { alert('Error: ' + newConv.error); return; }
    convId = newConv.id;
    await refreshConvList();
    document.getElementById('messages').innerHTML = '<div id="empty-state"><p>New conversation — say hello!</p></div>';
    document.getElementById('msg-input').focus();
  } catch(e) { alert('Error: ' + e.message); }
  finally { btn.disabled = false; }
}

async function refreshConvList() {
  const list = document.getElementById('conv-list');
  list.innerHTML = '';
  try {
    const convs = await api(`/api/agents/${agentId}/conversations`);
    if (convs.error || !convs.length) return;
    convs.forEach(c => renderConvCard(c, list));
    document.querySelectorAll('.conv-card').forEach(el =>
      el.classList.toggle('active', el.dataset.convId === convId));
  } catch(e) { /* ignore */ }
}

async function deleteAgent(toDeleteId, name) {
  if (!confirm(`Delete agent "${name}"?`)) return;
  try {
    const res = await api(`/api/agents/${toDeleteId}`, {method:'DELETE'});
    if (res.error) { alert('Error: ' + res.error); return; }
    document.querySelector(`.agent-item[data-id="${toDeleteId}"]`)?.remove();
    if (toDeleteId === agentId) {
      agentId = null;
      convId = null;
      document.getElementById('chat-header').textContent = 'Select an agent';
      document.getElementById('messages').innerHTML = '<div id="empty-state"><svg width="44" height="44" viewBox="0 0 24 24" fill="none" stroke="#475569" stroke-width="1.5"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg><p>Select an agent or create a new one</p></div>';
      document.getElementById('msg-input').disabled = true;
      document.getElementById('send-btn').disabled = true;
      document.getElementById('conv-panel').style.display = 'none';
    }
    const el = document.getElementById('agents-list');
    if (!el.children.length) el.innerHTML = '<div style="padding:6px 10px;font-size:12px;color:#334155;">No agents yet</div>';
  } catch(e) { alert('Error: ' + e.message); }
}

// ── MCP Servers ───────────────────────────────────────────────────────────────

async function loadMcpServers() {
  try {
    const servers = await api('/api/mcp-servers');
    const el = document.getElementById('mcp-list');
    el.innerHTML = '';
    if (servers.error) { el.innerHTML = err(servers.error); return; }
    if (!servers.length) { el.innerHTML = '<div style="padding:6px 10px;font-size:12px;color:#334155;">No servers registered</div>'; return; }
    servers.forEach(s => renderMcpServer(s, el));
  } catch(e) { console.error(e); }
}

function renderMcpServer(s, container) {
  const item = document.createElement('div');
  item.className = 'mcp-item';
  item.dataset.id = s.id;
  item.innerHTML = `
    <div class="mcp-item-row" onclick="toggleMcpTools('${s.id}', this)">
      <span class="chevron" id="chev-${s.id}">▶</span>
      <span class="mcp-icon">🔌</span>
      <span class="mcp-name">${esc(s.name)}</span>
      <span class="type-tag">${esc(s.type.replace('_','​'))}</span>
      <div class="mcp-actions">
        <button class="mcp-btn" title="Refresh tools" onclick="event.stopPropagation();refreshMcp('${s.id}','${esc(s.name)}')">↺</button>
        <button class="mcp-btn" title="Delete server" onclick="event.stopPropagation();deleteMcp('${s.id}','${esc(s.name)}')">✕</button>
      </div>
    </div>
    <div class="mcp-tools-panel" id="mcp-panel-${s.id}">
      <div class="mcp-loading">Loading tools…</div>
    </div>`;
  container.appendChild(item);
}

async function toggleMcpTools(serverId, rowEl) {
  const panel = document.getElementById(`mcp-panel-${serverId}`);
  const chev  = document.getElementById(`chev-${serverId}`);
  const isOpen = panel.classList.contains('open');
  panel.classList.toggle('open', !isOpen);
  chev.classList.toggle('open', !isOpen);

  if (!isOpen && panel.querySelector('.mcp-loading')) {
    try {
      const tools = await api(`/api/mcp-servers/${serverId}/tools`);
      panel.innerHTML = '';
      if (tools.error) { panel.innerHTML = `<div class="mcp-empty">${esc(tools.error)}</div>`; return; }
      if (!tools.length) { panel.innerHTML = '<div class="mcp-empty">No tools found</div>'; return; }
      tools.forEach(t => {
        const row = document.createElement('div');
        row.className = 'mcp-tool-row';
        row.innerHTML = `<span class="mcp-tool-name-text">${esc(t.name)}</span>${t.description ? `<span class="mcp-tool-desc" title="${esc(t.description)}">${esc(t.description.slice(0,60))}${t.description.length>60?'…':''}</span>` : ''}`;
        panel.appendChild(row);
      });
    } catch(e) { panel.innerHTML = `<div class="mcp-empty">${esc(e.message)}</div>`; }
  }
}

async function refreshMcp(serverId, name) {
  try {
    const panel = document.getElementById(`mcp-panel-${serverId}`);
    panel.innerHTML = '<div class="mcp-loading">Refreshing…</div>';
    panel.classList.add('open');
    document.getElementById(`chev-${serverId}`).classList.add('open');
    await api(`/api/mcp-servers/${serverId}/refresh`, {method:'POST'});
    // Reload tools
    const tools = await api(`/api/mcp-servers/${serverId}/tools`);
    panel.innerHTML = '';
    if (!tools.error && tools.length) {
      tools.forEach(t => {
        const row = document.createElement('div');
        row.className = 'mcp-tool-row';
        row.innerHTML = `<span class="mcp-tool-name-text">${esc(t.name)}</span>`;
        panel.appendChild(row);
      });
    } else {
      panel.innerHTML = '<div class="mcp-empty">No tools</div>';
    }
  } catch(e) { alert('Refresh failed: ' + e.message); }
}

async function deleteMcp(serverId, name) {
  if (!confirm(`Delete MCP server "${name}"?`)) return;
  try {
    const res = await api(`/api/mcp-servers/${serverId}`, {method:'DELETE'});
    if (res.error) { alert('Error: ' + res.error); return; }
    document.querySelector(`.mcp-item[data-id="${serverId}"]`)?.remove();
    const el = document.getElementById('mcp-list');
    if (!el.children.length) el.innerHTML = '<div style="padding:6px 10px;font-size:12px;color:#334155;">No servers registered</div>';
  } catch(e) { alert('Error: ' + e.message); }
}

// ── Register Server Modal ─────────────────────────────────────────────────────

function showRegisterModal() {
  openModal(`
    <h3>Register MCP Server</h3>
    <label class="field-label">Server name</label>
    <input id="rs-name" placeholder="my-server" autocomplete="off">
    <label class="field-label">Transport type</label>
    <select id="rs-type" onchange="updateRegisterForm()">
      <option value="streamable_http">Streamable HTTP</option>
      <option value="sse">SSE</option>
      <option value="stdio">STDIO (local command)</option>
    </select>

    <div id="rs-form-http">
      <label class="field-label">Server URL</label>
      <input id="rs-url" placeholder="http://host:port/mcp" type="url">
      <label class="field-label">Auth token <span style="color:#334155">(optional)</span></label>
      <input id="rs-token" placeholder="Bearer token" type="password">
    </div>

    <div id="rs-form-stdio" style="display:none">
      <label class="field-label">Command</label>
      <input id="rs-cmd" placeholder="node" autocomplete="off">
      <label class="field-label">Arguments <span style="color:#334155">(one per line)</span></label>
      <textarea id="rs-args" placeholder="/path/to/server.js&#10;--port 3000"></textarea>
      <label class="field-label">Env vars <span style="color:#334155">(KEY=value, one per line)</span></label>
      <textarea id="rs-env" placeholder="API_KEY=abc123"></textarea>
    </div>

    <div class="modal-btns">
      <button class="btn-cancel" onclick="closeModal()">Cancel</button>
      <button class="btn-primary" id="rs-submit" onclick="registerServer()">Register</button>
    </div>
  `);
  document.getElementById('rs-name').focus();
}

function updateRegisterForm() {
  const type = document.getElementById('rs-type').value;
  document.getElementById('rs-form-http').style.display  = type !== 'stdio' ? 'block' : 'none';
  document.getElementById('rs-form-stdio').style.display = type === 'stdio' ? 'block' : 'none';
}

async function registerServer() {
  const type = document.getElementById('rs-type').value;
  const name = document.getElementById('rs-name').value.trim();
  if (!name) { alert('Server name is required'); return; }

  const body = { name, type };

  if (type !== 'stdio') {
    const url = document.getElementById('rs-url').value.trim();
    if (!url) { alert('Server URL is required'); return; }
    body.url = url;
    const tok = document.getElementById('rs-token').value.trim();
    if (tok) body.auth_token = tok;
  } else {
    const cmd = document.getElementById('rs-cmd').value.trim();
    if (!cmd) { alert('Command is required'); return; }
    body.command = cmd;
    body.args = document.getElementById('rs-args').value.trim().split('\n').map(s => s.trim()).filter(Boolean);
    const envLines = document.getElementById('rs-env').value.trim().split('\n').filter(Boolean);
    if (envLines.length) {
      body.env = {};
      envLines.forEach(l => { const eq = l.indexOf('='); if (eq>0) body.env[l.slice(0,eq).trim()] = l.slice(eq+1).trim(); });
    }
  }

  setSubmitState('rs-submit', true, 'Registering…');
  try {
    const server = await api('/api/mcp-servers', {method:'POST', json:body});
    if (server.error) { alert('Error: ' + server.error); setSubmitState('rs-submit', false, 'Register'); return; }
    closeModal();
    const el = document.getElementById('mcp-list');
    if (el.querySelector('div[style]')) el.innerHTML = '';  // clear "no servers" msg
    renderMcpServer(server, el);
  } catch(e) { alert('Error: ' + e.message); setSubmitState('rs-submit', false, 'Register'); }
}

// ── Create Agent Modal ────────────────────────────────────────────────────────

async function showCreateModal() {
  openModal(`
    <h3>New Agent</h3>
    <label class="field-label">Name</label>
    <input id="ca-name" value="Chat Agent" autocomplete="off">
    <label class="field-label">Model</label>
    <select id="ca-model"><option disabled>Loading models…</option></select>
    <label class="field-label">Persona</label>
    <input id="ca-persona" value="I am a helpful AI assistant." autocomplete="off">

    <div class="tools-section">
      <h4>Built-in Tools</h4>
      <div class="tool-checks">
        <label class="tool-check"><input type="checkbox" value="web_search" checked> web_search</label>
        <label class="tool-check"><input type="checkbox" value="run_code" checked> run_code</label>
      </div>

      <h4>MCP Tools</h4>
      <div id="ca-mcp-tools"><div class="mcp-loading-msg">Loading MCP servers…</div></div>
    </div>

    <div class="modal-btns">
      <button class="btn-cancel" onclick="closeModal()">Cancel</button>
      <button class="btn-primary" id="ca-submit" onclick="createAgent()">Create</button>
    </div>
  `);
  document.getElementById('ca-name').focus();

  // Populate model dropdown from live Letta API
  try {
    const modelsData = await api('/api/models');
    const sel = document.getElementById('ca-model');
    if (sel && modelsData && !modelsData.error && modelsData.length) {
      const groups = {};
      modelsData.forEach(m => {
        if (!groups[m.provider]) groups[m.provider] = [];
        groups[m.provider].push(m);
      });
      sel.innerHTML = '';
      Object.keys(groups).sort().forEach(provider => {
        const og = document.createElement('optgroup');
        og.label = provider;
        groups[provider].forEach(m => {
          const opt = document.createElement('option');
          opt.value = m.handle;
          opt.textContent = m.display_name;
          if (m.handle === 'anthropic/claude-sonnet-4-6') opt.selected = true;
          og.appendChild(opt);
        });
        sel.appendChild(og);
      });
      if (!sel.value) sel.selectedIndex = 0;
    }
  } catch(e) {
    const sel = document.getElementById('ca-model');
    if (sel) sel.innerHTML = '<option value="openai/gpt-4.1">gpt-4.1 (fallback)</option>';
  }

  // Load MCP servers + their tools in parallel
  try {
    const servers = await api('/api/mcp-servers');
    const mcpEl = document.getElementById('ca-mcp-tools');
    if (!mcpEl) return; // modal was closed
    if (servers.error || !servers.length) {
      mcpEl.innerHTML = '<div class="mcp-loading-msg" style="color:#334155">No MCP servers registered</div>';
      return;
    }
    const withTools = await Promise.all(servers.map(async s => {
      try { const t = await api(`/api/mcp-servers/${s.id}/tools`); return {...s, tools: t.error ? [] : t}; }
      catch { return {...s, tools: []}; }
    }));
    if (!mcpEl.isConnected) return;
    mcpEl.innerHTML = '';
    withTools.forEach((s, si) => {
      if (!s.tools.length) return;
      const group = document.createElement('div');
      group.className = 'mcp-tool-group';
      const chevId = `ca-chev-${si}`;
      const listId = `ca-list-${si}`;
      group.innerHTML = `
        <div class="mcp-tool-group-hdr" onclick="toggleCaGroup('${listId}','${chevId}')">
          <span class="mcp-tg-chev open" id="${chevId}">▶</span>
          <span class="mcp-tg-name">${esc(s.name)}</span>
          <span class="mcp-tg-badge">${esc(s.type)}</span>
          <span style="font-size:11px;color:#475569">${s.tools.length} tool${s.tools.length!==1?'s':''}</span>
        </div>
        <div class="mcp-tool-list open" id="${listId}">
          ${s.tools.map(t => `
            <label class="mcp-tool-check">
              <input type="checkbox" name="mcp-tool" value="${esc(t.id)}">
              <div class="mcp-tool-check-info">
                <div>${esc(t.name)}</div>
                ${t.description ? `<div class="mcp-tool-check-desc">${esc(t.description.slice(0,80))}${t.description.length>80?'…':''}</div>` : ''}
              </div>
            </label>`).join('')}
        </div>`;
      mcpEl.appendChild(group);
    });
    if (!mcpEl.children.length) mcpEl.innerHTML = '<div class="mcp-loading-msg" style="color:#334155">No tools available from registered servers</div>';
  } catch(e) {
    const mcpEl = document.getElementById('ca-mcp-tools');
    if (mcpEl) mcpEl.innerHTML = `<div class="mcp-loading-msg" style="color:#ef4444">${esc(e.message)}</div>`;
  }
}

function toggleCaGroup(listId, chevId) {
  document.getElementById(listId).classList.toggle('open');
  document.getElementById(chevId).classList.toggle('open');
}

async function createAgent() {
  const name    = document.getElementById('ca-name').value.trim() || 'Chat Agent';
  const model   = document.getElementById('ca-model').value;
  const persona = document.getElementById('ca-persona').value.trim() || 'I am a helpful AI assistant.';

  const tools = [...document.querySelectorAll('.tool-checks input:checked')].map(el => el.value);
  const toolIds = [...document.querySelectorAll('input[name="mcp-tool"]:checked')].map(el => el.value);

  setSubmitState('ca-submit', true, 'Creating…');
  try {
    const agent = await api('/api/agents', {method:'POST', json:{name, model, persona, tools, tool_ids: toolIds}});
    if (agent.error) { alert('Error: ' + agent.error); setSubmitState('ca-submit', false, 'Create'); return; }
    closeModal();
    await loadAgents();
    selectAgent(agent.id, agent.name);
  } catch(e) { alert('Error: ' + e.message); setSubmitState('ca-submit', false, 'Create'); }
}

// ── Chat ──────────────────────────────────────────────────────────────────────

function renderMessages(messages) {
  let i = 0;
  while (i < messages.length) {
    const m = messages[i];
    const t = (m.type||'').toLowerCase();
    if (t === 'user_message') { appendBubble('user', m.content||''); i++; }
    else if (t === 'assistant_message') { appendBubble('assistant', m.content||''); i++; }
    else if (t.includes('tool_') || t.includes('reasoning') || t.includes('thinking') || t.includes('internal_monologue')) {
      const group = [];
      while (i < messages.length) {
        const tt = (messages[i].type||'').toLowerCase();
        if (tt.includes('tool_') || tt.includes('reasoning') || tt.includes('thinking') || tt.includes('internal_monologue')) {
          group.push(messages[i]); i++;
        } else break;
      }
      appendToolGroup(group);
    } else { i++; }
  }
}

function appendBubble(role, content) {
  const el = document.getElementById('messages');
  const row = document.createElement('div');
  row.className = `msg-row ${role}`;
  const rendered = role === 'assistant' ? marked.parse(content) : `<p>${esc(content).replace(/\n/g,'<br>')}</p>`;
  row.innerHTML = `<div class="msg-label">${role==='user'?'You':'Assistant'}</div><div class="msg-bubble">${rendered}</div>`;
  el.appendChild(row);
  if (typeof Prism !== 'undefined') {
    Prism.highlightAllUnder(row);
  }
  row.querySelectorAll('pre').forEach(pre => {
    const codeText = pre.textContent || '';
    const wrapper = document.createElement('div');
    wrapper.style.cssText = 'position:relative;';

    const button = document.createElement('button');
    button.className = 'code-copy-btn';
    button.style.cssText = 'position:absolute;top:8px;right:8px;padding:4px 8px;background:#334155;border:none;border-radius:4px;color:#94a3b8;cursor:pointer;font-size:11px;opacity:0;transition:opacity 0.2s;';
    button.textContent = 'Copy';
    button.addEventListener('click', e => {
      e.stopPropagation();
      copyToClipboard(codeText, button);
    });

    pre.parentElement.insertBefore(wrapper, pre);
    wrapper.appendChild(button);
    wrapper.appendChild(pre);
    wrapper.addEventListener('mouseenter', () => { button.style.opacity = '0.6'; });
    wrapper.addEventListener('mouseleave', () => { button.style.opacity = '0'; });
  });
  return row;
}

function appendToolGroup(msgs) {
  const el = document.getElementById('messages');
  const wrap = document.createElement('div');
  wrap.className = 'tool-group';
  msgs.forEach(m => {
    const t = (m.type||'').toLowerCase();
    let icon, title, body;
    if (t.includes('tool_call')) {
      icon = '🔧'; title = m.tool_name || 'Tool call';
      body = m.tool_args ? tryFmt(m.tool_args) : '';
    } else if (t.includes('tool_return')) {
      icon = '↩'; title = 'Tool result'; body = m.tool_return || m.content || '';
    } else {
      icon = '💭'; title = 'Reasoning'; body = m.content || '';
    }
    if (!body) return;
    const card = document.createElement('div');
    card.className = 'tool-card';
    card.innerHTML = `
      <div class="tool-card-hdr" onclick="toggleCard(this)">
        <span>${icon}</span>
        <span class="tool-card-title">${esc(title)}</span>
        <button class="tool-card-copy" onclick="event.stopPropagation();copyFromCard(this)">Copy</button>
        <span class="tool-card-chev">▼</span>
      </div>
      <div class="tool-card-body">${esc(body)}</div>`;
    wrap.appendChild(card);
  });
  if (wrap.children.length) el.appendChild(wrap);
}

function toggleCard(hdr) {
  hdr.classList.toggle('expanded');
  hdr.nextElementSibling.classList.toggle('open');
}

function copyToClipboard(text, button) {
  navigator.clipboard.writeText(text).then(() => {
    if (!button) return;
    const originalText = button.textContent;
    button.textContent = 'Copied!';
    setTimeout(() => { button.textContent = originalText; }, 1200);
  }).catch(err => alert('Failed to copy: ' + err));
}

function copyFromCard(button) {
  const bodyEl = button.closest('.tool-card')?.querySelector('.tool-card-body');
  copyToClipboard(bodyEl ? bodyEl.textContent : '', button);
}

async function send() {
  if (busy || !agentId) return;
  const input = document.getElementById('msg-input');
  const text  = input.value.trim();
  if (!text) return;
  busy = true;
  input.value = ''; input.style.height = 'auto';
  document.getElementById('send-btn').disabled = true;

  const msgsEl = document.getElementById('messages');
  const emptyState = document.getElementById('empty-state');
  if (emptyState) emptyState.remove();

  appendBubble('user', text);

  // Optimistically update this conversation's summary card on first message
  if (convId) {
    const card = document.querySelector(`.conv-card[data-conv-id="${convId}"] .conv-summary`);
    if (card && card.textContent.trim() === 'New conversation') {
      card.textContent = text.slice(0, 60) + (text.length > 60 ? '…' : '');
    }
  }

  const typing = document.createElement('div');
  typing.className = 'typing-wrap';
  typing.innerHTML = '<div class="typing-label">Assistant</div><div class="typing-bubble"><div class="dot"></div><div class="dot"></div><div class="dot"></div></div>';
  msgsEl.appendChild(typing);
  scrollBottom();

  try {
    const url = convId
      ? `/api/conversations/${convId}/messages`
      : `/api/agents/${agentId}/messages`;
    const data = await api(url, {method:'POST', json:{content:text}});
    typing.remove();
    if (data.error) appendBubble('assistant', `⚠ ${data.error}`);
    else renderMessages(data.messages || []);
  } catch(e) {
    typing.remove(); appendBubble('assistant', `⚠ ${e.message}`);
  }
  busy = false;
  document.getElementById('send-btn').disabled = false;
  scrollBottom();
  input.focus();
}

// ── Utilities ─────────────────────────────────────────────────────────────────

function tryFmt(s) { try { return JSON.stringify(JSON.parse(s), null, 2); } catch { return s; } }
function esc(s) { return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }
function err(msg) { return `<div style="padding:8px 10px;font-size:12px;color:#ef4444;">${esc(msg)}</div>`; }
function scrollBottom() { const e = document.getElementById('messages'); e.scrollTop = e.scrollHeight; }

async function api(url, {method='GET', json}={}) {
  const opts = {method, headers:{}};
  if (json) { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(json); }
  const res = await fetch(url, opts);
  return res.json();
}

function openModal(html) {
  closeModal();
  const overlay = document.createElement('div');
  overlay.className = 'overlay';
  overlay.id = 'modal-overlay';
  overlay.innerHTML = `<div class="modal">${html}</div>`;
  overlay.addEventListener('click', e => { if (e.target === overlay) closeModal(); });
  document.body.appendChild(overlay);
}

function closeModal() {
  document.getElementById('modal-overlay')?.remove();
}

function setSubmitState(id, disabled, label) {
  const btn = document.getElementById(id);
  if (!btn) return;
  btn.disabled = disabled;
  btn.textContent = label;
}

// ── Input wiring ──────────────────────────────────────────────────────────────

document.getElementById('msg-input').addEventListener('input', function() {
  this.style.height = 'auto';
  this.style.height = Math.min(this.scrollHeight, 180) + 'px';
});
document.getElementById('msg-input').addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
});
document.getElementById('send-btn').addEventListener('click', send);

// ── Boot ──────────────────────────────────────────────────────────────────────
loadAgents();
loadMcpServers();
</script>
</body>
</html>"""


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    print(f"\n  Letta Chat UI → http://localhost:{port}\n")
    app.run(host="0.0.0.0", port=port, debug=False)
