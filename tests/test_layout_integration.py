"""Opt-in browser integration test, enabled in CI and for local smoke checks."""
import json
import os
from pathlib import Path
import subprocess
import sys
import yaml
import pytest

REPO = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(os.environ.get('LHTML_BROWSER_TEST') != '1', reason='Set LHTML_BROWSER_TEST=1 for Chrome')
def test_two_pages_same_folder_have_distinct_reports(tmp_path):
    source = tmp_path / 'src'
    source.mkdir()
    for name, title in [('a', 'Alpha'), ('b', 'Beta')]:
        (source / (name + '.html.j2')).write_text(
            "{% set pageTitle = '" + title + "' %}\n<h1>" + title + '</h1>')
    config = tmp_path / 'configure.yaml'
    config.write_text(yaml.safe_dump({'source_directory': 'src', 'plugin': []}))
    result = subprocess.run([sys.executable, str(REPO / 'generate.py'), '-i', str(config), '--layout'],
                            capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    for name in ('a', 'b'):
        folder = tmp_path / '.layout/pages' / (name + '.html')
        assert (folder / 'layout.json').is_file()
        assert (folder / 'render.png').is_file()
        assert (folder / 'layout.md').is_file()
        assert json.loads((folder / 'layout.json').read_text())['source'] == 'src/' + name + '.html.j2'
        assert (tmp_path / '.site' / (name + '.html')).is_file()
    assert (tmp_path / '.layout/contact_01.png').is_file()
    summary = (tmp_path / '.layout/summary.md').read_text()
    assert 'a.html' in summary and 'b.html' in summary


@pytest.mark.skipif(os.environ.get('LHTML_BROWSER_TEST') != '1', reason='Set LHTML_BROWSER_TEST=1 for Chrome')
def test_nested_fixed_element_lines_and_changes(tmp_path):
    source = tmp_path / 'src/s'
    source.mkdir(parents=True)
    page = source / 'index.html.j2'
    page.write_text("= Title\n\ndiv::[font-size:85%;]\nA line of text that runs under the box\n"
                    "::[position:fixed; top:60px; left:100px; width:300px; height:80px; "
                    "background-color:rgb(200,0,0);] ::\n::\n")
    config = tmp_path / 'configure.yaml'
    config.write_text(yaml.safe_dump({'source_directory': 'src', 'plugin': [],
                                      'theme': str(REPO / 'themes/slides')}))
    run = lambda: subprocess.run([sys.executable, str(REPO / 'generate.py'), '-i', str(config), '--layout'],
                                 capture_output=True, text=True, timeout=90)
    assert run().returncode == 0
    report = (tmp_path / '.layout/pages/s/index.html/layout.md').read_text()
    assert '| 1 | 1 | title |' in report                     # line of the source (data-lhtml-src)
    assert 'in #2 |' in report                              # the fixed box, measured on its own
    assert 'HIDDEN TEXT #2 under #3' in report or 'COLLISION #2 × #3' in report
    page.write_text(page.read_text().replace('top:60px', 'top:550px'))
    assert run().returncode == 0
    changes = (tmp_path / '.layout/changes.md').read_text()
    assert '1 changed' in changes and 'moved by (+0, +490) px' in changes


@pytest.mark.skipif(os.environ.get('LHTML_BROWSER_TEST') != '1', reason='Set LHTML_BROWSER_TEST=1 for Chrome')
def test_formulas_svg_figures_auto_rows_and_render(tmp_path):
    import zlib
    import struct

    def png(path, w, h):
        row = b'\x00' + b'\x80\x80\x80' * w
        chunk = lambda t, d: struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d))
        path.write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0))
                         + chunk(b'IDAT', zlib.compress(row * h)) + chunk(b'IEND', b''))

    source = tmp_path / 'src'
    for name in ('math', 'svg', 'auto', 'wrap'):
        (source / name / 'assets').mkdir(parents=True)
    (source / 'math/index.html.j2').write_text(
        '= Formulas\n\n* Translation: linear blend, \\(t=\\sum_j \\alpha_j\\,t_j\\)\n'
        '* Rotation: \\(q=\\dfrac{\\sum_j \\alpha_j\\,q_j}{\\big\\|\\sum_j \\alpha_j\\,q_j\\big\\|}\\) (SLERP)\n')
    (source / 'svg/assets/fig.svg').write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 100" width="200" height="100">'
        '<line x1="0" y1="50" x2="200" y2="50" stroke="black" stroke-width="3"/>'
        '<text x="40" y="58" font-size="20">over the line</text>'
        '<text x="40" y="90" font-size="14" paint-order="stroke" stroke="white" stroke-width="6">halo</text>'
        '<circle cx="-30" cy="20" r="10"/></svg>')
    (source / 'svg/index.html.j2').write_text("{% set layout = 'side' %}\n= SVG\n\n* Text\n\nmedia::\nimg::assets/fig.svg\n::\n")
    png(source / 'auto/assets/a.png', 300, 200)
    png(source / 'auto/assets/b.png', 200, 200)
    (source / 'auto/index.html.j2').write_text(
        "{% set layout = 'stack' %}\n= Auto\n\n* Above\n\nmedia::(.row .auto .s)\ncol::\nimg::assets/a.png\n"
        "credit:: A ::\n::\ncol::\nimg::assets/b.png\ncredit:: B ::\n::\n::\n\n* Below\n")
    (source / 'math/index.html.j2').write_text(
        (source / 'math/index.html.j2').read_text() +
        '\n<ul style="font-size:36px;line-height:1.4"><li>A preceding line</li>'
        '<li>\\(R=\\begin{pmatrix}a&b&c\\\\d&e&f\\\\g&h&j\\end{pmatrix}\\)</li></ul>')
    (source / 'wrap/index.html.j2').write_text(
        "= Wrap\n\n<div style=\"width:420px\">\n\n* A short sentence that wraps in this narrow column\n\n"
        "<p>A short paragraph that wraps in this narrow column</p>\n\n</div>\n")
    config = tmp_path / 'configure.yaml'
    config.write_text(yaml.safe_dump({'source_directory': 'src',
                                      'plugin': ['plugins/auto_wrap.py', 'plugins/menu.py'],
                                      'theme': str(REPO / 'themes/slides')}))
    run = lambda *extra: subprocess.run([sys.executable, str(REPO / 'generate.py'), '-i', str(config), *extra],
                                        capture_output=True, text=True, timeout=120)
    result = run('--layout')
    assert result.returncode == 0, result.stdout + result.stderr
    report = lambda name: (tmp_path / '.layout/pages' / name / 'index.html/layout.md').read_text()
    math_layout = json.loads((tmp_path / '.layout/pages/math/index.html/layout.json').read_text())
    assert any(b['role'] == 'formula' for b in math_layout['subblocks'])
    assert not math_layout['analysis']['internal_collisions']
    assert 'WRAPPED' not in report('math')                    # a formula is one box, not lines
    wrap = report('wrap')
    assert 'SHORT WRAPPED' in wrap and 'list item "A short sentence' in wrap and 'paragraph "A short paragraph' in wrap
    assert 'SHORT WRAPPED' not in report('svg') + report('auto')
    svg = report('svg')
    assert 'SVG OVERFLOW' in svg and 'px left' in svg
    assert 'SVG LABEL' in svg and '"over the line" is drawn across a line' in svg and '"halo"' not in svg
    auto = json.loads((tmp_path / '.layout/pages/auto/index.html/layout.json').read_text())
    assert 'COLLAPSED' not in report('auto')
    heights = [m['h'] for b in auto['blocks'] for m in b['media']]
    assert heights and all(0 < h <= 200 for h in heights)     # drawn, at most their size
    result = run('--render', str(source / 'svg/assets/fig.svg'))
    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / '.layout/render/src/svg/assets/fig.svg.png').is_file()


@pytest.mark.skipif(os.environ.get('LHTML_BROWSER_TEST') != '1', reason='Set LHTML_BROWSER_TEST=1 for Chrome')
def test_svg_checks_edge_cases(tmp_path):
    import time
    source = tmp_path / 'src'
    svgs = {
        # no viewBox, sizes in cm: not units of the content (no false overflow)
        'cm': '<svg xmlns="http://www.w3.org/2000/svg" width="10cm" height="5cm">'
              '<rect x="10" y="10" width="300" height="150" fill="blue"/></svg>',
        # drawn far beyond the viewBox: cut
        'far': '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" width="100" height="100">'
               '<rect x="10" y="10" width="50" height="50"/><rect x="200" y="10" width="50" height="50" fill="red"/></svg>',
        # small units: a few hundredths beyond a 1×1 viewBox, shown at 600 px
        'unit': '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1" width="600" height="600">'
                '<rect x="0" y="0" width="1.03" height="1" fill="green"/></svg>',
        # many labels and lines (a plot): measured in a bounded time
        'plot': '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 1000" width="1000" height="1000">'
                + ''.join(f'<line x1="0" y1="{k}" x2="1000" y2="{k}" stroke="black"/>' for k in range(0, 1000, 1))
                + ''.join(f'<text x="{(k * 37) % 900}" y="{(k * 53) % 1000}" font-size="12">l{k}</text>' for k in range(300))
                + '</svg>',
    }
    for name, svg in svgs.items():
        (source / name / 'assets').mkdir(parents=True)
        (source / name / 'assets/fig.svg').write_text(svg)
        (source / name / 'index.html.j2').write_text(f"{{% set layout = 'side' %}}\n= {name}\n\n* Text\n\nmedia::\nimg::assets/fig.svg\n::\n")
    (source / 'inline').mkdir()
    (source / 'inline/index.html.j2').write_text(
        '= Inline\n\n<style>.later { display: none; }</style>\n'
        # letterboxed: visible in the box of the svg, out of its viewBox (not cut)
        '<svg viewBox="0 0 100 100" width="600" height="200"><rect x="-80" y="10" width="50" height="50"/></svg>\n'
        # hidden by the CSS of the page: not drawn
        '<svg viewBox="0 0 100 100" width="200" height="200"><rect width="50" height="50"/>'
        '<g class="later"><rect x="150" width="50" height="50"/></g></svg>\n'
        '<div><img src="assets/a.svg"><img class="hidden" src="assets/a.svg"></div>\n')
    (source / 'inline/assets').mkdir()
    (source / 'inline/assets/a.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10" width="100" height="100"><rect width="10" height="10"/></svg>')
    config = tmp_path / 'configure.yaml'
    config.write_text(yaml.safe_dump({'source_directory': 'src',
                                      'plugin': ['plugins/auto_wrap.py', 'plugins/menu.py'],
                                      'theme': str(REPO / 'themes/slides')}))
    start = time.monotonic()
    result = subprocess.run([sys.executable, str(REPO / 'generate.py'), '-i', str(config), '--layout'],
                            capture_output=True, text=True, timeout=170)
    assert result.returncode == 0, result.stdout + result.stderr
    assert time.monotonic() - start < 120
    report = lambda name: (tmp_path / '.layout/pages' / name / 'index.html/layout.md').read_text()
    assert 'SVG OVERFLOW' not in report('cm')
    assert 'SVG OVERFLOW' in report('far') and 'px right' in report('far')
    assert 'SVG OVERFLOW' in report('unit') and 'px right' in report('unit')
    assert 'SVG LABEL' in report('plot')
    inline = report('inline')
    assert 'SVG OVERFLOW' not in inline and 'COLLAPSED' not in inline


@pytest.mark.skipif(os.environ.get('LHTML_BROWSER_TEST') != '1', reason='Set LHTML_BROWSER_TEST=1 for Chrome')
def test_render_files_outside_the_project(tmp_path):
    project = tmp_path / 'project'
    (project / 'src').mkdir(parents=True)
    config = project / 'configure.yaml'
    config.write_text(yaml.safe_dump({'source_directory': 'src', 'plugin': []}))
    for folder, size in (('out1', 20), ('out2', 50)):
        (tmp_path / folder).mkdir()
        (tmp_path / folder / 'f.svg').write_text(
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}"><rect width="{size}" height="{size}"/></svg>')
    result = subprocess.run([sys.executable, str(REPO / 'generate.py'), '-i', str(config),
                             '--render', str(tmp_path / 'out1/f.svg'), '--render', str(tmp_path / 'out2/f.svg')],
                            capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    pngs = sorted((project / '.layout/render/_outside').rglob('f.svg.png'))
    assert len(pngs) == 2 and pngs[0].read_bytes() != pngs[1].read_bytes()


@pytest.mark.skipif(os.environ.get('LHTML_BROWSER_TEST') != '1', reason='Set LHTML_BROWSER_TEST=1 for Chrome')
def test_readiness_waits_for_explicit_async_setup_and_preserves_legacy(tmp_path):
    source = tmp_path / 'src'
    source.mkdir()
    (source / 'async.html.j2').write_text(
        '= Async\n<script>window.__lhtmlReady.optIn(); window.__lhtmlReady.waitUntil(new Promise(resolve => '
        'setTimeout(() => { const el = document.createElement("p"); el.textContent = "Finished async setup"; '
        'document.body.append(el); resolve(); }, 300)));</script>')
    (source / 'legacy.html.j2').write_text(
        '= Legacy\n<script>setTimeout(() => { const el = document.createElement("p"); '
        'el.textContent = "Legacy delayed setup"; document.body.append(el); }, 300);</script>')
    config = tmp_path / 'configure.yaml'
    config.write_text(yaml.safe_dump({'source_directory': 'src', 'plugin': ['plugins/auto_wrap.py'],
                                      'theme': str(REPO / 'themes/slides')}))
    result = subprocess.run([sys.executable, str(REPO / 'generate.py'), '-i', str(config), '--layout'],
                            cwd=REPO, capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    for page, text in [('async', 'Finished async setup'), ('legacy', 'Legacy delayed setup')]:
        layout = json.loads((tmp_path / f'.layout/pages/{page}.html/layout.json').read_text())
        assert text in json.dumps(layout)
    # the base never loads the agent extension, and writes none of its outputs
    assert not (tmp_path / '.layout/verification.json').exists()
    assert not (tmp_path / '.source-map').exists()
