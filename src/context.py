"""Bounded, source-labelled projections of shared collaboration context."""
from datetime import datetime, timezone

from .errors import ValidationError


MAX_ITEMS = 100
MAX_SOURCE_ITEMS = 200
FRESH_SECONDS = {
    "session_registry": 15 * 60,
    "agent_report": 24 * 60 * 60,
    "local_git": 15 * 60,
    "github_verified": 30 * 60,
}


def _when(value):
    if not isinstance(value, str) or not value or len(value) > 50:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso(value):
    parsed = _when(value)
    return parsed.isoformat().replace("+00:00", "Z") if parsed else None


def _freshness(observed_at, now, source):
    parsed = _when(observed_at)
    if parsed is None:
        return "unknown"
    age = max(0, (now - parsed).total_seconds())
    threshold = FRESH_SECONDS.get(source)
    if threshold is None:
        return "current"
    return "fresh" if age <= threshold else "stale"


def _text(value, limit):
    return value[:limit] if isinstance(value, str) else ""


def _item(identifier, kind, source, scope, observed_at, data, now):
    observed = _iso(observed_at)
    if observed is None:
        return None
    return {
        "id": _text(str(identifier), 120),
        "kind": kind,
        "source": source,
        "scope": scope,
        "observed_at": observed,
        "freshness": _freshness(observed, now, source),
        "privacy": "shared_structured",
        "data": data,
    }


def _matches(item, task_id=None, member_id=None):
    data = item["data"]
    if task_id is not None and data.get("task_id") != task_id:
        return False
    if member_id is not None and data.get("member_id") != member_id:
        return False
    return True


class ContextStore:
    """Project existing snapshot sections into a stable, bounded read model."""

    @staticmethod
    def project(snapshot, *, task_id=None, member_id=None, limit=50, now=None):
        if type(task_id) is not int and task_id is not None:
            raise ValidationError("Task id must be a positive integer")
        if type(task_id) is int and task_id <= 0:
            raise ValidationError("Task id must be a positive integer")
        if member_id is not None and (not isinstance(member_id, str) or not member_id.strip()):
            raise ValidationError("Member id must be a nonempty string")
        if type(limit) is not int or not 1 <= limit <= MAX_ITEMS:
            raise ValidationError("Context limit must be between 1 and 100")
        if not isinstance(snapshot, dict):
            raise ValidationError("Context source must be a snapshot object")
        now = now or datetime.now(timezone.utc)
        items = []

        for row in snapshot.get("tasks", [])[:MAX_SOURCE_ITEMS]:
            if isinstance(row, dict) and type(row.get("id")) is int:
                items.append(_item(
                    "task:" + str(row["id"]), "task", "task", "project", row.get("created_at"),
                    {"task_id": row["id"], "title": _text(row.get("title"), 200),
                     "scope": _text(row.get("scope"), 250), "state": _text(row.get("state"), 40),
                     "member_id": row.get("owner_member_id")}, now))

        for row in snapshot.get("sessions", [])[:MAX_SOURCE_ITEMS]:
            if isinstance(row, dict):
                items.append(_item(
                    "session:" + str(row.get("id", "")), "session", "session_registry", "member",
                    row.get("updated_at"),
                    {"session_id": row.get("id"), "member_id": _text(row.get("member_id"), 120),
                     "tool": _text(row.get("tool"), 60), "repository": _text(row.get("repository"), 500),
                     "branch": _text(row.get("branch"), 250), "task_id": row.get("task_id")}, now))

        for row in snapshot.get("progress", [])[:MAX_SOURCE_ITEMS]:
            if isinstance(row, dict):
                items.append(_item(
                    "progress:" + str(row.get("task_id", "")), "progress", "agent_report", "task",
                    row.get("updated_at"),
                    {"task_id": row.get("task_id"), "member_id": _text(row.get("member_id"), 120),
                     "state": _text(row.get("state"), 40), "summary": _text(row.get("summary"), 1000),
                     "evidence": _text(row.get("evidence"), 1000)}, now))

        for row in snapshot.get("requests", [])[:MAX_SOURCE_ITEMS]:
            if isinstance(row, dict):
                items.append(_item(
                    "request:" + str(row.get("id", "")), "request", "collaboration_request", "task",
                    row.get("created_at"),
                    {"request_id": row.get("id"), "task_id": row.get("task_id"),
                     "member_id": _text(row.get("sender_member_id"), 120),
                     "receiver_member_id": _text(row.get("receiver_member_id"), 120) or None,
                     "context_version": row.get("context_version"), "body": _text(row.get("body"), 4000),
                     "read_at": _iso(row.get("read_at")), "processed_at": _iso(row.get("processed_at")),
                     "resolved_at": _iso(row.get("resolved_at")),
                     "reply_count": len(row.get("replies", [])) if isinstance(row.get("replies"), list) else 0}, now))

        for row in snapshot.get("contracts", [])[:MAX_SOURCE_ITEMS]:
            if isinstance(row, dict):
                versions = row.get("versions") if isinstance(row.get("versions"), list) else []
                head = versions[-1] if versions else {}
                items.append(_item(
                    "contract:" + str(row.get("id", "")), "contract", "contract", "project",
                    row.get("created_at"),
                    {"contract_id": row.get("id"), "contract_key": _text(row.get("contract_key"), 200),
                     "current_version": row.get("current_version"), "effective_version": row.get("effective_version"),
                     "title": _text(head.get("title"), 200), "member_id": _text(head.get("proposer_member_id"), 120)}, now))

        git = snapshot.get("git") if isinstance(snapshot.get("git"), dict) else {}
        for row in git.get("events", [])[:MAX_SOURCE_ITEMS]:
            if isinstance(row, dict):
                items.append(_item(
                    "git:" + str(row.get("id", "")), "git_observation", "local_git", "task",
                    row.get("captured_at"),
                    {"task_id": row.get("task_id"), "member_id": _text(row.get("member_id"), 120),
                     "branch": _text(row.get("branch"), 250), "head": _text(row.get("head"), 64),
                     "paths": row.get("paths", [])[:50] if isinstance(row.get("paths"), list) else []}, now))
        for row in git.get("deliveries", [])[:MAX_SOURCE_ITEMS]:
            if isinstance(row, dict):
                items.append(_item(
                    "delivery:" + str(row.get("ref_id", row.get("release_id", ""))), "delivery", "github_verified", "task",
                    row.get("sync_at"),
                    {key: row[key] for key in ("task_id", "branch", "commit_sha", "pr_number", "release_id", "tag_name", "state", "stale") if key in row}, now))

        items = [item for item in items if item and _matches(item, task_id, member_id)]
        items.sort(key=lambda item: (item["observed_at"], item["source"], item["id"]), reverse=True)
        return {
            "items": items[:limit],
            "truncated": len(items) > limit,
            "limit": limit,
            "filters": {"task_id": task_id, "member_id": member_id},
            "privacy": "shared_structured_only",
            "generated_at": now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
