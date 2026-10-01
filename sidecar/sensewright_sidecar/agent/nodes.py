"""Agent graph nodes."""

from __future__ import annotations

import logging
from typing import Any

from ..llm import LLMResponse, ProviderRegistry
from ..memory import MemKey, MemoryStore
from ..schemas import ChatRequest, ChatResponse, HeyRequest, ToolCall, ToolResultRequest
from ..tools.rails import DirectiveRails
from ..tools.registry import get_tool_schemas
from .prompts import build_hey_prompt, build_system_prompt, split_thought, strip_thought
from .state import AgentState, Turn

logger = logging.getLogger(__name__)


class AgentNodes:
    """Container for agent graph nodes with shared dependencies."""

    def __init__(
        self,
        registry: ProviderRegistry,
        memory: MemoryStore,
        default_autonomy: str = "semi",
        default_lang: str = "en",
        rails: DirectiveRails | None = None,
        dejavu_chance: float = 0.05,
        memory_enabled: bool = True,
    ):
        self.registry = registry
        self.memory = memory
        self.default_autonomy = default_autonomy
        self.default_lang = default_lang
        self.rails = rails
        # M2: probability a forgotten memory resurfaces as a déjà vu hint.
        try:
            self.dejavu_chance = min(1.0, max(0.0, float(dejavu_chance)))
        except (TypeError, ValueError):
            self.dejavu_chance = 0.05
        # v0.3 §15.11: the memory layer can be disabled (native deterministic mode).
        self.memory_enabled = bool(memory_enabled)
        self._states: dict[str, AgentState] = {}

    def _get_state(self, sim_key: str) -> AgentState:
        if sim_key not in self._states:
            self._states[sim_key] = AgentState(
                sim_id=sim_key,
                autonomy_level=self.default_autonomy,
                lang=self.default_lang,
            )
        return self._states[sim_key]

    def _parse_sim_key(self, sim) -> str:
        return f"{sim.player_id}:{sim.save_id}:{sim.sim_id}"

    def _parse_mem_key(self, sim) -> MemKey:
        return MemKey(player_id=sim.player_id, save_id=sim.save_id, sim_id=sim.sim_id)

    async def recall_node(self, req: ChatRequest | HeyRequest) -> dict[str, Any]:
        """Recall recent memories and profile for the Sim."""
        sim_key = self._parse_sim_key(req.sim)
        mem_key = self._parse_mem_key(req.sim)
        state = self._get_state(sim_key)

        # Load profile from memory if not in state
        if not state.profile:
            profile = await self.memory.get_profile(mem_key)
            if profile:
                state.profile = profile

        # Get recent events
        events: list[dict[str, Any]] = []
        if self.memory_enabled:
            events = await self.memory.recent_events(mem_key, limit=10)

            # M2: revisiting is remembering — touch the memories used in context.
            event_ids = [
                event.get("id")
                for event in events
                if isinstance(event, dict) and event.get("id") is not None
            ]
            if event_ids:
                try:
                    await self.memory.touch_events(mem_key, event_ids)
                except Exception:
                    pass

            # M2: a forgotten memory may resurface as a subtle déjà vu hint.
            hint = await self._dejavu_hint(mem_key)
            if hint:
                events = list(events) + [
                    {
                        "type": "dejavu",
                        "content": {"message": hint},
                        "importance": 0.2,
                        "strength": 0.1,
                    }
                ]

        return {
            "state": state,
            "mem_key": mem_key,
            "profile": state.profile,
            "recent_events": events,
            "lang": req.lang or self.default_lang,
        }

    async def _dejavu_hint(self, mem_key: MemKey) -> str:
        """Rarely surface a forgotten memory as a truncated déjà vu hint."""
        import random

        if not self.memory_enabled or self.dejavu_chance <= 0.0:
            return ""
        if random.random() >= self.dejavu_chance:
            return ""
        try:
            candidates = await self.memory.recent_events(mem_key, limit=50, min_strength=0.0)
        except Exception:
            return ""
        weak = [event for event in candidates if float(event.get("strength") or 1.0) < 0.2]
        if not weak:
            return ""
        from ..memory.decay import dejavu_hint as _hint

        text = self._event_text(weak[-1])
        return _hint(text) if text else ""

    @staticmethod
    def _event_text(event: dict[str, Any]) -> str:
        content = event.get("content")
        if isinstance(content, dict):
            for key in ("message", "text", "summary"):
                value = content.get(key)
                if value:
                    return str(value)
        return ""

    async def build_prompt_node(self, recall_result: dict[str, Any], req: ChatRequest) -> dict[str, Any]:
        """Build the system prompt with context."""
        state = recall_result["state"]
        profile = recall_result["profile"]
        lang = recall_result["lang"]

        # Build context from request and events
        context = {
            "world_time": req.context.get("world_time", "unknown"),
            "location": req.context.get("location", "unknown"),
            "mood": req.context.get("mood", "neutral"),
            "needs": req.context.get("needs", {}),
            # Who the Sim is talking to and how well it knows them shapes what is
            # spoken (the private thought is always free). Best-effort: the mod may
            # not send these yet.
            "audience": req.context.get("audience", "someone"),
            "intimacy": req.context.get("intimacy", "a stranger / unknown"),
        }

        # Get tool schemas for autonomy level
        tool_schemas = get_tool_schemas(state.autonomy_level)
        tools_desc = self._format_tools(tool_schemas)

        system_prompt = build_system_prompt(
            profile=profile,
            lang=lang,
            autonomy=state.autonomy_level,
            context=context,
            tools_description=tools_desc,
            memory_context=self._format_memories(recall_result.get("recent_events") or []),
        )

        # Build message history
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(state.get_recent_context(max_turns=5))
        messages.append({"role": "user", "content": req.message})

        return {
            **recall_result,
            "messages": messages,
            "system_prompt": system_prompt,
            "tool_schemas": tool_schemas,
            "tools": list(tool_schemas.values()),
        }

    async def build_hey_prompt_node(self, recall_result: dict[str, Any], req: HeyRequest) -> dict[str, Any]:
        """Build the prompt for a spontaneous hey."""
        profile = recall_result["profile"]
        lang = recall_result["lang"]
        context = {
            "world_time": req.context.get("world_time", "unknown"),
            "location": req.context.get("location", "unknown"),
            "mood": req.context.get("mood", "neutral"),
        }
        prompt = build_hey_prompt(profile=profile, lang=lang, context=context)
        messages = [{"role": "system", "content": prompt}]
        return {
            **recall_result,
            "messages": messages,
        }

    async def llm_node(self, prompt_result: dict[str, Any]) -> dict[str, Any]:
        """Call the LLM via registry."""
        messages = prompt_result["messages"]
        lang = prompt_result["lang"]

        tools = prompt_result.get("tools") or None
        try:
            response: LLMResponse = await self.registry.complete(
                messages,
                lang=lang,
                temperature=None,  # uses settings default
                max_tokens=None,   # uses settings default
                tools=tools,
            )
            return {
                **prompt_result,
                "llm_response": response,
                "error": None,
            }
        except Exception as e:
            logger.warning(f"LLM call failed: {e}")
            return {
                **prompt_result,
                "llm_response": None,
                "error": e,
            }

    async def persist_node(self, llm_result: dict[str, Any], req: ChatRequest | HeyRequest) -> dict[str, Any]:
        """Persist the conversation turn and any events."""
        state = llm_result["state"]
        mem_key = llm_result["mem_key"]
        response = llm_result.get("llm_response")

        # fase-3: the model answers in two channels. Record the private thought as
        # its own event (so life/memory evolve) and only ever speak `spoken`.
        thought, spoken = split_thought(response.text if response else "")

        turn = Turn(
            user_message=req.message if isinstance(req, ChatRequest) else "",
            assistant_reply=spoken,
            timestamp=__import__("time").time(),
            lang=llm_result["lang"],
        )

        if response:
            if thought:
                await self.memory.add_event(mem_key, {
                    "type": "thought",
                    "content": {"text": thought, "kind": "chat"},
                    "importance": 0.5,
                })
            # Add the spoken reply as event
            await self.memory.add_event(mem_key, {
                "type": "chat",
                "content": {"role": "assistant", "message": spoken},
                "importance": 0.5,
            })
            # Add user message as event
            if isinstance(req, ChatRequest):
                await self.memory.add_event(mem_key, {
                    "type": "chat",
                    "content": {"role": "user", "message": req.message},
                    "importance": 0.5,
                })

        state.add_turn(turn)

        return {
            **llm_result,
            "turn": turn,
            "spoken_text": spoken,
            "thought": thought,
        }

    async def format_response_node(self, persist_result: dict[str, Any]) -> ChatResponse:
        """Format the final ChatResponse, gating tool calls through the rails.

        Tool calls denied by the rails are dropped and recorded as events; the
        remaining calls are returned to the mod for local execution.
        """
        response = persist_result.get("llm_response")

        if not response:
            # No LLM available or error - return native fallback
            return ChatResponse(
                reply="",
                provider=None,
                model=None,
                message_key="notify.no_llm_native",
                message_args={},
            )

        state: AgentState = persist_result["state"]
        mem_key: MemKey = persist_result["mem_key"]

        allowed: list[ToolCall] = []
        denied: list[str] = []
        for call in response.tool_calls:
            if self.rails is not None:
                decision = self.rails.check(str(mem_key), call.name)
                if not decision.allowed:
                    denied.append(call.name)
                    continue
            allowed.append(ToolCall(id=call.id, name=call.name, args=call.arguments))
            if self.rails is not None:
                self.rails.note_executed(str(mem_key), call.name)

        if allowed:
            state.set_pending_tool_calls(
                [
                    {"id": call.id, "name": call.name, "args": call.args, "status": "pending"}
                    for call in allowed
                ]
            )

        for tool_name in denied:
            await self.memory.add_event(
                mem_key,
                {
                    "type": "directive_denied",
                    "content": {"tool": tool_name},
                    "importance": 0.4,
                },
            )

        # fase-3: only the spoken channel reaches the player (the thought was recorded).
        reply = persist_result.get("spoken_text")
        if reply is None:
            reply = response.text or ""
        message_key: str | None = None
        if not reply:
            if denied and not allowed:
                message_key = "error.directive_denied"
            elif not allowed:
                message_key = "error.brain_foggy"

        return ChatResponse(
            reply=reply,
            provider=response.provider,
            model=response.model,
            tool_calls=allowed,
            message_key=message_key,
            message_args={},
        )

    async def format_hey_response_node(self, persist_result: dict[str, Any]) -> ChatResponse:
        """Format the hey response."""
        response = persist_result.get("llm_response")
        if response:
            # Defensive: a private thought must never be spoken.
            return ChatResponse(
                reply=strip_thought(response.text),
                provider=response.provider,
                model=response.model,
            )
        return ChatResponse(
            reply="",
            provider=None,
            model=None,
            message_key="notify.no_llm_native",
            message_args={},
        )

    def _format_tools(self, tool_schemas: dict[str, Any]) -> str:
        if not tool_schemas:
            return "No tools available."
        lines = ["Available tools:"]
        for name, schema in tool_schemas.items():
            desc = schema.get("description", "")
            lines.append(f"  - {name}: {desc}")
        return "\n".join(lines)

    @staticmethod
    def _format_memories(events: list[dict[str, Any]]) -> str:
        """Render recalled memories as a compact context block (M1/M2)."""
        lines: list[str] = []
        for event in events:
            if not isinstance(event, dict):
                continue
            content = event.get("content")
            if not isinstance(content, dict):
                continue
            event_type = str(event.get("type") or "")
            if event_type == "consolidated_memory":
                summary = content.get("summary")
                if summary:
                    lines.append(f"- You remember: {summary}")
            elif event_type == "dejavu":
                text = content.get("message")
                if text:
                    lines.append(f"- You vaguely remember... {text}")
            else:
                for key in ("message", "text", "summary"):
                    value = content.get(key)
                    if value:
                        lines.append(f"- {value}")
                        break
        return "\n".join(lines[-8:])

    async def handle_tool_result(self, req: ToolResultRequest) -> dict[str, Any]:
        """Match a tool result to its pending call and record it in memory."""
        for state in self._states.values():
            resolved = state.resolve_tool_call(req.tool_call_id, req.ok, req.result, req.error)
            if resolved is None:
                continue

            mem_key = self._mem_key_from_sim_key(state.sim_id)
            if mem_key is not None:
                await self.memory.add_event(
                    mem_key,
                    {
                        "type": "tool_result",
                        "content": {
                            "tool": resolved.get("name", ""),
                            "tool_call_id": req.tool_call_id,
                            "ok": req.ok,
                            "error": req.error,
                        },
                        "importance": 0.3,
                    },
                )

            logger.debug(f"Tool result {req.tool_call_id} resolved (ok={req.ok})")
            return {
                "ok": True,
                "resolved": True,
                "pending": len(state.pending_tool_calls),
            }

        logger.debug(f"Tool result {req.tool_call_id} had no matching pending call")
        return {"ok": True, "resolved": False}

    @staticmethod
    def _mem_key_from_sim_key(sim_key: str) -> MemKey | None:
        """Rebuild a MemKey from an ``AgentState.sim_id`` composite string."""
        parts = sim_key.split(":", 2)
        if len(parts) != 3:
            return None
        sim_id_text = parts[2]
        sim_id = int(sim_id_text) if sim_id_text.lstrip("-").isdigit() else 0
        return MemKey(player_id=parts[0], save_id=parts[1], sim_id=sim_id)