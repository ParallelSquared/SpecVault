"""Reading a path is refused as early as saving one is.

Analyze and Hash open whatever path they are handed. Checking the share only
at Save meant two things: somebody could fill in a whole form for a library
they were never going to be allowed to catalogue, and the endpoints would read
any file the service account could reach -- answering, to anyone who could
reach the server, whether a given path exists and what it hashes to.
"""
import pytest

from app import share

WINDOWS_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"

OFF_SHARE = [
    r"C:\Windows\win.ini",
    r"C:\Users\someone\Desktop\secret.tsv",
    "/etc/passwd",
    r"\\OTHER-SERVER\Share\thing.tsv",
]


@pytest.fixture
def lab(tmp_path, monkeypatch):
    monkeypatch.setattr(share, "CONFIG", share.ShareConfig(
        server_root=str(tmp_path),
        mounts=[
            share.Mount(share.WINDOWS, r"\\PTI\Lab"),
            share.Mount(share.WINDOWS, "L:"),
            share.Mount(share.MAC, "/Volumes/Lab"),
        ],
    ))
    return tmp_path


def write_library(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "Modified.Sequence\tStripped.Sequence\tProtein.Group\tPrecursor.Charge\n"
        "AC(UniMod:4)DEK\tACDEK\tP1;P2\t2\n",
        encoding="utf-8",
    )
    return path


# ------------------------------------------------- refused before any reading

@pytest.mark.parametrize("path", OFF_SHARE)
def test_analyze_refuses_a_path_off_the_share(client, lab, path):
    response = client.post("/libraries/analyze", json={"path": path})
    assert response.status_code == 400
    assert "not on the lab share" in response.json()["detail"]


@pytest.mark.parametrize("path", OFF_SHARE)
def test_hashing_refuses_a_path_off_the_share(client, lab, path):
    response = client.post("/libraries/hash-file", json={"path": path})
    assert response.status_code == 400
    assert "not on the lab share" in response.json()["detail"]


def test_reading_a_log_off_the_share_is_refused(client, lab):
    response = client.post("/libraries/analyze-log",
                           json={"path": r"C:\Users\someone\report.log.txt"})
    assert response.status_code == 400
    assert "not on the lab share" in response.json()["detail"]


def test_a_log_given_to_analyze_is_checked_too(client, lab):
    write_library(lab / "Libraries" / "foo.tsv")
    response = client.post("/libraries/analyze", json={
        "path": r"L:\Libraries\foo.tsv",
        "creation_log_path": r"C:\Users\someone\report.log.txt",
    })
    assert response.status_code == 400
    assert "creation_log_path" in response.json()["detail"]


def test_an_existing_file_off_the_share_is_refused_not_hashed(client, lab, tmp_path):
    """The point is that nothing is read. A real file that exists and could be
    hashed is still refused, so the endpoint says nothing about it."""
    outside = tmp_path.parent / "outside.tsv"
    write_library(outside)
    response = client.post("/libraries/hash-file", json={"path": str(outside)})
    assert response.status_code == 400
    assert "content_hash" not in response.json()


def test_a_missing_path_off_the_share_gives_the_same_answer(client, lab):
    """Refused before existence is tested, so the response cannot be used to
    find out what is on the server's disk.

    The message does echo the path back -- that is the caller's own input, and
    seeing how it was read is useful when a pasted path has stray quotes. What
    it must not do is differ according to whether the file is there.
    """
    real = client.post("/libraries/hash-file", json={"path": r"C:\Windows\win.ini"})
    unreal = client.post("/libraries/hash-file", json={"path": r"C:\Windows\nope.ini"})

    assert real.status_code == unreal.status_code == 400
    said = lambda response, path: response.json()["detail"].replace(path, "<path>")  # noqa: E731
    assert said(real, r"C:\Windows\win.ini") == said(unreal, r"C:\Windows\nope.ini")


# ----------------------------------------------------- the share still works

def test_analyze_still_works_on_the_share(client, lab):
    write_library(lab / "Libraries" / "foo.tsv")
    response = client.post("/libraries/analyze", json={"path": r"L:\Libraries\foo.tsv"})
    assert response.status_code == 200
    assert response.json()["precursors"] == 1


def test_hashing_still_works_on_the_share(client, lab):
    write_library(lab / "Libraries" / "foo.tsv")
    response = client.post("/libraries/hash-file",
                           json={"path": "/Volumes/Lab/Libraries/foo.tsv"})
    assert response.status_code == 200
    assert response.json()["content_hash"]


def test_a_catalog_with_no_share_reads_anything(client, lab, monkeypatch, tmp_path):
    """A deployment that has not set a share up is not suddenly unable to
    analyse its libraries."""
    monkeypatch.setattr(share, "CONFIG", share.ShareConfig("", [], require_on_share=False))
    anywhere = write_library(tmp_path.parent / "anywhere.tsv")
    response = client.post("/libraries/hash-file", json={"path": str(anywhere)})
    assert response.status_code == 200


def test_an_open_share_reads_anything(client, lab, monkeypatch, tmp_path):
    """require_on_share: false is the deliberate way to allow it."""
    monkeypatch.setattr(share, "CONFIG", share.CONFIG._replace(require_on_share=False))
    anywhere = write_library(tmp_path.parent / "open.tsv")
    response = client.post("/libraries/hash-file", json={"path": str(anywhere)})
    assert response.status_code == 200
