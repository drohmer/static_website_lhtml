"""Measure the pages in headless Chrome, and write the images of the report.

The measurement itself is the Node script plugins/assets/layout_measure.js,
run by `run_node`, which also runs the other Node scripts of the generator
(contact sheets, --render, PDF export).
"""
import json
import os
import subprocess
import tempfile
import threading
from pathlib import Path

from rich.progress import BarColumn, MofNCompleteColumn, Progress, TextColumn, TimeRemainingColumn
from rich.table import Column

from lhtml_site.layout.report import contact_sheets_html

# The Node scripts stay next to those of the PDF export for now; they move
# when the targets do (step 7 of docs/design.md).
SCRIPTS = Path(__file__).resolve().parents[2] / 'plugins' / 'assets'


def run_node(script, arguments, label=None, chrome=None, log=None):
    """Run one of the Node scripts of SCRIPTS; its lines 'progress <done> <total> <item>'
    on stdout are shown as a progress bar (`label`). `chrome` is the Chrome
    executable to run instead of the one downloaded by puppeteer. What the
    script says about the browser it took ('chrome: ...') is logged, so that
    a report measured with another Chrome than the usual one says so.
    Returns its stderr."""
    if chrome:
        arguments = arguments + [f'--chrome={chrome}']
    cmd = ['node', script if os.path.isabs(script) else str(SCRIPTS / script)] + arguments
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                encoding='utf-8', errors='replace')
    except FileNotFoundError:
        raise RuntimeError('node not found: install Node.js, then run `npm install` '
                           'in the static_website_lhtml directory')
    errors = []
    reader = threading.Thread(target=lambda: errors.extend(proc.stderr))   # no deadlock on a full pipe
    reader.start()
    with Progress(TextColumn('        {task.description}'), BarColumn(bar_width=24), MofNCompleteColumn(),
                  TimeRemainingColumn(),
                  TextColumn('{task.fields[item]}', table_column=Column(max_width=40, no_wrap=True,
                                                                         overflow='ellipsis')),
                  transient=True,
                  disable=label is None) as progress:
        task = progress.add_task(label or '', total=None, item='')
        for line in proc.stdout:
            parts = line.rstrip('\n').split(' ', 3)
            if parts[0] == 'progress' and len(parts) == 4:
                progress.update(task, completed=int(parts[1]), total=int(parts[2]),
                                item=parts[3].removesuffix('/index.html'))
    proc.wait()
    reader.join()
    stderr = ''.join(errors)
    for line in stderr.splitlines():
        if line.startswith('chrome:') and log is not None:
            log.warning(line)
    if 'Cannot find module' in stderr:
        raise RuntimeError('puppeteer not found: run `npm install` in the static_website_lhtml directory')
    if 'Could not find Chrome' in stderr or 'Browser was not found' in stderr:
        raise RuntimeError('Chrome not found: run `npx puppeteer browsers install chrome` '
                           '(npm may skip the download of puppeteer), or give the Chrome to run '
                           "with the configuration key 'chrome' (or PUPPETEER_EXECUTABLE_PATH)")
    if proc.returncode:
        raise RuntimeError(f'{script} failed ({proc.returncode}): {stderr.strip()}')
    return stderr


def write_contact_sheets(output_dir, rows, viewport, options, log, changed=None):
    """Write contact_NN.html and screenshot them as contact_NN.png (only the
    sheets showing the pages `changed`, a set of row indices, when given). A
    sheet whose HTML is the one of its picture already is not taken again."""
    sheets = []
    per_sheet = options['contact_columns'] * options['contact_rows']
    for i, html in enumerate(contact_sheets_html(rows, viewport, options['contact_columns'],
                                                 options['contact_rows']), 1):
        if changed is not None and not any((i - 1) * per_sheet <= k < i * per_sheet for k in changed):
            continue
        html_path = os.path.abspath(os.path.join(output_dir, f'contact_{i:02d}.html'))
        png_path = html_path[:-len('.html')] + '.png'
        try:                                # the same sheet of the same pictures: kept
            shown_renders = [os.path.join(output_dir, rel, 'render.png')
                             for _, rel, _ in rows[(i - 1) * per_sheet:i * per_sheet]]
            with open(html_path, encoding='utf-8') as fid:
                if fid.read() == html and os.path.getmtime(png_path) >= max(
                        [os.path.getmtime(html_path)] + [os.path.getmtime(r) for r in shown_renders]):
                    continue
        except OSError:
            pass
        with open(html_path, 'w', encoding='utf-8', errors='replace', newline='\n') as fid:
            fid.write(html)
        sheets.append({'html': html_path, 'png': png_path})
    if not sheets:
        return
    run_node_on('layout_contact.js', sheets, [], 'Contact sheets', options['chrome'], log)


def run_node_on(script, items, arguments, label, chrome, log):
    """Run a Node script of SCRIPTS on `items`, given as a temporary JSON file
    (--input); the errors it reports on stderr ('<script>: ...') are logged."""
    with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False, encoding='utf-8') as fid:
        json.dump(items, fid)
        input_json = fid.name
    try:
        stderr = run_node(script, [f'--input={input_json}'] + arguments, label=label, chrome=chrome, log=log)
        prefix = script.removesuffix('.js') + ':'
        for line in stderr.splitlines():
            if line.startswith(prefix):
                log.error(line)
    finally:
        os.remove(input_json)


def warn_degenerate_root(measured, options, log):
    """A root selector that does not match the theme gives one block per page:
    the whole content is a single box, and every check on the blocks
    (collisions, alignment, gaps) is then empty while the report looks
    healthy. Say so, with the root actually used."""
    degenerate = [p['name'] for p, _, layout in measured if len(layout.get('blocks') or []) <= 1]
    if len(degenerate) < len(measured) or not measured:
        return                      # a single page may legitimately hold one block
    used = measured[0][2].get('root') or options['root']
    log.warning(f"Layout report: every page was measured as a single block (root: '{used}'). "
                f"The root selector probably does not match the theme; the checks on the blocks "
                f"found nothing. The theme declares its content element in its theme.yaml "
                f"('layout: root:', lhtml_site/theme.py); a project overrides it under 'layout:'.")
