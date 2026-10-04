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


def ignore_hidden(root, templates=True):
    """Filter of copy_tree: hidden files at the top level of `root` (as the
    previous 'cp -r root/*'), .git / .DS_Store everywhere, and the page
    templates (.html.j2) unless `templates`."""
    root = os.path.abspath(root)

    def ignore(directory, names):
        top_level = os.path.abspath(directory) == root
        return {n for n in names
                if n in ('.git', '.DS_Store') or (top_level and n.startswith('.'))
                or (not templates and n.endswith('.html.j2'))}
    return ignore


def _inside(path, directory):
    return path == directory or path.startswith(os.path.join(directory, ''))


def copy_tree(source, target, ignore=None, exclude=()):
    """Copy the directory `source` into `target` (created, or completed).

    The generator writes into the copy: it must never write through a link
    into the sources. A symbolic link to a directory is thus copied as a
    directory; a link to a file stays a link, relative if it still leads to
    the same file from the copy, else absolute. A link to a directory being
    copied (an ancestor) stays a link if it is relative and inside `source`,
    else it is not copied. The directories `exclude` and `target` itself
    (e.g. the site, reached through a link) are not copied.
    `ignore(directory, names)` gives the names not to copy (as copytree).
    Returns the warnings (links not copied)."""
    os.makedirs(target, exist_ok=True)
    root = os.path.abspath(source)
    real_root = os.path.realpath(source)
    excluded = {os.path.realpath(p) for p in exclude if p} | {os.path.realpath(target)}
    warnings = []

    def copy_link(path, destination):
        link = os.readlink(path)
        if not os.path.isabs(link) and os.path.exists(path):
            mirrored = os.path.normpath(os.path.join(os.path.dirname(path), link))
            if not (_inside(mirrored, root)
                    and os.path.realpath(mirrored) == os.path.realpath(path)):
                link = os.path.realpath(path)   # the relative link would lead elsewhere
        if os.path.lexists(destination):
            os.remove(destination)
        os.symlink(link, destination)

    def copy(directory, destination, ancestors):
        os.makedirs(destination, exist_ok=True)
        names = sorted(os.listdir(directory))
        skipped = ignore(directory, names) if ignore else set()
        for name in names:
            if name in skipped:
                continue
            path, path_target = os.path.join(directory, name), os.path.join(destination, name)
            if os.path.isdir(path):
                real = os.path.realpath(path)
                if real in excluded:
                    continue
                if real in ancestors:       # copying it would never end
                    link = os.readlink(path) if os.path.islink(path) else ''
                    if link and not os.path.isabs(link) and _inside(
                            os.path.normpath(os.path.join(directory, link)), root) and _inside(real, real_root):
                        copy_link(path, path_target)
                    else:
                        warnings.append(f"'{path}' leads to a directory containing it: not copied")
                    continue
                copy(path, path_target, ancestors | {real})
            elif os.path.islink(path):
                copy_link(path, path_target)
            else:
                if os.path.islink(path_target):
                    os.remove(path_target)
                shutil.copy2(path, path_target)

    copy(source, target, frozenset({real_root}))
    return warnings


def copy_directories(dir_source, dir_target, templates=True, exclude=()):
    """Copy source directory to target, replacing target if it exists (see
    copy_tree). Hidden files at the top level, .git and .DS_Store are not
    copied, nor the page templates (.html.j2) with templates=False.
    Returns the warnings."""
    if os.path.isdir(dir_target):
        shutil.rmtree(dir_target)
    return copy_tree(dir_source, dir_target, ignore_hidden(dir_source, templates), exclude)


def write_file(path, text):
    """Write a generated file; a symbolic link at its place is replaced (not
    written through)."""
    if os.path.islink(path):
        os.remove(path)
    with open(path, 'w', encoding='utf-8') as fid:
        fid.write(text)
