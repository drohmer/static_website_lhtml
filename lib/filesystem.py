"""File system utilities for static_website_lhtml."""

import heapq
import os
import shutil
from pathlib import Path

import yaml


# Directories of a build in progress or of a backup (lib/build_output.py)
BUILD_DIRECTORIES = ('.site-build-', '.site-backup-')


def shown(path, start=None):
    """A path as a message or a report writes it: with '/', on Windows too,
    relative to `start` (a link of a report: it may climb out of it), or to
    the current directory (a message) when it is inside it, absolute
    otherwise (outside it, another drive)."""
    try:
        relative = Path(os.path.relpath(path, start or os.curdir))
    except ValueError:
        return Path(path).as_posix()
    if start is None and relative.parts[:1] == ('..',):
        return Path(os.path.abspath(path)).as_posix()
    return relative.as_posix()


def read_text(path):
    """The text of a file of the project. A file that is not UTF-8 says so
    with its name and the byte that stopped the reading: the message of the
    decoder alone names neither."""
    try:
        with open(path, encoding='utf-8') as stream:
            return stream.read()
    except UnicodeDecodeError as exc:
        raise ValueError(f"'{Path(path).as_posix()}' is not UTF-8 text (byte {exc.start}): "
                         f"save it in UTF-8") from None


def read_yaml(path):
    """The YAML of a file of the project (None when it is empty). A file
    that cannot be read, is not UTF-8 or is not YAML raises ValueError
    naming it."""
    try:
        return yaml.safe_load(read_text(path))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"cannot read '{Path(path).as_posix()}': {exc}") from None


def find_files_in_hierarchy(root, condition, exclude=()):
    """The files under `root` whose name satisfies `condition`, as pairs
    (directory relative to root - '' or 'a/b/', with '/' on Windows too -,
    file name), in order: by directory, then by name.

    A directory is visited once per path that reaches it, but never inside
    itself (a link to an ancestor). The directories `exclude` (e.g. the
    site, reached through a link) and the build directories of the
    generator (.site-build-*, .site-backup-*) are not visited."""
    root = os.fspath(root)
    excluded = {os.path.realpath(p) for p in exclude if p}
    found = []
    pending = [(root, 0, frozenset())]      # heap: smallest path first
    counter = 0
    while pending:
        directory, _, ancestors = heapq.heappop(pending)
        real = os.path.realpath(directory)
        if real in ancestors or real in excluded or os.path.basename(real).startswith(BUILD_DIRECTORIES):
            continue
        ancestors = ancestors | {real}
        local = Path(os.path.relpath(directory, root)).as_posix()
        local = '' if local == '.' else local + '/'
        for name in sorted(os.listdir(directory)):
            path = os.path.join(directory, name)
            if os.path.isfile(path) and condition(name):
                found.append((local, name))
            elif os.path.isdir(path):
                counter += 1
                heapq.heappush(pending, (path, counter, ancestors))
    return found


def ignore_hidden(root, skip=None):
    """Filter of copy_tree: the hidden files and directories of `root`, at
    every level (a `.notes.md` written next to a slide is no more published
    than one at the top), and the files for which `skip(name)` is true."""
    root = os.path.abspath(root)

    def ignore(directory, names):
        return {n for n in names
                if n.startswith('.') or (skip is not None and skip(n))}
    return ignore


def _inside(path, directory):
    return path == directory or path.startswith(os.path.join(directory, ''))


def copy_tree(source, target, ignore=None, exclude=()):
    """Copy the directory `source` into `target` (created, or completed).

    The generator writes into the copy: it must never write through a link
    into the sources. A symbolic link to a directory is thus copied as a
    directory; a link to a file stays a link only if it is relative and leads
    to the same file of the copy, else the file is copied (a dangling link is
    copied as is). A link to a directory being
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
        if os.path.lexists(destination):
            try:
                os.remove(destination)
            except (IsADirectoryError, PermissionError):   # Windows: a link to a directory
                os.rmdir(destination)
        if os.path.exists(path):
            mirrored = os.path.normpath(os.path.join(os.path.dirname(path), link))
            if os.path.isabs(link) or not (_inside(mirrored, root) and
                                           os.path.realpath(mirrored) == os.path.realpath(path)):
                shutil.copy2(path, destination)     # the link would lead out of the copy
                return
        os.symlink(link, destination, target_is_directory=os.path.isdir(path))

    def copy(directory, destination, ancestors):
        os.makedirs(destination, exist_ok=True)
        names = sorted(os.listdir(directory))
        skipped = ignore(directory, names) if ignore else set()
        for name in names:
            if name in skipped:
                continue
            path, path_target = os.path.join(directory, name), os.path.join(destination, name)
            if os.path.realpath(path) in excluded:      # a file or a directory named by the caller
                continue
            if os.path.isdir(path):
                real = os.path.realpath(path)
                if real in excluded or os.path.basename(real).startswith(BUILD_DIRECTORIES):
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


def copy_directories(dir_source, dir_target, skip=None, exclude=()):
    """Copy source directory to target, replacing target if it exists (see
    copy_tree). Hidden files at the top level, .git and .DS_Store are not
    copied, nor the files for which `skip(name)` is true. Returns the warnings."""
    if os.path.isdir(dir_target):
        shutil.rmtree(dir_target)
    return copy_tree(dir_source, dir_target, ignore_hidden(dir_source, skip), exclude)


def write_file(path, text):
    """Write a generated file; a symbolic link at its place is replaced (not
    written through)."""
    if os.path.islink(path):
        os.remove(path)
    with open(path, 'w', encoding='utf-8', newline='\n') as fid:
        fid.write(text)
