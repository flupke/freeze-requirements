freeze-requirements
===================

A script to help creating and maintaining frozen requirements for pip, inspired
by this `Mozilla dev team blog post
<http://blog.mozilla.org/webdev/2013/01/11/switching-to-pip-for-python-deployments/>`_.

Frozen requirements contain the packages you specified, plus all their
dependencies, with pinned versions.

For example if you have ``requirements.txt`` containing this::

    pyramid
    sqlalchemy

The frozen version would be::

    # This file has been automatically generated, DO NOT EDIT!

    # Frozen requirements for "requirements.txt"

    pastedeploy==1.5.2
    pyramid==1.5.1
    repoze.lru==0.6
    setuptools==5.5.1
    sqlalchemy==0.9.7
    translationstring==1.1
    venusian==1.0
    webob==1.4
    zope.deprecation==4.1.1
    zope.interface==4.1.1

Then you can use the frozen requirements in your deployment scripts with ``pip
install -r requirements-frozen.txt --no-deps``, and enjoy consistent
deployments even if some packages are updated on pypi.

freeze-requirements can also put the downloaded source packages in a pypi-like
directory structure on your web server, so you can speed up your deployments
with ``pip install -r requirements-frozen.txt --index-url
http://mywebserver.com/pypi-mirror``, and also build `wheels
<http://pythonwheels.com/>`_ to speed up deployments even more.

Installation
------------

Install from pypi::

    $ pip install freeze-requirements

Or from source::

    $ ./setup.py install

Examples
--------

Create frozen versions of two requirements files (they will be named
``requirements-frozen.txt`` and ``requirements2-frozen.txt`` in this example,
the ``-frozen`` suffix can be customized with ``--separate-requirements-suffix``)::

    $ freeze-requirements freeze --separate-requirements requirements.txt requirements2.txt

Merge multiple requirements in a single file::

    $ freeze-requirements freeze --merged-requirements requirements-merged.txt requirements.txt requirements2.txt

Use a cache to avoid reprocessing known requirements files::

    $ freeze-requirements freeze --cache-dependencies requirements.txt

Download source packages and build wheels for them, putting them in a pypi-like
directory structure::

    $ freeze-requirements freeze --output-dir /path/to/my/pypi --build-wheels requirements.txt

