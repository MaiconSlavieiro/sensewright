"""ModelRouter — maps a purpose to an ordered list of (provider, model) routes.

Applies the ``free_only`` guard (REQ-LLM-03): when enabled, any paid model is
filtered out at the client level, before a single HTTP request is dispatched.
The routed provider (from Layer 2 ``llm.routes.*``) is tried first; if it is
disabled, unfree (under free_only) or has no usable model, the router falls back
across every enabled provider in config order.
"""
from __future__ import annotations

from typing import Dict, List, NamedTuple

from ..config import Config
from .providers.base import is_free_model


class RouteCandidate(NamedTuple):
    provider: str
    model: str


class ModelRouter:
    def __init__(self, config: Config) -> None:
        self._config = config

    def plan(self, purpose_id: str) -> List[RouteCandidate]:
        """Return the ordered candidate routes for a purpose (may be empty)."""
        providers = self._config.providers()
        free_only = self._config.free_only

        candidates: List[RouteCandidate] = []
        seen: set = set()

        route = self._config.route_for(purpose_id)
        routed_provider = route.get("provider")
        routed_model = route.get("model")

        # 1. Routed provider/model first.
        if routed_provider and routed_provider in providers and providers[routed_provider].get("enabled"):
            model = routed_model or (providers[routed_provider].get("models") or [None])[0]
            if model and (not free_only or is_free_model(model, providers[routed_provider])):
                candidates.append(RouteCandidate(routed_provider, model))
                seen.add((routed_provider, model))

        # 2. Fallback across every enabled provider's models in config order.
        for provider_name, cfg in providers.items():
            if not cfg.get("enabled"):
                continue
            for model in cfg.get("models") or []:
                if (provider_name, model) in seen:
                    continue
                if free_only and not is_free_model(model, cfg):
                    continue
                candidates.append(RouteCandidate(provider_name, model))
                seen.add((provider_name, model))

        return candidates

    def has_route(self, purpose_id: str) -> bool:
        return bool(self.plan(purpose_id))
