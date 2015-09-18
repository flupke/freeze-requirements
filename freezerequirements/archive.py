import tarfile
import zipfile


class Archive(object):
    '''
    An wrapper offering a common interface around :mod:`tarfile` and
    :mod:`zipfile`.
    '''

    def __init__(self, filename):
        valid_exts = [
            ('.tar.gz', tarfile.open, 'getnames'),
            ('.zip', zipfile.ZipFile, 'namelist'),
            ('.tar.bz2', tarfile.open, 'getnames'),
        ]
        for ext, self.opener, self.get_names_func_name in valid_exts:
            if filename.endswith(ext):
                break
        else:
            raise ValueError('%s: unknown archive format' % filename)
        self.filename = filename

    def get_names(self):
        with self.opener(self.filename) as archive:
            members_func = getattr(archive, self.get_names_func_name)
            return members_func()

    def extract_all(self, path):
        with self.opener(self.filename) as archive:
            archive.extractall(path)
