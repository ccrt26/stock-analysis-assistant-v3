"""复盘价格上下文纯函数的确定性测试：公式、61日窗口边界、缺口、除权与入口口径。"""

from datetime import date, timedelta

import pytest

from stock_analyzer.ops.forward_monitor import _build_review_price_context


def _flat_sessions(count: int, start: date = date(2026, 1, 1)) -> list[date]:
    return [start + timedelta(days=i) for i in range(count)]


def _rows(
    days: list[date],
    *,
    open_: float = 7.9,
    high: float = 8.03075,
    low: float = 7.76925,
    close: float = 7.9,
    amount: float = 100.0,
) -> list[dict]:
    return [
        dict(date=day, open=open_, high=high, low=low, close=close, amount=amount)
        for day in days
    ]


def _benchmark(days: list[date], *, open_: float = 100.0, close: float = 100.0) -> list[dict]:
    return [dict(trade_date=day, open=open_, close=close) for day in days]


def test_review_context_original_target_and_including_today_amount():
    days = [date(2026, 1, 1) + timedelta(days=i) for i in range(61)]
    rows = [
        dict(date=d, open=7.9, high=8.03075, low=7.76925,
             close=7.9, amount=100.0)
        for d in days
    ]
    rows[40]["open"] = 7.19
    rows[40]["low"] = 7.19
    rows[-1]["amount"] = 200.0
    result = _build_review_price_context(
        action_date=days[40], analysis_date=days[-1],
        session_dates=days, adjusted_history=rows,
        normalization_factor=1.0,
        benchmark_daily=[
            dict(trade_date=d, open=100.0, close=100.0) for d in days
        ],
    )
    levels = result["price_levels"]
    assert levels["target_price"] == pytest.approx(8.628)
    assert levels["remaining_return_to_target"] == pytest.approx(8.628 / 7.9 - 1)
    assert levels["atr20"] == pytest.approx(0.2615)
    assert levels["remaining_atr_to_target"] == pytest.approx(0.728 / 0.2615)
    assert result["recent_sessions"][-1]["amount_ratio_including_today_20d"] == pytest.approx(200 / 105)


def test_target_and_remaining_distance_from_entry_7_19() -> None:
    """入口7.19、当前7.90、ATR20为0.2615：目标8.628，余程按符号保留。"""
    days = _flat_sessions(61)
    rows = _rows(days)
    rows[40]["open"] = 7.19
    rows[40]["low"] = 7.19
    rows[-1]["close"] = 7.90
    result = _build_review_price_context(
        action_date=days[40],
        analysis_date=days[-1],
        session_dates=days,
        adjusted_history=rows,
        normalization_factor=1.0,
        benchmark_daily=_benchmark(days),
    )
    levels = result["price_levels"]
    assert levels["entry_reference_price"] == pytest.approx(7.19)
    assert levels["target_price"] == pytest.approx(8.628)
    assert levels["remaining_return_to_target"] == pytest.approx(8.628 / 7.90 - 1)
    assert levels["remaining_atr_to_target"] == pytest.approx(0.728 / 0.2615)


def test_amount_ratio_uses_including_today_average_not_2() -> None:
    """20个会话前19日成交额100、今日200：含当日均额105，量比200/105。"""
    days = _flat_sessions(61)
    rows = _rows(days)
    rows[-1]["amount"] = 200.0
    result = _build_review_price_context(
        action_date=days[40],
        analysis_date=days[-1],
        session_dates=days,
        adjusted_history=rows,
        normalization_factor=1.0,
        benchmark_daily=_benchmark(days),
    )
    recent = result["recent_sessions"]
    assert len(recent) == 5
    assert recent[-1]["amount_ratio_including_today_20d"] == pytest.approx(200 / 105)
    assert recent[-1]["amount_change_1d"] == pytest.approx(1.0)
    assert recent[-1]["close_return_1d"] == pytest.approx(0.0)


def test_dividend_adjustment_normalizes_entry_and_target() -> None:
    """除权：入口raw10/F1、当前raw6/F2；收益20%，归一入口5、当前6、目标6。

    adjusted_history 记录的是 raw×当日复权因子：入口10×1=10，当前6×2=12。
    """
    days = _flat_sessions(61)
    rows = _rows(days)
    rows[40].update(open=10.0, high=10.2, low=9.8, close=10.0)
    rows[-1].update(open=12.0, high=12.2, low=11.8, close=12.0)
    result = _build_review_price_context(
        action_date=days[40],
        analysis_date=days[-1],
        session_dates=days,
        adjusted_history=rows,
        normalization_factor=2.0,
        benchmark_daily=_benchmark(days),
    )
    levels = result["price_levels"]
    assert levels["entry_reference_price"] == pytest.approx(5.0)
    assert levels["current_close"] == pytest.approx(6.0)
    assert levels["target_price"] == pytest.approx(6.0)
    assert result["post_entry_sessions"][-1]["close_return"] == pytest.approx(0.2)
    assert result["stock_excess_since_entry"] == pytest.approx(0.2)


def test_high_close_return_excludes_formation_day() -> None:
    """形成日收盘12、行动日开盘10、后续最高收盘11：最高收盘收益10%。"""
    days = _flat_sessions(61)
    rows = _rows(days)
    rows[39].update(open=12.0, high=12.2, low=11.9, close=12.0)  # 形成日
    rows[40].update(open=10.0, high=10.2, low=9.9, close=10.1)  # 行动日
    rows[50].update(open=10.9, high=11.1, low=10.8, close=11.0)  # 后续最高收盘
    result = _build_review_price_context(
        action_date=days[40],
        analysis_date=days[-1],
        session_dates=days,
        adjusted_history=rows,
        normalization_factor=1.0,
        benchmark_daily=_benchmark(days),
    )
    post = result["post_entry_sessions"]
    assert len(post) == 21
    best = max(item["close_return"] for item in post)
    assert best == pytest.approx(0.10)
    assert all(item["close_return"] != pytest.approx(0.20) for item in post)


def test_same_code_two_episodes_keep_separate_entries() -> None:
    """同代码两个episode，入口10和12：当前11分别+10%和−8.3333%。"""
    days = _flat_sessions(61)
    rows = _rows(days)
    rows[-1]["close"] = 11.0
    for entry_open, expected in ((10.0, 0.10), (12.0, -1.0 / 12.0)):
        current = _rows(days)
        current[40]["open"] = entry_open
        current[-1] = {**current[-1], "close": 11.0}
        result = _build_review_price_context(
            action_date=days[40],
            analysis_date=days[-1],
            session_dates=days,
            adjusted_history=current,
            normalization_factor=1.0,
            benchmark_daily=_benchmark(days),
        )
        last = result["post_entry_sessions"][-1]
        assert last["close_return"] == pytest.approx(expected, rel=1e-6)


def test_benchmark_windows_use_only_provided_benchmark_rows() -> None:
    """benchmark另附000001.SH行：读取层只传000300.SH，窗口与入口均用沪深300。"""
    days = _flat_sessions(61)
    rows = _rows(days)
    rows[40]["open"] = 10.0
    rows[-1]["close"] = 11.0
    benchmark = _benchmark(days)
    benchmark[-1]["close"] = 102.0  # 分析日收盘抬升
    benchmark[-2]["close"] = 101.0  # 前一收盘抬升
    benchmark[40]["open"] = 100.0
    # 模拟读取层误传的其他指数行不应出现在输入里；这里只校验函数只用给定行。
    result = _build_review_price_context(
        action_date=days[40],
        analysis_date=days[-1],
        session_dates=days,
        adjusted_history=rows,
        normalization_factor=1.0,
        benchmark_daily=benchmark,
    )
    assert result["benchmark_return_since_entry"] == pytest.approx(0.02)
    assert result["stock_excess_since_entry"] == pytest.approx(0.10 - 0.02)
    windows = {item["days"]: item for item in result["benchmark_windows"]}
    assert windows[1]["return"] == pytest.approx(102.0 / 101.0 - 1.0)
    assert windows[3]["return"] == pytest.approx(0.02)
    assert windows[5]["return"] == pytest.approx(0.02)
    assert windows[20]["return"] == pytest.approx(0.02)
    assert windows[1]["start_date"] == days[-2].isoformat()
    assert windows[1]["end_date"] == days[-1].isoformat()


def test_missing_action_day_open_keeps_entry_empty() -> None:
    """行动日无开盘、后一天有报价：原参考价仍空，不得后移入口。"""
    days = _flat_sessions(61)
    rows = _rows(days)
    del rows[40]  # 行动日无报价
    result = _build_review_price_context(
        action_date=days[40],
        analysis_date=days[-1],
        session_dates=days,
        adjusted_history=rows,
        normalization_factor=1.0,
        benchmark_daily=_benchmark(days),
    )
    levels = result["price_levels"]
    assert levels["entry_reference_price"] is None
    assert levels["target_price"] is None
    assert levels["remaining_return_to_target"] is None
    assert result["stock_excess_since_entry"] is None
    post = result["post_entry_sessions"]
    assert post[0]["date"] == days[40].isoformat()  # 空行保留，不被后一天顶替
    assert post[0]["close"] is None and post[0]["close_return"] is None
    assert post[1]["date"] == days[41].isoformat()
    assert "review_context_missing_action_day_open" in result["limitations"]


def test_gap_days_preserve_holes_and_empty_dependent_windows() -> None:
    """日历中间缺报价：保留缺口，受影响的均额/前高/ATR为空，其余合法事实保留。"""
    days = _flat_sessions(61)
    rows = _rows(days)
    rows[40]["open"] = 7.19
    del rows[50]  # 中间缺一个会话报价
    del rows[-2]  # 最近窗口内也缺一个
    result = _build_review_price_context(
        action_date=days[40],
        analysis_date=days[-1],
        session_dates=days,
        adjusted_history=rows,
        normalization_factor=1.0,
        benchmark_daily=_benchmark(days),
    )
    post = result["post_entry_sessions"]
    assert any(item["date"] == days[50].isoformat() and item["close"] is None for item in post)
    recent = result["recent_sessions"]
    assert any(item["date"] == days[59].isoformat() and item["close"] is None for item in recent)
    levels = result["price_levels"]
    assert levels["prior60_high"] is None  # 前高窗口不完整
    assert levels["atr20"] is None  # ATR窗口不完整
    assert "review_context_incomplete_prior60" in result["limitations"]
    assert "review_context_incomplete_atr20" in result["limitations"]
    assert levels["entry_reference_price"] == pytest.approx(7.19)
    assert levels["current_close"] == pytest.approx(7.9)
    assert result["benchmark_windows"][-1]["return"] == pytest.approx(0.0)


def test_insufficient_session_history_leaves_windows_empty() -> None:
    """不足20/60个会话：前高、ATR、20日窗口为空，入口与5日近期仍可计算。"""
    days = _flat_sessions(15)
    rows = _rows(days)
    rows[5]["open"] = 7.19
    result = _build_review_price_context(
        action_date=days[5],
        analysis_date=days[-1],
        session_dates=days,
        adjusted_history=rows,
        normalization_factor=1.0,
        benchmark_daily=_benchmark(days),
    )
    levels = result["price_levels"]
    assert levels["prior60_high"] is None
    assert levels["atr20"] is None
    assert result["recent_sessions"][-1]["amount_ratio_including_today_20d"] is None
    assert result["post_entry_sessions"][0]["close_return"] == pytest.approx(
        7.9 / 7.19 - 1
    )
    assert "review_context_incomplete_prior60" in result["limitations"]


def test_missing_analysis_factor_blanks_money_levels_only() -> None:
    """分析日F缺失：人民币价位字段为空，入口收益类字段保持可算。"""
    days = _flat_sessions(61)
    rows = _rows(days)
    rows[40]["open"] = 7.19
    rows[-1]["close"] = 7.90
    result = _build_review_price_context(
        action_date=days[40],
        analysis_date=days[-1],
        session_dates=days,
        adjusted_history=rows,
        normalization_factor=None,
        benchmark_daily=_benchmark(days),
    )
    levels = result["price_levels"]
    assert levels["entry_reference_price"] is None
    assert levels["current_close"] is None
    assert levels["target_price"] is None
    assert levels["remaining_return_to_target"] is None
    assert levels["prior60_high"] is None
    assert levels["prior60_high_date"] is not None  # 日期事实仍保留
    last_post = result["post_entry_sessions"][-1]
    assert last_post["close"] is None  # 归一价缺失
    assert last_post["close_return"] == pytest.approx(7.90 / 7.19 - 1)  # 收益保留
    assert "review_context_missing_analysis_day_factor" in result["limitations"]


def test_prior60_takes_latest_of_tied_highs() -> None:
    """并列最高值取最近一次发生日期。"""
    days = _flat_sessions(61)
    rows = _rows(days)
    rows[10]["high"] = 8.5
    rows[30]["high"] = 8.5
    rows[40]["open"] = 7.19
    result = _build_review_price_context(
        action_date=days[40],
        analysis_date=days[-1],
        session_dates=days,
        adjusted_history=rows,
        normalization_factor=1.0,
        benchmark_daily=_benchmark(days),
    )
    assert result["price_levels"]["prior60_high"] == pytest.approx(8.5)
    assert result["price_levels"]["prior60_high_date"] == days[30].isoformat()


def test_completed_target_keeps_signed_remaining_fields() -> None:
    """已完成目标时剩余字段保留符号，不渲染成"还差负数"以外的值。"""
    days = _flat_sessions(61)
    rows = _rows(days)
    rows[40]["open"] = 7.19
    rows[-1]["close"] = 9.0  # 已超过目标8.628
    result = _build_review_price_context(
        action_date=days[40],
        analysis_date=days[-1],
        session_dates=days,
        adjusted_history=rows,
        normalization_factor=1.0,
        benchmark_daily=_benchmark(days),
    )
    levels = result["price_levels"]
    assert levels["target_price"] == pytest.approx(8.628)
    assert levels["remaining_return_to_target"] < 0  # 符号保留，由展示层决定措辞
    assert levels["remaining_atr_to_target"] < 0


def test_recent_sessions_may_include_pre_action_days_with_dates() -> None:
    """recent_sessions 可能含推荐前日期，必须保留日期字段。"""
    days = _flat_sessions(61)
    rows = _rows(days)
    rows[58]["open"] = 7.19  # 行动日在最后5日之内
    result = _build_review_price_context(
        action_date=days[58],
        analysis_date=days[-1],
        session_dates=days,
        adjusted_history=rows,
        normalization_factor=1.0,
        benchmark_daily=_benchmark(days),
    )
    recent = result["recent_sessions"]
    assert [item["date"] for item in recent] == [
        days[index].isoformat() for index in range(56, 61)
    ]
    assert recent[0]["date"] < result["post_entry_sessions"][0]["date"]