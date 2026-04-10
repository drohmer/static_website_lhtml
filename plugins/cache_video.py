import sys
import os
import shutil
import yaml
import pathlib
import re
from multiprocessing import Process

sys.path.append(os.path.dirname(os.path.abspath(__file__)) + '/video_convert/')
import video_convert

from lib.structure import load_structure


default_asset_path = 'assets/'
default_cache_video_directory = 'cache_video_directory/'
default_cache_name = 'cache_video_codecs/'
executable_video_convert = 'ffpb'
default_threads = '16'


def generate_cache_videos(meta, cache_video_directory, structure):
    os.makedirs(cache_video_directory, exist_ok=True)

    videos_candidate = []
    for entry in structure:
        local_path = entry['dir']
        asset_path = local_path + default_asset_path
        if os.path.isdir(meta['site_directory'] + asset_path):
            asset_files = os.listdir(meta['site_directory'] + asset_path)
            for f in asset_files:
                if f.endswith('.mp4') or f.endswith('.webm') or f.endswith('.mkv'):
                    videos_candidate.append({'path': asset_path, 'name': f})

    print(f'\t Total videos found in assets: {len(videos_candidate)}')

    videos_to_run = []
    for video_path in videos_candidate:
        path_cache = cache_video_directory + video_path['path'] + default_cache_name
        video_extension = pathlib.Path(video_path['name']).suffix
        video_name = video_path['name'][:-len(video_extension)]
        os.makedirs(path_cache, exist_ok=True)

        expected_video_cache = {
            'h264': path_cache + video_name + '-h264.mp4',
            'vp9': path_cache + video_name + '-vp9.webm',
        }
        for codec in expected_video_cache:
            if not os.path.isfile(expected_video_cache[codec]):
                videos_to_run.append({'source': video_path, 'destination': expected_video_cache})
                break

    print(f'\t Videos not present in cache: {len(videos_to_run)}')
    print()

    args_convert = {'exec': executable_video_convert, 'threads': default_threads}
    procs = []
    for entry in videos_to_run:
        video_source_path = meta['site_directory'] + entry['source']['path'] + entry['source']['name']
        for codec in entry['destination']:
            video_destination_path = entry['destination'][codec]
            if codec == 'h264':
                proc = Process(target=video_convert.convert_video_mp4_h264,
                               args=(video_source_path, video_destination_path, args_convert))
                procs.append(proc)
            if codec == 'vp9':
                proc = Process(target=video_convert.convert_video_webm_vp9,
                               args=(video_source_path, video_destination_path, args_convert))
                procs.append(proc)

    print(f'Start video conversion with {len(procs)} process.')
    for proc in procs:
        proc.start()
    for proc in procs:
        proc.join()

    if os.path.isfile('ffmpeg2pass-0.log'):
        os.remove('ffmpeg2pass-0.log')


def pre_process(meta):
    if 'cache_video_directory' not in meta:
        cache_video_directory = default_cache_video_directory
        print(f"Couldn't find meta parameter 'cache_video_directory'. Using default: '{default_cache_video_directory}'.")
    else:
        cache_video_directory = meta['cache_video_directory']

    structure = load_structure(meta['site_directory'])
    generate_cache_videos(meta, cache_video_directory, structure)

    # Copy videos in site
    if os.path.isdir(cache_video_directory) and os.listdir(cache_video_directory):
        print('\n\t Copy videos cache in site directory')
        for item in os.listdir(cache_video_directory):
            src = os.path.join(cache_video_directory, item)
            dst = os.path.join(meta['site_directory'], item)
            if os.path.isdir(src):
                shutil.copytree(src, dst, dirs_exist_ok=True)
            else:
                shutil.copy2(src, dst)
