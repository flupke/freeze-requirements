from __future__ import print_function

import sys
import shutil
import atexit
import os.path as op
import string
import hashlib
import os
import bisect
import tempfile
from collections import defaultdict
from distutils.version import LooseVersion
from itertools import takewhile
import glob
import six
import re

import sh
from setuptools.package_index import distros_for_filename

from .archive import Archive


CLI_COLORS = {
    'header': 95,
    'okblue': 94,
    'okgreen': 92,
    'warning': 93,
    'fail': 91,
}
_canonicalize_regex = re.compile(r"[-_.]+")


class cd(object):
    '''
    A context manager that changes the current working directory.
    '''

    def __init__(self, path):
        self.path = path

    def __enter__(self):
        self.prev_cwd = os.getcwd()
        os.chdir(self.path)

    def __exit__(self, exc_type, exc_val, exc_tb):
        os.chdir(self.prev_cwd)


def colored(color, text):
    '''
    Add color to text.
    '''
    return '\033[%sm%s\033[0m' % (CLI_COLORS[color], text)


def likely_distro(filename):
    '''
    Get the first distro as returned by :func:`distros_for_filename` that has a
    version that starts with a number.
    '''
    distros = [d for d in distros_for_filename(filename)
               if d.version and d.version[0] in string.digits]
    if len(distros) < 1:
        raise ValueError("can't find distro for %s" % filename)
    return distros[0]


def file_hash(filename):
    '''
    Return the hash of *filename* contents.
    '''
    with open(filename) as fp:
        return hashlib.sha1(fp.read()).hexdigest()


def cache_dir():
    '''
    Return the application's cache directory.
    '''
    cache_dir = os.environ.get('XDG_CACHE_HOME', op.expanduser('~/.cache'))
    return op.join(cache_dir, 'freeze-requirements')


def cache_path(filename):
    '''
    Get cache path for *filename*.
    '''
    return op.join(cache_dir(), file_hash(filename))


def group_and_select_packages(packages_groups):
    '''
    Group *packages_groups* by distribution key, and sort them by version
    number.

    *packages_groups* must be a list of tuples containing requirements filename
    and associated packages filenames list, e.g.::

        [
            ('requirements1.txt', ['foo-0.1.tar.gz', 'bar-0.2.tar.gz']),
            ('requirements2.txt', ['bar-0.3.tar.gz']),
            ('requirements3.txt', ['foo-0.1.tar.gz'])
        ]

    Return a dict organized by distro names, containing versions and origin
    requirements files::

        {
            'foo': [('0.1', ['requirements1.txt', 'requirements3.txt'])],
            'bar': [
                ('0.2', ['requirements1.txt']),
                ('0.3', ['requirements2.txt']),
            ]
        }

    Versions are sorted in ascending order, so the last item is always the
    highest version.
    '''
    # Create a dict with sorted versions
    grouped_packages = defaultdict(
        lambda: {'versions': [], 'reqs_files': defaultdict(list)}
    )
    for reqs_file, packages in packages_groups:
        for package in packages:
            distro = likely_distro(package)
            entry = grouped_packages[distro.key]
            version = LooseVersion(distro.version)
            if version not in entry['versions']:
                bisect.insort(entry['versions'], version)
            entry['reqs_files'][str(version)].append(reqs_file)
    # Unwrap dict to its final form
    ret = defaultdict(list)
    for distro, entry in grouped_packages.items():
        for version in entry['versions']:
            version = str(version)
            ret[distro].append((version, entry['reqs_files'][version]))
    return dict(ret)


class StringWithAttrs(six.text_type):
    '''
    An unicode subclass, to be able to add attributes.
    '''

    pass


def create_work_dir():
    '''
    Create a temporary work directory, automatically cleaned at exit.
    '''
    path = tempfile.mkdtemp(prefix='freeze-requirements-')
    atexit.register(shutil.rmtree, path)
    return path


def run_setup_with_setuptools(*commands):
    '''
    Run setup.py in the current directory, ensuring setuptools is activated.

    Return command stdout.
    '''
    python = sh.Command(sys.executable)
    return python(
        '-c',
        "import setuptools;__file__='setup.py';"
        "exec(compile(open(__file__).read().replace('\\r\\n', '\\n'), "
        "__file__, 'exec'))",
        *commands
    )


def get_wheel_name(package_filename):
    '''
    Get wheel archive name from a source package filename.
    '''
    archive = Archive(package_filename)

    # Extract package to a temp directory
    temp_dir = create_work_dir()
    archive.extract_all(temp_dir)

    # Find where packages have been extracted
    extracted_package_dir = commonprefix(
        op.realpath(op.join(temp_dir, p)) for p in archive.get_names()
    )

    # Run setup.py wheel_name
    with cd(extracted_package_dir):
        output = run_setup_with_setuptools('wheel_name')
    return output.splitlines()[-1]


def allnamesequal(name):
    return all(n == name[0] for n in name[1:])


def commonprefix(paths, sep=None):
    '''
    :func:`os.path.commonprefix` is buggy and can return non-existent paths.
    This version works correctly.
    '''
    if sep is None:
        sep = op.sep
    bydirectorylevels = zip(*[p.split(sep) for p in paths])
    return sep.join(x[0] for x in takewhile(allnamesequal, bydirectorylevels))


def build_wheel(pip, source_archive):
    '''
    Build a wheel package from source_archive, in a temp directory.

    Return the wheel package filename.
    '''
    wheel_dir = create_work_dir()

    # On newer versions of pip, we get a traceback when running "pip wheel" on
    # unittest2, we need to ignore the error to trigger the workaround below.
    try:
        pip.wheel('--no-deps', source_archive, wheel_dir=wheel_dir)
    except sh.ErrorReturnCode:
        pass

    # "pip wheel" fails on unittest2 because they use a stupid custom class
    # instead of a string for the version number in setup.py; pip does not set
    # a non-zero return code in this case, the error is just printed and no
    # wheel is built, so we have to check if the wheel dir is empty.
    #
    # The workaround is to run "setup.py sdist bdist_wheel", sdist converts the
    # version to string somewhere in the process...
    wheel_dir_content = os.listdir(wheel_dir)
    if wheel_dir_content:
        return op.join(wheel_dir, wheel_dir_content[0])

    # Engage WTF mode
    build_dir = create_work_dir()
    archive = Archive(source_archive)
    archive.extract_all(build_dir)
    source_dir = commonprefix(
        op.realpath(op.join(build_dir, p)) for p in archive.get_names())
    with cd(source_dir):
        run_setup_with_setuptools('sdist', 'bdist_wheel')
    dist_dir = op.join(source_dir, 'dist')
    wheel_filename = glob.glob(op.join(dist_dir, '*.whl'))
    return wheel_filename[0]


def canonicalize_distro_name(name):
    # Copied from packaging.utils
    # This is taken from PEP 503.
    return _canonicalize_regex.sub("-", name).lower()
