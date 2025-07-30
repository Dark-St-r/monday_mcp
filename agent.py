"""
monday-bot/agent.py
Minimal Google ADK agent that can call
1. Make.com MCP (SSE)
2. Monday.com MCP (SSE)
Goal: "Do Monday automations via natural language."
"""
import os
import json
import logging
import asyncio
import requests
from typing import Any, Dict, List

from google.adk.agents import LlmAgent
from google.adk.tools import FunctionTool
from google.adk.sessions import InMemorySessionService
from google.adk.runners import Runner
from google.generativeai import configure

# ---------- 0. Configure Gemini via AI Studio ----------
configure(api_key=os.environ.get("GOOGLE_API_KEY", "MONDAY_API_TOKEN"))

# ---------- 1. Helper: SSE MCP -> list[FunctionTool] ----------
def build_sse_tools(endpoint: str, name_prefix: str, headers: Dict[str, str] = None) -> List[FunctionTool]:
    """
    Pull the tool manifest from an SSE MCP endpoint and
    turn every listed tool into a Google ADK FunctionTool.
    """
    try:
        headers = headers or {}
        handshake = requests.get(f"{endpoint}/mcp", headers=headers, timeout=10).json()
        tools = []

        for t in handshake.get("tools", []):
            def make_call(input_json: str) -> str:
                payload = {"tool": t["name"], "arguments": json.loads(input_json)}
                resp = requests.post(f"{endpoint}/call", json=payload, headers=headers, timeout=15)
                resp.raise_for_status()
                return resp.text

            tool_name = f"{name_prefix}_{t['name']}"
            make_call.__name__ = tool_name
            
            tools.append(
                FunctionTool(
                    function=make_call,
                    name=tool_name,
                    description=t["description"],
                    parameters=t["inputSchema"],
                )
            )
        return tools
    except Exception as e:
        logging.warning(f"Failed to load tools from {endpoint}: {e}")
        return []

# ---------- 2. Build the two MCP tool bundles ----------
# Get Monday.com auth token from environment
monday_token = os.environ.get("MONDAY_API_TOKEN", "")
# New monday.com MCP server with Bearer token authentication
monday_headers = {"Authorization": f"Bearer {monday_token}"} if monday_token else {}

make_tools   = build_sse_tools(
    "https://us2.make.com/mcp/api/v1/u/12508d4f-a637-469c-8821-9c16667c0f41/sse",
    "make"
)
# Updated monday_tools using the new MCP server configuration
monday_tools = build_sse_tools(
    "https://mcp.monday.com/sse",
    "monday",
    monday_headers
)

# ---------- 3. Create the ADK agent ----------
agent = LlmAgent(
    name="monday_bot",
    model="gemini-2.0-flash",
    instruction=(
        "You are a helpful assistant that can automate Monday.com boards "
        "by invoking Make.com scenarios and Monday.com native actions. "
        "Keep answers brief."
    ),
    tools=make_tools + monday_tools,
)

# ---------- 4. Async CLI chat loop ----------
async def main():
    logging.basicConfig(level=logging.INFO)
    session_service = InMemorySessionService()
    runner = Runner(
        agent=agent,
        session_service=session_service,
        app_name="monday_bot"
    )

    session_id = "cli"
    user_id = "dev"

    # Create session if it doesn't exist
    try:
        session = await session_service.get_session(session_id)
    except:
        session = await session_service.create_session(
            session_id=session_id, 
            user_id=user_id, 
            app_name="monday_bot"
        )

    print("🤖  Monday-bot ready.  Type 'quit' to exit.\n")
    while True:
        user = input("> ")
        if user.strip().lower() in {"quit", "exit"}:
            break
        
        try:
            # Fix: Use proper message format for ADK Runner
            from google.adk.sessions import UserMessage
            
            message = UserMessage(content=user)
            events = runner.run_async(
                session_id=session_id,
                user_id=user_id,
                message=message,  # Changed from new_message to message
            )
            
            # Process the async generator to get the final response
            final_response = ""
            async for event in events:
                if hasattr(event, 'content') and event.content:
                    final_response = event.content
                elif hasattr(event, 'text'):
                    final_response = event.text
            
            print(final_response or "No response received.")
            
        except Exception as e:
            print(f"Error: {e}")
            print("Please make sure your GOOGLE_API_KEY is set and the MCP endpoints are accessible.")

if __name__ == "__main__":
    asyncio.run(main())
