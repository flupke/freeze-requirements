import os.path as op

from nose.tools import assert_equal

from freezerequirements.utils import (likely_distro, group_and_select_packages,
                                      get_wheel_name)


DATA_DIR = op.join(op.dirname(__file__), 'data')


def test_likely_distro():
    distro = likely_distro('lizard-2013-01-29-16-44-48.878536.tar.gz')
    assert_equal(distro.key, 'lizard')
    assert_equal(distro.version, '2013-01-29-16-44-48.878536')
    distro = likely_distro('stashy-client-0.1.3.tar.gz')
    assert_equal(distro.key, 'stashy-client')
    assert_equal(distro.version, '0.1.3')


def test_group_and_select_packages():
    pkgs = [
        ('requirements1.txt', ['foo-1.3.tar.gz', 'bar-0.1.tar.gz']),
        ('requirements2.txt', ['foo-1.4.tar.gz', 'bar-0.1.tar.gz']),
        ('requirements3.txt', [
            'baz-2014-01-29-16-44-48.878536.tar.gz',
            'baz-2013-01-29-16-44-48.878536.tar.gz',
        ]),
    ]
    assert_equal(group_and_select_packages(pkgs), {
        'foo': [
            ('1.3', ['requirements1.txt']),
            ('1.4', ['requirements2.txt'])
        ],
        'bar': [('0.1', ['requirements1.txt', 'requirements2.txt'])],
        'baz': [
            ('2013-01-29-16-44-48.878536', ['requirements3.txt']),
            ('2014-01-29-16-44-48.878536', ['requirements3.txt']),
        ],
    })


def test_get_wheel_name():
    setuptools_package = op.join(DATA_DIR, 'simple-setuptools-0.0.0.tar.gz')
    assert get_wheel_name(setuptools_package).endswith('.whl')
    distutils_package = op.join(DATA_DIR, 'simple-distutils-0.0.0.tar.gz')
    assert get_wheel_name(distutils_package).endswith('.whl')
    distutils_package = op.join(DATA_DIR, 'simple-setuptools-0.0.0.zip')
    assert get_wheel_name(distutils_package).endswith('.whl')
