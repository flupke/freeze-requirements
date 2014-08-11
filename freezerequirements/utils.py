import os.path as op
import string
import hashlib
import os
import bisect
from collections import defaultdict
from distutils.version import LooseVersion

from setuptools.package_index import distros_for_filename


def likely_distro(filename):
    '''
    Get the first distro as returned by :func:`distros_for_filename` that has a
    version that starts with a number.
    '''
    distros = [d for d in distros_for_filename(filename)
            if d.version
            and d.version[0] in string.digits]
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
    create_entry = lambda: {'versions': [], 'reqs_files': defaultdict(list)}
    grouped_packages = defaultdict(create_entry)
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


class StringWithAttrs(unicode):
    '''
    An unicode subclass, to be able to add attributes.
    '''

    pass


