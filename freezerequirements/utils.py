import os.path as op
import urllib
import string
import hashlib
import os

from setuptools.package_index import distros_for_filename


def likely_distro(filename):
    """
    Get the first distro as returned by :func:`distros_for_filename` that has a
    version that starts withe a number.
    """
    distros = [d for d in distros_for_filename(filename) 
            if d.version 
            and d.version[0] in string.digits]
    if len(distros) < 1:
        raise ValueError("can't find distro for %s" % filename)
    return distros[0]


def file_hash(filename):
    """
    Return the hash of *filename* contents.
    """
    with open(filename) as fp:
        return hashlib.sha1(fp.read()).hexdigest()


def cache_dir():
    """
    Return the application's cache directory.
    """
    cache_dir = os.environ.get('XDG_CACHE_HOME', op.expanduser('~/.cache'))
    return op.join(cache_dir, 'freeze-requirements')


def cache_path(filename):
    """
    Get cache path for *filename*.
    """
    filename = op.abspath(filename)
    key = "%s-%s" % (urllib.quote_plus(filename), file_hash(filename))
    return op.join(cache_dir(), key)
