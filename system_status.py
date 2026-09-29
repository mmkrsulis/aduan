"""Secret-free audit presentation and shared worker liveness storage."""
import json
import re
import time

HEARTBEAT_STALE_SECONDS = 300
SENSITIVE = re.compile(r'password|secret|token|key|authorization|cookie|credential|session', re.I)


def safe_metadata(raw):
    def redact(value):
        if isinstance(value, dict):
            return {k: '[REDACTED]' if SENSITIVE.search(k) else redact(v) for k, v in value.items()}
        if isinstance(value, list):
            return [redact(v) for v in value]
        return value
    try:
        value = json.loads(raw or '{}')
        # Legacy free text cannot be safely interpreted as structured metadata.
        if not isinstance(value, (dict, list)):
            return '[Metadata unavailable]'
        return json.dumps(redact(value), ensure_ascii=False)
    except (ValueError, TypeError, RecursionError):
        return '[Metadata unavailable]'


def migrate(con):
    con.execute('CREATE TABLE IF NOT EXISTS worker_heartbeats (worker TEXT PRIMARY KEY, updated_at REAL NOT NULL)')


def heartbeat(con, now=None):
    con.execute("INSERT INTO worker_heartbeats(worker,updated_at) VALUES('openwa',?) ON CONFLICT(worker) DO UPDATE SET updated_at=excluded.updated_at", (time.time() if now is None else now,))
    con.commit()
