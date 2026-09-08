from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Protocol


class MemoryStore(Protocol):
    # WARM tier — worker entities
    def save_worker(self, profile: dict[str, Any]) -> None: ...
    def load_worker(self, name: str) -> dict[str, Any] | None: ...
    def list_workers(self) -> list[str]: ...
    def archive_worker(self, name: str, reason: str | None = None) -> bool: ...
    # COLD tier — job events
    def record_event(self, event: dict[str, Any]) -> None: ...
    def find_events(self, query: str) -> list[dict[str, Any]]: ...
    # Semantic search over WARM tier
    def search_similar_failure_workers(
        self, task_text: str, *, limit: int = 20
    ) -> set[str]: ...
    # HOT tier — live coordinator state (counters, policy)
    def get_state(self, key: str) -> dict[str, Any] | None: ...
    def set_state(self, key: str, body: dict[str, Any]) -> None: ...
    # REFERENCE tier — immutable settlement receipts
    def put_reference(self, key: str, body: dict[str, Any], metadata: dict[str, Any] | None = None) -> None: ...
    def get_reference(self, key: str) -> dict[str, Any] | None: ...
    # Cross-tier search (entities + events + state + references)
    def search_all(self, query: str, *, limit: int = 20) -> list[dict[str, Any]]: ...
    # Storage hygiene
    def storage_status(self) -> dict[str, Any]: ...


def _load_bound_credentials(db_path: str) -> dict[str, Any]:
    """If ``sibyl init`` has been run, adopt its tenant/account so writes land
    in the same partition the ``sibyl`` CLI (and the bound Sibyl account) sees.

    Returns an empty dict when no credentials are found, in which case
    ``MemoryClient.local`` falls back to the SDK's default tenant.
    """
    # Look next to the DB first (the CLI's convention), then $SIBYL_HOME, then
    # ~/.sibyl-memory. Env override wins over everything.
    explicit = os.getenv("SIBYL_CREDENTIALS")
    candidates = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    if db_path:
        candidates.append(Path(db_path).expanduser().parent / "credentials.json")
    home = os.getenv("SIBYL_HOME")
    if home:
        candidates.append(Path(home).expanduser() / "credentials.json")
    candidates.append(Path.home() / ".sibyl-memory" / "credentials.json")

    seen: set[Path] = set()
    for path in candidates:
        try:
            path = path.resolve()
        except OSError:
            continue
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        try:
            return json.loads(path.read_text(encoding="utf-8")) or {}
        except (OSError, json.JSONDecodeError):
            continue
    return {}


class SibylMemoryStore:
    """Adapter using the public Sibyl MemoryClient API.

    When ``sibyl init`` has bound this machine to a Sibyl account, the store
    automatically opens the DB under that account's tenant so writes are
    visible to ``sibyl memory list`` and to future ``sibyl-memory-*`` tools.
    Otherwise it falls back to the SDK's default tenant (useful for unit
    tests and ephemeral demos).
    """

    def __init__(self, path: str):
        try:
            from sibyl_memory_client import MemoryClient
        except ImportError as exc:
            raise RuntimeError("Install sibyl-memory-client to use SibylMemoryStore") from exc

        creds = _load_bound_credentials(path)
        kwargs: dict[str, Any] = {}
        tenant = creds.get("tenant_id") or creds.get("account_id")
        if tenant:
            kwargs["tenant_id"] = tenant
        if creds.get("account_id"):
            kwargs["account_id"] = creds["account_id"]
        if creds.get("session_token"):
            kwargs["session_token"] = creds["session_token"]
        if creds.get("tier"):
            kwargs["tier"] = creds["tier"]
        self.credentials_bound = bool(tenant)
        self.tenant_id = tenant or ""
        self.client = MemoryClient.local(path, **kwargs)

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

    def delete_worker(self, name: str) -> bool:
        """Best-effort delete via the underlying client.

        Returns True if the client reported a successful delete. Falls back to
        a no-op (returning False) when the client cannot delete — callers can
        overwrite instead.
        """
        try:
            return bool(self.client.delete_entity("relay_worker", name))
        except Exception as exc:  # noqa: BLE001
            if exc.__class__.__name__ == "NotFoundError":
                return False
            raise

    def archive_worker(self, name: str, reason: str | None = None) -> bool:
        """Archive a worker instead of hard-deleting it.

        Sibyl's archive tier moves the entity out of the active set but keeps
        it recoverable — the audit-preserving way to retire a worker. Falls
        back to delete when the client lacks archive support.
        """
        try:
            self.client.archive_entity("relay_worker", name, reason=reason)
            return True
        except Exception as exc:  # noqa: BLE001
            if exc.__class__.__name__ == "NotFoundError":
                return False
            # Older clients without archive support → fall back to delete.
            return self.delete_worker(name)

    def search_similar_failure_workers(self, task_text: str, *, limit: int = 20) -> set[str]:
        """Return names of workers whose stored profile semantically matches
        ``task_text`` AND has at least one recorded failure note.

        This is the *fourth* Sibyl primitive Praetor loads on: semantic
        search. Each meaningful token from the task is issued as a separate
        FTS5 query against the ``relay_worker`` category (Sibyl's
        ``search_entities`` treats a multi-token query as ``AND``; issuing
        per-token queries gives us an ``ANY``-token contract that matches
        the deterministic in-memory fallback). Filtering to workers with
        ``failures > 0`` ensures a name-only match (e.g., a worker called
        ``risk-reviewer`` matching the word "risk") never counts as a
        "past-failure-related-to-this-task" signal.

        The router uses this to downweight workers whose known failures
        resemble the current task — turning flat reputation into
        task-aware reputation.
        """
        if not task_text or not task_text.strip():
            return set()
        import re

        # Only keep tokens long enough to be discriminating. Two-char tokens
        # (``a``, ``in``, ``on``) both spam the FTS index and inflate the
        # false-positive rate.
        tokens = {
            tok.lower()
            for tok in re.split(r"\W+", task_text)
            if len(tok) >= 4
        }
        if not tokens:
            return set()
        matches: set[str] = set()
        for token in tokens:
            try:
                results = self.client.search_entities(
                    token, category="relay_worker", limit=limit
                )
            except Exception:  # noqa: BLE001 - FTS may reject some query syntax
                continue
            for r in results or []:
                if not isinstance(r, dict):
                    continue
                body = r.get("body")
                if isinstance(body, str):
                    try:
                        body = json.loads(body)
                    except json.JSONDecodeError:
                        body = None
                if not isinstance(body, dict) or not body.get("failure_notes"):
                    continue
                name = body.get("name") or r.get("name")
                if not name:
                    continue
                # Require the hit token to actually appear in the recorded
                # failure notes — otherwise a token like "risk" matching a
                # capability field would over-fire. This mirrors the
                # in-memory store's failure-notes-only contract.
                notes_text = " ".join(str(n) for n in body["failure_notes"]).lower()
                if token in notes_text:
                    matches.add(name)
        return matches

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

    # -- HOT tier: live coordinator state -------------------------------
    def get_state(self, key: str) -> dict[str, Any] | None:
        try:
            result = self.client.get_state(key)
        except Exception as exc:  # noqa: BLE001
            if exc.__class__.__name__ == "NotFoundError":
                return None
            raise
        if isinstance(result, dict) and "body" in result and isinstance(result["body"], (dict, str)):
            body = result["body"]
            return json.loads(body) if isinstance(body, str) else body
        return result

    def set_state(self, key: str, body: dict[str, Any]) -> None:
        self.client.set_state(key, body)

    # -- REFERENCE tier: immutable settlement receipts ------------------
    def put_reference(self, key: str, body: dict[str, Any], metadata: dict[str, Any] | None = None) -> None:
        self.client.set_reference(key, body, metadata=metadata)

    def get_reference(self, key: str) -> dict[str, Any] | None:
        try:
            result = self.client.get_reference(key)
        except Exception as exc:  # noqa: BLE001
            if exc.__class__.__name__ == "NotFoundError":
                return None
            raise
        if isinstance(result, dict) and "body" in result:
            body = result["body"]
            if isinstance(body, str):
                try:
                    return json.loads(body)
                except json.JSONDecodeError:
                    return {"body": body, **{k: v for k, v in result.items() if k != "body"}}
            if isinstance(body, dict):
                return body
        return result

    # -- Cross-tier search ---------------------------------------------
    def search_all(self, query: str, *, limit: int = 20) -> list[dict[str, Any]]:
        if not query or not query.strip():
            return []
        try:
            results = self.client.search(query, limit=limit)
        except Exception:  # noqa: BLE001 - FTS may reject some query syntax
            return []
        out: list[dict[str, Any]] = []
        for r in results or []:
            if not isinstance(r, dict):
                continue
            out.append(
                {
                    "tier": r.get("tier") or r.get("category") or "",
                    "name": r.get("name") or r.get("key") or "",
                    "category": r.get("category", ""),
                    "body": r.get("body"),
                }
            )
        return out

    # -- Storage hygiene ------------------------------------------------
    def storage_status(self) -> dict[str, Any]:
        try:
            status = self.client.free_tier_status()
            return {"available": True, **(status if isinstance(status, dict) else {})}
        except Exception as exc:  # noqa: BLE001
            return {"available": False, "error": str(exc)}


class InMemoryStore:
    """Deterministic test/demo store with the same behavior as the adapter."""

    def __init__(self):
        self.workers: dict[str, dict[str, Any]] = {}
        self.events: list[dict[str, Any]] = []
        self.states: dict[str, dict[str, Any]] = {}
        self.references: dict[str, dict[str, Any]] = {}
        self.archived: dict[str, dict[str, Any]] = {}

    def save_worker(self, profile: dict[str, Any]) -> None:
        self.workers[profile["name"]] = json.loads(json.dumps(profile))

    def load_worker(self, name: str) -> dict[str, Any] | None:
        profile = self.workers.get(name)
        return json.loads(json.dumps(profile)) if profile else None

    def list_workers(self) -> list[str]:
        return sorted(self.workers)

    def delete_worker(self, name: str) -> bool:
        return self.workers.pop(name, None) is not None

    def archive_worker(self, name: str, reason: str | None = None) -> bool:
        profile = self.workers.pop(name, None)
        if profile is None:
            return False
        self.archived[name] = {**profile, "_archive_reason": reason}
        return True

    def get_state(self, key: str) -> dict[str, Any] | None:
        s = self.states.get(key)
        return json.loads(json.dumps(s)) if s is not None else None

    def set_state(self, key: str, body: dict[str, Any]) -> None:
        self.states[key] = json.loads(json.dumps(body))

    def put_reference(self, key: str, body: dict[str, Any], metadata: dict[str, Any] | None = None) -> None:
        self.references[key] = json.loads(json.dumps(body))

    def get_reference(self, key: str) -> dict[str, Any] | None:
        r = self.references.get(key)
        return json.loads(json.dumps(r)) if r is not None else None

    def search_all(self, query: str, *, limit: int = 20) -> list[dict[str, Any]]:
        if not query or not query.strip():
            return []
        q = query.lower()
        out: list[dict[str, Any]] = []
        for name, profile in self.workers.items():
            if q in json.dumps(profile).lower():
                out.append({"tier": "warm", "name": name, "category": "relay_worker", "body": profile})
        for key, body in self.references.items():
            if q in json.dumps(body).lower() or q in key.lower():
                out.append({"tier": "reference", "name": key, "category": "reference", "body": body})
        for ev in self.events:
            if q in json.dumps(ev).lower():
                out.append({"tier": "cold", "name": ev.get("type", "event"), "category": "event", "body": ev})
            if len(out) >= limit:
                break
        return out[:limit]

    def storage_status(self) -> dict[str, Any]:
        return {
            "available": True,
            "backend": "in-memory",
            "entities": len(self.workers),
            "events": len(self.events),
            "references": len(self.references),
        }

    def search_similar_failure_workers(self, task_text: str, *, limit: int = 20) -> set[str]:
        """Deterministic mirror of the Sibyl semantic search primitive.

        Token-overlap (>= 3 chars, case-insensitive) between the task text and
        each worker's ``failure_notes`` is treated as a "past-failure-related-
        to-this-task" hit. Same contract as :class:`SibylMemoryStore`, just
        without FTS5 — so tests and offline demos behave identically.
        """
        if not task_text or not task_text.strip():
            return set()
        import re

        tokens = {
            tok.lower()
            for tok in re.split(r"\W+", task_text)
            if len(tok) >= 4
        }
        if not tokens:
            return set()
        matches: set[str] = set()
        for name, profile in self.workers.items():
            notes = profile.get("failure_notes") or []
            if not notes:
                continue
            notes_text = " ".join(str(n) for n in notes).lower()
            note_tokens = {
                tok.lower()
                for tok in re.split(r"\W+", notes_text)
                if len(tok) >= 4
            }
            if tokens & note_tokens:
                matches.add(name)
            if len(matches) >= limit:
                break
        return matches

    def record_event(self, event: dict[str, Any]) -> None:
        self.events.append(json.loads(json.dumps(event)))

    def find_events(self, query: str) -> list[dict[str, Any]]:
        return [event for event in self.events if query.lower() in json.dumps(event).lower()]
