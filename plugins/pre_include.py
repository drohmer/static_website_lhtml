import os

from lib.structure import built_pages, template_path


def pre_process(meta):
    files_to_include = meta['plugin_arg']['pre_include']
    content_to_include = []
    for f in files_to_include:
        # relative paths are relative to the configuration directory
        f = os.path.join(meta.get('config_directory', ''), f)
        with open(f, 'r') as fid:
            content_to_include.append(fid.read())

    for entry in built_pages(meta):
        file_path = template_path(meta, entry)

        with open(file_path, 'r') as fid:
            file_content = fid.read()

        new_file_content = '\n'.join(content_to_include) + '\n' + file_content

        with open(file_path, 'w') as fid:
            fid.write(new_file_content)
