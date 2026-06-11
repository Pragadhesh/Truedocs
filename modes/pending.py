"""Temporary store for drift analysis results pending user approval.

Keyed by '{process_id}|{thread_ts}'.  Survives only for the process lifetime —
if the app restarts the user needs to run run-truedocs again.

We store the ChangeAnalysis (not pre-baked HTML) so the approve handler can
re-fetch the latest Confluence page and apply changes to fresh content.
"""
from __future__ import annotations

from modes.diff import ChangeAnalysis

_store: dict[str, str] = {}  # JSON-serialized ChangeAnalysis


def put(process_id: str, thread_ts: str, analysis: ChangeAnalysis) -> None:
    _store[f"{process_id}|{thread_ts}"] = analysis.model_dump_json()


def get(process_id: str, thread_ts: str) -> ChangeAnalysis | None:
    data = _store.get(f"{process_id}|{thread_ts}")
    if data is None:
        return None
    return ChangeAnalysis.model_validate_json(data)


def delete(process_id: str, thread_ts: str) -> None:
    _store.pop(f"{process_id}|{thread_ts}", None)
