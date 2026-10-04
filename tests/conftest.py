import pytest

from master_duel_advisor.cli import build_pipeline
from master_duel_advisor.demo import generate_demo


@pytest.fixture
def assets(tmp_path):
    return generate_demo(tmp_path/"demo")


@pytest.fixture
def pipeline(assets):
    instance = build_pipeline(assets["calibration"], assets["database"])
    yield instance
    instance.perception.cards.close()
