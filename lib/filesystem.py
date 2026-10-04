"""File system utilities for static_website_lhtml."""

import heapq
import os
import shutil


def directory_name_clean(d_in):
    d = d_in
    if d == '' or d == '.':
        return ''
    if not d.endswith('/'):
        d = d + '/'
    return d


class FilepathRelative:
    def __init__(self, **kwargs):
        self.root_directory = ''
        self.path_local = ''
        self.filename = ''
        self.level = 0

        for k in kwargs:
            getattr(self, k)
        vars(self).update(kwargs)

    def __str__(self):
        return f"FilepathRelative('root_directory':'{self.root_directory}', 'path_local':'{self.path_local}', 'filename':'{self.filename}', 'level':'{self.level}')"

    def __repr__(self):
        return str(self)

    def filepath(self):
        return directory_name_clean(self.root_directory) + directory_name_clean(self.path_local) + self.filename

    def filepath_local(self):
        return directory_name_clean(self.path_local) + self.filename

    def path_to_root(self):
        return '../' * self.level


def find_files_in_hierarchy(src_dir, condition, max_depth=None):
    """Find files at any depth, avoiding directory symlink cycles.

    An optional explicit depth limit remains available to callers. Separate
    aliases of a directory are traversed, but an ancestor cannot be revisited.
    """
    roots = [src_dir] if isinstance(src_dir, (str, os.PathLike)) else src_dir
    files_found = []
    for root in roots:
        root = os.fspath(root)
        pending = [(root, 0, 0, frozenset())]   # heap: smallest path first
        counter = 0
        while pending:
            directory, _, depth, ancestors = heapq.heappop(pending)
            real_directory = os.path.realpath(directory)
            if real_directory in ancestors:
                continue
            ancestors = ancestors | {real_directory}
            for name in sorted(os.listdir(directory)):
                path = os.path.join(directory, name)
                if os.path.isfile(path) and condition(name):
                    local = os.path.relpath(directory, root)
                    if local == '.':
                        local = ''
                    files_found.append({'path': FilepathRelative(
                        root_directory=directory_name_clean(root),
                        path_local=directory_name_clean(local), level=depth, filename=name)})
            if max_depth is None or depth < max_depth:
                for name in sorted(os.listdir(directory)):
                    path = os.path.join(directory, name)
                    if os.path.isdir(path):
                        counter += 1
                        heapq.heappush(pending, (path, counter, depth + 1, ancestors))
    return files_found


def _ignore_hidden(root, templates=True):
    """copytree filter: hidden files at the top level of `root` (as the
    previous 'cp -r root/*'), .git / .DS_Store everywhere, and the page
    templates (.html.j2) unless `templates`."""
    root = os.path.abspath(root)

    def ignore(directory, names):
        top_level = os.path.abspath(directory) == root
        return {n for n in names
                if n in ('.git', '.DS_Store') or (top_level and n.startswith('.'))
                or (not templates and n.endswith('.html.j2'))}
    return ignore


def copy_directories(dir_source, dir_target, templates=True):
    """Copy source directory to target, replacing target if it exists.
    Symbolic links are copied as links (dangling links are kept as is).
    With templates=False, the page templates (.html.j2) are not copied."""
    if os.path.isdir(dir_target):
        shutil.rmtree(dir_target)
    shutil.copytree(dir_source, dir_target, symlinks=True, ignore=_ignore_hidden(dir_source, templates))
