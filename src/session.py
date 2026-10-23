"""WebSocket session manager for Foam-Agent.

Bridges NullFlux frontend protocol to Foam-Agent's LangGraph workflow.
"""

import asyncio
import json
import time
from pathlib import Path
from typing import Any, Optional

from fastapi import WebSocket

from services.checkpoint import auto_commit, log_recent, init_repo
from services.parallel_dispatch import dispatch_tools
from config import Config
from utils import LLMService


class Session:
    """Per-connection session state."""

    def __init__(self, ws: WebSocket, config: Config):
        self.ws = ws
        self.config = config
        self.auto_mode = True
        self.aborted = False
        self.running = False
        self.case_dir: Optional[str] = None
        self.llm_service = LLMService(config)

    async def send(self, msg: dict) -> None:
        """Send JSON message to frontend."""
        try:
            await self.ws.send_json(msg)
        except Exception:
            pass

    async def send_term(self, line: str) -> None:
        await self.send({"type": "term", "line": line})

    async def send_phase(self, phase: str, detail: str, tool: str = "") -> None:
        await self.send({"type": "agent_phase", "phase": phase, "detail": detail, "tool": tool})

    async def send_tool_call(self, id: str, name: str, args: dict) -> None:
        await self.send({"type": "tool_call", "id": id, "name": name, "args": args})

    async def send_tool_result(self, id: str, name: str, result: Any) -> None:
        await self.send({"type": "tool_result", "id": id, "name": name, "result": str(result)})

    async def send_delta(self, text: str) -> None:
        await self.send({"type": "delta", "text": text})

    async def send_usage(self, usage: dict) -> None:
        await self.send({"type": "usage", "usage": usage})

    async def send_checkpoints(self) -> None:
        if self.case_dir and Path(self.case_dir).exists():
            commits = await log_recent(Path(self.case_dir), n=20)
            await self.send({"type": "checkpoints", "list": commits})


class SessionManager:
    """Manages all WebSocket sessions."""

    def __init__(self):
        self.sessions: dict[str, Session] = {}

    def create(self, ws: WebSocket, config: Config) -> Session:
        session = Session(ws, config)
        # Use id(ws) as key since WebSocket objects are unique
        self.sessions[str(id(ws))] = session
        return session

    def remove(self, ws: WebSocket) -> None:
        self.sessions.pop(str(id(ws)), None)

    def get(self, ws: WebSocket) -> Optional[Session]:
        return self.sessions.get(str(id(ws)))
