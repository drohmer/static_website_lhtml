import os

def find_files_in_hierarchy(src_dir, condition, max_depth=5):
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

        for f in all_files_name:
            if condition(f)==True:
                current_file = current_dir+'/'+f
                files_found.append({'filename':f,'dir':current_dir+'/','level':depth})

        if depth<max_depth:
            for d in all_dirs_name:
                add_reccursive.insert(0,[current_dir+'/'+d,depth+1])

    return files_found

def copy_directories(dir_source, dir_target):

    # Clear previous target before copy
    if os.path.isdir(dir_target):
        os.system(f'rm -rf {dir_target}')

    # Create dir
    assert not os.path.isdir(dir_target)
    os.makedirs(dir_target)
    assert os.path.isdir(dir_target)

    # Copy
    os.system(f'cp -r {dir_source}* {dir_target}')