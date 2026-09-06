"""Render PRISM as an offline HTML or a modular source preview. Standard library only."""
from pathlib import Path
from typing import Any, Mapping
import argparse
import json
ROOT = Path(__file__).resolve().parents[1]


def _payload(snapshot: Mapping[str, Any], demo_showcase: bool) -> str:
    """Copy only metadata; no quote, reference-price or review transformations."""
    data = dict(snapshot)
    if not demo_showcase:
        data['presentation'] = {**data.get('presentation', {}), 'demoShowcase': False}
    return json.dumps(data, ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c')


def render_html(snapshot: Mapping[str, Any], *, demo_showcase: bool = False) -> str:
    """Integration entry point: an existing exporter supplies compatible data.

    Production defaults to the input record order. demo_showcase=True reproduces
    the approved example focus order. This never changes research decisions.
    """
    html = (ROOT / 'src/shell.html').read_text(encoding='utf-8')
    css = '\n'.join((ROOT / 'src' / name).read_text(encoding='utf-8') for name in ['base.css','prism.css'])
    replacements = {
        '/*__CSS__*/': css,
        '/*__DATA__*/': _payload(snapshot, demo_showcase),
        '/*__CORE__*/': (ROOT / 'src/core.js').read_text(encoding='utf-8'),
        '/*__APP__*/': (ROOT / 'src/app.js').read_text(encoding='utf-8'),
        '/*__EFFECTS__*/': (ROOT / 'src/effects.js').read_text(encoding='utf-8'),
    }
    for marker, value in replacements.items():
        if html.count(marker) != 1:
            raise ValueError(f'Expected exactly one template marker: {marker}')
        html = html.replace(marker, value)
    return html


def build(data_path: Path | None = None, output: Path | None = None) -> tuple[Path, ...]:
    snapshot = json.loads((data_path or ROOT / 'data/snapshot.json').read_text(encoding='utf-8'))
    demo = data_path is None
    dist = output or ROOT / 'dist/guanlan-prism.html'
    dist.parent.mkdir(parents=True, exist_ok=True)
    dist.write_text(render_html(snapshot, demo_showcase=demo), encoding='utf-8')
    if output:
        return (dist,)
    shell = (ROOT / 'src/shell.html').read_text(encoding='utf-8')
    modular = shell.replace('<style>/*__CSS__*/</style>', '<link rel="stylesheet" href="src/base.css">\n<link rel="stylesheet" href="src/prism.css">')
    modular = modular.replace('/*__DATA__*/', _payload(snapshot, demo))
    for key, file in [('CORE','core'),('APP','app'),('EFFECTS','effects')]:
        modular = modular.replace(f'<script>/*__{key}__*/</script>', f'<script src="src/{file}.js"></script>')
    index = ROOT / 'index.html'
    index.write_text(modular, encoding='utf-8')
    return dist, index


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, help='Compatible real snapshot JSON; bundled example remains unchanged')
    parser.add_argument('--out', type=Path, help='Write a single offline HTML to this path')
    args = parser.parse_args()
    for generated in build(args.data, args.out):
        print(generated)
