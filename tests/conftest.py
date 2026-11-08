import json

import pytest

from mason.config import load_config
from mason.llm import LLM


@pytest.fixture
def config(tmp_path):
    cfg = load_config()
    cfg.cache_dir = tmp_path / "cache"
    cfg.state_dir = tmp_path / "state"
    return cfg


@pytest.fixture
def fake_llm(tmp_path):
    """Factory: fake_llm(responder) -> offline LLM. responder(request) returns model text."""

    def make(responder=lambda req: "ok", **kw):
        return LLM.fake(responder, tmp_dir=tmp_path, **kw)

    return make


def as_json(obj) -> str:
    return json.dumps(obj)
