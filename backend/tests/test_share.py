"""Paths from Windows, Mac and Linux have to land on the same stored value.

If they do not, the catalog grows a second entry every time someone on a
different machine adds a library that is already in it -- which is the failure
the share-relative path exists to prevent.
"""
import json

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

    def test_server_root_can_be_left_out(self, tmp_path):
        """And normally is: the server finds its own way in from the mounts."""
        good = tmp_path / "share.json"
        good.write_text(
            json.dumps({"mounts": [{"os": share.this_os(), "prefix": str(tmp_path)}]}),
            encoding="utf-8",
        )
        assert share.load(str(good)).server_root == str(tmp_path)

    def test_a_server_root_given_is_used_as_given(self, tmp_path):
        good = tmp_path / "share.json"
        good.write_text(json.dumps({
            "server_root": "/srv/lab",
            "mounts": [{"os": share.this_os(), "prefix": str(tmp_path)}],
        }), encoding="utf-8")
        assert share.load(str(good)).server_root == "/srv/lab"


class TestFindingTheServersOwnMount:
    """One share.json for every host: each server takes the first mount for
    its own kind of machine that is really there."""

    MOUNTS = [
        share.Mount(share.WINDOWS, r"\\PTI\Lab"),
        share.Mount(share.WINDOWS, "L:"),
        share.Mount(share.MAC, "/Volumes/Lab"),
        share.Mount(share.LINUX, "/home/ip2/syno_mount/lab"),
    ]

    def detect(self, machine, there):
        return share.detect_root(self.MOUNTS, machine=machine, exists=lambda p: p in there)

    def test_the_linux_box_finds_its_mount(self):
        assert self.detect(share.LINUX, {"/home/ip2/syno_mount/lab"}) == "/home/ip2/syno_mount/lab"

    def test_a_windows_pc_finds_the_unc_path(self):
        assert self.detect(share.WINDOWS, {r"\\PTI\Lab", "L:"}) == r"\\PTI\Lab"

    def test_a_windows_service_without_l_drive_still_finds_the_share(self):
        """The old trap: a mapped drive is a logged-in session's, and a
        service has none. Listed first or not, a missing L: is passed over."""
        mounts = [share.Mount(share.WINDOWS, "L:"), share.Mount(share.WINDOWS, r"\\PTI\Lab")]
        found = share.detect_root(mounts, machine=share.WINDOWS, exists=lambda p: p == r"\\PTI\Lab")
        assert found == r"\\PTI\Lab"

    def test_another_kinds_mount_is_never_chosen(self):
        """A Linux server never picks a Windows path just because it exists."""
        assert self.detect(share.LINUX, {r"\\PTI\Lab", "/home/ip2/syno_mount/lab"}) \
            == "/home/ip2/syno_mount/lab"

    def test_a_share_that_is_away_falls_back_to_the_first_listed(self):
        """Down at startup is not misconfigured: point at the right place and
        find the files once the share is back."""
        assert self.detect(share.WINDOWS, set()) == r"\\PTI\Lab"

    def test_no_mount_for_this_kind_of_machine_means_no_share(self):
        mounts = [share.Mount(share.WINDOWS, r"\\PTI\Lab")]
        assert share.detect_root(mounts, machine=share.LINUX, exists=lambda p: True) == ""


class TestTheLinuxBox:
    """The real Linux mount, end to end."""

    @pytest.fixture(autouse=True)
    def linux(self, monkeypatch):
        mounts = share.load().mounts  # the shipped share.json
        monkeypatch.setattr(share, "CONFIG", share.ShareConfig(
            server_root=share.detect_root(
                mounts, machine=share.LINUX, exists=lambda p: p == "/home/ip2/syno_mount/lab"),
            mounts=mounts,
        ))

    def test_its_paths_are_the_same_library_as_windows_paths(self):
        assert share.to_canonical("/home/ip2/syno_mount/lab/ZC/paths.txt") == "ZC/paths.txt"
        assert share.to_canonical(r"\\PTI\Lab\ZC\paths.txt") == "ZC/paths.txt"

    def test_it_opens_files_through_its_own_mount(self):
        assert share.to_local("ZC/paths.txt") == "/home/ip2/syno_mount/lab/ZC/paths.txt"

    def test_linux_users_are_shown_that_mount(self):
        assert share.to_display("ZC/paths.txt", share.LINUX) == "/home/ip2/syno_mount/lab/ZC/paths.txt"


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


class TestADriveLetterGetsItsSeparator:
    r"""`L:` names a drive, not a root, so joining to it needs the separator.

    "L:Libraries\foo.tsv" is a legal Windows path meaning foo.tsv under
    whatever the current directory on L: happens to be -- a different file,
    and usually no file at all. ntpath.join produces exactly that, and it
    stayed hidden because the share lists a UNC path first and only the first
    mount of a flavour is ever displayed.
    """

    @pytest.fixture
    def drive_first(self, monkeypatch):
        monkeypatch.setattr(share, "CONFIG", share.ShareConfig(
            server_root="L:",
            mounts=[share.Mount(share.WINDOWS, "L:")],
        ))

    def test_display_keeps_the_root(self, drive_first):
        assert share.to_display("Libraries/foo.tsv", share.WINDOWS) == r"L:\Libraries\foo.tsv"

    def test_the_server_opens_the_right_file(self, drive_first):
        assert share.to_local("Libraries/foo.tsv") == r"L:\Libraries\foo.tsv"

    def test_what_is_shown_can_be_pasted_back(self, drive_first):
        shown = share.to_display("Libraries/foo.tsv", share.WINDOWS)
        assert share.to_canonical(shown) == "Libraries/foo.tsv"

    def test_a_unc_prefix_is_left_as_it_was(self, monkeypatch):
        monkeypatch.setattr(share, "CONFIG", share.ShareConfig(
            server_root=r"\\PTI\Lab",
            mounts=[share.Mount(share.WINDOWS, r"\\PTI\Lab")],
        ))
        assert share.to_display("Libraries/foo.tsv", share.WINDOWS) == (
            r"\\PTI\Lab\Libraries\foo.tsv"
        )
