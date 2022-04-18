import os
import shutil
from tqdm import tqdm


def find_files_filter_list(files,dirs):
    if 'private' in dirs:
        dirs.remove('private')

    if 'no_web_parse.txt' in files:
        return ([],[])
    if 'no_web_parse_subdirs.txt' in files:
        return (files,[])
    return (files, dirs)


def find_files_in_hierarchy(src_dir, filter_list=find_files_filter_list, file_condition=lambda x:True, max_depth=-1):
    files_found = []
    add_reccursive = []

    if isinstance(src_dir,str):
        add_reccursive = [[src_dir,0]]
    else:
        for d in src_dir:
            add_reccursive.append([d,0])

    
    while len(add_reccursive)>0:
        add_reccursive = sorted(add_reccursive)
        current_dir, depth = add_reccursive.pop(0)
        current_dir_content = sorted(os.listdir(current_dir))

        if current_dir.endswith('/'):
            current_dir = current_dir[:-1]

        all_files_name = list(filter(lambda x: os.path.isfile(current_dir+'/'+x), current_dir_content)) 
        all_dirs_name  = list(filter(lambda x: os.path.isdir(current_dir+'/'+x), current_dir_content)) 

        all_files_name, all_dirs_name = filter_list(all_files_name, all_dirs_name)

        for f in all_files_name:
            if file_condition(f)==True:
                current_file = current_dir+'/'+f
                files_found.append({'filename':f,'dir':current_dir+'/','level':depth})

        if depth<max_depth or max_depth<0:
            for d in all_dirs_name:
                add_reccursive.insert(0,[current_dir+'/'+d,depth+1])

    return files_found

def copy_files(files_to_copy, dir_output, relative_root):
    if os.path.isdir(dir_output)==False:
        os.system('mkdir -p '+dir_output)
    assert os.path.isdir(dir_output)

    for f in tqdm(files_to_copy):
        pathIn = f['dir']+f['filename']
        assert os.path.isfile(pathIn)

        N = len(relative_root)
        relative_file = pathIn[N:]
        if pathIn[:N]!=relative_root:
            print(f'Problem with file {f} : relative_root {relative_root} doesn\'t seems to match')
            assert False

        pathOut = dir_output+'/'+relative_file
        dir_file_to_copy = os.path.dirname(pathOut)
        if not os.path.isdir(dir_file_to_copy):
            os.system('mkdir -p '+dir_file_to_copy)
        shutil.copyfile(pathIn, pathOut)
        assert os.path.isfile(pathOut)

def copy_directories(dir_source, dir_target):

    # Clear previous target before copy
    if os.path.isdir(dir_target):
        os.system(f'rm -rf {dir_target}')

    # Create dir
    assert not os.path.isdir(dir_target)
    os.makedirs(dir_target)
    assert os.path.isdir(dir_target)

    # Copy
    #os.system(f'cp -r {dir_source}* {dir_target}')
    os.system(f'rsync -arh --info=progress2 {dir_source}* {dir_target}')