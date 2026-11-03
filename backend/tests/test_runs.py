"""The raw files a library was built from: stored like any path, never refused.

A run on the share is stored share-relative, so every machine is shown it the
way that machine writes paths -- a run saved from Windows used to reach a Mac
as \\\\PTI\\Lab\\..., which a Mac cannot paste anywhere. A run elsewhere, on
an instrument's own disk, is kept exactly as written: it records where the
data came from, and a library is not refused because its runs have moved.
"""
import pytest

import libraries
from app import share

WINDOWS_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
MAC_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"

ON_SHARE = r"\\PTI\Lab\JMod\Data\run1.raw"
ON_INSTRUMENT = r"D:\Xcalibur\data\run2.raw"


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
    libraries.write(tmp_path / "Libraries" / "foo.tsv", "PEPTIDK")
    return tmp_path


def save(client, runs, ua=WINDOWS_UA):
    response = client.post("/libraries/", headers={"User-Agent": ua}, json={
        "path": r"L:\Libraries\foo.tsv", "creator": "ZC", "source_runs": runs,
    })
    assert response.status_code == 201, response.text
    return response.json()


def shown_to(client, library_id, ua):
    return client.get(f"/libraries/{library_id}", headers={"User-Agent": ua}).json()


# ------------------------------------------------------------------ stored

def test_a_run_on_the_share_is_stored_share_relative(client, lab):
    assert save(client, [ON_SHARE])["source_runs"] == ["JMod/Data/run1.raw"]


def test_every_spelling_of_one_run_is_stored_the_same(client, lab):
    """And so is one run, not three."""
    saved = save(client, [
        r"\\PTI\Lab\JMod\Data\run1.raw",
        r"L:\JMod\Data\run1.raw",
        "/Volumes/Lab/JMod/Data/run1.raw",
    ])
    assert saved["source_runs"] == ["JMod/Data/run1.raw"]


def test_a_run_off_the_share_is_kept_as_written(client, lab):
    """Never refused: the library is still saved, and the run still says
    where the data came from."""
    assert save(client, [ON_INSTRUMENT])["source_runs"] == [ON_INSTRUMENT]


def test_pasted_quotes_and_spaces_are_cleaned(client, lab):
    """Windows' "Copy as path" wraps each one in quotes."""
    saved = save(client, [f'  "{ON_SHARE}"  ', f'"{ON_INSTRUMENT}"', "   "])
    assert saved["source_runs"] == ["JMod/Data/run1.raw", ON_INSTRUMENT]


def test_no_runs_is_none(client, lab):
    assert save(client, [])["source_runs"] is None


# ------------------------------------------------------------------- shown

def test_windows_is_shown_a_windows_path(client, lab):
    library = save(client, [ON_SHARE])
    assert shown_to(client, library["id"], WINDOWS_UA)["display_source_runs"] == [ON_SHARE]


def test_a_mac_is_shown_a_mac_path(client, lab):
    """The point of it. Saved from Windows, read on a Mac."""
    library = save(client, [ON_SHARE], ua=WINDOWS_UA)
    assert shown_to(client, library["id"], MAC_UA)["display_source_runs"] == [
        "/Volumes/Lab/JMod/Data/run1.raw",
    ]


def test_a_run_off_the_share_is_shown_as_written_to_everyone(client, lab):
    """Not dressed up with the share's prefix -- there is no share path for it
    to have, and "/Volumes/Lab/D:\\Xcalibur\\..." opens nothing."""
    library = save(client, [ON_INSTRUMENT])
    for ua in (WINDOWS_UA, MAC_UA):
        assert shown_to(client, library["id"], ua)["display_source_runs"] == [ON_INSTRUMENT]


# ---------------------------------------------------- edited, restored, history

def test_an_edit_stores_runs_the_same_way(client, lab):
    library = save(client, [])
    edited = client.patch(f"/libraries/{library['id']}", json={
        "source_runs": ["/Volumes/Lab/JMod/Data/run1.raw"],
    }).json()
    assert edited["source_runs"] == ["JMod/Data/run1.raw"]


def test_restoring_with_details_stores_runs_the_same_way(client, lab):
    library = save(client, [])
    client.delete(f"/libraries/{library['id']}")
    restored = client.post(f"/libraries/{library['id']}/restore", json={
        "details": {"source_runs": [r"L:\JMod\Data\run1.raw"]},
    }).json()
    assert restored["source_runs"] == ["JMod/Data/run1.raw"]


def test_the_history_shows_runs_for_the_machine_asking(client, lab):
    library = save(client, [ON_SHARE])
    history = client.get(f"/libraries/{library['id']}/history",
                         headers={"User-Agent": MAC_UA}).json()
    assert history[0]["data"]["source_runs"] == ["/Volumes/Lab/JMod/Data/run1.raw"]
