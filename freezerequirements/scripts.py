from __future__ import print_function

import os
import sys
import atexit
import os.path as op
import tempfile
import shutil
import json
import collections

import sh
import click

from freezerequirements.utils import (likely_distro, cache_dir, cache_path,
        group_and_select_packages, StringWithAttrs)


TEMPFILES_PREFIX = 'freeze-requirements-'


@click.group()
def main():
    '''
    A tool to freeze pip requirements files.
    '''


@click.command()
@click.argument('requirements', nargs=-1,
        type=click.Path(exists=True, dir_okay=False))
@click.option('-o', '--output-dir', help='Put downloaded python packages '
        'and wheels here', metavar='DIR')
@click.option('-m', '--merged-requirements', type=click.File(mode='w'),
        help='Merge all requirements in FILE', metavar='FILE')
@click.option('--separate-requirements/--no-separate-requirements',
        default=False, help='Create separate frozen requirements next to each '
        'input requirements file')
@click.option('--separate-requirements-suffix', default='-frozen', 
        help='suffix to insert before file extensions to create separate '
        'frozen requirements filenames')
@click.option('-c', '--pip-cache', help='Pip download cache', metavar='DIR')
@click.option('--use-mirrors/--no-use-mirrors', default=False,
        help='use pypi mirrors')
@click.option('--cache-dependencies/--no-cache-dependencies', default=False,
        help='Use a cache to speed up processing of unchanged requirements '
        'files')
@click.option('--pip', default='pip', help='Path to the pip executable',
        type=click.Path(dir_okay=False))
@click.option('--build-wheels/--no-build-wheels', default=False,
        help='Build wheel packages from the requirements')
@click.option('--allow-external', 'pip_externals', multiple=True,
        metavar='PACKAGE')
@click.option('--allow-all-external/--no-allow-all-external',
        'pip_allow_all_external', default=False)
@click.option('--allow-insecure', 'pip_insecures', multiple=True,
        metavar='PACKAGE')
@click.option('-x', '--exclude', 'excluded_packages', multiple=True,
        help='Exclude a package from the frozen requirements',
        metavar='PACKAGE')
@click.option('--use-ext-wheel', 'ext_wheels', multiple=True,
        help='Do not try to build wheel for PACKAGE, but still include it in '
        'the frozen output; use --use-ext-wheel multiple times to specify '
        'multiple packages', metavar='PACKAGE')
@click.option('--output-index-url', help='Add an --index-url in the generated '
        'requirements file', metavar='URL')
def freeze(requirements, output_dir, pip_cache, cache_dependencies,
        use_mirrors, pip, build_wheels, pip_externals, pip_allow_all_external,
        pip_insecures, excluded_packages, ext_wheels, output_index_url,
        merged_requirements, separate_requirements,
        separate_requirements_suffix):
    '''
    Create a frozen requirement file from one or more requirement files.
    '''
    # Verify options
    if output_dir:
        if not op.isdir(output_dir):
            print('Output directory does not exist: %s' % output_dir,
                    file=sys.stderr)
            sys.exit(1)
    elif build_wheels:
        print('Using --build-wheels without --output makes no sense',
                file=sys.stderr)
        sys.exit(1)

    # Pre-process options
    excluded_packages = list(excluded_packages)
    requirements = list(requirements)
    excluded_packages.extend(ext_wheels)
    check_versions_conflicts = separate_requirements

    # Create packages collect dir
    packages_collect_dir = tempfile.mkdtemp(prefix=TEMPFILES_PREFIX)
    atexit.register(shutil.rmtree, packages_collect_dir)

    if cache_dependencies:
        reqs_cache_dir = cache_dir()
        if not op.exists(reqs_cache_dir):
            os.makedirs(reqs_cache_dir)

    # Prepare reused shell commands
    pip = sh.Command(pip)
    move_forced = sh.mv.bake('-f')

    # Filter excluded packages from requirements files
    filtered_requirements_refs = []
    ext_wheels_lines = collections.defaultdict(list)
    if excluded_packages:
        for i, requirement in enumerate(requirements):
            excluded_something = False
            filtered_lines = []
            with open(requirement) as fp:
                for line in fp:
                    excluded_package = False
                    for pkg in excluded_packages:
                        if pkg in line:
                            excluded_package = True
                            excluded_something = True
                            if pkg in ext_wheels:
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
                requirements[i] = filtered_reqs.name
                # Keep a reference to tempfile to avoid garbage collection
                filtered_requirements_refs.append(filtered_reqs)

    # Download packages
    print('Downloading packages...', file=sys.stderr)
    requirements_packages = []
    wheels = {}
    for requirement in requirements:
        # Check cache
        original_requirement = getattr(requirement, 'original_name',
                requirement)
        if cache_dependencies:
            deps_cache_path = cache_path(original_requirement)
            if op.exists(deps_cache_path):
                print('%s dependencies found in cache' % original_requirement,
                        file=sys.stderr)
                with open(deps_cache_path) as fp:
                    requirements_packages.append((original_requirement,
                        json.load(fp)))
                continue
        print(original_requirement, file=sys.stderr)
        # Download python source packages from requirement file
        temp_dir = tempfile.mkdtemp(prefix=TEMPFILES_PREFIX)
        atexit.register(shutil.rmtree, temp_dir)
        pip_args = ['--no-use-wheel']
        pip_kwargs = {'requirement': requirement, 'download': temp_dir}
        if pip_cache:
            if not op.exists(pip_cache):
                os.makedirs(pip_cache)
            pip_kwargs['download_cache'] = pip_cache
        if use_mirrors:
            pip_args.append('--use-mirrors')
        if pip_allow_all_external:
            pip_args.append('--allow-all-external')
        for external in pip_externals:
            pip_args += ['--allow-external', external]
        for insecure in pip_insecures:
            pip_args += ['--allow-insecure', insecure]
        pip.install(*pip_args, **pip_kwargs)
        # List downloaded packages
        dependencies = os.listdir(temp_dir)
        requirements_packages.append((original_requirement, dependencies))
        # Build wheel packages
        if build_wheels:
            print('  Building wheels...', file=sys.stderr)
            for package in dependencies:
                package_path = op.join(temp_dir, package)
                final_path = op.join(packages_collect_dir, package)
                wheel_dir = tempfile.mkdtemp(prefix=TEMPFILES_PREFIX)
                atexit.register(shutil.rmtree, wheel_dir)
                pip.wheel('--no-deps', package_path, wheel_dir=wheel_dir)
                wheels[final_path] = op.join(wheel_dir, os.listdir(wheel_dir)[0])
        # Update cache and move packages to the packages collect dir
        if cache_dependencies:
            with open(deps_cache_path, 'w') as fp:
                json.dump(dependencies, fp)
        move_forced(sh.glob(op.join(temp_dir, '*')), packages_collect_dir)
    print(file=sys.stderr)

    # Move packages to their final destination
    packages = [op.join(packages_collect_dir, p)
            for p in os.listdir(packages_collect_dir)]
    if output_dir and packages:
        print('Moving packages to their final destination...',
                file=sys.stderr)
        for package in packages:
            distro = likely_distro(package)
            dst_dir = op.join(output_dir, distro.key)
            if not op.exists(dst_dir):
                os.makedirs(dst_dir)
            move_forced(package, dst_dir)
            if build_wheels:
                move_forced(wheels[package], dst_dir)
        print(file=sys.stderr)

    # Group packages by distribution key and sort them by version
    grouped_packages = group_and_select_packages(requirements_packages)
    if check_versions_conflicts:
        errors = []
        for distro, versions in grouped_packages.items():
            if len(versions) > 1:
                lines = ['  - %s:' % distro]
                lines.extend('    - %s==%s coming from %s' %
                        (distro, version, ', '.join(requirements))
                        for version, requirements in versions)
                errors.append('\n'.join(lines))
        if errors:
            print('Found versions conflicts:', file=sys.stderr)
            print('\n'.join(errors), file=sys.stderr)
            sys.exit(1)

    # Format merged requirements
    if merged_requirements:
        format_requirements(merged_requirements, requirements_packages,
                grouped_packages, excluded_packages, output_index_url,
                ext_wheels_lines)
        print('Wrote merged frozen requirements in %s' %
                merged_requirements.name, file=sys.stderr)

    # Format separate requirements
    if separate_requirements:
        for requirements_file, packages in requirements_packages:
            root, ext = op.splitext(requirements_file)
            filename = root + separate_requirements_suffix + ext
            with open(filename, 'w') as fp:
                format_requirements(fp, [(requirements_file, packages)],
                grouped_packages, excluded_packages, output_index_url,
                ext_wheels_lines)
            print('Wrote separate frozen requirements for %s in %s' %
                    (requirements_file, filename), file=sys.stderr)


def format_requirements(fp, packages_groups, grouped_packages,
        excluded_packages, output_index_url, ext_wheels_lines):
    '''
    Format the *(requirements_file, packages_list)* list *packages_groups* to
    *fp*.
    '''
    fp.write('# This file has been automatically generated, DO NOT EDIT!\n')
    fp.write('\n')
    if output_index_url:
        fp.write('--index-url %s\n' % output_index_url, )
        fp.write('\n')
    seen = set()
    for requirements_file, packages in packages_groups:
        fp.write('# Frozen requirements for "%s"\n' % requirements_file)
        fp.write('\n')
        distros = [likely_distro(p) for p in packages]
        for distro in sorted(distros, key=lambda d: d.key):
            if distro.key in seen or distro.key in excluded_packages:
                continue
            seen.add(distro.key)
            versions = grouped_packages[distro.key]
            fp.write('%s==%s\n' % (distro.key, versions[-1][0]))
        for pkg in ext_wheels_lines[requirements_file]:
            fp.write('%s\n' % pkg.strip())
        fp.write('\n')


@click.command()
@click.argument('requirements', nargs=-1)
def cache_infos(requirements):
    '''
    Print cache information for the given list of requirements.
    '''
    for req in requirements:
        req_cache = cache_path(req)
        if not op.exists(req_cache):
            req_cache = 'not cached'
        print('%s %s' % (req, req_cache))


main.add_command(freeze)
main.add_command(cache_infos)
