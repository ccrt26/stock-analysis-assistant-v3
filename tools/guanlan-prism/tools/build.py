"""Render PRISM as an offline HTML or a modular source preview. Standard library only.

模板替换合同（F11/T42—T45）：
- 占位符只在原 shell 模板上查找与计数，一次替换；插入的正文/代码即使包含与
  占位符同名的文本也不会被当成下一轮模板指令。
- 单文件与拆分预览共用同一份有序资产清单（base→prism→v3，core→rules→app→effects）。
- JSON 输出为标准有限值 JSON：NaN/Infinity 明确报错，不默默变 0；
  '<' 转义防止正文中出现 </script> 提前结束页面脚本。
"""
from pathlib import Path
from typing import Any, Mapping
import argparse
import json
import re
ROOT = Path(__file__).resolve().parents[1]

# 单一有序资产清单：单文件内联与拆分预览都按此顺序生成（T45）。
STYLES = ('base.css', 'prism.css', 'v3.css')
SCRIPTS = ('core.js', 'rules.js', 'app.js', 'effects.js')
SCRIPT_KEYS = {name: name.split('.')[0].upper() for name in SCRIPTS}
MARKERS = (
    ('CSS', '/*__CSS__*/'),
    ('DATA', '/*__DATA__*/'),
    *[(SCRIPT_KEYS[name], f'/*__{SCRIPT_KEYS[name]}__*/') for name in SCRIPTS],
)


def _payload(snapshot: Mapping[str, Any]) -> str:
    """Serialize source data unchanged; escaping '<' prevents script termination.

    allow_nan=False：非有限数值（NaN/Infinity）直接抛 ValueError，不输出
    浏览器 JSON.parse 拒绝的内容，也不自动补 0（T44）。
    """
    return json.dumps(
        dict(snapshot), ensure_ascii=False, separators=(',', ':'), allow_nan=False,
    ).replace('<', '\\u003c')


def _validate(snapshot: Mapping[str, Any]) -> None:
    """必需元数据与数组长度在构建期校验；空记录列表合法，坏输入明确报错（G1）。"""
    import re
    analysis = snapshot.get('analysis_date')
    if not isinstance(analysis, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', analysis):
        raise ValueError(f'analysis_date 必须是 YYYY-MM-DD：{analysis!r}')
    dates = snapshot.get('dates')
    if not isinstance(dates, list) or not dates:
        raise ValueError('快照缺少非空 dates 交易日序列')
    market = snapshot.get('market', [])
    if not isinstance(market, list) or len(market) != len(dates):
        raise ValueError(f'market 长度 {len(market)} 与 dates 长度 {len(dates)} 不一致')
    if not isinstance(snapshot.get('stocks', []), list):
        raise ValueError('stocks 必须是数组（可为空）')
    session = snapshot.get('sessionDates')
    if session is not None and (not isinstance(session, list) or len(session) != len(dates)):
        raise ValueError(f'sessionDates 长度与 dates 长度不一致')


def render_html(snapshot: Mapping[str, Any]) -> str:
    """Existing exporters supply a dated snapshot. No demo-only selection branch."""
    _validate(snapshot)
    template = (ROOT / 'src/shell.html').read_text(encoding='utf-8')
    replacements = {
        'CSS': '\n'.join(
            (ROOT / 'src' / name).read_text(encoding='utf-8') for name in STYLES),
        'DATA': _payload(snapshot),
        **{
            SCRIPT_KEYS[name]: (ROOT / 'src' / name).read_text(encoding='utf-8')
            for name in SCRIPTS
        },
    }
    for _, marker in MARKERS:
        if template.count(marker) != 1:
            raise ValueError(f'Expected exactly one template marker: {marker}')
    # 单遍分割替换：只有原模板上的占位符参与扫描；插入的正文/代码即使包含
    # 与占位符同名的文本，也不会被当成模板指令（F11/T42）。
    mapping = {marker: replacements[key] for key, marker in MARKERS}
    pattern = re.compile('(' + '|'.join(re.escape(m) for _, m in MARKERS) + ')')
    html = ''.join(
        mapping.get(chunk, chunk) for chunk in pattern.split(template)
    )
    return html


def build(data_path: Path | None = None, output: Path | None = None) -> tuple[Path, ...]:
    snapshot = json.loads((data_path or ROOT / 'data/snapshot.json').read_text(encoding='utf-8'))
    dist = output or ROOT / 'dist/guanlan-prism.html'
    dist.parent.mkdir(parents=True, exist_ok=True)
    dist.write_text(render_html(snapshot), encoding='utf-8')
    if output:
        return (dist,)
    # 拆分预览：同一模板、同一资产清单，仅把内联替换为引用（T45）。
    shell = (ROOT / 'src/shell.html').read_text(encoding='utf-8')
    payload = _payload(snapshot)
    html = shell.replace('<script id="snapshot" type="application/json">/*__DATA__*/</script>',
                         f'<script id="snapshot" type="application/json">{payload}</script>')
    html = html.replace('<style>/*__CSS__*/</style>',
                        '\n'.join(f'<link rel="stylesheet" href="src/{name}">' for name in STYLES))
    for name in SCRIPTS:
        html = html.replace(f'<script>/*__{SCRIPT_KEYS[name]}__*/</script>',
                            f'<script src="src/{name}"></script>')
    index = ROOT / 'index.html'
    index.write_text(html, encoding='utf-8')
    return dist, index


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, help='Compatible real snapshot JSON; bundled example remains unchanged')
    parser.add_argument('--out', type=Path, help='Write a single offline HTML to this path')
    args = parser.parse_args()
    for generated in build(args.data, args.out):
        print(generated)
