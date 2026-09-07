from __future__ import annotations

import json
from typing import Any, Protocol


class MemoryStore(Protocol):
    def save_worker(self, profile: dict[str, Any]) -> None: ...
    def load_worker(self, name: str) -> dict[str, Any] | None: ...
    def list_workers(self) -> list[str]: ...
    def record_event(self, event: dict[str, Any]) -> None: ...
    def find_events(self, query: str) -> list[dict[str, Any]]: ...


class SibylMemoryStore:
    """Adapter using the public Sibyl MemoryClient API."""

    def __init__(self, path: str):
        try:
            from sibyl_memory_client import MemoryClient
        except ImportError as exc:
            raise RuntimeError("Install sibyl-memory-client to use SibylMemoryStore") from exc
        self.client = MemoryClient.local(path)

    def save_worker(self, profile: dict[str, Any]) -> None:
        self.client.set_entity("relay_worker", profile["name"], profile)

    def load_worker(self, name: str) -> dict[str, Any] | None:
        try:
            result = self.client.get_entity("relay_worker", name)
        except Exception as exc:
            # The shipped client raises NotFoundError for a cold lookup.
            if exc.__class__.__name__ != "NotFoundError":
                raise
            return None
        if result is None:
            return None
        if isinstance(result, dict) and "body" in result:
            if isinstance(result["body"], str):
                return json.loads(result["body"])
            if isinstance(result["body"], dict):
                return result["body"]
        return result

    def list_workers(self) -> list[str]:
        # ``list_entities`` is the documented enumeration primitive: it returns
        # every entity in a category deterministically. ``search_entities`` is
        # FTS-backed (default ``limit=20`` and query-syntax sensitive), so it is
        # the wrong tool for "give me all workers" and would silently truncate
        # once more than 20 workers exist. See docs.sibyllabs.org (memory API).
        try:
            results = self.client.list_entities(category="relay_worker", limit=10_000)
        except TypeError:  # older clients may not accept a limit kwarg
            results = self.client.list_entities(category="relay_worker")
        names = [
            item["name"]
            for item in results or []
            if isinstance(item, dict) and item.get("name")
        ]
        return sorted(set(names))

    def record_event(self, event: dict[str, Any]) -> None:
        self.client.write_event(acted=[json.dumps(event, sort_keys=True)])

    def find_events(self, query: str, *, limit: int = 1000) -> list[dict[str, Any]]:
        # Read a generous window rather than the client default (50) so history
        # reconstruction is not silently truncated.
        try:
            results = self.client.read_events(limit=limit)
        except TypeError:  # pragma: no cover - defensive for older signatures
            results = self.client.read_events()
        events: list[dict[str, Any]] = []
        for result in results or []:
            if not isinstance(result, dict):
                continue
            texts = result.get("acted") or []
            for text in texts:
                try:
                    event = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if query.lower() in json.dumps(event).lower():
                    events.append(event)
        return events


class InMemoryStore:
    """Deterministic test/demo store with the same behavior as the adapter."""

    def __init__(self):
        self.workers: dict[str, dict[str, Any]] = {}
        self.events: list[dict[str, Any]] = []

    def save_worker(self, profile: dict[str, Any]) -> None:
        self.workers[profile["name"]] = json.loads(json.dumps(profile))

    def load_worker(self, name: str) -> dict[str, Any] | None:
        profile = self.workers.get(name)
        return json.loads(json.dumps(profile)) if profile else None

    def list_workers(self) -> list[str]:
        return sorted(self.workers)

    def record_event(self, event: dict[str, Any]) -> None:
        self.events.append(json.loads(json.dumps(event)))

    def find_events(self, query: str) -> list[dict[str, Any]]:
        return [event for event in self.events if query.lower() in json.dumps(event).lower()]
