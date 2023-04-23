from jinja2 import Environment, FileSystemLoader
# pip3 install Jinja2
# pip3 install jinja-markdown
import sass      #pip3 install libsass
import tidylib   #pip3 install pytidylib
import yaml # pip install pyyaml
import json 
import os
import shutil
import argparse
import subprocess
import sys
import importlib.util
import platform


from lib import filesystem
from lib import generator_tool
from lib import logger

file_dir = os.path.dirname(os.path.abspath(__file__))+'/'
sys.path.append(file_dir)
sys.path.append(file_dir+'lib/lhtml/src/')
import lhtml



# Default meta parameter
#  These parameters can be writen over using a configuration file
#    python generate.py [-i configurationFilePath]
meta = {
    # where are the source files
    'source_directory': 'src_site/', 
    # output directory
    'site_directory': '_site', 
    'theme': 'theme_templates/webpage-frame/',
    'config_file': 'configure.yaml',
    'plugin': ['plugins/menu.py', 'plugins/redirection_first_page.py'], 
    'debug': False,
    'level_print': 0,
    'path_config': '',
    'config_directory': '',
    'lib_directory': os.path.dirname(os.path.abspath(__file__))+'/'
}

def read_arguments(meta):
    parser = argparse.ArgumentParser(description='Generate Website.')
    parser.add_argument('-d','--debug', action='store_true',help='Display more information for debug and keep temporary files.')
    parser.add_argument('-c','--clean', action='store_true',help='Clean the directories.')
    parser.add_argument('-i','--input_config', help='Input yaml configuration file. Default=configure.yaml')
    args = parser.parse_args()

    if args.input_config != None:
        meta['config_file'] = args.input_config
    if args.debug == True:
        meta['debug'] = True
    
    meta['args'] = args



def try_plugin(plugin_filepath, function_name):
    print(plugin_filepath)
    assert os.path.isfile(plugin_filepath)

    spec = importlib.util.spec_from_file_location('plugin', plugin_filepath)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    if function_name in dir(module):
        log.keyvalue('Run', plugin_filepath)
        func = getattr(module, function_name)
        func(meta)

def load_config_file(meta):

    if meta['config_file']!='':
        if os.path.isfile(meta['config_file'])==False:
            log.error('Cannot find configuration file \''+meta['config_file']+'\'')
        assert os.path.isfile(meta['config_file'])
   
        prt_debug('Found configuration file \''+meta['config_file']+'\'')

        with open(meta['config_file']) as fid:
            config = yaml.load(fid, Loader=yaml.loader.SafeLoader)
        for key in config.keys():
            meta[key] = config[key]
        prt_debug('\n')

        meta['config_directory'] = os.path.dirname(os.path.abspath(meta['config_file']))+'/'

    
def clean_directories(meta):
    os.system('rm -rf '+meta['site_directory'])
    os.system('rm -rf lib/__pycache__')
    os.system('rm -rf plugins/__pycache__')
    print('Directories cleaned\n')

if __name__== '__main__':

    python_version = platform.python_version_tuple()
    if python_version[0]!=3:
        print('\nError: Need python 3')
        print('Current version:',python_version,'\n')
        assert(python_version[0]==3)

    read_arguments(meta)
    
    log = logger.Logger(indent_level_base=meta['level_print'])
    meta['log'] = log
    

    prt_debug = lambda msg, level=0 : generator_tool.print_debug(msg, meta['debug'], meta['level_print'], level)

    # Load config file
    load_config_file(meta)

    # Pre Check
    assert os.path.isdir(meta['config_directory'])
    meta['source_directory'] = meta['config_directory']+meta['source_directory']
    meta['site_directory']   = meta['config_directory']+meta['site_directory']
    if 'cache_video_directory' in meta:
        meta['cache_video_directory']   = meta['config_directory']+meta['cache_video_directory']
    meta['theme'] = meta['config_directory']+meta['theme']
    if not os.path.isdir(meta['source_directory']):
        log.error('Cannot find directory \''+meta['source_directory']+'\'')
    assert os.path.isdir(meta['source_directory'])
    assert os.path.isdir(meta['theme'])

 
    # Clean directories
    if meta['args'].clean==True:
        clean_directories(meta)
        exit()
        
    

    tidylib.BASE_OPTIONS = {}
    tidyOptions = {'doctype':'html5','show-warnings':'no'}

    # warn-proprietary-attributes is only available in recent version
    python_version = platform.python_version_tuple()
    if int(python_version[0])>=3 and int(python_version[1])>=8 :
        tidyOptions['warn-proprietary-attributes']='no'


    dir_source = meta['source_directory']
    dir_site   = meta['site_directory']

    log.display('[bold white]****************************',pre='\n')
    log.display('[bold white]  Start website generator')
    log.display('[bold white]****************************'),
    log.keyvalue('info',f'Source: {dir_source}', indent_level=1)
    log.keyvalue('info',f'Plugins: '+str(meta['plugin']), indent_level=1)
    
    log.title('Data preparation',pre='\n')
    log.tic()

    # Copy source to site
    prt_debug(f'Copy source files \'{dir_source}\' -> \'{dir_site}\'')
    filesystem.copy_directories(dir_source, dir_site)
    prt_debug("Copy source done\n",level=1)

    # Copy current theme
    prt_debug('Copy current theme \''+meta['theme']+f'\' -> \'{dir_site}theme/\'')
    theme_src = meta['theme']
    theme_dst = dir_site+'/theme/'
    filesystem.copy_directories(theme_src, theme_dst)
    prt_debug('Copy theme done\n',level=1)



    # Find all html.j2 files
    prt_debug(f'Look for jinja template files in \'{dir_site}\' ...')
    template_files = filesystem.find_files_in_hierarchy(dir_site, lambda f: f.endswith('.html.j2'))
    prt_debug(f'Found {len(template_files)} template files\n',level=1)

    # Try to find additional config.yaml file near the source file
    generator_tool.extract_additional_config(template_files)

    # Try to find title for each file
    generator_tool.extract_titles(template_files)

    # Export files as yaml stucture for other process
    generator_tool.export_structure(template_files, dir_site+'/structure/', dir_site)

    log.ok_elapsed()


    
    # Run plugins pre-process
    log.title('Pre-process',pre='\n')
    log.tic()
    for plugin_filepath in meta['plugin']:
        try_plugin(meta['config_directory']+plugin_filepath, 'pre_process')
    log.ok_elapsed()
    


    # Load jinja
    prt_debug(f'Load jinja environment on {dir_site}')
    file_loader = FileSystemLoader(dir_site)
    env = Environment(loader=file_loader,extensions=['jinja_markdown.MarkdownExtension'])
    prt_debug('Jinja environment loaded\n', level=1)


    # Convert all jinja files
    log.title('Convert HTML',pre='\n')
    log.tic()
    log.keyvalue('Found',f'{len(template_files)} template files')
    for k,element in enumerate(template_files):
        template_path_local = element['path'].filepath_local()

        template_path = element['path'].filepath()
        
        prt_debug(f'- {template_path}', level=1)
        path_to_root = element['path'].path_to_root()

        # Run Jinja
        template = env.get_template(template_path_local)
        output_html = template.render({'pathToRoot':path_to_root, 'pageID':k})
        
        # Run LHTML
        meta['current_directory'] = element['path'].root_directory + element['path'].path_local
        output_html = lhtml.run(output_html, meta)

        # Tidy
        tidy_html, error_tidy_html = tidylib.tidy_document(output_html, options=tidyOptions)
        if error_tidy_html!="":
            print("Tidy found error in file "+template_path)
            print(error_tidy_html)
            #debug:
            if args.debug==True:
                debug = output_html.split('\n')
                for k,line in enumerate(debug):
                    print(k+1,': ',line)

        # Copy file in output directory
        template_path_output = template_path.replace('.html.j2','.html')
        with open(template_path_output,'w') as fid:
            fid.write(tidy_html)
        
        # Remove template file
        if meta['debug']==False:
            os.remove(template_path)

    log.ok_elapsed()


    
    


    # Find sass files
    sass_directory = 'theme/css/'
    prt_debug(f'Look for sass files in {dir_site}{sass_directory} ...')
    sass_files = filesystem.find_files_in_hierarchy(dir_site, lambda f: f.endswith('.sass'))
    prt_debug(f'Found {len(sass_files)} sass files\n', level=1)

    for element in sass_files:
        path_sass = dir_site+element['dir'][len(dir_site):]+element['filename']
        css_txt = sass.compile(filename=path_sass)
        
        # write css file
        path_css_output = path_sass.replace('.sass', '.css')
        with open(path_css_output,'w') as fid:
            fid.write(css_txt)

        # remove sass file
        os.remove(path_sass)



    # Run plugins post-process
    log.title('Post-process',pre='\n')
    log.tic()
    for plugin_filepath in meta['plugin']:
        try_plugin(meta['config_directory']+plugin_filepath, 'post_process')
    log.ok_elapsed()

print()
