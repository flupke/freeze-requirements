freeze-requirements
===================

A script to help creating and maintaining frozen requirements for pip.

It is inspired by this `Mozilla dev team blog post <http://blog.mozilla.org/webdev/2013/01/11/switching-to-pip-for-python-deployments/>`_, 
who recently switched to pip for deployment.

Basically it downloads packages from one or more pip 'normal' requirements
files (the ones you use for development, containing only the 'top level'
dependencies), and outputs the corresponding list of requirements to copy/paste
in your frozen production requirements files.

It can also upload the packages to your private pypi repository, and even
download the packages from there to save bandwidth.

Installation
------------

Install from pypi::

    $ sudo pip install freeze-requirements

Or from source::

    $ sudo ./setup.py install

If you want to use ``--upload`` you also need fabric::

    $ sudo pip install fabric

Examples
--------

Download packages locally::

    freeze-requirements requirements.txt --output /tmp/packages

Process multiple requirements files at once::

    freeze-requirements requirements.txt requirements2.txt --output /tmp/packages

Download packages and upload them to a remote host::

    freeze-requirements requirements.txt --upload user@private-pypi.example.com:/home/pypi/packages

Same as above but download packages from the remote host. This may be faster as
there is no need to upload the packages from your machine and the remote host
may have a faster internet connection (pip needs to be installed on the remote
host)::

    freeze-requirements requirements.txt --upload user@private-pypi.example.com:/home/pypi/packages --remote-pip
    
