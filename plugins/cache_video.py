import sys
import os
import yaml
import pathlib
import re
from multiprocessing import Process

sys.path.append(os.path.dirname(os.path.abspath(__file__))+'/video_convert/')
import video_convert

sys.path.append('lib')
sys.path.append('../lib')
import filesystem

sys.path.append('lib/lhtml/src/')
import lhtml


default_asset_path = 'assets/'
default_cache_video_directory = 'cache_video_directory/'
default_cache_name = 'cache_video_codecs/'
executable_video_convert = 'ffpb' # or ffpmeg
default_threads = '16'

path_current_file = os.path.dirname(os.path.abspath(__file__))+'/'


def load_structure(site_directory):
    structure_path = site_directory+'/structure/structure.yaml'
    with open(structure_path) as fid:
        structure = yaml.load(fid, Loader=yaml.loader.SafeLoader)
    return structure

def generate_cache_videos(meta, cache_video_directory, structure):
    if not os.path.isdir(cache_video_directory):
        os.system(f'mkdir -p {cache_video_directory}')

    videos_candidate = []
    for entry in structure:
        local_path = entry['dir']
        asset_path = local_path+default_asset_path
        if os.path.isdir(meta['site_directory']+asset_path):
            asset_files = os.listdir(meta['site_directory']+asset_path)
            
            for f in asset_files:
                if f.endswith('.mp4') or f.endswith('.webm') or f.endswith('.mkv'):
                    videos_candidate.append({'path':asset_path, 'name':f})

    print('\t Total videos found in assets: '+str(len(videos_candidate)))


    videos_to_run = []
    for video_path in videos_candidate:
        path_cache = cache_video_directory+video_path['path']+default_cache_name
        video_extension = pathlib.Path(video_path['name']).suffix
        video_name = video_path['name'][:-len(video_extension)]
        if not os.path.isdir(path_cache):
            os.system(f'mkdir -p {path_cache}')

        expected_video_cache = {'h264':path_cache+video_name+'-h264.mp4', 'vp9':path_cache+video_name+'-vp9.webm'}
        for codec in expected_video_cache.keys():
            v = expected_video_cache[codec]
            if os.path.isfile(v) == False:
                videos_to_run.append({'source':video_path, 'destination':expected_video_cache})
                break
    
    print('\t Videos not present in cache: '+str(len(videos_to_run)))
    print()

    args_convert = {}
    args_convert['exec'] = executable_video_convert
    args_convert['threads'] = default_threads
    counter = 0
    procs = []
    for entry in videos_to_run:
        video_source_path = meta['site_directory']+entry['source']['path']+entry['source']['name']
        #print(f"Video {counter}/{len(videos_to_run)}")
        for codec in entry['destination'].keys():
            video_destination_path = entry['destination'][codec]

            if codec=='h264':
                proc = Process(target=video_convert.convert_video_mp4_h264, args=(video_source_path, video_destination_path, args_convert,))
                procs.append(proc)
                #video_convert.convert_video_mp4_h264(video_source_path, video_destination_path, args_convert)
            if codec=='vp9':
                proc = Process(target=video_convert.convert_video_webm_vp9, args=(video_source_path, video_destination_path, args_convert,))
                procs.append(proc)
                #video_convert.convert_video_webm_vp9(video_source_path, video_destination_path, args_convert)
        counter = counter+1

    print(f'Start video conversion with {len(procs)} process.')
    for proc in procs:
        proc.start()
        
    for proc in procs:
        proc.join()

    
    # Clear temporary file
    if os.path.isfile('ffmpeg2pass-0.log'):
        os.system('rm ffmpeg2pass-0.log')
        

# def cache_video_html_adapter(meta, cache_video_directory, structure):

#     for entry in structure:
#         filepath = meta['site_directory'] + entry['dir'] + entry['filename'].replace('.html','.html.j2')
#         with open(filepath, 'r') as fid:
#             file_content = fid.read()
        
#         # find videoplay::assets/
#         r_videoplay = r'videoplay::assets/(.*?)\[(.*?)\]'

#         regex_code = re.compile(r_videoplay,  re.DOTALL | re.MULTILINE)
#         match = re.finditer(regex_code, file_content)
#         for it in match:
#             sentence = file_content[it.span()[0]:it.span()[1]]
#             file_video = lhtml.analyse_tag(sentence)['text']
#             extension = pathlib.Path(file_video).suffix

            
#             expected_file_video_h264 = file_video[:-len(extension)].replace('assets/','assets/'+default_cache_name)+'-h264.mp4'
#             expected_file_video_vp9 = file_video[:-len(extension)].replace('assets/','assets/'+default_cache_name)+'-vp9.webm'
#             print(file_video)
#             print(expected_file_video_vp9)
            

            





def pre_process(meta):
    if 'cache_video_directory' not in meta:
        cache_video_directory = default_cache_video_directory
        print(f'Couldn\'t find meta parameter \'cache_video_directory\'. Use default directory value \'{default_cache_video_directory}\'.')
    else:
        cache_video_directory = meta['cache_video_directory']

    structure = load_structure(meta['site_directory'])
    
    generate_cache_videos(meta, cache_video_directory, structure)

    # copy videos in site
    print('\n\t Copy videos cache in site directory')
    cmd = f'cp -r {cache_video_directory}* '+meta['site_directory']
    os.system(cmd)

   
    # cache_video_html_adapter(meta, cache_video_directory, structure)
    
    

    


            