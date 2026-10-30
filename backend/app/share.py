"""Where a library lives, in a form that means the same thing on every machine.

The same file on the lab share has a different path depending on who is
looking at it:

    \\\\PTI\\Lab\\Libraries\\foo.tsv     a Windows machine, by UNC
    L:\\Libraries\\foo.tsv               the same machine, by mapped drive
    /Volumes/Lab/Libraries/foo.tsv       a Mac
    /mnt/lab/Libraries/foo.tsv           a Linux box

There is no absolute path that works everywhere, so the catalog does not store
one. It stores the part that is the same for everyone -- "Libraries/foo.tsv",
the path *within the share* -- and each side renders it the way its own
machine wants it. The server resolves it against its own view of the share to
read the file; the browser shows it in the flavour the person is on.

Two things fall out of this for free. A library catalogued from a Mac and the
same library catalogued from Windows produce the same stored path, so the
unique constraint on it finally catches the duplicate it was always meant to.
And a path that matches none of the known mounts is, by definition, not on the
share -- which is the check that keeps libraries nobody else can open out of a
catalog whose whole purpose is that everyone can open them.

The mounts are configuration, not code: see share.json next to this package,
or point SHARE_CONFIG somewhere else.
"""
import json
import ntpath
import os
import posixpath
import re
from typing import List, NamedTuple, Optional

# Where the config lives unless SHARE_CONFIG says otherwise. Beside the backend
# package rather than inside it: it describes this deployment, not the code.
_DEFAULT_CONFIG = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "share.json"
)

WINDOWS = "windows"
MAC = "mac"
LINUX = "linux"

# A Windows path either starts \\server\share or with a drive letter. Used to
# decide which separator to join with, so one config key describes the server's
# own mount without a second key saying what kind of path it is.
_WINDOWS_PATH = re.compile(r"^(\\\\|[A-Za-z]:)")


class Mount(NamedTuple):
    """One way of reaching the share, as some machine sees it."""
    os: str       # WINDOWS, MAC or LINUX -- which flavour to show it to
    prefix: str   # e.g. "L:", "\\\\PTI\\Lab", "/Volumes/Lab"


class ShareConfig(NamedTuple):
    server_root: str      # how *this* server reaches the share
    mounts: List[Mount]
    # False lets a library outside the share be catalogued anyway. The default
    # is to refuse: a path only one person can open is worse than no entry,
    # because the catalog says the library is available when it is not.
    require_on_share: bool = True


def load(path: Optional[str] = None) -> ShareConfig:
    """Read the share configuration. A missing or malformed file leaves the
    catalog with no share: paths are then stored as typed and nothing is
    rejected, so a misconfigured server is awkward rather than unusable."""
    path = path or os.getenv("SHARE_CONFIG") or _DEFAULT_CONFIG
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        root = str(data["server_root"])
        mounts = [Mount(str(m["os"]), str(m["prefix"])) for m in data["mounts"]]
    except (OSError, ValueError, KeyError, TypeError):
        return ShareConfig("", [], require_on_share=False)
    return ShareConfig(root, mounts, bool(data.get("require_on_share", True)))


CONFIG = load()


def configured() -> bool:
    """Whether a share is set up at all. Without one every path is stored as it
    was typed, which is what the catalog did before any of this existed."""
    return bool(CONFIG.server_root and CONFIG.mounts)


def _separators(path: str) -> str:
    """Both separators mean the same thing to us: people paste either."""
    return path.replace("\\", "/")


def _strip_prefix(path: str, prefix: str) -> Optional[str]:
    """What follows *prefix* in *path*, or None if it is not under it.

    Compared case-insensitively. The share is served from Windows, where
    Libraries/Foo.tsv and libraries/foo.tsv are one file, and a Mac user who
    types the mount in lower case should not create a second entry for it.
    """
    path_parts = [p for p in _separators(path).split("/") if p]
    prefix_parts = [p for p in _separators(prefix).split("/") if p]
    if len(path_parts) < len(prefix_parts):
        return None
    if [p.lower() for p in path_parts[:len(prefix_parts)]] != [p.lower() for p in prefix_parts]:
        return None
    return "/".join(path_parts[len(prefix_parts):])


def to_canonical(path: str) -> Optional[str]:
    """The share-relative form of *path*, or None if it is not on the share.

    The remainder keeps the case it was typed in -- only the mount is matched
    loosely -- so the stored path still reads the way the person wrote it.
    """
    if not path or not configured():
        return None
    # The server's own view of the share counts as a mount whether or not it
    # is listed as one: a path this server produced -- translated out of a
    # creation log, say -- is on the share by construction, and should not
    # depend on the config happening to repeat server_root under mounts.
    for mount in [*CONFIG.mounts, Mount(WINDOWS, CONFIG.server_root)]:
        remainder = _strip_prefix(path, mount.prefix)
        if remainder is None:
            continue
        # A path that climbs out of the share with .. is not on the share,
        # whatever its prefix said.
        normalised = posixpath.normpath(remainder)
        if normalised in (".", "") or normalised.startswith(".."):
            return None
        return normalised
    return None


def to_local(canonical: str) -> str:
    """The path this server opens to read a canonical path's file."""
    if not configured():
        return canonical
    root = CONFIG.server_root
    if _WINDOWS_PATH.match(root):
        return ntpath.join(root, canonical.replace("/", "\\"))
    return posixpath.join(root, canonical)


def to_display(canonical: str, flavour: str = WINDOWS) -> str:
    """A canonical path written the way a *flavour* machine wants to see it.

    Where a flavour has several mounts configured the first wins, so the order
    in share.json decides what people are shown -- put the spelling you want
    read first. Falls back to the server's own view when that flavour has no
    mount at all, so an unrecognised browser gets a usable path rather than a
    bare fragment.
    """
    if not configured():
        return canonical
    mount = next((m for m in CONFIG.mounts if m.os == flavour), None)
    if mount is None:
        return to_local(canonical)
    if mount.os == WINDOWS:
        return ntpath.join(mount.prefix, canonical.replace("/", "\\"))
    return posixpath.join(mount.prefix, canonical)


def is_absolute(path: str) -> bool:
    """Whether *path* names a machine's own root -- a drive letter, a UNC
    server, or a leading slash. What is left is relative, and the only
    relative paths here are canonical ones."""
    return bool(_WINDOWS_PATH.match(path) or path.startswith(("/", "\\")))


def resolve(path: str) -> str:
    """The local path for something that may be canonical or may be absolute.

    Paths arriving from a form are whatever the person pasted; paths read from
    the catalog are canonical. This takes either, so a caller that cannot tell
    them apart does not have to.
    """
    if not path:
        return path
    if not is_absolute(path):
        return to_local(path)  # already canonical
    canonical = to_canonical(path)
    return to_local(canonical) if canonical is not None else path


def describe_mounts() -> str:
    """Every prefix the share is reachable by, for an error message.

    All of them, not one per flavour: someone whose path was refused needs to
    know what *is* accepted, and a Windows user who reaches the share by a
    mapped drive is not helped by being shown only the UNC path.
    """
    return ", ".join(dict.fromkeys(mount.prefix for mount in CONFIG.mounts))
