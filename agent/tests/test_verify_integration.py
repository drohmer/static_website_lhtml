"""Opt-in browser tests of --verify (agent extension): LHTML_BROWSER_TEST=1."""
import json
import os
from pathlib import Path
import subprocess
import sys
import yaml
import pytest

REPO = Path(__file__).resolve().parents[2]


@pytest.mark.skipif(os.environ.get('LHTML_BROWSER_TEST') != '1', reason='Set LHTML_BROWSER_TEST=1 for Chrome')
def test_verify_health_crops_and_resolution(tmp_path):
    source = tmp_path / 'src/s'
    source.mkdir(parents=True)
    page = source / 'index.html.j2'
    page.write_text('= Verification\n\n'
        'div::[position:fixed;left:100px;top:200px;width:200px;height:100px;background:red;] A ::\n'
        'div::[position:fixed;left:120px;top:220px;width:200px;height:100px;background:blue;] B ::\n'
        'img::missing.png\n<script>throw new Error("fixture error")</script>')
    config = tmp_path / 'configure.yaml'
    config.write_text(yaml.safe_dump({'source_directory': 'src',
                                      'plugin': ['plugins/auto_wrap.py', 'plugins/menu.py'],
                                      'theme': str(REPO / 'themes/slides')}))
    def run():
        result = subprocess.run([sys.executable, str(REPO / 'generate.py'), '-i', str(config), '--verify'],
                                capture_output=True, text=True, timeout=90)
        assert result.returncode == 0, result.stdout + result.stderr
        folder = tmp_path / '.layout/pages/s/index.html'
        return folder, json.loads((folder / 'verification.json').read_text())
    folder, value = run()
    assert value['status'] == 'incomplete'
    assert {'image', 'javascript'} <= {e['type'] for e in value['render_health']['errors']}
    assert any(d['type'] == 'collisions' for d in value['diagnostics'])
    assert any((folder / d['evidence']['crop']).is_file() for d in value['diagnostics'] if 'crop' in d['evidence'])
    page.write_text('= Verification\n\nA simple page.\n')
    folder, value = run()
    assert value['status'] == 'pass'
    assert value['changes']['resolved']
    assert not (folder / 'issues').exists()


@pytest.mark.skipif(os.environ.get('LHTML_BROWSER_TEST') != '1', reason='Set LHTML_BROWSER_TEST=1 for Chrome')
def test_persistent_include_identity_and_incremental_dependencies(tmp_path):
    source = tmp_path / 'src'
    (source / 'parts').mkdir(parents=True)
    shared = source / 'parts/common.j2'
    (source / 'shared').mkdir()
    image = source / 'shared/figure.svg'
    image.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100"><rect width="200" height="100" fill="red"/></svg>')
    shared.write_text('div::[position:fixed;left:100px;top:200px;width:200px;height:100px;background:red;] Shared ::\n'
                      'img::../shared/figure.svg\n')
    for name in ('a', 'b', 'c'):
        folder = source / name
        folder.mkdir()
        folder.joinpath('index.html.j2').write_text('= ' + name + '\n' +
            ('{% include "parts/common.j2" %}\n' if name != 'c' else 'Other content\n'))
    config = tmp_path / 'configure.yaml'
    config.write_text(yaml.safe_dump({'source_directory': 'src', 'theme': str(REPO / 'themes/slides'),
                                     'plugin': ['plugins/auto_wrap.py', 'plugins/menu.py']}))
    def run(*args):
        result = subprocess.run([sys.executable, str(REPO / 'generate.py'), '-i', str(config), '--verify', *args],
                                capture_output=True, text=True, timeout=90)
        assert result.returncode == 0, result.stdout + result.stderr
    def read(name):
        return json.loads((tmp_path / '.layout/pages' / name / 'index.html/layout.json').read_text())
    run()
    before = read('a')
    old = next(b for b in before['blocks'] if 'Shared' in b['signature'])
    untouched = (tmp_path / '.layout/pages/c/index.html/render.png').stat().st_mtime_ns
    shared.write_text('\n\n' + shared.read_text().replace('Shared', 'Edited label'))
    run('--only', 'a')
    after = read('a')
    new = next(b for b in after['blocks'] if 'Edited label' in b['signature'])
    assert new['stable_id'] == old['stable_id']
    assert new['source'] == 'src/parts/common.j2:3'
    assert new['provenance']['ranges'][0]['file'] == 'src/parts/common.j2'
    assert 'Edited label' in (tmp_path / '.site/b/index.html').read_text()
    assert (tmp_path / '.layout/pages/c/index.html/render.png').stat().st_mtime_ns == untouched
    aggregate = json.loads((tmp_path / '.layout/verification.json').read_text())
    measured = {p['page'] for p in aggregate['pages'] if p.get('measured')}
    assert measured == {'a/index.html', 'b/index.html'}
    assert all(read(name)['freshness']['status'] == 'current' for name in ('a', 'b', 'c'))
    image.write_text(image.read_text().replace('red', 'blue'))
    run('--only', 'a')
    assert (tmp_path / '.site/shared/figure.svg').read_text() == image.read_text()
    assert (tmp_path / '.layout/pages/c/index.html/render.png').stat().st_mtime_ns == untouched
    assert all(read(name)['freshness']['status'] == 'current' for name in ('a', 'b', 'c'))


@pytest.mark.skipif(os.environ.get('LHTML_BROWSER_TEST') != '1', reason='Set LHTML_BROWSER_TEST=1 for Chrome')
def test_internal_geometry_and_source_evidence(tmp_path):
    source = tmp_path / 'src'
    source.mkdir()
    (source / 'bad.html.j2').write_text('''<div class="col" style="width:160px;font-size:30px">
<p>First text</p><p style="transform:translateY(-65px)">Second text</p>
<div style="height:20px;overflow:hidden"><p>Hidden content<br>More content</p></div>
<ul><li style="white-space:nowrap">A very long sentence extending outside the column</li></ul>
</div>''')
    (source / 'good.html.j2').write_text('''<div class="col" style="width:400px;font-size:30px;background:#ddd">
<ul><li>First item</li><li>Second item</li></ul>
<figure><figcaption>A caption</figcaption></figure></div>''')
    config = tmp_path / 'configure.yaml'
    config.write_text(yaml.safe_dump({'source_directory': 'src', 'plugin': []}))
    result = subprocess.run([sys.executable, str(REPO / 'generate.py'), '-i', str(config), '--verify'],
                            capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    folder = tmp_path / '.layout/pages/bad.html'
    layout = json.loads((folder / 'layout.json').read_text())
    assert layout['analysis']['internal_collisions']
    assert layout['analysis']['internal_clipped']
    assert layout['analysis']['internal_overflow']
    report = json.loads((folder / 'verification.json').read_text())
    defects = [d for d in report['diagnostics'] if d['type'].startswith('internal_')]
    assert all(d['sources'] and d['block_anchors'] and d['bounds'] for d in defects)
    assert (folder / 'internal-overlay.png').is_file()
    good = json.loads((tmp_path / '.layout/pages/good.html/layout.json').read_text())
    assert not good['analysis']['internal_collisions']
    assert not good['analysis']['internal_clipped']
    assert not good['analysis']['internal_overflow']


@pytest.mark.skipif(os.environ.get('LHTML_BROWSER_TEST') != '1', reason='Set LHTML_BROWSER_TEST=1 for Chrome')
def test_role_design_in_rendered_content(tmp_path):
    source = tmp_path / 'src'
    source.mkdir()
    (source / 'index.html.j2').write_text('''<h1 style="font-size:36px">A title</h1>
<div style="font-size:36px"><p>Normal body text</p><p>Another normal paragraph</p>
<p style="font-size:16px">Body too small</p>
<p class="legende" style="font-size:16px">Readable small caption</p>
<div class="source" style="font-size:12px">Image credit</div>
<figure><svg width="20" height="20"><rect width="20" height="20"/></svg></figure>
<svg data-lhtml-role="decorative" width="20" height="20"><rect width="20" height="20"/></svg>
</div>''')
    (source / 'free.html.j2').write_text('<style>body {font-size:16px}</style>\nPlain body text without a container.\n')
    config = tmp_path / 'configure.yaml'
    config.write_text(yaml.safe_dump({'source_directory': 'src', 'plugin': []}))
    result = subprocess.run([sys.executable, str(REPO / 'generate.py'), '-i', str(config), '--verify'],
                            capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    folder = tmp_path / '.layout/pages/index.html'
    value = json.loads((folder / 'layout.json').read_text())
    findings = value['analysis']['role_design']
    assert {f['kind'] for f in findings} == {'font_min', 'title_hierarchy', 'figure_size'}
    assert [f['role'] for f in findings if f['kind'] == 'font_min'] == ['body']
    assert all(d['kind'] != 'min_font' for d in value['analysis']['dense'])
    structured = json.loads((folder / 'verification.json').read_text())
    assert structured['checks']['role_design']
    defects = [d for d in structured['diagnostics'] if d['type'] == 'role_design']
    assert all(d['sources'] and d['block_anchors'] and d['evidence'].get('crop') for d in defects)
    assert 'DESIGN title_hierarchy' in (folder / 'layout.md').read_text()

    free = json.loads((tmp_path / '.layout/pages/free.html/layout.json').read_text())
    assert any(d['kind'] == 'font_min' and d['role'] == 'body' for d in free['analysis']['role_design'])


@pytest.mark.skipif(os.environ.get('LHTML_BROWSER_TEST') != '1', reason='Set LHTML_BROWSER_TEST=1 for Chrome')
def test_interactive_states_frames_failures_and_reproducible_render(tmp_path):
    import hashlib
    source = tmp_path / 'src'
    assets = source / 'assets'
    assets.mkdir(parents=True)
    (assets / 'demo.html').write_text('''<!DOCTYPE html><style>body{margin:0;font:24px sans-serif}</style>
<button id="mode" onclick="this.classList.add('active')">Change mode</button>
<canvas id="c" width="200" height="100"></canvas>
<script>function draw(t){const c=document.querySelector('canvas').getContext('2d');
c.fillStyle=t>=500?'blue':'red';c.fillRect(0,0,200,100);requestAnimationFrame(draw)}requestAnimationFrame(draw)</script>''')
    (source / 'index.html.j2').write_text('''<style>body{font:36px sans-serif}
@keyframes slide {from {left:700px} to {left:100px}}
#a,#b,#css{position:absolute;top:150px;left:100px;width:300px;height:60px}
#b{top:350px}#css{left:700px;animation:slide 1s linear infinite}</style>
<h1>Interactive fixture</h1><div id="a">Stable text</div><div id="b">Moving text</div>
<div id="css">CSS animated</div>
<iframe id="demo" src="assets/demo.html" style="position:absolute;left:700px;top:450px;width:500px;height:300px"></iframe>
<button id="reveal" style="position:absolute;top:850px" onclick="document.querySelector('#b').style.top='150px'">Reveal</button>
<script>function move(t){document.querySelector('#b').style.top=(t>=500?150:350)+'px';requestAnimationFrame(move)}requestAnimationFrame(move)</script>''')
    config = tmp_path / 'configure.yaml'
    config.write_text(yaml.safe_dump({'source_directory': 'src', 'plugin': [], 'plugin_arg': {'layout_report': {
        'interactive': {'max_states': 4, 'pages': {'index.html': [
            {'name': 'mode', 'time_ms': 800, 'actions': [{'type': 'click', 'frame': '#demo', 'selector': '#mode'}],
             'expect': [{'frame': '#demo', 'selector': '#mode.active', 'visible': True}]},
            {'name': 'missing', 'actions': [{'type': 'click', 'selector': '#absent'}]},
        ]}}}}}))
    def run():
        result = subprocess.run([sys.executable, str(REPO / 'generate.py'), '-i', str(config), '--verify'],
                                capture_output=True, text=True, timeout=90)
        assert result.returncode == 0, result.stdout + result.stderr
        folder = tmp_path / '.layout/pages/index.html'
        return folder, json.loads((folder / 'layout.json').read_text()), json.loads((folder / 'verification.json').read_text())
    folder, value, structured = run()
    assert not value['analysis']['collisions']
    states = {s['id']: s for s in value['interactive']['states']}
    assert states['auto-mid']['layout']['analysis']['collisions']
    assert states['mode']['journal'][0]['completed']
    assert states['missing']['status'] == 'failed'
    assert structured['status'] == 'failed'
    assert {'css_animation', 'requestAnimationFrame'} <= set(structured['interactive_coverage']['detected'])
    assert structured['frames'][0]['status'] == 'incomplete'  # canvas geometry is not semantic approval
    assert (folder / 'states/mode/frames/f1/layout.json').is_file()
    defects = [d for d in structured['diagnostics'] if d.get('state_id') == 'auto-mid']
    assert defects and any(d['evidence'].get('crop') for d in defects)
    image = folder / 'states/auto-mid/render.png'
    before = hashlib.sha256(image.read_bytes()).hexdigest()
    run()
    assert hashlib.sha256(image.read_bytes()).hexdigest() == before


@pytest.mark.skipif(os.environ.get('LHTML_BROWSER_TEST') != '1', reason='Set LHTML_BROWSER_TEST=1 for Chrome')
def test_gif_and_video_sampled_at_known_frames(tmp_path):
    import shutil
    encoder = shutil.which('ffmpeg')
    if not encoder:
        pytest.skip('ffmpeg required for a synthetic media fixture')
    source = tmp_path / 'src'
    assets = source / 'assets'
    assets.mkdir(parents=True)
    for extension in ('gif', 'mp4'):
        result = subprocess.run([encoder, '-v', 'error', '-f', 'lavfi', '-i',
            'testsrc=size=120x80:rate=4:duration=2', '-pix_fmt', 'yuv420p', '-y', str(assets / ('sample.' + extension))],
            capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stderr
    (source / 'index.html.j2').write_text('<h1>Media fixture</h1>\n'
        '<img src="assets/sample.gif"><video src="assets/sample.mp4" autoplay muted loop></video>')
    config = tmp_path / 'configure.yaml'
    config.write_text(yaml.safe_dump({'source_directory': 'src', 'plugin': []}))
    result = subprocess.run([sys.executable, str(REPO / 'generate.py'), '-i', str(config), '--verify'],
                            capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    folder = tmp_path / '.layout/pages/index.html'
    value = json.loads((folder / 'layout.json').read_text())
    states = {s['id']: s for s in value['interactive']['states']}
    assert {'gif', 'video'} <= set(value['interactive']['detected'])
    assert all('layout' in s for s in states.values()), states
    samples = states['auto-mid']['layout']['media_samples']
    assert next(s for s in samples if s['type'] == 'gif')['frame_index'] == 4
    video = next(s for s in samples if s['type'] == 'video')
    assert video['time'] == pytest.approx(video['duration'] * .5)
    assert (folder / 'render.png').read_bytes() != (folder / 'states/auto-mid/render.png').read_bytes()


@pytest.mark.skipif(os.environ.get('LHTML_BROWSER_TEST') != '1', reason='Set LHTML_BROWSER_TEST=1 for Chrome')
def test_frames_measured_without_interactive_states(tmp_path):
    source = tmp_path / 'src/s'
    (source / 'assets').mkdir(parents=True)
    (source / 'assets/demo.html').write_text('<!doctype html><html><body><p>Demo text</p></body></html>')
    (source / 'index.html.j2').write_text('= Frame\n\n'
        '<iframe src="assets/demo.html" style="position:absolute;left:700px;top:450px;width:500px;height:300px"></iframe>\n')
    config = tmp_path / 'configure.yaml'
    config.write_text(yaml.safe_dump({'source_directory': 'src', 'theme': str(REPO / 'themes/slides'),
                                     'plugin': ['plugins/auto_wrap.py', 'plugins/menu.py'],
                                     'plugin_arg': {'layout_report': {'interactive': {'enabled': False}}}}))
    result = subprocess.run([sys.executable, str(REPO / 'generate.py'), '-i', str(config), '--verify'],
                            capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    folder = tmp_path / '.layout/pages/s/index.html'
    value = json.loads((folder / 'verification.json').read_text())
    assert not value['states']
    assert [f['id'] for f in value['frames']] == ['f1']
    assert (folder / 'frames/f1/verification.json').is_file()
    assert not value['render_health']['unchecked']
