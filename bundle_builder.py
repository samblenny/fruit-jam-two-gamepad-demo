# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Copyright 2024 Sam Blenny
"""
A CircuitPython project bundle builder for use with Adafruit Playground guides.

This is meant to be invoked as a GithHub Actions workflow as defined in
.github/workflows/bundle_builder.yml. You can run it manually as `make bundle`.

CircuitPython library bundle zip files get cached in ~/.cache/circuitpython/

To customize the contents of your project bundle, edit bundle_manifest.cfg
according to the comments in that file.
"""
from configparser import ConfigParser
import os
import os.path
from os.path import abspath, basename, expanduser, isdir, isfile
import re
import shutil
import subprocess
from zipfile import ZipFile


MANIFEST = 'bundle_manifest.cfg'
CACHE_DIR = abspath(expanduser('~/.cache/circuitpython'))

def run(cmd):
    result = subprocess.run(cmd, shell=True, check=True, capture_output=True)
    return result.stdout.decode('utf-8').strip()

# Read the bundle manifest file
config = ConfigParser(allow_no_value=True)
config.read(MANIFEST)
cfg = {
    '10.x': config.get('library_bundle', '10.x', fallback=None),
    'guide_link': config.get('meta', 'guide_link', fallback=None),
    'lib': [k for (k, v) in config.items('lib')],
    'root': [k for (k, v) in config.items('root')],
}

# Get repository url, name, and commit hash metadata from git
git_remote = run('git config --get remote.origin.url')
git_remote = re.sub(r'git@github\.com:', 'https://github.com/', git_remote)
git_remote = re.sub(r'\.git$', '', git_remote)
repo_name = run('basename `git rev-parse --show-toplevel`')
try:
    commit = run('git rev-parse --short HEAD')
except subprocess.CalledProcessError:
    commit = "NO_COMMIT"

# prepare file and directory paths
files = {
    'zip':    os.path.join('build', f'{repo_name}-{commit}.zip'),
    'readme': os.path.join('build', repo_name, 'README.txt'),
}
dirs = {
    'cache':  CACHE_DIR,
    'root':   os.path.join('build', repo_name),
    '10.x':    os.path.join('build', repo_name, 'CircuitPython 10.x'),
    '10_lib':  os.path.join('build', repo_name, 'CircuitPython 10.x', 'lib'),
}

# Create the directory tree of the zip archive and downloads cache
for d in dirs.values():
    if not isdir(d):
        os.makedirs(d)

# Stage files into the zip archive directory tree
for src in cfg['root']:
    dst = dirs['10.x']
    if isfile(src):
        shutil.copy2(src, dst)
    elif isdir(src):
        shutil.copytree(src, os.path.join(dst, basename(src)))
    else:
        raise FileNotFoundError(src)

# Download library bundle archives with curl, use cache for local testing
url10 = cfg['10.x']
cache = dirs['cache']
zip10path = os.path.join(cache, basename(url10))
if not isfile(zip10path):
    print("downloading", url10)
    run(f"cd {cache} && curl -L -O {url10}")

# Locate and extract mpy archive files for the specified library names.
# This assumes that libraries may be a single .mpy file or a directory with
# potentially many .mpy files.
def extract_libs(zip_path, dst_dir, lib_names):
    zf = ZipFile(zip_path)
    info_list = zf.infolist()
    # Step 1: find the source files (might be nested in a directory)
    # For archive member paths like ".../lib/NAME.mpy" or ".../lib/NAME/...",
    # this regular expression should capture just the "NAME" part, which should
    # be a library name.
    lib_re = re.compile(r'^[^/]*/lib/(?:([^/]*).mpy|([^/]*)/)')
    src_items = []
    for i in info_list:
        result = lib_re.match(i.filename)
        if result:
            captured_name = result[1] or result[2]
            for lib in lib_names:
                if lib == captured_name:
                    src_items.append(i)
    # Step 2: extract the matching files to the destination path ('.../lib/')
    for i in src_items:
        # The split > slice > join here is to remove the first two directories
        # from filenames inside the zip archive. For example, starting with
        # "adafruit-circuitpython-bundle-9.x-mpy-20240625/lib/adafruit_midi/note_on.mpy",
        # the result would be "adafruit_midi/note_on.mpy"
        dst_path = os.path.join(dst_dir, '/'.join(i.filename.split('/')[2:]))
        # Ensure the full destination directory tree exists
        (head, tail) = os.path.split(dst_path)
        os.makedirs(head, exist_ok=True)
        # Extract the file with open and write, because using extract() would
        # create the prefix directories that we just went to all the trouble of
        # identifying and removing
        with zf.open(i, 'r') as f_src:
            with open(dst_path, 'wb') as f_dst:
                f_dst.write(f_src.read())

extract_libs(zip10path, dirs['10_lib'], cfg['lib'])

# Generate the README file
readme = f"""
This is a CircuitPython project bundle for {repo_name}.

To use this bundle, follow the guide at:
{cfg['guide_link']}

Libraries in '{repo_name}/CircuitPython 10.x/lib' came from:
{cfg['10.x']}

The rest of this project's code is from commit {commit} of git repo:
{git_remote}
""".strip()
with open(files['readme'], 'w') as f:
    print(readme, file=f)

# Make the zip file
run(f"cd build; zip -r {basename(files['zip'])} {basename(dirs['root'])}")

# Print an unzip listing for the Actions workflow log
print(run(f"unzip -l {files['zip']}"))
