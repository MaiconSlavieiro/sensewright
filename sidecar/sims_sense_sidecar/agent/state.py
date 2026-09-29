"""Agent state types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4


@dataclass
class Turn:
    """A single conversation turn."""

    id: str = field(default_factory=lambda: str(uuid4()))
    user_message: str = ""
    assistant_reply: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tool_results: list[dict[str, Any]] = field(default_factory=list)
    timestamp: float = 0.0
    lang: str = "en"


@dataclass
class AgentState:
    """Per-Sim agent state."""

    sim_id: str  # "player_id:save_id:sim_id"
    profile: dict[str, Any] = field(default_factory=dict)
    turns: list[Turn] = field(default_factory=list)
    autonomy_level: str = "semi"
    lang: str = "en"
    pending_tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tool_results: list[dict[str, Any]] = field(default_factory=list)

    def add_turn(self, turn: Turn) -> None:
        self.turns.append(turn)
        # Keep last 20 turns
        if len(self.turns) > 20:
            self.turns = self.turns[-20:]

    def set_pending_tool_calls(self, calls: list[dict[str, Any]]) -> None:
        """Replace the pending tool calls awaiting execution by the mod."""
        self.pending_tool_calls = [dict(call) for call in calls]

    def resolve_tool_call(
        self,
        tool_call_id: str,
        ok: bool,
        result: Any = None,
        error: str | None = None,
    ) -> dict[str, Any] | None:
        """Mark a pending tool call resolved; return the call, or None if unknown."""
        for index, call in enumerate(self.pending_tool_calls):
            if call.get("id") == tool_call_id:
                resolved = self.pending_tool_calls.pop(index)
                resolved["status"] = "ok" if ok else "failed"
                resolved["ok"] = ok
                resolved["result"] = result
                resolved["error"] = error
                self.tool_results.append(resolved)
                if len(self.tool_results) > 50:
                    self.tool_results = self.tool_results[-50:]
                return resolved
        return None

    def pending_tool_ids(self) -> list[str]:
        """IDs of the tool calls still awaiting a result."""
        return [str(call.get("id", "")) for call in self.pending_tool_calls]

    def get_recent_context(self, max_turns: int = 5) -> list[dict[str, str]]:
        """Get recent conversation context as message list."""
        messages = []
        for turn in self.turns[-max_turns:]:
            if turn.user_message:
                messages.append({"role": "user", "content": turn.user_message})
            if turn.assistant_reply:
                messages.append({"role": "assistant", "content": turn.assistant_reply})
        return messages