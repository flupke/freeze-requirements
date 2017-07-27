from __future__ import print_function

import os
import sys
import os.path as op
import tempfile
import json
import collections

import sh
import click
from pip.req import InstallRequirement

from .utils import (likely_distro, cache_dir, cache_path,
                    group_and_select_packages, StringWithAttrs,
                    create_work_dir, get_wheel_name, colored, build_wheel,
                    canonicalize_distro_name)
from .exceptions import VersionsConflicts


@click.group()
def main():
    '''
    A tool to freeze pip requirements files.
    '''
    # Disable sh truncation of errors
    sh.ErrorReturnCode.truncate_cap = None


@click.command()
@click.argument('requirements', nargs=-1,
                type=click.Path(exists=True, dir_okay=False))
@click.option('-o', '--output-dir', help='Put downloaded python packages '
              'and wheels here', metavar='DIR')
@click.option('-m', '--merged-requirements', type=click.File(mode='w'),
              help='Merge all requirements in FILE', metavar='FILE')
@click.option('--separate-requirements/--no-separate-requirements',
              default=False, help='Create separate frozen requirements next '
              'to each input requirements file')
@click.option('--separate-requirements-suffix', default='-frozen',
              help='suffix to insert before file extensions to create '
              'separate frozen requirements filenames')
@click.option('--cache-dependencies/--no-cache-dependencies', default=False,
              help='Use a cache to speed up processing of unchanged '
              'requirements files')
@click.option('--pip', default='pip', help='Path to the pip executable',
              type=click.Path(dir_okay=False))
@click.option('--build-wheels/--no-build-wheels', default=False,
              help='Build wheel packages from the requirements')
@click.option('--rebuild-wheels/--no-rebuild-wheels', default=True,
              help='Check for wheels in the output directory before '
              'rebuilding them')
@click.option('-x', '--exclude', 'excluded_packages', multiple=True,
              help='Exclude a package from the frozen requirements; you may '
              'specify --exclude multiple times; PACKAGE may also take the '
              'form [req_path]:[package_name], to exclude a package from '
              'a specific separate requirement', metavar='PACKAGE')
@click.option('--exclude-requirements', type=click.File(mode='r'),
              multiple=True, help='Exclude packages contained in '
              'requirements FILE; you may specify --exclude-requirements '
              'multiple times', metavar='FILE')
@click.option('--use-ext-wheel', 'ext_wheels', multiple=True,
              help='Do not try to build wheel for PACKAGE, but still '
              'include it in the frozen output; use --use-ext-wheel '
              'multiple times to specify multiple packages', metavar='PACKAGE')
@click.option('--output-index-url', help='Add an --index-url in the generated '
              'requirements file', metavar='URL')
@click.option('--loose', 'loose_packages', multiple=True, metavar='PACKAGE',
              help='Do not specify version for PACKAGE in the output '
              'requirements file(s)')
@click.option('--loose-requirements/--no-loose-requirements', default=False,
              help='Generate loose requirements files')
@click.option('--loose-requirements-suffix', default='-loose',
              metavar='SUFFIX', help='Loose requirements filenames are '
              'generated with this suffix')
@click.option('--max-conflict-resolution-iterations', default=10)
def freeze(requirements, output_dir, cache_dependencies, pip, build_wheels,
           excluded_packages, ext_wheels, output_index_url,
           merged_requirements, separate_requirements,
           separate_requirements_suffix, rebuild_wheels, exclude_requirements,
           loose_packages, loose_requirements, loose_requirements_suffix,
           max_conflict_resolution_iterations):
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
    for excluded_reqs_fp in exclude_requirements:
        excluded_packages.extend(
            p.strip() for p in excluded_reqs_fp
            if p.strip() and not p.strip().startswith('#')
        )
    loose_packages = set(loose_packages)

    check_versions_conflicts = separate_requirements

    if cache_dependencies:
        reqs_cache_dir = cache_dir()
        if not op.exists(reqs_cache_dir):
            os.makedirs(reqs_cache_dir)

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
                    prefix='freeze-requirements-filtered-reqs-'
                )
                filtered_reqs.writelines(filtered_lines)
                filtered_reqs.flush()
                filtered_reqs.name = StringWithAttrs(filtered_reqs.name)
                filtered_reqs.name.original_name = requirement
                requirements[i] = filtered_reqs.name
                # Keep a reference to tempfile to avoid garbage collection
                filtered_requirements_refs.append(filtered_reqs)

    for _ in range(max_conflict_resolution_iterations):
        try:
            requirements_packages, grouped_packages = collect_packages(
                requirements, output_dir, cache_dependencies, build_wheels,
                rebuild_wheels, pip, check_versions_conflicts
            )
        except VersionsConflicts as exc:
            if not exc.reqs_cache_paths:
                sys.exit(1)
            print('Trying to automatically resolve conflicts by reprocessing '
                  'cached dependencies', file=sys.stderr)
            for path in exc.reqs_cache_paths:
                os.unlink(path)
        else:
            break
    else:
        print('Failed to resolve conflicts after %s retries' %
              max_conflict_resolution_iterations, file=sys.stderr)
        sys.exit(1)

    # Format merged requirements
    if merged_requirements:
        format_requirements(merged_requirements, requirements_packages,
                            grouped_packages, excluded_packages,
                            output_index_url, ext_wheels_lines)
        print('Wrote merged frozen requirements in %s' %
              merged_requirements.name, file=sys.stderr)

    # Format separate requirements
    if separate_requirements:
        for requirements_file, packages in requirements_packages:
            root, ext = op.splitext(requirements_file)
            filename = root + separate_requirements_suffix + ext
            with open(filename, 'w') as fp:
                format_requirements(fp, [(requirements_file, packages)],
                                    grouped_packages, excluded_packages,
                                    output_index_url, ext_wheels_lines)
            print('Wrote separate frozen requirements for %s in %s' %
                  (requirements_file, filename), file=sys.stderr)

    # Format loose requirements
    if loose_requirements and loose_packages:
        for requirements_file, packages in requirements_packages:
            root, ext = op.splitext(requirements_file)
            filename = root + loose_requirements_suffix + ext
            with open(filename, 'w') as fp:
                format_requirements(fp, [(requirements_file, packages)],
                                    grouped_packages, excluded_packages,
                                    output_index_url, ext_wheels_lines,
                                    loose_packages=loose_packages)
            print('Wrote separate loose requirements for %s in %s' %
                  (requirements_file, filename), file=sys.stderr)


def collect_packages(requirements, output_dir, cache_dependencies,
                     build_wheels, rebuild_wheels, pip_bin,
                     check_versions_conflicts):
    '''
    Collect all packages and their requirements to *output_dir*, optionally
    build wheel files in the process.
    '''
    # Create packages collect dir
    packages_collect_dir = create_work_dir()

    # Prepare reused shell commands
    pip = sh.Command(pip_bin)
    move_forced = sh.mv.bake('-f')

    # Download packages
    requirements_packages = []
    wheels = {}
    deps_cache_map = collections.defaultdict(set)
    cache_updates = {}
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
                    dependencies = json.load(fp)
                requirements_packages.append((original_requirement,
                                              dependencies))
                # Store dependencies cache path for each distro name in it, so
                # we can retrieve cache files associated with version conflicts
                # later
                for pkg_filename in dependencies:
                    pkg_name = likely_distro(pkg_filename).key
                    deps_cache_map[pkg_name].add(deps_cache_path)
                continue
        print(original_requirement, file=sys.stderr)
        # Download python source packages from requirement file
        print('  Downloading packages...', file=sys.stderr)
        temp_dir = create_work_dir()
        try:
            pip.download(requirement=requirement, dest=temp_dir,
                         no_binary=':all:')
        except sh.ErrorReturnCode as exc:
            print(exc.stdout, file=sys.stderr)
            print(exc.stderr, file=sys.stderr)
            sys.exit(1)
        # List downloaded packages
        dependencies = os.listdir(temp_dir)
        requirements_packages.append((original_requirement, dependencies))
        # Build wheel packages
        if build_wheels:
            print('  Building wheels...', file=sys.stderr)
            for package in dependencies:
                package_path = op.join(temp_dir, package)
                # Check the wheel does not already exist
                if not rebuild_wheels:
                    wheel_name = get_wheel_name(package_path)
                    distro = likely_distro(package)
                    final_wheel_path = op.join(
                        output_dir,
                        canonicalize_distro_name(distro.key),
                        wheel_name
                    )
                    if op.exists(final_wheel_path):
                        print(colored('okgreen', '  %s already built, skipped'
                                      % final_wheel_path), file=sys.stderr)
                        continue
                    else:
                        print(colored('okblue', '  %s not found, rebuilding' %
                                      final_wheel_path), file=sys.stderr)
                # Nope, build wheel
                final_path = op.join(packages_collect_dir, package)
                wheels[final_path] = build_wheel(pip, package_path)
        # Save cache content for later and move packages to the packages
        # collect dir
        if cache_dependencies:
            cache_updates[deps_cache_path] = json.dumps(dependencies)
        move_forced(sh.glob(op.join(temp_dir, '*')), packages_collect_dir)
    print(file=sys.stderr)

    # Move packages to their final destination
    packages = [op.join(packages_collect_dir, p)
                for p in os.listdir(packages_collect_dir)]
    if output_dir and packages:
        print('Moving packages to their final destination...', file=sys.stderr)
        for package in packages:
            distro = likely_distro(package)
            dst_dir = op.join(output_dir, canonicalize_distro_name(distro.key))
            if not op.exists(dst_dir):
                os.makedirs(dst_dir)
            move_forced(package, dst_dir)
            if build_wheels and package in wheels:
                move_forced(wheels[package], dst_dir)
        print(file=sys.stderr)

    # Commit cache
    for filename, contents in cache_updates.items():
        with open(filename, 'w') as fp:
            fp.write(contents)

    # Group packages by distribution key and sort them by version
    grouped_packages = group_and_select_packages(requirements_packages)
    if check_versions_conflicts:
        errors = []
        deps_cache_paths = set()
        for distro, versions in grouped_packages.items():
            if len(versions) > 1:
                lines = ['  - %s:' % distro]
                lines.extend(
                    '    - %s==%s coming from %s' %
                    (distro, version, ', '.join(requirements))
                    for version, requirements in versions
                )
                errors.append('\n'.join(lines))
                deps_cache_paths.update(deps_cache_map[distro])
        if errors:
            print('Found versions conflicts:', file=sys.stderr)
            print('\n'.join(errors), file=sys.stderr)
            raise VersionsConflicts(deps_cache_paths)

    return requirements_packages, grouped_packages


def format_requirements(fp, packages_groups, grouped_packages,
                        excluded_packages, output_index_url, ext_wheels_lines,
                        loose_packages=set()):
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
            if (distro.key in seen or
                    distro.key in excluded_packages or
                    '%s:%s' % (requirements_file, distro.key) in
                    excluded_packages):
                continue
            seen.add(distro.key)
            versions = grouped_packages[distro.key]
            if distro.key not in loose_packages:
                line = '%s==%s' % (distro.key, versions[-1][0])
            else:
                line = distro.key
            fp.write('%s\n' % line)
        for line in ext_wheels_lines[requirements_file]:
            req = InstallRequirement.from_line(line)
            if req.name in loose_packages:
                fp.write('%s\n' % req.name)
            else:
                fp.write('%s\n' % line.strip())
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
