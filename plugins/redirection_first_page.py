import sys
import os
import re
import yaml

sys.path.append('lib')
sys.path.append('../lib')
#import filesystem


def create_html_redirection(url):
    html = f'''
<html> 
    <head> 
        <meta http-equiv="refresh" content="0; url={url}" /> 
    </head> 
    <body> 
        Redirection to <a href="{url}">{url}</a> 
    </body> 
</html> 
'''

    return html

def post_process(meta):

    structure_path = meta['site_directory']+'/structure/structure.yaml'
    with open(structure_path) as fid:
        structure = yaml.load(fid, Loader=yaml.loader.SafeLoader)

    url = structure[0]['dir'] + structure[0]['filename']
    html = create_html_redirection(url)

    redirection_path = meta['site_directory']+'/index.html'
    with open(redirection_path,'w') as fid:
        fid.write(html)


if __name__=='__main__':

    redirection_path = '_site/index.html'
    url = '_site/content/01_introduction/index.html'

    html = create_html_redirection(url)

    with open(redirection_path,'w') as fid:
        fid.write(html)

    



