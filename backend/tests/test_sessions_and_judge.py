"""Direct endpoint tests for session CRUD and answer judging."""

import uuid as uuid_mod
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import app.routers.chat as chat
from app.models import ChatSessionDB, User


def _user() -> User:
    return User(id=uuid_mod.uuid4(), username="stu", password_hash="x")


def _session(user_id) -> ChatSessionDB:
    return ChatSessionDB(id=uuid_mod.uuid4(), user_id=user_id, subject="math")


class FakeResult:
    def __init__(self, obj=None, items=None):
        self._obj = obj
        self._list = list(items or [])

    def scalar_one_or_none(self):
        return self._obj

    def scalars(self):
        return self

    def all(self):
        return self._list


class FakeDB:
    """Programmable AsyncSession double that records observable DB effects."""

    def __init__(self, *results):
        self._results = list(results)
        self.selects = []
        self.last_select = None
        self.added = []
        self.deleted = []
        self.commits = 0
        self.refreshed = []

    async def execute(self, sel):
        self.last_select = sel
        self.selects.append(sel)
        return self._results.pop(0) if self._results else FakeResult()

    def add(self, obj):
        self.added.append(obj)

    async def delete(self, obj):
        self.deleted.append(obj)

    async def commit(self):
        self.commits += 1

    async def refresh(self, obj):
        self.refreshed.append(obj)
        now = datetime.now(timezone.utc)
        if obj.id is None:
            obj.id = uuid_mod.uuid4()
        if obj.created_at is None:
            obj.created_at = now
        if obj.updated_at is None:
            obj.updated_at = now


async def test_create_session_defaults():
    user = _user()
    db = FakeDB()

    out = await chat.create_session(chat.SessionCreate(), user, db)

    assert len(db.added) == 1
    assert db.commits == 1
    assert db.refreshed == db.added
    assert db.added[0].subject == "math"
    assert db.added[0].title is None
    assert isinstance(out.id, str)
    assert out.title is None
    assert out.subject == "math"
    assert out.message_count == 0
    assert out.created_at is not None
    assert out.updated_at is not None


async def test_create_session_truncates_subject():
    db = FakeDB()
    req = chat.SessionCreate(subject="s" * 100)

    await chat.create_session(req, _user(), db)

    assert len(req.subject) == 32
    assert len(db.added[0].subject) == 32
    assert db.added[0].subject == "s" * 32


@pytest.mark.parametrize(
    ("raw_title", "expected"),
    [("t" * 60, "t" * 40), ("   ", None)],
    ids=["long-title", "blank-title"],
)
async def test_create_session_truncates_title(raw_title, expected):
    db = FakeDB()

    await chat.create_session(chat.SessionCreate(title=raw_title), _user(), db)

    assert db.added[0].title == expected


async def test_create_session_empty_subject_defaults_math():
    db = FakeDB()

    await chat.create_session(chat.SessionCreate(subject=""), _user(), db)

    assert db.added[0].subject == "math"


async def test_list_sessions_filters_by_owner_and_orders():
    user = _user()
    older = _session(user.id)
    newer = _session(user.id)
    now = datetime.now(timezone.utc)
    older.created_at = older.updated_at = now - timedelta(days=1)
    newer.created_at = newer.updated_at = now
    db = FakeDB(FakeResult(items=[newer, older]))

    out = await chat.list_sessions(user, db)

    assert len(out) == 2
    assert [item.id for item in out] == [str(newer.id), str(older.id)]
    assert "user_id" in str(db.last_select.whereclause)
    assert "DESC" in str(db.last_select).upper()


async def test_delete_session_owned():
    user = _user()
    session = _session(user.id)
    db = FakeDB(FakeResult(obj=session))

    assert await chat.delete_session(str(session.id), user, db) is None
    assert db.deleted == [session]
    assert db.commits >= 1


async def test_delete_session_foreign_or_unknown_404():
    with pytest.raises(HTTPException) as exc_info:
        await chat.delete_session(
            str(uuid_mod.uuid4()), _user(), FakeDB(FakeResult(obj=None))
        )
    assert exc_info.value.status_code == 404


async def test_delete_session_invalid_uuid_400():
    with pytest.raises(HTTPException) as exc_info:
        await chat.delete_session("not-a-uuid", _user(), FakeDB())
    assert exc_info.value.status_code == 400


async def test_touch_bumps_count_and_auto_titles():
    user = _user()
    session = _session(user.id)
    session.message_count = 0
    session.title = None
    db = FakeDB(FakeResult(obj=session))
    message = "m" * 50

    out = await chat.touch_session(
        str(session.id), chat.SessionTouch(message=message), user, db
    )

    assert session.message_count == 1
    assert session.title == "m" * 40
    assert out.message_count == 1
    assert out.title == "m" * 40
    assert db.commits == 1
    assert db.refreshed == [session]


async def test_touch_keeps_existing_title():
    user = _user()
    session = _session(user.id)
    session.message_count = 4
    session.title = "已有标题"
    db = FakeDB(FakeResult(obj=session))

    out = await chat.touch_session(
        str(session.id), chat.SessionTouch(message="新消息"), user, db
    )

    assert session.title == "已有标题"
    assert session.message_count == 5
    assert out.title == "已有标题"
    assert out.message_count == 5


async def test_touch_404_and_400():
    user = _user()
    with pytest.raises(HTTPException) as not_found:
        await chat.touch_session(
            str(uuid_mod.uuid4()), chat.SessionTouch(message="x"), user,
            FakeDB(FakeResult(obj=None)),
        )
    assert not_found.value.status_code == 404

    with pytest.raises(HTTPException) as invalid:
        await chat.touch_session(
            "not-a-uuid", chat.SessionTouch(message="x"), user, FakeDB()
        )
    assert invalid.value.status_code == 400


class FakeLLM:
    def __init__(self, content=None, error=None):
        self.content = content
        self.error = error

    async def ainvoke(self, prompt):
        if self.error is not None:
            raise self.error
        return SimpleNamespace(content=self.content)


@pytest.mark.parametrize(
    ("content", "expected_correct"),
    [
        ('{"correct": true, "feedback": "对", "correct_answer": "42"}', True),
        ('{"correct": false, "feedback": "错", "correct_answer": "42"}', False),
    ],
    ids=["true", "false"],
)
async def test_judge_accepts_strict_boolean(content, expected_correct, monkeypatch):
    monkeypatch.setattr("app.engine.llm.get_llm", lambda: FakeLLM(content))

    out = await chat.judge_answer(
        chat.JudgeRequest(question="6*7?", answer="42"), _user()
    )

    assert out.correct is expected_correct
    assert out.feedback in {"对", "错"}
    assert out.correct_answer == "42"


@pytest.mark.parametrize(
    "content",
    [
        '{"correct": "false", "feedback": "x"}',
        '{"feedback": "x"}',
        '{"correct": "true", "feedback": "x"}',
    ],
    ids=["string-false", "missing-correct", "string-true"],
)
async def test_judge_rejects_non_boolean_or_missing_correct(content, monkeypatch):
    monkeypatch.setattr("app.engine.llm.get_llm", lambda: FakeLLM(content))

    with pytest.raises(HTTPException) as exc_info:
        await chat.judge_answer(
            chat.JudgeRequest(question="q", answer="a"), _user()
        )
    assert exc_info.value.status_code == 502


async def test_judge_rejects_non_json(monkeypatch):
    monkeypatch.setattr(
        "app.engine.llm.get_llm", lambda: FakeLLM("这不是JSON")
    )
    with pytest.raises(HTTPException) as exc_info:
        await chat.judge_answer(
            chat.JudgeRequest(question="q", answer="a"), _user()
        )
    assert exc_info.value.status_code == 502


async def test_judge_converts_llm_exception_to_502(monkeypatch):
    monkeypatch.setattr(
        "app.engine.llm.get_llm", lambda: FakeLLM(error=RuntimeError("boom"))
    )
    with pytest.raises(HTTPException) as exc_info:
        await chat.judge_answer(
            chat.JudgeRequest(question="q", answer="a"), _user()
        )
    assert exc_info.value.status_code == 502


async def test_judge_extracts_json_from_markdown_fence(monkeypatch):
    content = (
        '```json\n{"correct": true, "feedback": "f", '
        '"correct_answer": "a"}\n```'
    )
    monkeypatch.setattr("app.engine.llm.get_llm", lambda: FakeLLM(content))

    out = await chat.judge_answer(
        chat.JudgeRequest(question="q", answer="a"), _user()
    )
    assert out.correct is True
    assert out.feedback == "f"
    assert out.correct_answer == "a"


async def test_judge_truncates_feedback_and_correct_answer(monkeypatch):
    content = (
        '{"correct": false, "feedback": "' + "f" * 300
        + '", "correct_answer": "' + "a" * 300 + '"}'
    )
    monkeypatch.setattr("app.engine.llm.get_llm", lambda: FakeLLM(content))

    out = await chat.judge_answer(
        chat.JudgeRequest(question="q", answer="a"), _user()
    )
    assert out.feedback == "f" * 200
    assert out.correct_answer == "a" * 200


async def test_judge_missing_correct_answer_returns_none(monkeypatch):
    content = '{"correct": true, "feedback": "ok"}'
    monkeypatch.setattr("app.engine.llm.get_llm", lambda: FakeLLM(content))

    out = await chat.judge_answer(
        chat.JudgeRequest(question="q", answer="a"), _user()
    )
    assert out.correct is True
    assert out.correct_answer is None
