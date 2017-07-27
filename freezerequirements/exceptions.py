class FreezeRequirementsError(Exception):

    pass


class VersionsConflicts(FreezeRequirementsError):

    def __init__(self, reqs_cache_paths):
        self.reqs_cache_paths = reqs_cache_paths
