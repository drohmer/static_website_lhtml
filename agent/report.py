"""Steps of the layout report specific to --verify (agent extension).

plugins/layout_report.py calls these functions only when meta['verify'] is
set; without them it writes the usual layout report (layout.json, layout.md,
summary.md, changes.md, render.png).
"""
import json
import os

from lib import dependencies
from agent.interactive import validate as validate_interactive, options_for as interactive_options
from agent.verification import write_report, refresh_report
from agent.triage import write_queue

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets')


def options(options):
    """Options of the layout report under --verify: images (for the issue crops)."""
    validate_interactive(options.get('interactive', {}))
    return dict(options, images=True)


def page_entry(options, name):
    """Extra fields of a page given to layout_measure.js: its interactive states."""
    return {'interactive': interactive_options(options.get('interactive', {}), name, True)}


def measurement_failed(pages, previous_layouts, output_dir, error):
    """The measure failed: every page is 'failed' (its last geometry is kept, but
    never presented as a successful verification)."""
    rows = []
    for p in pages:
        os.makedirs(p['out'], exist_ok=True)
        if p['name'] in previous_layouts:
            with open(os.path.join(p['out'], 'layout.json'), 'w') as fid:
                json.dump(previous_layouts[p['name']], fid, indent=1)
        rows.append(_failed(p, str(error), output_dir))
    _write_aggregate(output_dir, rows, [])


def _write_failed(folder, message, render_health=False):
    with open(os.path.join(folder, 'verification.json'), 'w') as fid:
        json.dump({'schema_version': 1, 'status': 'failed',
                   'render_health': {'status': 'failed', 'errors': [{'type': 'measurement', 'message': message}]},
                   'diagnostics': [], 'checks': {'geometry': False, 'render_health': render_health,
                                                'visual_review': False}}, fid, indent=2)


def _failed(p, message, output_dir):
    """Report and aggregate row of a page whose measure failed."""
    os.makedirs(p['out'], exist_ok=True)
    _write_failed(p['out'], message)
    return {'page': p['name'], 'status': 'failed',
            'report': os.path.relpath(os.path.join(p['out'], 'verification.json'), output_dir)}


class Verification:
    """The verification of one run of the layout report."""

    def __init__(self, meta, options, output_dir, analyse, page_markdown, count_problems, count_warnings, run_node):
        self.meta, self.options, self.output_dir, self.run_node = meta, options, output_dir, run_node
        self.analyse, self.page_markdown = analyse, page_markdown
        self.count_problems, self.count_warnings = count_problems, count_warnings
        self.rows, self.crop_folders = [], []

    def _row(self, p, value, layout, measured):
        self.rows.append({'page': p['name'], 'status': value['status'], 'measured': measured,
                          'freshness': layout.get('freshness'),
                          'report': os.path.relpath(os.path.join(p['out'], 'verification.json'), self.output_dir)})

    def retained(self, p, layout):
        """A page not measured again: its report, with its validity refreshed."""
        self._row(p, refresh_report(p['out'], layout), layout, False)

    def prepare(self, p, layout, previous, limits):
        """Before the page reports are written: source anchors, provenance of the
        media, and the reports of the frames and interactive states."""
        meta = self.meta
        layout['verification_mode'] = True
        layout['page_context'] = meta.get('page_contexts', {}).get(p['name'], {})
        if meta.get('source_registry'):
            for finding in layout['analysis'].get('lint', []):
                finding['source_anchor'] = meta['source_registry'].line_anchor(p['source'], finding.get('line'))
        for block in layout['blocks'] + layout.get('subblocks', []):
            for media in block.get('media', []):
                original = dependencies.local_resource(media.get('url', ''), p['html'])
                if original is not None:
                    original = dependencies.canonical_input(original, meta)
                    media['provenance'] = {'file': os.path.relpath(original, meta['config_directory']),
                        'producers': [os.path.relpath(str(original) + suffix, meta['config_directory'])
                                      for suffix in ('.py', '.tex') if os.path.isfile(str(original) + suffix)]}
        self._nested(p, layout, layout, p['out'], previous, limits)

    def _nested(self, p, layout, current, folder, old, limits):
        meta, options = self.meta, self.options
        children = []
        for frame in current.get('frame_layouts', []):
            child = frame['layout']
            original = dependencies.local_resource(frame['url'], p['html'])
            child['source'] = os.path.relpath(dependencies.canonical_input(original, meta), meta['config_directory']) \
                if original else layout['source']
            child['frame_origin'] = frame.get('origin')
            display_scale = frame['box']['width'] / child['viewport']['w']
            child['design_pixel_scale'] = layout['viewport']['w'] / 1920 / display_scale
            for block in child['blocks'] + child.get('subblocks', []):
                if not block.get('source'):
                    block['source'] = child['source']
                    block['source_precision'] = 'frame_document_without_line'
                    block['stable_id'] = (child['source'] + ':dom:' + block['dom_id']) if block.get('dom_id') else \
                        child['source'] + ':measured-index:' + str(block['id'])
            before = next((f['layout'] for f in (old or {}).get('frame_layouts', []) if f['id'] == frame['id']), None)
            children.append((child, os.path.join(folder, 'frames', frame['id']), before))
        errors = []
        for state in current.get('interactive', {}).get('states', []):
            state_folder = os.path.join(folder, 'states', state['id'])
            os.makedirs(state_folder, exist_ok=True)
            if 'layout' in state:
                child = state['layout']
                child['state_id'] = state['id']
                child['source'] = layout['source']
                before = next((s.get('layout') for s in (old or {}).get('interactive', {}).get('states', [])
                               if s['id'] == state['id']), None)
                children.append((child, state_folder, before))
            else:
                errors.append({'kind': state['id'], 'message': state['error']['message']})
                with open(os.path.join(state_folder, 'verification.json'), 'w') as fid:
                    json.dump({'schema_version': 1, 'status': 'failed', 'state_id': state['id'],
                               'source': layout['source'], 'plan': state['plan'], 'render_health': state['render_health'],
                               'diagnostics': [], 'checks': {'geometry': False, 'interactive_states': False}},
                              fid, indent=2)
        current['analysis']['interactive_errors'] = errors
        for child, child_folder, before in children:
            self.analyse(child, options['threshold'], limits=limits, design_rules=options.get('design_rules'))
            child['freshness'] = layout.get('freshness')
            child['dependencies'] = layout.get('dependencies')
            child['verification_mode'] = True
            child['page_context'] = layout['page_context']
            self._nested(p, layout, child, child_folder, before, limits)
            os.makedirs(child_folder, exist_ok=True)
            with open(os.path.join(child_folder, 'layout.json'), 'w') as fid:
                json.dump(child, fid, indent=1)
            with open(os.path.join(child_folder, 'layout.md'), 'w') as fid:
                fid.write(self.page_markdown(p['name'], child['source'], child))
            child_report = write_report(child_folder, child, before)
            for state in current.get('interactive', {}).get('states', []):
                if state.get('layout') is child:
                    state['status'] = child_report['status']
            self.crop_folders.append(child_folder)
        current['analysis']['nested_problems'] = sum(self.count_problems(c['analysis']) for c, _, _ in children)
        current['analysis']['nested_warnings'] = sum(self.count_warnings(c['analysis']) for c, _, _ in children)

    def measured(self, p, layout, previous):
        """After the page reports are written: its verification.json."""
        self._row(p, write_report(p['out'], layout, previous), layout, True)
        self.crop_folders.append(p['out'])

    def finish(self, pages, previous, errors=''):
        """Issue crops, the aggregate verification.json and the triage queue."""
        if self.crop_folders:
            with open(os.path.join(self.output_dir, '.crops.json'), 'w') as fid:
                json.dump(self.crop_folders, fid)
            try:
                self.run_node(os.path.join(ASSETS, 'verification_crops.js'), [os.path.join(self.output_dir, '.crops.json')])
            finally:
                os.remove(os.path.join(self.output_dir, '.crops.json'))
        reported = {row['page'] for row in self.rows}
        for p in pages:
            if p['name'] not in reported:           # its measure failed: the error of layout_measure.js
                message = next((line.split(': ', 2)[-1] for line in errors.splitlines()
                                if line.startswith('layout_measure: ' + p['html'] + ':')),
                               'measurement failed (see the build log)')
                self.rows.append(_failed(p, message, self.output_dir))
        _write_aggregate(self.output_dir, self.rows, [p['name'] for p in previous])
        write_queue(self.output_dir)


def _write_aggregate(output_dir, rows, unmeasured):
    statuses = {row['status'] for row in rows if row.get('measured', True)}
    status = next((s for s in ('failed', 'incomplete', 'issues') if s in statuses), 'pass')
    with open(os.path.join(output_dir, 'verification.json'), 'w') as fid:
        json.dump({'schema_version': 1, 'status': status, 'scope': 'measured_pages',
                   'pages': rows, 'unmeasured_pages': unmeasured, 'visual_review': False}, fid, indent=2)
