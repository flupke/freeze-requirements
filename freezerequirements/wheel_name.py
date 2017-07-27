'''
Setuptools extension used to retrieve wheel package name for a distribution.
'''
from distutils.core import Command
from wheel.bdist_wheel import bdist_wheel


class wheel_name(Command):

    description = 'get archive name of a wheel distribution'
    user_options = []

    def initialize_options(self):
        pass

    def finalize_options(self):
        pass

    def run(self):
        # Workaround a very WTF bug if version defined in setup.py is not a
        # string (seen in unittest2)
        if not isinstance(self.distribution.metadata.version, basestring):
            self.distribution.metadata.version = \
                str(self.distribution.metadata.version)

        bdist_wheel_obj = bdist_wheel(self.distribution)
        bdist_wheel_obj.ensure_finalized()
        archive_basename = bdist_wheel_obj.get_archive_basename()
        print archive_basename + '.whl'
