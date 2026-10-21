"""Transcoded variants of the videos of a project, written next to them.

A core asset stage, not a plugin. LHTML writes a `<video>` with the sources
`media(page_directory)` lists: the variants found in
`<assets>/cache_video_codecs/` of the published site, the source as written
otherwise. LHTML probes no file itself (LHTML 3).

The stage runs when a project says where its cache lives:

    cache_video_directory: 'cache_video_directory/'

and does nothing otherwise. The previous plugin fell back to a default
directory and printed that it had done so; a project that wants transcoded
videos says where they go, and one that does not pays nothing.

The name of the cache directory and the rule that only a directory named
`assets` has variants are this module's: changing the theme does not change
the identity of the cache.
"""
import os
import posixpath
import pathlib
import shutil
from multiprocessing import Pool

from lhtml_site.doctor import find_command, install_hint
from lhtml_site.structure import built_pages
from lhtml_site.video_convert import video_convert

ASSET_DIRECTORY = 'assets/'
CACHE_VIDEO_DIR = 'cache_video_codecs/'
VIDEO_SUFFIXES = ('.mp4', '.webm', '.mkv')
CONVERTER = 'ffpb'
THREADS = '16'
MAX_JOBS = 4            # ffpb is already threaded: a few at a time, not one per video

# What is produced for each video, and by what.
VARIANTS = {'h264': ('-h264.mp4', video_convert.convert_video_mp4_h264),
            'vp9': ('-vp9.webm', video_convert.convert_video_webm_vp9)}

# The sources a <video> offers, in the order the browser tries them. -h265 is
# not produced here any more, but a cache made before may hold it.
SOURCES = [('-vp9.webm', 'video/webm'), ('-h265.mp4', 'video/mp4'), ('-h264.mp4', 'video/mp4')]


def media(page_directory):
    """The resolver given to LHTML for a page whose published directory is
    `page_directory`: media(src) -> [(url, mime type)] of the variants that
    exist next to a video of an assets/ directory, [] for the source as written."""
    def sources(src):              # src and the urls are URLs: '/' on Windows too
        stem, _ = posixpath.splitext(src)
        directory, name = posixpath.dirname(stem), posixpath.basename(stem)
        if posixpath.basename(directory) != ASSET_DIRECTORY.rstrip('/'):
            return []
        variants = posixpath.join(directory, CACHE_VIDEO_DIR)
        return [(posixpath.join(variants, name + suffix), mime) for suffix, mime in SOURCES
                if os.path.isfile(os.path.join(page_directory, variants, name + suffix))]
    return sources


def _videos_of(meta, pages):
    """The videos in the assets of the pages built, once each: several pages
    of a directory, or several occurrences of a page, share its assets."""
    found = []
    for entry in pages:
        assets = entry['dir'] + ASSET_DIRECTORY
        directory = meta['site_directory'] / assets
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
    source, codec, destination, converter = job
    VARIANTS[codec][1](source, destination, {'exec': converter, 'threads': THREADS})


def run(meta):
    """Make the missing variants and copy those of the videos built into the
    site (not the whole cache: a page removed keeps its cache). Does
    nothing unless the project declares `cache_video_directory:`."""
    cache_directory = meta.get('cache_video_directory')
    if not cache_directory:
        return
    log = meta['log']
    videos = _videos_of(meta, built_pages(meta))
    work = _missing_variants(cache_directory, videos)
    (log.info if work else log.detail)(f'{len(videos)} video(s) in the assets, {len(work)} to transcode')
    converter = find_command(CONVERTER)
    jobs = [(os.fspath(meta['site_directory'] / source), codec, destination, converter)
            for source, destinations in work for codec, destination in destinations.items()]
    if jobs and converter is None:
        # A page still shows its video, as written: said, not a failed build
        log.warning(f'{CONVERTER} not found: {len(work)} video(s) not transcoded, shown as written '
                    f'({install_hint(CONVERTER)}; it runs ffmpeg)')
        jobs = []
    if jobs:
        with Pool(processes=min(MAX_JOBS, len(jobs))) as pool:
            pool.map(_convert, jobs)

    variants = _variants_in_cache(cache_directory, videos)
    for relative in variants:
        target = os.path.join(meta['site_directory'], relative)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copy2(os.path.join(cache_directory, relative), target)
    # The cache of a page that no longer exists is not published; a full
    # build says where it is (--only builds some pages: the others' look orphan)
    if not meta.get('only'):
        directories = _orphan_directories(cache_directory, variants)
        if directories:
            shown = ', '.join(directories[:5]) + (', ...' if len(directories) > 5 else '')
            log.info(f'{len(directories)} directory(ies) of {cache_directory} belong to no video '
                     f'of the site, not published (remove them if their page is gone): {shown}')


def _variants_in_cache(cache_directory, videos):
    """The variants in the cache of the videos built, relative to the cache:
    the ones made now and those an earlier cache holds (-h265)."""
    found = []
    for assets, name in videos:
        stem = name[:-len(pathlib.Path(name).suffix)]
        for suffix, _ in SOURCES:
            relative = os.path.normpath(os.path.join(assets, CACHE_VIDEO_DIR, stem + suffix))
            if os.path.isfile(os.path.join(cache_directory, relative)):
                found.append(relative)
    return found


def _orphan_directories(cache_directory, variants):
    """The directories of the cache holding a file that is no variant of a
    video built (hidden files, such as .DS_Store, aside), relative to it."""
    kept = set(variants)
    orphans = set()
    for directory, _, files in os.walk(cache_directory):
        relative = os.path.relpath(directory, cache_directory)
        for name in files:
            if not name.startswith('.') and os.path.normpath(os.path.join(relative, name)) not in kept:
                orphans.add(relative)
    return sorted(orphans)
