"""Transcoded variants of the videos of a project, written next to them.

A core asset stage, not a plugin. It changes what a core stage emits
through a side channel: LHTML probes `<assets>/cache_video_codecs/` when it
writes a `<video>` and adds a `<source>` per variant it finds there
(lhtml/export_html.py). A plugin that silently changes the output of the
engine is not an extension; it is a stage of the build that was not
declared as one.

The stage runs when a project says where its cache lives:

    cache_video_directory: 'cache_video_directory/'

and does nothing otherwise. The previous plugin fell back to a default
directory and printed that it had done so; a project that wants transcoded
videos says where they go, and one that does not pays nothing.

What is still undeclared, and belongs to the LHTML boundary (design note
4.4): the name of the cache directory, shared with LHTML through an
imported constant, and the rule that only a directory named `assets` is
probed at all.
"""
import os
import pathlib
import shutil
from multiprocessing import Pool

from lhtml.export_html import CACHE_VIDEO_DIR

from lib.structure import built_pages
from lib.video_convert import video_convert

ASSET_DIRECTORY = 'assets/'
VIDEO_SUFFIXES = ('.mp4', '.webm', '.mkv')
CONVERTER = 'ffpb'
THREADS = '16'
MAX_JOBS = 4            # ffpb is already threaded: a few at a time, not one per video

# What is produced for each video, and by what.
VARIANTS = {'h264': ('-h264.mp4', video_convert.convert_video_mp4_h264),
            'vp9': ('-vp9.webm', video_convert.convert_video_webm_vp9)}


def _videos_of(meta, pages):
    """The videos in the assets of the pages built, once each: several pages
    of a directory, or several occurrences of a page, share its assets."""
    found = []
    for entry in pages:
        assets = entry['dir'] + ASSET_DIRECTORY
        directory = meta['site_directory'] + assets
        if not os.path.isdir(directory):
            continue
        for name in sorted(os.listdir(directory)):
            if name.endswith(VIDEO_SUFFIXES) and (assets, name) not in found:
                found.append((assets, name))
    return found


def _missing_variants(cache_directory, videos):
    """[(source, {codec: destination})] of the videos with a variant to make."""
    work = []
    for assets, name in videos:
        target = os.path.join(cache_directory, assets, CACHE_VIDEO_DIR)
        stem = name[:-len(pathlib.Path(name).suffix)]
        destinations = {codec: os.path.join(target, stem + suffix)
                        for codec, (suffix, _) in VARIANTS.items()}
        if any(not os.path.isfile(path) for path in destinations.values()):
            os.makedirs(target, exist_ok=True)
            work.append((assets + name, destinations))
    return work


def _convert(job):
    source, codec, destination = job
    VARIANTS[codec][1](source, destination, {'exec': CONVERTER, 'threads': THREADS})


def run(meta):
    """Make the missing variants and copy the cache into the site. Does
    nothing unless the project declares `cache_video_directory:`."""
    cache_directory = meta.get('cache_video_directory')
    if not cache_directory:
        return
    log = meta['log']
    videos = _videos_of(meta, built_pages(meta))
    work = _missing_variants(cache_directory, videos)
    log.keyvalue('info', f'{len(videos)} video(s) in the assets, '
                         f'{len(work)} to transcode', indent_level=1)
    jobs = [(meta['site_directory'] + source, codec, destination)
            for source, destinations in work for codec, destination in destinations.items()]
    if jobs:
        with Pool(processes=min(MAX_JOBS, len(jobs))) as pool:
            pool.map(_convert, jobs)

    if os.path.isdir(cache_directory) and os.listdir(cache_directory):
        for item in os.listdir(cache_directory):
            source = os.path.join(cache_directory, item)
            target = os.path.join(meta['site_directory'], item)
            if os.path.isdir(source):
                shutil.copytree(source, target, dirs_exist_ok=True)
            else:
                shutil.copy2(source, target)
