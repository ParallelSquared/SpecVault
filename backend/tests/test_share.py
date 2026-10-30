"""Paths from Windows, Mac and Linux have to land on the same stored value.

If they do not, the catalog grows a second entry every time someone on a
different machine adds a library that is already in it -- which is the failure
the share-relative path exists to prevent.
"""
import pytest

from app import share


@pytest.fixture(autouse=True)
def configured(monkeypatch):
    """The share as a deployment would configure it."""
    monkeypatch.setattr(share, "CONFIG", share.ShareConfig(
        server_root=r"\\PTI\Lab",
        mounts=[
            share.Mount(share.WINDOWS, r"\\PTI\Lab"),
            share.Mount(share.WINDOWS, "L:"),
            share.Mount(share.MAC, "/Volumes/Lab"),
            share.Mount(share.LINUX, "/mnt/lab"),
        ],
    ))


# Every way the same file is written, on every machine someone might use
SAME_FILE = [
    r"\\PTI\Lab\Libraries\foo.tsv",
    r"L:\Libraries\foo.tsv",
    "/Volumes/Lab/Libraries/foo.tsv",
    "/mnt/lab/Libraries/foo.tsv",
    # Windows accepts forward slashes, and people paste them
    "//PTI/Lab/Libraries/foo.tsv",
    "L:/Libraries/foo.tsv",
]


@pytest.mark.parametrize("path", SAME_FILE)
def test_every_mount_gives_the_same_canonical_path(path):
    assert share.to_canonical(path) == "Libraries/foo.tsv"


def test_all_of_them_agree_with_each_other():
    """Stated directly, because this is the whole point of the module."""
    assert len({share.to_canonical(p) for p in SAME_FILE}) == 1


def test_the_mount_matches_case_insensitively_but_the_rest_is_kept():
    """The share is served from Windows, so the mount's case means nothing --
    but the stored path should still read the way it was typed."""
    assert share.to_canonical(r"l:\Libraries\Foo.tsv") == "Libraries/Foo.tsv"
    assert share.to_canonical(r"\\pti\lab\Libraries\Foo.tsv") == "Libraries/Foo.tsv"


def test_a_path_off_the_share_is_refused():
    assert share.to_canonical(r"C:\Users\someone\Desktop\foo.tsv") is None
    assert share.to_canonical("/Users/someone/Desktop/foo.tsv") is None
    assert share.to_canonical(r"\\OTHER\Share\foo.tsv") is None


def test_a_near_miss_on_the_mount_is_refused():
    """L:\\ is the share; LAB:\\ and \\\\PTI\\Lab2 are not, and a prefix
    compared as text rather than as whole folders would accept them."""
    assert share.to_canonical(r"\\PTI\Lab2\foo.tsv") is None
    assert share.to_canonical("/Volumes/Lab2/foo.tsv") is None


def test_climbing_out_of_the_share_is_refused():
    """A prefix on the share does not make the path on the share."""
    assert share.to_canonical(r"L:\Libraries\..\..\Windows\system.ini") is None
    assert share.to_canonical("/Volumes/Lab/../Secrets/keys.txt") is None


def test_the_share_root_itself_is_not_a_library():
    assert share.to_canonical("L:") is None
    assert share.to_canonical("/Volumes/Lab") is None


def test_dots_inside_the_share_are_resolved_not_refused():
    assert share.to_canonical(r"L:\Libraries\sub\..\foo.tsv") == "Libraries/foo.tsv"


def test_local_path_is_the_servers_own_view():
    assert share.to_local("Libraries/foo.tsv") == r"\\PTI\Lab\Libraries\foo.tsv"


def test_display_renders_for_the_viewers_machine():
    canonical = "Libraries/foo.tsv"
    assert share.to_display(canonical, share.WINDOWS) == r"\\PTI\Lab\Libraries\foo.tsv"
    assert share.to_display(canonical, share.MAC) == "/Volumes/Lab/Libraries/foo.tsv"
    assert share.to_display(canonical, share.LINUX) == "/mnt/lab/Libraries/foo.tsv"


def test_display_falls_back_to_the_server_mount_for_an_unknown_flavour():
    assert share.to_display("Libraries/foo.tsv", "bsd") == r"\\PTI\Lab\Libraries\foo.tsv"


def test_round_trip_through_every_flavour():
    """Rendering for a machine and reading it back gives the same path."""
    canonical = "Libraries/deep/nested/foo.tsv"
    for flavour in (share.WINDOWS, share.MAC, share.LINUX):
        assert share.to_canonical(share.to_display(canonical, flavour)) == canonical


def test_resolve_takes_either_a_canonical_or_a_pasted_path():
    assert share.resolve("Libraries/foo.tsv") == r"\\PTI\Lab\Libraries\foo.tsv"
    assert share.resolve(r"L:\Libraries\foo.tsv") == r"\\PTI\Lab\Libraries\foo.tsv"


def test_a_path_off_the_share_resolves_to_itself():
    """So that a catalog configured without a share, or an entry saved before
    one was, still opens the file it names."""
    assert share.resolve(r"C:\elsewhere\foo.tsv") == r"C:\elsewhere\foo.tsv"


class TestWithoutAShare:
    """A server with no share.json still works; it just stores what it is given."""

    @pytest.fixture(autouse=True)
    def unconfigured(self, monkeypatch):
        monkeypatch.setattr(share, "CONFIG", share.ShareConfig("", [], require_on_share=False))

    def test_nothing_is_canonicalised(self):
        assert share.to_canonical(r"L:\Libraries\foo.tsv") is None

    def test_paths_pass_through_untouched(self):
        assert share.resolve(r"L:\Libraries\foo.tsv") == r"L:\Libraries\foo.tsv"
        assert share.to_local("Libraries/foo.tsv") == "Libraries/foo.tsv"


class TestConfigLoading:
    def test_a_missing_file_leaves_the_catalog_without_a_share(self, tmp_path):
        config = share.load(str(tmp_path / "nothing.json"))
        assert config.server_root == ""
        assert config.require_on_share is False

    def test_a_malformed_file_does_not_take_the_server_down(self, tmp_path):
        bad = tmp_path / "share.json"
        bad.write_text("{not json", encoding="utf-8")
        assert share.load(str(bad)).mounts == []

    def test_a_real_file_is_read(self, tmp_path):
        good = tmp_path / "share.json"
        good.write_text(
            '{"server_root": "/srv/lab", "mounts": [{"os": "linux", "prefix": "/srv/lab"}]}',
            encoding="utf-8",
        )
        config = share.load(str(good))
        assert config.server_root == "/srv/lab"
        assert config.mounts == [share.Mount("linux", "/srv/lab")]
        assert config.require_on_share is True

    def test_the_shipped_config_is_valid(self):
        """share.json in the repo must parse, or a fresh deployment silently
        comes up with no share at all."""
        config = share.load()
        assert config.server_root, "shipped share.json did not load"
        assert config.mounts


class TestPosixServer:
    """The server does not have to be the Windows box; only the share is."""

    @pytest.fixture(autouse=True)
    def posix(self, monkeypatch):
        monkeypatch.setattr(share, "CONFIG", share.ShareConfig(
            server_root="/mnt/lab",
            mounts=[share.Mount(share.WINDOWS, "L:"), share.Mount(share.LINUX, "/mnt/lab")],
        ))

    def test_local_path_uses_posix_separators(self):
        assert share.to_local("Libraries/foo.tsv") == "/mnt/lab/Libraries/foo.tsv"

    def test_a_windows_path_still_canonicalises(self):
        assert share.to_canonical(r"L:\Libraries\foo.tsv") == "Libraries/foo.tsv"
