#!/usr/bin/env python
from setuptools import setup, find_packages
import os

here = os.path.abspath(os.path.dirname(__file__))
README = open(os.path.join(here, 'README.rst')).read()
NEWS = open(os.path.join(here, 'NEWS.txt')).read()


version = '0.4.6'

install_requires = [
    'click',
    'sh',
]


setup(name='freeze-requirements',
    version=version,
    description="A script to help creating and maintaining frozen requirements for pip",
    long_description=README + '\n\n' + NEWS,
    classifiers=[
        # Get strings from http://pypi.python.org/pypi?%3Aaction=list_classifiers
        'License :: OSI Approved :: BSD License',
        'Operating System :: POSIX',
        'Intended Audience :: Developers',
        'Topic :: Software Development :: Build Tools',
        'Topic :: System :: Software Distribution',
    ],
    keywords='pip requirements frozen',
    author='Luper Rouch',
    author_email='luper.rouch@gmail.com',
    url='https://github.com/Stupeflix/freeze-requirements',
    license='BSD',
    packages=find_packages(),
    include_package_data=True,
    zip_safe=False,
    install_requires=install_requires,
    entry_points={
        'console_scripts': [
            'freeze-requirements=freezerequirements.cli:main'
        ],
        'distutils.commands': [
            'wheel_name=freezerequirements.wheel_name:wheel_name',
        ],
    }
)
