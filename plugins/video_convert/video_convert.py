import os
import argparse

default_threads = 8

def convert_video_webm_av1(f_in, f_out, args):
    assert os.path.isfile(f_in)

    codec_video = 'libaom-av1'
    quality_video = '20' #0 (lossless) - 51 (worst); 17 - invisible loss 

    codec_audio = 'libopus'
    quality_audio = '128k'

    executable = args['exec']
    threads = default_threads
    if 'threads' in args:
        threads = args['threads']

    cmd = f'{executable} -i {f_in} -row-mt 1 -threads {threads} -c:v {codec_video} -b:v 0  -crf {quality_video} -strict experimental -c:a {codec_audio} -b:a {quality_audio} -y {f_out}'

    print(cmd)
    os.system(cmd)

    assert os.path.isfile(f_out)

def convert_video_webm_vp9(f_in, f_out, args):
    assert os.path.isfile(f_in)

    codec_video = 'libvpx-vp9'
    quality_video = '30' #0 (lossless) - 51 (worst); 17 - invisible loss 
    quality_preset = '-deadline good' #good or best

    codec_audio = 'libopus'
    quality_audio = '128k'

    executable = args['exec']

    threads = default_threads
    if 'threads' in args:
        threads = args['threads']

    pass_1 = f'{executable} -i {f_in} -threads {threads} -c:v {codec_video} -b:v 0 {quality_preset} -crf {quality_video} -pass 1 -an -f null /dev/null'
    pass_2 = f'{executable} -i {f_in} -row-mt 1 -threads {threads} -c:v {codec_video} -b:v 0 {quality_preset} -crf {quality_video} -pass 2 -c:a {codec_audio} -b:a {quality_audio} -y {f_out}'

    print(pass_1)
    os.system(pass_1)
    print(pass_2)
    os.system(pass_2)

    assert os.path.isfile(f_out)

def convert_video_mp4_h264(f_in, f_out, args):
    assert os.path.isfile(f_in)

    codec_video = 'libx264'
    quality_video = '20' #0 (lossless) - 51 (worst); 17 - invisible loss 
    quality_preset = '-preset medium' # faster fast medium slow slower

    codec_audio = 'libvorbis'
    quality_audio = '128k'

    executable = args['exec']

    threads = default_threads
    if 'threads' in args:
        threads = args['threads']

    cmd = f'{executable} -i {f_in} -threads {threads} -c:v {codec_video} {quality_preset} -crf {quality_video} -c:a {codec_audio} -b:a {quality_audio} -y {f_out}'
    print(cmd)
    os.system(cmd)
    assert os.path.isfile(f_out)


def convert_video_mp4_h265(f_in, f_out, args):
    assert os.path.isfile(f_in)

    codec_video = 'libx265'
    quality_video = '30' #0 (lossless) - 51 (worst); 17 - invisible loss 
    quality_preset = '-preset medium'

    codec_audio = 'libvorbis'
    quality_audio = '128k'

    executable = args['exec']
    
    threads = default_threads
    if 'threads' in args:
        threads = args['threads']

    cmd = f'{executable} -i {f_in} -threads {threads} -c:v {codec_video} {quality_preset} -crf {quality_video} -c:a {codec_audio} -b:a {quality_audio} -y {f_out}'

    print(cmd)
    os.system(cmd)
    assert os.path.isfile(f_out)



def check_file(f):
    assert os.path.isfile(f)

    cmd = f'ffmpeg -v error -i {f} -f null - '
    os.system(cmd)

if __name__ == '__main__':

    parser = argparse.ArgumentParser()
    parser.add_argument('--output', '-o', help='Output filename')
    parser.add_argument('--input', '-i', help='Input filename') #'input_file', nargs=argparse.REMAINDER)
    meta = vars(parser.parse_args())

    file_in = meta['input']
    file_out = meta['output']
    if len(file_in)==0:
        print("Error no input file provided")
        exit()
    if len(file_out)==0:
        print("Error no output file provided")
        exit()
    
    if not os.path.isfile(file_in):
        print('Error input_file',file_in,'cannot doesn\'t exist')
        exit()
    
    args = {}
    args['exec'] = 'ffpb' # ffmpeg / ffpb

    # Automatic codec recognition
    file_out_name, extension = os.path.splitext(file_out)
    if extension == '.webm':
        convert_video_webm_vp9(file_in, file_out, args)
    elif extension == '.mp4':
        convert_video_mp4_h265(file_in, file_out, args)
    else:
        print('Cannot recognize known extension for output file',file_out)
        exit(0)

