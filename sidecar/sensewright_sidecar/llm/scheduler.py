"""LLMScheduler — the single orchestration point for all 33 purposes.

Implements F16 / REQ-SCHED-*: one scheduler, tier-based SLOs and concurrency,
deduplication via ``dedup_key``, asymmetric refund (game budget refunded on
timeout/network failure; provider rate limit never refunded), and a background
worker thread for ``bg``/``deep`` tiers. Every path returns a valid result —
either the LLM output or a 0-key deterministic fallback (REQ-SCHED: "Timeout ->
Template").
"""
from __future__ import annotations

import atexit
import json
import queue
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional

from ..config import Config
from ..fallbacks import render_fallback
from ..observability.logging import get_logger, set_trace_id
from ..purposes import get_purpose
from ..schemas import generate_trace_id, normalize_lang, sanitize_payload
from .base import LLMError, LLMJob, LLMResult, LLMTimeout, ProviderResponse
from .budgeter import GameBudgeter
from .chain import ProviderChain
from .context import ContextAssembler
from .limits import estimate_tokens
from .router import ModelRouter

logger = get_logger("llm.scheduler")

#: Tiers processed on the background worker thread.
_BACKGROUND_TIERS = ("bg", "deep")


#: Reasoning-model wrappers (deepseek/openrouter reasoners) that some models emit
#: around the requested JSON. Stripped before parsing so a generation is not
#: benched just because it wrapped the payload in a thinking tag.
_THINKING_TAG_RE = re.compile(
    r"<(?:thinking|reasoning|thought|analysis)[^>]*>.*?</(?:thinking|reasoning|thought|analysis)>",
    re.DOTALL,
)


def _balanced_json_block(text: str, prefer_last: bool = False) -> Dict[str, Any]:
    """Return the first (or last) balanced ``{...}`` object parsed from ``text``."""
    starts = [i for i, ch in enumerate(text) if ch == "{"]  # noqa: E741 - 'ch' is a char
    if not starts:
        return {}
    indices = starts[::-1] if prefer_last else starts
    for start in indices:
        depth = 0
        in_string = False
        escape = False
        for index in range(start, len(text)):
            char = text[index]
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start:index + 1]
                    try:
                        data = json.loads(candidate)
                        if isinstance(data, dict):
                            return data
                    except json.JSONDecodeError:
                        pass
                    break
    return {}


def _extract_json(text: str) -> Dict[str, Any]:
    """Parse a provider's text into a JSON object, robust to prose wrappers.

    Reasoning models (deepseek/openrouter reasoners) may wrap the requested JSON
    in ``<thinking>``/``<reasoning>`` tags or emit prose before the object; both
    are stripped/ignored so a generation does not get benched as "unusable".
    """
    if not text:
        return {}
    stripped = text.strip()
    # Strip markdown code fences.
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z]*\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped).strip()
    # Strip XML-style reasoning blocks.
    stripped = _THINKING_TAG_RE.sub("", stripped).strip()
    try:
        data = json.loads(stripped)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    # Prefer the first balanced object; fall back to the last (reasoning prose
    # may itself contain braces before the real payload).
    data = _balanced_json_block(stripped, prefer_last=False)
    if not data:
        data = _balanced_json_block(stripped, prefer_last=True)
    return data


#: Legacy ``[thought]...[/thought]`` block some models imitate from few-shots.
_THOUGHT_RE = re.compile(r"\[thought\](.*?)\[/thought\]", re.DOTALL)


def _recover_structured(purpose_id: str, text: str) -> Dict[str, Any]:
    """Salvage a generation that ignored the JSON instruction.

    Free models sometimes imitate a ``[thought]...[/thought]`` few-shot example
    instead of emitting JSON. Discarding the whole generation loses the thought
    and every intent, so map the block back to the purpose's expected shape.
    Returns ``{}`` when nothing usable is found.
    """
    if not text:
        return {}
    match = _THOUGHT_RE.search(text)
    if match is None:
        return {}
    thought = match.group(1).strip()
    remainder = _THOUGHT_RE.sub("", text).strip()
    if purpose_id == "sim.chat":
        if not remainder:
            return {}
        return {
            "response": remainder,
            "thought": thought,
            "intents": [],
            "trust_delta": 0.0,
        }
    if purpose_id in ("sim.impulse", "sim.reaction"):
        if not thought:
            return {}
        return {"thought": thought, "intents": []}
    return {"thought": thought} if thought else {}


class LLMScheduler:
    def __init__(self, config: Config) -> None:
        self._config = config
        self._router = ModelRouter(config)
        self._chain = ProviderChain(config)
        self._assembler = ContextAssembler(config)
        self._budgeter = GameBudgeter(int(config.gameplay("game_budget_tokens", 0)))
        self._queue: "queue.Queue[LLMJob]" = queue.Queue()
        self._in_flight: set = set()
        self._lock = threading.Lock()
        #: Per-tier concurrency gates (REQ-SCHED-01). A tier with concurrency=1
        #: serializes its calls; realtime/interactive benefit most since they
        #: run synchronously on multiple HTTP threads.
        self._tier_sems: Dict[str, threading.BoundedSemaphore] = {}
        #: Dedicated realtime-async pool (4.2): reactions/narration must not wait
        #: behind the single bg worker, and must not block the HTTP request thread.
        self._realtime_pool = ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="sensewright-realtime",
        )
        self._worker = threading.Thread(target=self._worker_loop, name="sensewright-llm-worker", daemon=True)
        self._worker.start()

    def _tier_semaphore(self, tier: str) -> Optional[threading.BoundedSemaphore]:
        with self._lock:
            sem = self._tier_sems.get(tier)
            if sem is None:
                try:
                    limit = int(self._config.tier(tier).get("concurrency", 1))
                except Exception:  # noqa: BLE001
                    limit = 1
                sem = threading.BoundedSemaphore(max(1, limit))
                self._tier_sems[tier] = sem
            return sem

    # ── config hot-reload (4.2) ──────────────────────────────────────────
    def reload_provider(self, name: str) -> None:
        """Rebuild a provider client after credentials changed at runtime."""
        self._chain.reload_provider(name)

    # ── public API ───────────────────────────────────────────────────────
    def run_purpose(
        self,
        purpose_id: str,
        context: Optional[Dict[str, Any]] = None,
        lang: str = "",
        trace_id: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> LLMResult:
        """Run a purpose synchronously. Never raises; always returns a result.

        Used by interactive/realtime paths (and directly by bg/deep when the
        caller wants the result inline).
        """
        context = context or {}
        lang = normalize_lang(lang)
        trace_id = trace_id or generate_trace_id()
        purpose = get_purpose(purpose_id)
        started = time.time()

        # 0-key / no-route fast path.
        if purpose is None or not self._router.has_route(purpose_id):
            return LLMResult(
                ok=True, data=render_fallback(purpose_id, lang, context),
                fallback=True, latency_s=time.time() - started,
            )

        tier = purpose.tier
        tier_cfg = self._config.tier(tier)
        slo = timeout if timeout is not None else float(tier_cfg.get("slo_seconds", 60.0))
        max_out = int(tier_cfg.get("max_output_tokens", purpose.out_tokens))
        temperature = 0.0 if tier_cfg.get("thinking_budget") == 0 else 0.7

        messages = self._assembler.assemble(purpose_id, context, lang)
        sim_id = context.get("sim_id")

        def _usable(response: ProviderResponse) -> bool:
            # Reject HTTP-200 generations we cannot parse; the chain then benches
            # the model and tries the next route. Without this, a reasoning model
            # that ignores the JSON instruction would silently fall back forever.
            return bool(
                _extract_json(response.text)
                or _recover_structured(purpose_id, response.text)
            )

        # Enforce per-tier concurrency (REQ-SCHED-01). Excess calls degrade to
        # the deterministic fallback instead of queueing behind a slow peer.
        est = estimate_tokens(json.dumps(messages, ensure_ascii=False)) + max_out
        if sim_id is not None and not self._budgeter.can_spend(int(sim_id), est):
            return LLMResult(
                ok=True, data=render_fallback(purpose_id, lang, context),
                fallback=True, error="game budget exhausted",
                latency_s=time.time() - started,
            )

        sem = self._tier_semaphore(tier)
        if not sem.acquire(blocking=False):
            return LLMResult(
                ok=True, data=render_fallback(purpose_id, lang, context),
                fallback=True, error="tier concurrency saturated",
                latency_s=time.time() - started,
            )

        # Asymmetric game budget (REQ-SCHED-02): debit the estimate at dispatch;
        # only the game budget is refunded on failure, never provider limits.
        if sim_id is not None:
            self._budgeter.spend(int(sim_id), est)
        response, provider_name, model = None, None, None
        try:
            response, provider_name, model = self._chain.run(
                purpose_id, messages, max_tokens=max_out,
                temperature=temperature, timeout=slo, validator=_usable,
            )
        except Exception:  # noqa: BLE001 - never let the chain crash the caller
            logger.exception("chain dispatch failed for %s", purpose_id)
        finally:
            sem.release()

        latency = time.time() - started
        if response is None:
            # All routes failed/timeout — refund the game budget (asymmetric rule).
            if sim_id is not None:
                self._budgeter.refund(int(sim_id), est)
            return LLMResult(
                ok=True, data=render_fallback(purpose_id, lang, context),
                fallback=True, error="no provider route succeeded",
                latency_s=latency,
            )

        data = _extract_json(response.text)
        if not data:
            data = _recover_structured(purpose_id, response.text)
        if not data:
            logger.warning(
                "llm.parse_failed purpose=%s provider=%s model=%s; using fallback "
                "(text[:160]=%r)",
                purpose_id, provider_name, model, (response.text or "")[:160],
            )
            data = render_fallback(purpose_id, lang, context)
        data = sanitize_payload(data)

        if sim_id is not None:
            # Settle the dispatch estimate against the provider-reported usage.
            self._budgeter.refund(int(sim_id), est)
            self._budgeter.spend(int(sim_id), response.total_tokens or est)
        logger.info(
            "llm.route purpose=%s provider=%s model=%s latency=%.2fs tokens=%s",
            purpose_id, provider_name, model, latency, response.total_tokens,
        )
        return LLMResult(
            ok=True, data=data, provider=provider_name, model=model, latency_s=latency,
        )

    def submit_bg(
        self,
        purpose_id: str,
        context: Optional[Dict[str, Any]] = None,
        lang: str = "",
        trace_id: Optional[str] = None,
        dedup_key: Optional[str] = None,
        callback: Optional[Callable[[LLMResult], None]] = None,
    ) -> None:
        """Enqueue a bg/deep job for the background worker (fire-and-forget)."""
        context = context or {}
        purpose = get_purpose(purpose_id)
        tier = purpose.tier if purpose else "bg"
        job = LLMJob(
            purpose_id=purpose_id, tier=tier, context=context,
            lang=normalize_lang(lang), trace_id=trace_id or generate_trace_id(),
            dedup_key=dedup_key or "",
        )
        # Reserve the dedup key at enqueue time so a slow worker cannot let
        # duplicate jobs pile up in the queue (e.g. one impulse per tick).
        if job.dedup_key:
            with self._lock:
                if job.dedup_key in self._in_flight:
                    return
                self._in_flight.add(job.dedup_key)
        job._callback = callback  # type: ignore[attr-defined]
        self._queue.put(job)

    def submit_async(
        self,
        purpose_id: str,
        context: Optional[Dict[str, Any]] = None,
        lang: str = "",
        trace_id: Optional[str] = None,
        dedup_key: Optional[str] = None,
        callback: Optional[Callable[[LLMResult], None]] = None,
    ) -> None:
        """Run a purpose on the dedicated realtime pool (fire-and-forget).

        Used for latency-sensitive, non-blocking paths (``sim.reaction``) that
        previously ran synchronously on the HTTP request thread (4.2).
        """
        context = context or {}
        purpose = get_purpose(purpose_id)
        tier = purpose.tier if purpose else "realtime"
        job = LLMJob(
            purpose_id=purpose_id, tier=tier, context=context,
            lang=normalize_lang(lang), trace_id=trace_id or generate_trace_id(),
            dedup_key=dedup_key or "",
        )
        if job.dedup_key:
            with self._lock:
                if job.dedup_key in self._in_flight:
                    return
                self._in_flight.add(job.dedup_key)
        job._callback = callback  # type: ignore[attr-defined]
        self._realtime_pool.submit(self._run_job, job)

    def _run_job(self, job: LLMJob) -> None:
        try:
            # Propagate the originating trace id into the worker thread so
            # bg/deep log lines stay greppable (REQ-OBS-01).
            set_trace_id(job.trace_id or "-")
            result = self.run_purpose(
                job.purpose_id, job.context, job.lang, job.trace_id,
            )
            callback = getattr(job, "_callback", None)
            if callback is not None:
                try:
                    callback(result)
                except Exception:  # noqa: BLE001
                    logger.exception("async callback failed for %s", job.purpose_id)
        except Exception:  # noqa: BLE001
            logger.exception("job execution error for %s", job.purpose_id)
        finally:
            if job.dedup_key:
                with self._lock:
                    self._in_flight.discard(job.dedup_key)

    def _worker_loop(self) -> None:
        while True:
            job = self._queue.get()
            self._run_job(job)

    def status(self) -> Dict[str, Any]:
        return {
            "chain": self._chain.status(),
            "queue_depth": self._queue.qsize(),
            "in_flight": list(self._in_flight),
            "game_budget": self._budgeter.snapshot(),
        }

    def shutdown(self) -> None:
        """Release the realtime pool on interpreter exit (the bg worker is a daemon)."""
        try:
            self._realtime_pool.shutdown(wait=False)
        except Exception:  # noqa: BLE001 - best-effort teardown
            pass


_scheduler_singleton: Optional[LLMScheduler] = None
_scheduler_lock = threading.Lock()


def get_scheduler() -> LLMScheduler:
    global _scheduler_singleton
    if _scheduler_singleton is None:
        from ..config import get_config
        with _scheduler_lock:
            if _scheduler_singleton is None:
                _scheduler_singleton = LLMScheduler(get_config())
                atexit.register(_scheduler_singleton.shutdown)
    return _scheduler_singleton
