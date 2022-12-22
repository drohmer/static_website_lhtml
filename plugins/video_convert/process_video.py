import os
import argparse
from video import *




#find all assets/video
def find_all_assets_videos(path):
    add_reccursive = [path]
    videos = []
    while len(add_reccursive)>0:
        add_reccursive = sorted(add_reccursive)
        current_dir = add_reccursive.pop(0)
        current_dir_content = sorted(os.listdir(current_dir))

        if current_dir.endswith('/'):
            current_dir = current_dir[:-1]

        all_files_name = list(filter(lambda x: os.path.isfile(current_dir+'/'+x), current_dir_content)) 
        all_dirs_name  = list(filter(lambda x: os.path.isdir(current_dir+'/'+x), current_dir_content)) 

        if current_dir.endswith('assets') :
            for f in all_files_name:
                name,ext = os.path.splitext(f)
                if ext=='.mp4' or ext=='.webm':
                    videos.append({'dir':current_dir,'file':f})

        for d in all_dirs_name:
            if d != 'private':
                add_reccursive.append(current_dir+'/'+d)

    return videos

def clean_video_codecs(path):
    add_reccursive = [path]
    while len(add_reccursive)>0:
        add_reccursive = sorted(add_reccursive)
        current_dir = add_reccursive.pop(0)
        current_dir_content = sorted(os.listdir(current_dir))

        if current_dir.endswith('/'):
            current_dir = current_dir[:-1]

        all_dirs_name  = list(filter(lambda x: os.path.isdir(current_dir+'/'+x), current_dir_content)) 


        if current_dir.endswith('assets/video_codecs'):
            os.system(f'rm -r {current_dir}')

        for d in all_dirs_name:
            if d != 'private':
                add_reccursive.append(current_dir+'/'+d)


def generate_videos(videos):
    for video in videos:

        d = video['dir']
        f = video['file']
        f_name, f_extension = os.path.splitext(f)
        
        file_source = d+'/'+f
        assert os.path.isfile(file_source)

        dir_video_codecs = d+'/video_codecs/'
        if not os.path.isdir(dir_video_codecs):
            os.system(f'mkdir {dir_video_codecs}')
        assert os.path.isdir(dir_video_codecs)
        
        args = {'exec':'ffpb'}

        # file_output_h265 = dir_video_codecs+f_name+'-h265.mp4'
        # if not os.path.isfile(file_output_h265):
        #     convert_video_mp4_h265(file_source, file_output_h265, args)
        # assert os.path.isfile(file_output_h265)
        # check_file(file_output_h265)

        file_output_vp9 = dir_video_codecs+f_name+'-vp9.webm'
        if not os.path.isfile(file_output_vp9):
            convert_video_webm_vp9(file_source, file_output_vp9, args)
        assert os.path.isfile(file_output_vp9)
        check_file(file_output_vp9)

        
        file_output_h264 = dir_video_codecs+f_name+'-h264.mp4'
        if not os.path.isfile(file_output_h264):
            convert_video_mp4_h264(file_source, file_output_h264, args)
        assert os.path.isfile(file_output_h264)
        check_file(file_output_h264)

if __name__ == '__main__':

    path = 'src'

    parser = argparse.ArgumentParser()
    parser.add_argument('--input', '-i', help='Input path')
    parser.add_argument('--reset', '-r', help='Force to remove all assets/video_codecs/ directories before recomputing', action='store_true')
    parser.add_argument('--clean', '-c', help='Only remove all assets/video_codecs/ directories', action='store_true')
    #parser.add_argument('--input', '-i', help='Input filename') #'input_file', nargs=argparse.REMAINDER)
    meta = vars(parser.parse_args())

    if meta['input'] != None:
        path = meta['input']

    if meta['clean'] == True or meta['reset']:
        print('\n---------------------------------------')
        print('Clean assets/video_codecs/ directories')
        clean_video_codecs(path)
        if meta['clean']:
            print('Cleaning performed')
            print()
            exit()

    videos = find_all_assets_videos(path)
    print('\n---------------------------------------')
    print('Found',len(videos),'source videos')

    print('\n---------------------------------------')
    print('Generate videos')
    generate_videos(videos)

    # clean
    os.system('rm -f ffmpeg2pass-0.log')
    print()
    

