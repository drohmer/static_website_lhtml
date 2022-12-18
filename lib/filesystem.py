import os

def directory_name_clean(d_in):
    d = d_in
    if d=='' or d=='.':
        return ''
    if not d.endswith('/'):
        d = d+'/'
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
        return f'FilepathRelative(\'root_directory\':\'{self.root_directory}\', \'path_local\':\'{self.path_local}\', \'filename\':\'{self.filename}\', \'level\':\'{self.level}\')'

    def __repr__(self):
        return str(self)

    def filepath(self):
        # Return full filepath        
        return directory_name_clean(self.root_directory) + directory_name_clean(self.path_local) + self.filename
    
    def filepath_local(self):
        # Return filepath without the root_directory
        return directory_name_clean(self.path_local) + self.filename
    
    def path_to_root(self):
        # Return the relative path to the root directory given the level
        return '../' * self.level
    


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
                local_dir = current_dir[len(src_dir):]
                if local_dir!='' and not local_dir.endswith('/'):
                    local_dir = local_dir+'/'
                if local_dir.startswith('/'):
                    local_dir = local_dir[1:]
                filepath = FilepathRelative(root_directory=src_dir, path_local=local_dir, level=depth, filename=f)
                files_found.append({'path':filepath})
                #{'filename':f,'root_dir':src_dir,'dir':current_dir[len(src_dir)+1:]+'/','level':depth})

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