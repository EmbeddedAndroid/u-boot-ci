"""Web links to an exact commit or file of a repository, for the hosts
the firmware CIs pin from. None when the host's URL scheme is unknown:
a report then shows the repository and the commit without a link."""


def _base(repo):
    return repo[:-4] if repo.endswith(".git") else repo.rstrip("/")


def commit_url(repo, commit):
    if not repo or not commit:
        return None
    b = _base(repo)
    if "github.com/" in b:
        return "%s/commit/%s" % (b, commit)
    if "git.kernel.org/" in repo:
        return "%s/commit/?id=%s" % (repo.rstrip("/"), commit)
    if "review.trustedfirmware.org/" in b:
        return "%s/+/%s" % (b, commit)
    if "git.u-boot-project.org/" in b or "source.denx.de/" in b:
        return "%s/-/commit/%s" % (b, commit)
    return None


def file_url(repo, commit, path):
    """The file (or directory) at path in that commit."""
    if not repo or not commit:
        return None
    b = _base(repo)
    path = path.lstrip("/")
    if "github.com/" in b:
        return "%s/tree/%s/%s" % (b, commit, path)
    if "git.kernel.org/" in repo:
        return "%s/tree/%s?id=%s" % (repo.rstrip("/"), path, commit)
    if "review.trustedfirmware.org/" in b:
        return "%s/+/%s/%s" % (b, commit, path)
    if "git.u-boot-project.org/" in b or "source.denx.de/" in b:
        return "%s/-/tree/%s/%s" % (b, commit, path)
    return None


def tag_url(repo, tag):
    if "git.kernel.org/" in repo:
        return "%s/tag/?h=%s" % (repo.rstrip("/"), tag)
    if "github.com/" in repo:
        return "%s/releases/tag/%s" % (_base(repo), tag)
    return None
