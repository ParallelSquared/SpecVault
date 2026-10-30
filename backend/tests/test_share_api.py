"""The API with a lab share configured.

The rest of the suite runs without one (see conftest.no_share), because it is
about reading libraries rather than about where they live. These tests are the
other half: that a library added from any machine lands on one stored path,
that one off the share is refused, and that everyone is shown paths their own
machine understands.
"""
import pytest

from app import share

WINDOWS_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
MAC_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
LINUX_UA = "Mozilla/5.0 (X11; Linux x86_64)"


@pytest.fixture
def lab(tmp_path, monkeypatch):
    """A share whose server view is tmp_path, reachable the four usual ways."""
    monkeypatch.setattr(share, "CONFIG", share.ShareConfig(
        server_root=str(tmp_path),
        # As share.json orders them: the spelling to show first, then the
        # other ways people reach the same share. server_root is understood
        # without being listed.
        mounts=[
            share.Mount(share.WINDOWS, r"\\PTI\Lab"),
            share.Mount(share.WINDOWS, "L:"),
            share.Mount(share.MAC, "/Volumes/Lab"),
            share.Mount(share.LINUX, "/mnt/lab"),
        ],
    ))
    return tmp_path


def write_library(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "Modified.Sequence\tStripped.Sequence\tProtein.Group\tPrecursor.Charge\n"
        "AC(UniMod:4)DEK\tACDEK\tP1;P2\t2\n"
        "PEPTIDK\tPEPTIDK\tP3\t2\n",
        encoding="utf-8",
    )
    return path


def add(client, path, ua=WINDOWS_UA, **fields):
    return client.post(
        "/libraries/",
        json={"path": path, "creator": "tester", **fields},
        headers={"User-Agent": ua},
    )


# ------------------------------------------------- one library, any machine

def test_paths_from_every_machine_store_the_same_way(client, lab):
    write_library(lab / "Libraries" / "foo.tsv")
    response = add(client, r"L:\Libraries\foo.tsv")
    assert response.status_code == 201
    assert response.json()["path"] == "Libraries/foo.tsv"


@pytest.mark.parametrize("pasted", [
    r"\\PTI\Lab\Libraries\foo.tsv",
    r"L:\Libraries\foo.tsv",
    "/Volumes/Lab/Libraries/foo.tsv",
    "/mnt/lab/Libraries/foo.tsv",
])
def test_the_same_library_from_a_second_machine_is_a_duplicate(client, lab, pasted):
    """The unique constraint on path only catches this because both spellings
    reduce to one. Before, each machine got its own row for the same file."""
    write_library(lab / "Libraries" / "foo.tsv")
    assert add(client, r"L:\Libraries\foo.tsv").status_code == 201

    second = add(client, pasted)
    assert second.status_code == 409, second.text
    assert "already exists" in second.json()["detail"]


def test_the_catalog_holds_one_row_for_it(client, lab):
    write_library(lab / "Libraries" / "foo.tsv")
    add(client, r"L:\Libraries\foo.tsv")
    add(client, "/Volumes/Lab/Libraries/foo.tsv")
    assert client.get("/libraries/").headers["X-Total-Count"] == "1"


# ------------------------------------------------------------- off the share

def test_a_library_off_the_share_is_refused(client, lab):
    response = add(client, r"C:\Users\someone\Desktop\foo.tsv")
    assert response.status_code == 400
    assert "not on the lab share" in response.json()["detail"]


def test_the_refusal_says_what_a_good_path_looks_like(client, lab):
    detail = add(client, "/home/someone/foo.tsv").json()["detail"]
    assert "/Volumes/Lab" in detail and "L:" in detail


def test_a_path_climbing_out_of_the_share_is_refused(client, lab):
    response = add(client, r"L:\Libraries\..\..\Windows\win.ini")
    assert response.status_code == 400


def test_a_creation_log_off_the_share_is_refused(client, lab):
    write_library(lab / "Libraries" / "foo.tsv")
    response = add(client, r"L:\Libraries\foo.tsv",
                   creation_log_path=r"C:\Users\someone\report.log.txt")
    assert response.status_code == 400
    assert "creation_log_path" in response.json()["detail"]


def test_source_runs_are_left_alone(client, lab):
    """Raw files may sit on an instrument's own storage, or be long deleted.
    Refusing the library because of where its runs were would help nobody."""
    write_library(lab / "Libraries" / "foo.tsv")
    response = add(client, r"L:\Libraries\foo.tsv",
                   source_runs=[r"D:\instrument\run1.raw"])
    assert response.status_code == 201
    assert response.json()["source_runs"] == [r"D:\instrument\run1.raw"]


def test_the_share_can_be_opened_up(client, lab, monkeypatch):
    monkeypatch.setattr(share, "CONFIG", share.CONFIG._replace(require_on_share=False))
    assert add(client, r"C:\elsewhere\foo.tsv").status_code == 201


# --------------------------------------------------------- shown back per OS

@pytest.mark.parametrize("ua, expected", [
    (WINDOWS_UA, r"\\PTI\Lab\Libraries\foo.tsv"),
    (MAC_UA, "/Volumes/Lab/Libraries/foo.tsv"),
    (LINUX_UA, "/mnt/lab/Libraries/foo.tsv"),
])
def test_each_machine_is_shown_a_path_it_understands(client, lab, ua, expected):
    write_library(lab / "Libraries" / "foo.tsv")
    add(client, r"L:\Libraries\foo.tsv")
    listed = client.get("/libraries/", headers={"User-Agent": ua}).json()[0]
    assert listed["display_path"] == expected
    assert listed["path"] == "Libraries/foo.tsv"  # identity is unchanged


def test_an_unknown_browser_gets_the_servers_own_spelling(client, lab):
    write_library(lab / "Libraries" / "foo.tsv")
    add(client, r"L:\Libraries\foo.tsv")
    listed = client.get("/libraries/", headers={"User-Agent": "curl/8.0"}).json()[0]
    assert listed["display_path"].endswith(r"\Libraries\foo.tsv")


def test_a_single_library_is_rendered_too(client, lab):
    write_library(lab / "Libraries" / "foo.tsv")
    library_id = add(client, r"L:\Libraries\foo.tsv").json()["id"]
    got = client.get(f"/libraries/{library_id}", headers={"User-Agent": MAC_UA}).json()
    assert got["display_path"] == "/Volumes/Lab/Libraries/foo.tsv"


# ------------------------------------------------------- the file still reads

def test_the_file_behind_a_stored_path_is_found(client, lab):
    write_library(lab / "Libraries" / "foo.tsv")
    body = add(client, r"L:\Libraries\foo.tsv").json()
    assert body["path_exists"] is True
    assert body["file_size"] > 0
    # read through the share, not from the pasted path
    assert body["precursors"] == 2


def test_analyze_accepts_a_path_from_any_machine(client, lab):
    write_library(lab / "Libraries" / "foo.tsv")
    for pasted in (r"L:\Libraries\foo.tsv", "/Volumes/Lab/Libraries/foo.tsv"):
        response = client.post("/libraries/analyze", json={"path": pasted})
        assert response.status_code == 200, response.text
        assert response.json()["precursors"] == 2


def test_hashing_accepts_a_path_from_any_machine(client, lab):
    write_library(lab / "Libraries" / "foo.tsv")
    first = client.post("/libraries/hash-file", json={"path": r"L:\Libraries\foo.tsv"})
    second = client.post("/libraries/hash-file", json={"path": "/mnt/lab/Libraries/foo.tsv"})
    assert first.json()["content_hash"] == second.json()["content_hash"]


# ------------------------------------------------------------------- editing

def test_a_patched_path_is_stored_canonically(client, lab):
    write_library(lab / "Libraries" / "foo.tsv")
    write_library(lab / "Libraries" / "bar.tsv")
    library_id = add(client, r"L:\Libraries\foo.tsv").json()["id"]

    patched = client.patch(f"/libraries/{library_id}",
                           json={"path": "/Volumes/Lab/Libraries/bar.tsv"})
    assert patched.status_code == 200
    assert patched.json()["path"] == "Libraries/bar.tsv"
    assert patched.json()["path_exists"] is True


def test_a_patched_path_off_the_share_is_refused(client, lab):
    write_library(lab / "Libraries" / "foo.tsv")
    library_id = add(client, r"L:\Libraries\foo.tsv").json()["id"]
    patched = client.patch(f"/libraries/{library_id}", json={"path": r"C:\elsewhere\x.tsv"})
    assert patched.status_code == 400
