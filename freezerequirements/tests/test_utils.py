from nose.tools import assert_equal

from freezerequirements.utils import likely_distro


def test_likely_distro():
    distro = likely_distro('lizard-2013-01-29-16-44-48.878536.tar.gz')
    assert_equal(distro.key, 'lizard')
    assert_equal(distro.version, '2013-01-29-16-44-48.878536')
    distro = likely_distro('stashy-client-0.1.3.tar.gz')
    assert_equal(distro.key, 'stashy-client')
    assert_equal(distro.version, '0.1.3')
