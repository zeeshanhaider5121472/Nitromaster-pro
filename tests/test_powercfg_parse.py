"""Unit tests: powercfg output parsing (locale-tolerant) and GUID constants."""
from __future__ import annotations

from nitromaster.core.power.powercfg import (
    SCHEME_BALANCED, SCHEME_HIGH_PERFORMANCE,
    parse_active_scheme, parse_query, parse_scheme_list,
)

EN_LIST = """
Existing Power Schemes (* Active)
-----------------------------------
Power Scheme GUID: a1841308-3541-4fab-bc81-f71556f20b4a  (Power saver)
Power Scheme GUID: 381b4222-f694-41f0-9685-ff5bb260df2e  (Balanced) *
Power Scheme GUID: 8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c  (High performance)
"""

ZH_LIST = """
现有电源方案 (* 活动)
-----------------------------------
电源方案 GUID: a1841308-3541-4fab-bc81-f71556f20b4a  (节能)
电源方案 GUID: 381b4222-f694-41f0-9685-ff5bb260df2e  (平衡) *
"""

EN_QUERY = """
Power Scheme GUID: 381b4222-f694-41f0-9685-ff5bb260df2e  (Balanced)
  Subgroup GUID: 54533251-82be-4824-96c1-47b60b740d00  (Processor power management)
    GUID Alias: SUB_PROCESSOR
    Power Setting GUID: be337238-0d82-4146-a960-4f3749d470c7  (Processor performance boost mode)
      GUID Alias: PERFBOOSTMODE
      Possible Setting Index: 000
      Current AC Power Setting Index: 0x00000002
      Current DC Power Setting Index: 0x00000001
"""

ZH_QUERY = """
电源方案 GUID: 381b4222-f694-41f0-9685-ff5bb260df2e  (平衡)
  子组 GUID: 54533251-82be-4824-96c1-47b60b740d00  (处理器电源管理)
    电源设置 GUID: be337238-0d82-4146-a960-4f3749d470c7  (处理器性能提升模式)
      可能的设置索引: 000
      当前交流电源设置索引: 0x00000002
      当前直流电源设置索引: 0x00000001
"""

POS_QUERY = """
  subgroup-ish GUID: 54533251-82be-4824-96c1-47b60b740d00  (unknown locale)
    something GUID: be337238-0d82-4146-a960-4f3749d470c7  (oddly localized)
      weird line 0x00000002
      another line 0x00000001
"""


def test_parse_scheme_list_english():
    schemes = parse_scheme_list(EN_LIST)
    assert len(schemes) == 3
    active = [s for s in schemes if s.active]
    assert len(active) == 1
    assert active[0].guid == SCHEME_BALANCED
    assert "Balanced" in active[0].name


def test_parse_scheme_list_chinese():
    schemes = parse_scheme_list(ZH_LIST)
    assert [s.guid for s in schemes if s.active] == [SCHEME_BALANCED]
    assert len(schemes) == 2


def test_parse_active_scheme():
    out = "Power Scheme GUID: 8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c  (High performance)"
    assert parse_active_scheme(out) == SCHEME_HIGH_PERFORMANCE
    assert parse_active_scheme("garbage") is None


def test_parse_query_english():
    values = parse_query(EN_QUERY)
    key = "be337238-0d82-4146-a960-4f3749d470c7"
    assert key in values
    assert values[key].ac == 2
    assert values[key].dc == 1


def test_parse_query_chinese():
    values = parse_query(ZH_QUERY)
    key = "be337238-0d82-4146-a960-4f3749d470c7"
    assert values[key].ac == 2
    assert values[key].dc == 1


def test_parse_query_positional_fallback():
    values = parse_query(POS_QUERY)
    key = "be337238-0d82-4146-a960-4f3749d470c7"
    # unknown locale: first index line = AC, second = DC
    assert values[key].ac == 2
    assert values[key].dc == 1
