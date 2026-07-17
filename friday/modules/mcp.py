"""
MCP Module — Model Context Protocol Support

Implements an MCP server that exposes FRIDAY tools as MCP-compatible endpoints.
This allows external AI agents/clients to use FRIDAY capabilities via MCP protocol.

MCP Spec: https://modelcontextprotocol.io
"""

import json
from typing import Any
from loguru import logger
from friday.modules import search, news, memory, image, music


# --- MCP Tool Registry ---
MCP_TOOLS: list[dict[str, Any]] = [
    {
        "name": "web_search",
        "description": "Search the web for current information using DuckDuckGo",
        "inputSchema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Search query"}},
            "required": ["query"],
        },
    },
    {
        "name": "fetch_news",
        "description": "Get latest news headlines on a topic",
        "inputSchema": {
            "type": "object",
            "properties": {"topic": {"type": "string", "description": "News topic"}},
            "required": ["topic"],
        },
    },
    {
        "name": "generate_image",
        "description": "Generate an AI image from a text description",
        "inputSchema": {
            "type": "object",
            "properties": {"prompt": {"type": "string", "description": "Image description"}},
            "required": ["prompt"],
        },
    },
    {
        "name": "play_music",
        "description": "Get YouTube URL for a song",
        "inputSchema": {
            "type": "object",
            "properties": {"song": {"type": "string", "description": "Song name and artist"}},
            "required": ["song"],
        },
    },
    {
        "name": "store_memory",
        "description": "Store a personal memory/fact for the user",
        "inputSchema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "What to remember"},
                "category": {"type": "string", "description": "Category (preference, fact, general)"},
            },
            "required": ["content"],
        },
    },
    {
        "name": "recall_memories",
        "description": "Recall stored memories for the user",
        "inputSchema": {
            "type": "object",
            "properties": {"user_id": {"type": "string", "description": "User ID"}},
            "required": ["user_id"],
        },
    },
]


def list_tools() -> list[dict[str, Any]]:
    """List all available MCP tools."""
    return MCP_TOOLS


def call_tool(name: str, arguments: dict[str, Any], user_id: str = "default") -> dict[str, Any]:
    """Execute an MCP tool by name with given arguments."""
    logger.info(f"MCP tool call: {name}({arguments})")

    try:
        if name == "web_search":
            result = search.web_search(arguments["query"])
            return {"content": [{"type": "text", "text": result or "No results found."}]}

        elif name == "fetch_news":
            result = news.fetch_news(arguments["topic"])
            return {"content": [{"type": "text", "text": result or "No news found."}]}

        elif name == "generate_image":
            url = image.generate_image_url(arguments["prompt"])
            return {"content": [{"type": "image", "data": url}, {"type": "text", "text": f"Image generated: {url}"}]}

        elif name == "play_music":
            url = music.get_youtube_url(arguments["song"])
            return {"content": [{"type": "text", "text": f"Music URL: {url}"}]}

        elif name == "store_memory":
            result = memory.add_memory(user_id, arguments["content"], arguments.get("category", "general"))
            return {"content": [{"type": "text", "text": f"Stored: {arguments['content']}"}]}

        elif name == "recall_memories":
            uid = arguments.get("user_id", user_id)
            memories = memory.get_memories(uid)
            text = "\n".join(f"- {m['content']} ({m['category']})" for m in memories) or "No memories stored."
            return {"content": [{"type": "text", "text": text}]}

        else:
            return {"content": [{"type": "text", "text": f"Unknown tool: {name}"}], "isError": True}

    except Exception as e:
        logger.error(f"MCP tool error: {e}")
        return {"content": [{"type": "text", "text": f"Tool error: {str(e)}"}], "isError": True}


def handle_mcp_request(request_body: dict) -> dict:
    """Handle a full MCP JSON-RPC request."""
    method = request_body.get("method", "")
    params = request_body.get("params", {})
    req_id = request_body.get("id", 1)

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "friday-mcp", "version": "2.0.0"},
            },
        }

    elif method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"tools": list_tools()},
        }

    elif method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})
        result = call_tool(tool_name, arguments)
        return {"jsonrpc": "2.0", "id": req_id, "result": result}

    else:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }
