"""Execute the tracked A2 renderer, without a second Markdown implementation."""
import json
import re
import subprocess
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / 'tools/guanlan-prism/concept-a/a2/overview.js'


def render(*articles):
    text = SOURCE.read_text()
    script = '\n'.join([next(l for l in text.splitlines() if l.startswith('const esc=')),
                        next(l for l in text.splitlines() if l.startswith('const safeHref=')),
                        text[text.index('let statementSequence='):text.index('function trackingNotice(')]])
    script += '\nprocess.stdout.write(JSON.stringify(' + json.dumps(articles) + '.map(statementParagraphs)));'
    result = subprocess.run(['node', '-e', script], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def test_repeated_source_has_four_links_one_definition_and_input_unchanged():
    body = '一[^行情]二[^行情]三[^行情]四[^行情]\n\n[^行情]: 原行情说明 [公司报告](https://example.org/report.pdf)'
    before = body.encode()
    html, = render(body)
    assert html.count('class="statement-footnote-ref"') == 4
    assert html.count('<li id=') == 1
    assert '[^行情]' not in html and body.encode() == before
    assert 'href="https://example.org/report.pdf"' in html
    targets = re.findall(r'class="statement-footnote-ref" href="#([^"]+)"', html)
    assert len(set(targets)) == 1 and f'id="{targets[0]}"' in html


def test_article_ids_do_not_collide():
    first, second = render('甲[^行情]\n\n[^行情]: 甲来源', '乙[^行情]\n\n[^行情]: 乙来源')
    assert not set(re.findall(r'id="([^"]+)"', first)) & set(re.findall(r'id="([^"]+)"', second))
    assert '乙来源' not in first and '甲来源' not in second


def test_multiline_fences_inline_code_and_adjacent_body():
    html, = render('正文[^甲] `[^甲]`\n\n[^甲]: 首行\n    次行\n\n    第三行\n\n相邻正文\n\n```md\n[^甲]: 代码\n[^甲]\n```')
    assert html.count('class="statement-footnote-ref"') == 1
    assert '<code>[^甲]</code>' in html
    assert '首行<br>次行<br><br>第三行' in html and '相邻正文' in html
    assert '<code>[^甲]: 代码\n[^甲]</code>' in html


def test_missing_conflicting_and_unsafe_sources_remain_visible():
    html, = render('正文[^缺]与[^甲] <script>alert(1)</script>\n\n[^甲]: [危险](javascript:alert)\n\n[^甲]: 冲突的另一来源')
    assert '来源缺失：缺' in html and '来源定义冲突：甲' in html and '冲突的另一来源' in html
    assert '<script>' not in html and 'href="javascript:' not in html


def test_old_article_without_notes_keeps_links_and_emphasis():
    html, = render('业务**数字**与[报告](https://example.org/a)\n\n- 条件一\n- 条件二')
    assert '<strong>数字</strong>' in html and '<ul class="original-copy">' in html
    assert 'statement-sources' not in html
