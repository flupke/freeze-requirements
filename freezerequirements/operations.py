import sys
import subprocess
import uuid
import os.path as op


def remote_move(src, dst):
    """
    Move a file on a remote host.
    """
    from fabric.api import run

    run('mv -fv %s %s' % (src, dst), stdout=sys.stderr)


def local_move(src, dst):
    """
    Move a file on local host.
    """
    subprocess.check_call('mv -fv %s %s' % (src, dst), shell=True,
            stdout=sys.stderr)


def remote_mkdtemp(prefix='', dir='/tmp'):
    """
    Create a remote temporary directory.
    """
    from fabric.api import run
    from fabric.contrib.files import exists

    while True:
        temp_dir = op.join(dir, '%s%s' % (prefix, uuid.uuid4().hex))
        if not exists(temp_dir):
            run('mkdir %s' % temp_dir, stdout=sys.stderr)
            break
    return temp_dir


def remote_listdir(location):
    from fabric.api import run

    return run('ls %s' % location, stdout=sys.stderr).split()


def remote_rmtree(location):
    from fabric.api import run

    run('rm -rf %s' % location, stdout=sys.stderr)
