from __future__ import print_function

import os
import sys
import atexit
import os.path as op
import subprocess
import argparse
import tempfile
import shutil
import functools
import json
import collections

try:
    from fabric.api import env, run, put
    import fabric.state
    fabric_present = True
except ImportError:
    fabric_present = False


from freezerequirements.utils import (likely_distro, cache_dir, cache_path,
        group_and_select_packages)
from freezerequirements.operations import (remote_move, local_move,
        remote_mkdtemp, remote_listdir, remote_rmtree)


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
    parser.add_argument('--output', '-o', help='put downloaded files here')
    parser.add_argument('--remote-pip', '-r', action='store_true',
            help='run pip on the destination host')
    parser.add_argument('--upload', '-u', help='upload files here; use '
            'user@host:/remote/dir syntax')
    parser.add_argument('--cache', '-c', help='make pip use this directory '
            'as a cache for downloaded packages')
    parser.add_argument('--cache-dependencies', action='store_true',
            help='use a cache to speed up processing of unchanged '
            'requirements files')
    parser.add_argument('--use-mirrors', action='store_true',
            help='use pypi mirrors')
    parser.add_argument('--connection-attempts', type=int, default=1,
            help='number of fabric connection attempts')
    parser.add_argument('--timeout', type=int, default=10,
            help='fabric connection timeout')
    parser.add_argument('--pip', default='pip', help='pip executable')
    parser.add_argument('--wheel', action='store_true',
            help='also build wheel packages from the requirements')
    parser.add_argument('--allow-external', action='append',
            dest='pip_externals')
    parser.add_argument('--allow-all-external', action='store_true')
    parser.add_argument('--allow-insecure', action='append',
            dest='pip_insecures')
    parser.add_argument('--exclude', '-x', action='append', metavar='PACKAGE',
            dest='excluded_packages', default=[], help='exclude PACKAGE from '
            'the frozen requirements file; use --exclude multiple times to '
            'exclude multiple packages')
    parser.add_argument('--use-ext-wheel', action='append', metavar='PACKAGE',
            dest='ext_wheels', default=[], help='do not try to build wheel '
            'for PACKAGE, but still include it in the frozen output; use '
            '--use-ext-wheel multiple times to specify multiple packages')
    options = parser.parse_args()

    # Verify options
    if not options.output and not options.upload:
        print('You must specify either --upload or --output', file=sys.stderr)
        sys.exit(1)
    if options.output and options.remote_pip:
        print("You can't use --output with --remote-pip", file=sys.stderr)
        sys.exit(1)
    if options.output:
        if not op.isdir(options.output):
            print('Output directory does not exist: %s' % options.output,
                    file=sys.stderr)
            sys.exit(1)
        output_dir = options.output
    else:
        output_dir = tempfile.mkdtemp(prefix=TEMPFILES_PREFIX)
        atexit.register(shutil.rmtree, output_dir)
    options.excluded_packages.extend(options.ext_wheels)

    if options.upload:
        if not fabric_present:
            print('You need to install fabric to use --upload',
                    file=sys.stderr)
            sys.exit(1)
        # Hide fabric commands logs
        fabric.state.output.running = False
        try:
            env.host_string, remote_dir = options.upload.split(':', 1)
        except ValueError:
            print('Invalid upload destination: %s' % options.upload,
                    file=sys.stderr)
            sys.exit(1)
        # Apply fabric options
        env.connection_attempts = options.connection_attempts
        env.timeout = options.timeout

    if options.cache_dependencies:
        reqs_cache_dir = cache_dir()
        if not op.exists(reqs_cache_dir):
            os.makedirs(reqs_cache_dir)

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

    # Alias functions to run pip locally or on the remote host
    if options.remote_pip:
        run_cmd = functools.partial(run, stdout=sys.stderr)
        mkdtemp = remote_mkdtemp
        listdir = remote_listdir
        rmtree = remote_rmtree
        put_package = remote_move
        move = remote_move
        # Upload requirements files to a temp directory
        print(SEPARATOR, file=sys.stderr)
        print('Uploading requirements...', file=sys.stderr)
        temp_dir = remote_mkdtemp(prefix=TEMPFILES_PREFIX)
        atexit.register(run, 'rm -rf %s' % temp_dir, stdout=sys.stderr)
        for i, requirement in enumerate(options.requirements):
            req_dir = op.join(temp_dir, str(i))
            run('mkdir %s' % req_dir, stdout=sys.stderr)
            remote_path = list(put(requirement, req_dir))[0]
            remote_path = StringWithAttrs(remote_path)
            remote_path.original_name = getattr(requirement, 'original_name',
                    requirement)
            options.requirements[i] = remote_path
        output_dir = op.join(temp_dir, 'packages')
        run('mkdir %s' % output_dir, stdout=sys.stderr)
        print(file=sys.stderr)
    else:
        run_cmd = functools.partial(subprocess.check_call, shell=True,
                stdout=sys.stderr)
        mkdtemp = tempfile.mkdtemp
        listdir = os.listdir
        rmtree = shutil.rmtree
        put_package = put
        move = local_move

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
                print('"%s" dependencies found in cache' %
                        original_requirement, file=sys.stderr)
                with open(deps_cache_path) as fp:
                    requirements_packages.append((original_requirement,
                        json.load(fp)))
                continue
        # Download requirements
        temp_dir = mkdtemp(prefix=TEMPFILES_PREFIX)
        atexit.register(rmtree, temp_dir)
        pip_cmd = '%s install -r %s --download %s' % (options.pip, requirement,
                temp_dir)
        if options.cache:
            run_cmd('mkdir -p %s' % options.cache)
            pip_cmd += ' --download-cache %s' % options.cache
        if options.use_mirrors:
            pip_cmd += ' --use-mirrors'
        if options.pip_externals:
            pip_cmd += ' --allow-external '
            pip_cmd += ' --allow-external '.join(options.pip_externals)
        if options.allow_all_external:
            pip_cmd += ' --allow-all-external'
        if options.pip_insecures:
            pip_cmd += ' --allow-insecure '
            pip_cmd += ' --allow-insecure '.join(options.pip_insecures)
        run_cmd(pip_cmd)
        # List downloaded packages
        dependencies = listdir(temp_dir)
        requirements_packages.append((original_requirement, dependencies))
        # Build wheel packages
        if options.wheel:
            wheels = {}
            for package in dependencies:
                package_path = op.join(temp_dir, package)
                final_path = op.join(output_dir, package)
                wheel_dir = mkdtemp(prefix=TEMPFILES_PREFIX)
                atexit.register(rmtree, wheel_dir)
                run_cmd('%s wheel --no-deps --wheel-dir %s %s' %
                        (options.pip, wheel_dir, package_path))
                wheels[final_path] = op.join(wheel_dir, listdir(wheel_dir)[0])
        # Update cache and move packages to their final destinations
        if options.cache_dependencies:
            with open(deps_cache_path, 'w') as fp:
                json.dump(dependencies, fp)
        move(op.join(temp_dir, '*'), output_dir)
    print(file=sys.stderr)

    # Upload or move packages to their final destination
    packages = [op.join(output_dir, p) for p in listdir(output_dir)]
    if packages and options.upload:
        print(SEPARATOR, file=sys.stderr)
        if options.remote_pip:
            print('Moving packages to their final destination...',
                    file=sys.stderr)
        else:
            print('Uploading packages...', file=sys.stderr)
        created_dirs = set()
        for package in packages:
            distro = likely_distro(package)
            dst_dir = op.join(remote_dir, distro.key)
            if dst_dir not in created_dirs:
                run('mkdir -p %s' % dst_dir, stdout=sys.stderr)
                created_dirs.add(dst_dir)
            put_package(package, dst_dir)
            if options.wheel:
                put_package(wheels[package], dst_dir)
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


class StringWithAttrs(unicode):

    pass
