import json
from pathlib import Path
import shutil
import subprocess
from html.parser import HTMLParser

import pytest


class RiskHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags = []
        self.text = []
    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))
    def handle_data(self, data):
        self.text.append(data)


def render_risk(s, collapsed):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is unavailable; this is not a passed JS verification")
    source = Path("tools/guanlan-prism/src/app.js").read_text(encoding="utf-8")
    start = source.index("function originalRiskMarkup(")
    end = source.index("\nfunction reviewBody(", start)
    helper = source[start:end]
    escape_function = r"""
const escape=t=>String(t??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
"""
    script = escape_function + helper + "\nconsole.log(originalRiskMarkup(" + json.dumps(s, ensure_ascii=False) + "," + json.dumps(collapsed) + "));"
    result = subprocess.run([node, "-e", script], capture_output=True, text=True, check=True)
    parsed = RiskHTML()
    parsed.feed(result.stdout)
    return result.stdout, parsed


def test_full_statement_risk_is_accessible_but_collapsed():
    row = {"reasonRisk": "原风险：同比下降，并且需连续收盘验证。"}
    before = dict(row)
    html, parsed = render_risk(row, True)
    details = [attrs for tag, attrs in parsed.tags if tag == "details"]
    assert len(details) == 1
    assert "open" not in details[0]
    assert "summary" in [tag for tag, _ in parsed.tags]
    assert row["reasonRisk"] in "".join(parsed.text)
    assert row == before


def test_missing_full_statement_keeps_risk_open():
    _, parsed = render_risk({"reasonRisk": "重要风险不能丢"}, False)
    assert "details" not in [tag for tag, _ in parsed.tags]
    assert "重要风险不能丢" in "".join(parsed.text)


def test_risk_text_does_not_become_html():
    text = '<script>alert("x")</script> & 原值'
    _, parsed = render_risk({"reasonRisk": text}, True)
    assert "script" not in [tag for tag, _ in parsed.tags]
    assert text in "".join(parsed.text)


def test_short_statement_extraction_preserves_all_three_sections(tmp_path):
    from tools.render_monitor_web import extract_daily_statement
    body = "**公司主要做什么**\n\n主营业务。\n\n**为什么会选它**\n\n支持事实与重要风险。\n\n**什么情况会让我改变看法**\n\n成交增加且连续收低时重评。"
    file = tmp_path / "daily-research-2026-09-09.md"
    file.write_text("## 今天明确推荐的股票\n\n### 样本公司（002831.SZ）\n\n" + body + "\n\n### 另一公司（000001.SZ）\n\n不应进入上一小节。\n", encoding="utf-8")
    statement, reason = extract_daily_statement(tmp_path, "2026-09-09", "样本公司", "002831.SZ")
    assert reason == ""
    assert statement == body
    assert "另一公司" not in statement


# ---------------------------------------------------------------------------
# 真实 reviewBody 调用（原推荐 tab 两分支），不只测辅助函数。
# ---------------------------------------------------------------------------

def _extract_function(source: str, name: str) -> str:
    start = source.index(f"function {name}(")
    end = source.index("\nfunction ", start + 1)
    return source[start:end]


def _run_review_body(s, review_tab="original"):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is unavailable; this is not a passed JS verification")
    source = Path("tools/guanlan-prism/src/app.js").read_text(encoding="utf-8")
    helper = _extract_function(source, "originalRiskMarkup")
    body = _extract_function(source, "reviewBody")
    stubs = r"""
const escape=t=>String(t??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
const richText=p=>String(p);
const state={reviewTab:'%s'};
const dateWord=s=>({d:'2026.09.09'});
const icon=n=>n;
""" % review_tab
    script = (
        stubs + helper + "\n" + body + "\n"
        + "console.log(JSON.stringify(reviewBody(" + json.dumps(s, ensure_ascii=False) + ", null, 0)));"
    )
    result = subprocess.run([node, "-e", script], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def test_review_body_original_tab_collapses_risk_when_full_statement_exists():
    s = {
        "name": "样本公司",
        "statementFull": "第一段支持事实。\n\n第二段包含重要风险。",
        "reasonFull": "摘要理由",
        "reasonRisk": "原风险文字。",
        "refKind": "",
        "formedOn": "2026-09-09",
    }
    before = json.dumps(s, ensure_ascii=False, sort_keys=True)
    html = _run_review_body(s)
    parsed = RiskHTML()
    parsed.feed(html)
    assert "第一段支持事实。" in html and "第二段包含重要风险。" in html
    details = [attrs for tag, attrs in parsed.tags if tag == "details"]
    assert len(details) == 1 and "open" not in details[0]
    assert "原始风险摘录" in "".join(parsed.text)
    assert "原风险文字。" in "".join(parsed.text)
    assert json.dumps(s, ensure_ascii=False, sort_keys=True) == before


def test_review_body_original_tab_keeps_risk_open_without_full_statement():
    s = {
        "name": "样本公司",
        "statementFull": "  ",
        "reasonFull": "当时存档的推荐理由摘要。",
        "reasonRisk": "唯一可见的风险文字不能折叠隐藏。",
        "refKind": "",
        "formedOn": "2026-09-09",
    }
    html = _run_review_body(s)
    parsed = RiskHTML()
    parsed.feed(html)
    assert "当时存档的推荐理由摘要。" in html
    assert "唯一可见的风险文字不能折叠隐藏。" in "".join(parsed.text)
    assert "details" not in [tag for tag, _ in parsed.tags]
    assert "原推荐中写下的风险" in html
