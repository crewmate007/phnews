"""Tests for the Supabase persistence layer (mvp/db.py).

No real Supabase needed: get_client() returns None without env vars (no-op
mode), and the mapping logic is exercised with a fake client that records
every table operation so we can assert the JSON->rows mapping is correct.
"""
import db


# --- no-op mode (no credentials) ---------------------------------------------

def test_get_client_none_without_env(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_KEY", raising=False)
    assert db.get_client() is None


def test_write_run_noop_without_env(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_KEY", raising=False)
    assert db.write_run({"groups": [{"name": "x"}]}, "ph", "2026-05-29") is False


# --- mapping logic with a fake client ----------------------------------------

class FakeResult:
    def __init__(self, data):
        self.data = data


class FakeQuery:
    """Records operations; returns deterministic ids on execute()."""
    def __init__(self, table, log):
        self.table = table
        self.log = log
        self._op = None
        self._payload = None

    def upsert(self, payload, on_conflict=None):
        self._op = "upsert"
        self._payload = payload
        return self

    def insert(self, payload):
        self._op = "insert"
        self._payload = payload
        return self

    def delete(self):
        self._op = "delete"
        return self

    def eq(self, *_):
        return self

    def execute(self):
        self.log.append((self.table, self._op, self._payload))
        if self.table == "runs":
            return FakeResult([{"id": "run-1"}])
        if self.table == "topics":
            n = len([x for x in self.log if x[0] == "topics" and x[1] == "insert"])
            return FakeResult([{"id": f"topic-{n}"}])
        return FakeResult([{}])


class FakeClient:
    def __init__(self):
        self.log = []

    def table(self, name):
        return FakeQuery(name, self.log)


SAMPLE_GROUP = {
    "name": "NBA Western Conference",
    "name_zh": "NBA西部决赛",
    "narrative": "Spurs vs Thunder",
    "topic_type": "sports",
    "density": 5,
    "entry_ids": [0, 1, 2],
    "market_hint": "Series winner",
    "source_mix": {"google_news": 5},
    "source_labels": ["Google News 5"],
    "R": 2, "R_reason": "clear", "S": 2, "S_reason": "official",
    "T": 2, "T_reason": "soon", "U": 2, "U_reason": "tight", "H": 2, "H_reason": "huge",
    "BDLT": {"B": 2, "D": 2, "L": 2, "T": 2, "total": 8},
    "bettable": True,
    "suggested_question": "Will the Spurs win?",
    "suggested_question_zh": "马刺会赢吗？",
    "resolution_source": "NBA.com",
    "disposition_hint": "top",
    "why_users_bet": "NBA crazy",
    "serious_candidates": [
        {"suggested_question": "Will the Spurs win?", "suggested_question_zh": "马刺会赢吗？",
         "resolution_source": "NBA.com", "R": 2, "S": 2, "T": 2, "U": 2, "H": 2,
         "BDLT": {"B": 2, "D": 2, "L": 2, "T": 2}},
        {"suggested_question": "Alt?", "suggested_question_zh": "备选？",
         "resolution_source": "ESPN", "R": 2, "S": 1, "T": 2, "U": 1, "H": 1,
         "BDLT": {"B": 1, "D": 1, "L": 1, "T": 1}},
    ],
    "reddit_angles": [
        {"subtopic": "draft", "question_en": "Reddit q", "question_zh": "侧写", "source": "NBA PR", "url": None},
    ],
    "tiktok_angles": [
        {"subtopic": "spurs", "question_en": "🔥 q", "question_zh": "🔥 爆款", "source": "NBA", "url": None},
    ],
    "source_examples": [
        {"id": 0, "source": "google_news", "source_label": "Google News", "section": "Sports",
         "title_en": "Spurs force Game 7", "title_zh": "Spurs force Game 7",
         "summary_en": "...", "summary_zh": "...", "link": "https://x", "rank_score": 28.0,
         "social_heat": "medium", "uncertainty": "medium"},
    ],
}


def _run_with_fake(monkeypatch, result):
    monkeypatch.setenv("SUPABASE_URL", "https://fake.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "fake-key")
    fake = FakeClient()
    monkeypatch.setattr(db, "get_client", lambda: fake)
    ok = db.write_run(result, "ph", "2026-05-29")
    return ok, fake.log


def test_write_run_maps_all_tables(monkeypatch):
    ok, log = _run_with_fake(monkeypatch, {
        "total_entries": 120, "clustered_at": "2026-05-29T00:00:00+00:00",
        "cluster_pipeline": "broad_then_angles", "target_group_range": [25, 60],
        "groups": [SAMPLE_GROUP],
    })
    assert ok is True
    ops = [(t, op) for t, op, _ in log]
    assert ("runs", "upsert") in ops
    assert ("topics", "delete") in ops
    assert ("topics", "insert") in ops
    assert ("angles", "insert") in ops
    assert ("source_examples", "insert") in ops


def test_topic_payload_fields(monkeypatch):
    _, log = _run_with_fake(monkeypatch, {"groups": [SAMPLE_GROUP]})
    topic_payload = next(p for t, op, p in log if t == "topics" and op == "insert")
    assert topic_payload["name"] == "NBA Western Conference"
    assert topic_payload["R"] == 2 and topic_payload["H"] == 2
    assert topic_payload["bettable"] is True
    assert topic_payload["bdlt"]["total"] == 8
    assert topic_payload["region"] == "ph" and topic_payload["run_date"] == "2026-05-29"
    assert topic_payload["serious_status"] == "done"
    assert topic_payload["reddit_status"] == "done"
    assert topic_payload["tiktok_status"] == "done"


def test_angles_flattened(monkeypatch):
    _, log = _run_with_fake(monkeypatch, {"groups": [SAMPLE_GROUP]})
    angle_rows = next(p for t, op, p in log if t == "angles" and op == "insert")
    types = [a["angle_type"] for a in angle_rows]
    assert types.count("serious_candidate") == 2
    assert types.count("reddit") == 1
    assert types.count("tiktok") == 1
    primary = [a for a in angle_rows if a["angle_type"] == "serious_candidate" and a["is_primary"]]
    assert len(primary) == 1
    assert primary[0]["question_en"] == "Will the Spurs win?"


def test_pending_checkpoints_when_angle_absent(monkeypatch):
    g = dict(SAMPLE_GROUP)
    g.pop("reddit_angles")
    g.pop("tiktok_angles")
    _, log = _run_with_fake(monkeypatch, {"groups": [g]})
    topic_payload = next(p for t, op, p in log if t == "topics" and op == "insert")
    assert topic_payload["reddit_status"] == "pending"
    assert topic_payload["tiktok_status"] == "pending"
    assert topic_payload["serious_status"] == "done"
