import re

from quant_vnext.alpha158_catalog import ALPHA158_RESEARCH_FACTORS
from quant_vnext.registry import default_registry


def test_alpha158_catalog_is_research_only():
    production_names = {item.name for item in default_registry().production()}
    assert ALPHA158_RESEARCH_FACTORS
    assert all(not item.production for item in ALPHA158_RESEARCH_FACTORS)
    assert not production_names.intersection(item.name for item in ALPHA158_RESEARCH_FACTORS)


def test_alpha158_catalog_has_no_future_refs():
    assert all(not re.search(r"Ref\([^)]*,\s*-\d+", item.formula) for item in ALPHA158_RESEARCH_FACTORS)


def test_alpha158_catalog_has_complete_contract_metadata():
    assert len({item.name for item in ALPHA158_RESEARCH_FACTORS}) == len(ALPHA158_RESEARCH_FACTORS)
    assert all(item.source == "qlib_alpha158" for item in ALPHA158_RESEARCH_FACTORS)
    assert all(item.period and item.period > 0 for item in ALPHA158_RESEARCH_FACTORS)
    assert all(item.validity == "research" for item in ALPHA158_RESEARCH_FACTORS)
