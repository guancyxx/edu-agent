"""Curriculum anchoring integration tests (A3): index singleton, assess weak-KP computation, router concept_id validation, update_node delta whitelist + mistake KP id. All deterministic — LLM seams are monkeypatched."""

import uuid as uuid_mod
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import HumanMessage

from app.engine import nodes


@pytest.fixture(autouse=True)
def _reset_index():
    import app.curriculum as cur

    cur._index = None
    yield
    cur._index = None


def test_get_index_loads_yaml():
    from app.curriculum import get_index

    index = get_index()
    assert get_index() is index
    assert len(index.list_by_grade("math", 7)) == 4
    assert sum(
        len(ch.knowledge_points)
        for grade in (7, 8)
        for ch in index.list_by_grade("math", grade)
    ) == 28
    assert index.get_kp("7-1-3").title == "有理数的加减法"


async def test_short_circuits_unaffected():
    state = {
        "messages": [HumanMessage(content="画个图讲讲负数")],
        "emotion_state": {"frustration": 0.9},
        "curriculum_kps": [{"id": "7-1-1"}],
        "weak_kps": [{"id": "7-1-1"}],
    }
    out = await nodes.router_node(state)
    assert out["selected_skill"] == "picture-explain"


async def test_router_passes_kp_context_and_keeps_valid_concept(monkeypatch):
    captured = {}

    async def fake_llm_json(skill, s):
        captured.update(s)
        return {
            "selected_skill": "concept-explain",
            "skill_layer": "atom",
            "skill_params": {"concept_id": "7-1-3"},
            "reason": "t",
        }

    monkeypatch.setattr(nodes, "_llm_json", fake_llm_json)
    state = {
        "subject": "math",
        "grade": 7,
        "curriculum_kps": [{"id": "7-1-3"}, {"id": "7-1-1"}],
        "weak_kps": [{"id": "7-1-3"}],
        "messages": [HumanMessage(content="我不懂有理数加减")],
        "emotion_state": {},
    }
    out = await nodes.router_node(state)
    assert out["skill_params"]["concept_id"] == "7-1-3"
    assert captured["weak_kps"] == [{"id": "7-1-3"}]
    assert len(captured["curriculum_kps"]) == 2


async def test_router_drops_invalid_concept_id(monkeypatch):
    async def fake_llm_json(skill, s):
        return {
            "selected_skill": "concept-explain",
            "skill_layer": "atom",
            "skill_params": {"concept_id": "负数加减随便写"},
            "reason": "t",
        }

    monkeypatch.setattr(nodes, "_llm_json", fake_llm_json)
    state = {
        "subject": "math",
        "grade": 7,
        "curriculum_kps": [{"id": "7-1-3"}, {"id": "7-1-1"}],
        "weak_kps": [{"id": "7-1-3"}],
        "messages": [HumanMessage(content="我不懂有理数加减")],
        "emotion_state": {},
    }
    out = await nodes.router_node(state)
    assert out["skill_params"]["concept_id"] == ""


async def test_router_keeps_concept_when_no_tree(monkeypatch):
    async def fake_llm_json(skill, s):
        return {
            "selected_skill": "concept-explain",
            "skill_layer": "atom",
            "skill_params": {"concept_id": "free-text"},
            "reason": "t",
        }

    monkeypatch.setattr(nodes, "_llm_json", fake_llm_json)
    state = {
        "subject": "math",
        "grade": 7,
        "messages": [HumanMessage(content="我不懂有理数加减")],
        "emotion_state": {},
    }
    out = await nodes.router_node(state)
    assert out["skill_params"]["concept_id"] == "free-text"


async def test_update_whitelists_delta_and_stamps_mistake(monkeypatch):
    from app.models import MistakeEntryDB
    from app.profile.models import StudentProfile

    uid = str(uuid_mod.uuid4())
    profile = StudentProfile(user_id=uid)
    fake_store = SimpleNamespace(load=AsyncMock(return_value=profile), save=AsyncMock())
    sessions = []

    class FakeSession:
        def __init__(self):
            self.added = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def add(self, obj):
            self.added.append(obj)

        async def commit(self):
            pass

    import app.database as database
    import app.profile.store as store

    monkeypatch.setattr(
        database,
        "async_session",
        lambda: (sessions.append(FakeSession()) or sessions[-1]),
    )
    monkeypatch.setattr(store, "profile_store", fake_store)
    state = {
        "student_id": uid,
        "subject": "math",
        "grade": 7,
        "comprehension_signal": "confused",
        "selected_skill": "concept-explain",
        "skill_params": {"concept_id": "7-1-2"},
        "knowledge_delta": {"7-1-2": 0.7, "乱写的key": 0.9},
        "messages": [HumanMessage(content="还是不懂")],
        "skill_output": "讲解",
    }
    out = await nodes.update_node(state)
    assert out == {}
    assert profile.knowledge_mastery == {"7-1-2": 0.7}
    assert len(sessions[1].added) == 1
    assert isinstance(sessions[1].added[0], MistakeEntryDB)
    assert sessions[1].added[0].knowledge_point_id == "7-1-2"


async def test_assess_computes_weak_kps(monkeypatch):
    async def fake(skill, s):
        return {"frustration": 0.1}

    monkeypatch.setattr(nodes, "_llm_json", fake)
    state = {
        "student_id": "",
        "messages": [HumanMessage(content="你好")],
        "subject": "math",
        "grade": 7,
        "knowledge_mastery": {"7-1-1": 0.8},
    }
    out = await nodes.assess_node(state)
    assert len(out["curriculum_kps"]) == 14
    assert out["weak_kps"][0]["id"] == "7-1-2"
    assert "7-1-1" not in [w["id"] for w in out["weak_kps"]]


async def test_assess_cold_start(monkeypatch):
    async def fake(skill, s):
        return {"frustration": 0.1}

    monkeypatch.setattr(nodes, "_llm_json", fake)
    state = {
        "student_id": "",
        "messages": [HumanMessage(content="你好")],
        "subject": "math",
        "grade": 7,
        "knowledge_mastery": {},
    }
    out = await nodes.assess_node(state)
    assert out["weak_kps"][0]["id"] == "7-1-1"
    curriculum = {kp["id"]: kp for kp in out["curriculum_kps"]}
    for weak in out["weak_kps"]:
        assert all(
            prereq not in curriculum
            for prereq in curriculum[weak["id"]]["prerequisites"]
        )


async def test_update_skips_malformed_delta_entries(monkeypatch):
    from app.profile.models import StudentProfile

    uid = str(uuid_mod.uuid4())
    profile = StudentProfile(user_id=uid)
    profile.knowledge_mastery = {"7-1-3": 0.8}  # must survive malformed entry
    fake_store = SimpleNamespace(load=AsyncMock(return_value=profile), save=AsyncMock())
    sessions = []

    class FakeSession:
        def __init__(self):
            self.added = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def add(self, obj):
            self.added.append(obj)

        async def commit(self):
            pass

    import app.database as database
    import app.profile.store as store

    monkeypatch.setattr(database, "async_session", lambda: (sessions.append(FakeSession()) or sessions[-1]))
    monkeypatch.setattr(store, "profile_store", fake_store)
    state = {
        "student_id": uid,
        "subject": "math",
        "grade": 7,
        "comprehension_signal": "understood",
        "selected_skill": "concept-explain",
        "skill_params": {},
        "knowledge_delta": {
            "7-1-2": 0.5,
            "7-1-3": {},
            "7-1-4": {"mastery": "abc"},
            "7-1-5": "nonsense",
            "7-1-1": True,
        },
        "messages": [HumanMessage(content="懂了")],
        "skill_output": "好",
    }
    out = await nodes.update_node(state)
    assert out == {}
    # only the valid numeric entry applied; existing 0.8 NOT erased by {}
    assert profile.knowledge_mastery == {"7-1-3": 0.8, "7-1-2": 0.5}
    # understood → no mistake recorded → only the profile session exists
    assert len(sessions) == 1
