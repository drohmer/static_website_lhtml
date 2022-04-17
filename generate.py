from jinja2 import Environment, FileSystemLoader
import sass      # pip3 install libsass
import scss      # pip3 install scss
from scss import parser as scssParser
import tidylib   # pip3 install pytidylib
import os
import shutil
import sys

from lib import filesystem

sys.path.append('lib/lhtml/src/')
import lhtml


meta = {
    'dir_source': 'src/',
    'dir_site': '_site',
    'theme': 'theme_templates/webpage-frame/'
}



if __name__== '__main__':


    dir_source = meta['dir_source']
    dir_site = meta['dir_site']

    sass_directory = 'theme/css/'


    tidylib.BASE_OPTIONS = {}
    tidyOptions = {'doctype':'html5'}

    # Copy src to _site
    print(f'Copy source files {dir_source} to {dir_site}')
    filesystem.copy_directories(dir_source, dir_site)
    print("\t Copy done\n")


    # Find all tpl.html files
    print(f'Look for template files in {dir_site} ...')
    template_files = filesystem.find_files_in_hierarchy(dir_site, lambda f: f.endswith('.tpl.html'))
    print(f'\t Found {len(template_files)} template files\n')

    # Copy current theme
    print('Copy current theme',meta['theme'],'into theme/')
    theme_src = dir_site+'/'+meta['theme']
    theme_dst = dir_site+'/theme/'
    filesystem.copy_directories(theme_src, theme_dst)
    print('\t Done\n')


    # Load jinja
    print(f'Load jinja environment on {dir_site}')
    file_loader = FileSystemLoader(dir_site)
    env = Environment(loader=file_loader)
    print('\t Jinja environment loaded\n')

    # Convert all tpl files
    print(f'Convert tpl.html files')
    for element in template_files:
        template_path_local = element['dir'][len(dir_site):]+element['filename']
        template_path = dir_site+template_path_local
        
        print('\t - ',template_path)
        path_to_root = '../'*element['level']

        # Run Jinja
        template = env.get_template(template_path_local)
        output_html = template.render({'pathToRoot':path_to_root})
        

        # Run LHTML
        output_html = lhtml.run(output_html)

        # Tidy
        tidyOptions['warn-proprietary-attributes']=False
        tidyOptions['drop-empty-elements']=False
        tidy_html, error_tidy_html = tidylib.tidy_document(output_html, options=tidyOptions)
        if error_tidy_html!="":
            print("Tidy found error in file "+template_path)
            print(error_tidy_html)
            # L = output_html.split('\n')
            # for k,l in enumerate(L):
            #     print(k,l)


        # Copy file in output directory
        template_path_output = template_path.replace('.tpl.html','.html')
        with open(template_path_output,'w') as fid:
            fid.write(tidy_html)
        
        # Remove template file
        os.remove(template_path)


    # Clean
    print()






    # Find sass and scss files
    print(f'Look for sass files in {dir_site}/{sass_directory} ...')
    sass_files = filesystem.find_files_in_hierarchy(dir_site+'/'+sass_directory, lambda f: f.endswith('.sass') or f.endswith('.scss'))

    print(f'\t Found {len(sass_files)} sass/scss files\n')
    for element in sass_files:
        path_sass = dir_site+element['dir'][len(dir_site):]+element['filename']
        css_txt = sass.compile(filename=path_sass)
        
        # write css file
        filename, extension = os.path.splitext(path_sass)
        path_css_output = path_sass.replace(extension, '.css')
        with open(path_css_output,'w') as fid:
            fid.write(css_txt)

        # remove sass file
        os.remove(path_sass)



