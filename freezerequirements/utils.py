import string

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
