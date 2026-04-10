"""File system utilities for static_website_lhtml."""

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


def find_files_in_hierarchy(src_dir, condition, max_depth=5):
    files_found = []
    add_reccursive = []

    if isinstance(src_dir, str):
        add_reccursive = [[src_dir, 0]]
    else:
        for d in src_dir:
            add_reccursive.append([d, 0])

    while len(add_reccursive) > 0:
        add_reccursive = sorted(add_reccursive)
        current_dir, depth = add_reccursive.pop(0)
        current_dir_content = sorted(os.listdir(current_dir))

        if current_dir.endswith('/'):
            current_dir = current_dir[:-1]

        all_files_name = [x for x in current_dir_content if os.path.isfile(current_dir + '/' + x)]
        all_dirs_name = [x for x in current_dir_content if os.path.isdir(current_dir + '/' + x)]

        for f in all_files_name:
            if condition(f):
                local_dir = current_dir[len(src_dir):]
                if local_dir != '' and not local_dir.endswith('/'):
                    local_dir = local_dir + '/'
                if local_dir.startswith('/'):
                    local_dir = local_dir[1:]
                filepath = FilepathRelative(root_directory=src_dir, path_local=local_dir, level=depth, filename=f)
                files_found.append({'path': filepath})

        if depth < max_depth:
            for d in all_dirs_name:
                add_reccursive.insert(0, [current_dir + '/' + d, depth + 1])

    return files_found


def copy_directories(dir_source, dir_target):
    """Copy source directory to target, replacing target if it exists."""
    if os.path.isdir(dir_target):
        shutil.rmtree(dir_target)
    shutil.copytree(dir_source, dir_target)
