from __future__ import print_function

import os
import sys
import atexit
import os.path as op
import argparse
import tempfile
import shutil
import json
import collections

import sh

from freezerequirements.utils import (likely_distro, cache_dir, cache_path,
        group_and_select_packages)


TEMPFILES_PREFIX = 'freeze-requirements-'
SEPARATOR = '-' * 78


def main():
    # Parse arguments
    parser = argparse.ArgumentParser(description='Download dependencies '
        'from requirements file(s) and upload them to your private pypi '
        'repository')
    parser.add_argument('requirements', nargs='+',
            help='a pip requirements file, you can specify multiple '
            'requirements files if needed')
    parser.add_argument('--output', '-o',
            help='put downloaded python packages and wheels here')
    parser.add_argument('--cache', '-c', help='make pip use this directory '
            'as a cache for downloaded packages')
    parser.add_argument('--cache-dependencies', action='store_true',
            help='use a cache to speed up processing of unchanged '
            'requirements files')
    parser.add_argument('--use-mirrors', action='store_true',
            help='use pypi mirrors')
    parser.add_argument('--pip', default='pip', help='pip executable')
    parser.add_argument('--wheel', action='store_true',
            help='also build wheel packages from the requirements')
    parser.add_argument('--allow-external', action='append', default=[],
            dest='pip_externals')
    parser.add_argument('--allow-all-external', action='store_true')
    parser.add_argument('--allow-insecure', action='append', default=[],
            dest='pip_insecures')
    parser.add_argument('--exclude', '-x', action='append', metavar='PACKAGE',
            dest='excluded_packages', default=[], help='exclude PACKAGE from '
            'the frozen requirements file; use --exclude multiple times to '
            'exclude multiple packages')
    parser.add_argument('--use-ext-wheel', action='append', metavar='PACKAGE',
            dest='ext_wheels', default=[], help='do not try to build wheel '
            'for PACKAGE, but still include it in the frozen output; use '
            '--use-ext-wheel multiple times to specify multiple packages')
    parser.add_argument('--cache-infos', action='store_true',
            help='show cache informations for the given requirements')
    options = parser.parse_args()

    if options.cache_infos:
        show_cache_infos(options.requirements)
        sys.exit(0)

    # Verify options
    if options.output:
        if not op.isdir(options.output):
            print('Output directory does not exist: %s' % options.output,
                    file=sys.stderr)
            sys.exit(1)
        output_dir = options.output
    elif options.wheel:
        print('Using --wheel without --output makes no sense', file=sys.stderr)
        sys.exit(1)
    packages_collect_dir = tempfile.mkdtemp(prefix=TEMPFILES_PREFIX)
    atexit.register(shutil.rmtree, packages_collect_dir)
    options.excluded_packages.extend(options.ext_wheels)

    if options.cache_dependencies:
        reqs_cache_dir = cache_dir()
        if not op.exists(reqs_cache_dir):
            os.makedirs(reqs_cache_dir)

    # Prepare reused shell commands
    pip = sh.Command(options.pip)
    move_forced = sh.mv.bake('-fv')

    # Filter excluded packages from requirements files
    filtered_requirements_refs = []
    ext_wheels_lines = collections.defaultdict(list)
    if options.excluded_packages:
        for i, requirement in enumerate(options.requirements):
            excluded_something = False
            filtered_lines = []
            with open(requirement) as fp:
                for line in fp:
                    excluded_package = False
                    for pkg in options.excluded_packages:
                        if pkg in line:
                            excluded_package = True
                            excluded_something = True
                            if pkg in options.ext_wheels:
                                ext_wheels_lines[requirement].append(line)
                            break
                    if not excluded_package:
                        filtered_lines.append(line)
            if excluded_something:
                filtered_reqs = tempfile.NamedTemporaryFile(
                        prefix='freeze-requirements-filtered-reqs-')
                filtered_reqs.writelines(filtered_lines)
                filtered_reqs.flush()
                filtered_reqs.name = StringWithAttrs(filtered_reqs.name)
                filtered_reqs.name.original_name = requirement
                options.requirements[i] = filtered_reqs.name
                # Keep a reference to tempfile to avoid garbage collection
                filtered_requirements_refs.append(filtered_reqs)

    # Download packages
    print(SEPARATOR, file=sys.stderr)
    print('Downloading packages...', file=sys.stderr)
    requirements_packages = []
    for requirement in options.requirements:
        # Check cache
        original_requirement = getattr(requirement, 'original_name',
                requirement)
        if options.cache_dependencies:
            deps_cache_path = cache_path(original_requirement)
            if op.exists(deps_cache_path):
                print('"%s" dependencies found in cache (%s)' %
                        (original_requirement, deps_cache_path),
                        file=sys.stderr)
                with open(deps_cache_path) as fp:
                    requirements_packages.append((original_requirement,
                        json.load(fp)))
                continue
        # Download python source packages from requirement file
        temp_dir = tempfile.mkdtemp(prefix=TEMPFILES_PREFIX)
        atexit.register(shutil.rmtree, temp_dir)
        pip_args = ['--no-use-wheel']
        pip_kwargs = {'requirement': requirement, 'download': temp_dir}
        if options.cache:
            if not op.exists(options.cache):
                os.makedirs(options.cache)
            pip_kwargs['download_cache'] = options.cache
        if options.use_mirrors:
            pip_args.append('--use-mirrors')
        if options.allow_all_external:
            pip_args.append(' --allow-all-external')
        for external in options.pip_externals:
            pip_args += ['--allow-external', external]
        for insecure in options.pip_insecures:
            pip_args += ['--allow-insecure', insecure]
        pip.install(*pip_args, **pip_kwargs)
        # List downloaded packages
        dependencies = os.listdir(temp_dir)
        requirements_packages.append((original_requirement, dependencies))
        # Build wheel packages
        if options.wheel:
            wheels = {}
            for package in dependencies:
                package_path = op.join(temp_dir, package)
                final_path = op.join(packages_collect_dir, package)
                wheel_dir = tempfile.mkdtemp(prefix=TEMPFILES_PREFIX)
                atexit.register(shutil.rmtree, wheel_dir)
                pip.wheel('--no-deps', package_path, wheel_dir=wheel_dir)
                wheels[final_path] = op.join(wheel_dir, os.listdir(wheel_dir)[0])
        # Update cache and move packages to the packages collect dir
        if options.cache_dependencies:
            with open(deps_cache_path, 'w') as fp:
                json.dump(dependencies, fp)
        move_forced(op.join(temp_dir, '*'), packages_collect_dir)
    print(file=sys.stderr)

    # Move packages to their final destination
    packages = [op.join(packages_collect_dir, p)
            for p in os.listdir(packages_collect_dir)]
    if output_dir and packages:
        print(SEPARATOR, file=sys.stderr)
        print('Moving packages to their final destination...',
                file=sys.stderr)
        for package in packages:
            distro = likely_distro(package)
            dst_dir = op.join(output_dir, distro.key)
            if not op.exists(dst_dir):
                os.makedirs(dst_dir)
            move_forced(package, dst_dir)
            if options.wheel:
                move_forced(wheels[package], dst_dir)
    print(file=sys.stderr)

    # Group packages by distribution key and sort them by version
    grouped_packages = group_and_select_packages(pkgs for reqs_file, pkgs in
            requirements_packages)

    # Print frozen requirements for each input requirements file
    print(SEPARATOR, file=sys.stderr)
    seen = set()
    print('# This file has been automatically generated, DO NOT EDIT!')
    print()
    for requirements_file, packages in requirements_packages:
        print('# Frozen requirements for "%s":' % requirements_file)
        print()
        distros = [likely_distro(p) for p in packages]
        for distro in sorted(distros, key=lambda d: d.key):
            if distro.key in seen or distro.key in options.excluded_packages:
                continue
            seen.add(distro.key)
            versions = grouped_packages[distro.key]
            if len(versions) > 1:
                print('# Picked highest version of %s in: %s' % (distro.key,
                        ', '.join(versions)))
            print('%s==%s' % (distro.key, versions[0]))
        for pkg in ext_wheels_lines[requirements_file]:
            print(pkg.strip())
        print()


def show_cache_infos(requirements):
    '''
    Print cache information for the given list of requirements.
    '''
    for req in requirements:
        req_cache = cache_path(req)
        if not op.exists(req_cache):
            req_cache = 'not cached'
        print('%s %s' % (req, req_cache))


class StringWithAttrs(unicode):

    pass
