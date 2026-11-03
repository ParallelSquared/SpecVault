"""Deleting a library takes it out of the catalog without losing it.

The row stays, marked with the day it went. That is what makes a wrong click
recoverable, and it has one consequence worth testing from several angles: a
deleted entry still owns its content hash and its paths, so adding the same
file again finds it rather than starting a second entry -- and is offered it
back instead of being told the path belongs to a library it cannot see.
"""
import pytest

import libraries


def write_library(path, peptide="PEPTIDK"):
    """One precursor, two fragments. *peptide* varies the contents, and so
    the hash -- two libraries with the same bytes are one library."""
    return str(libraries.write(path, peptide))


@pytest.fixture
def library(client, make_library, tmp_path):
    """One catalogued library whose file really exists, so it has a hash."""
    return make_library(write_library(tmp_path / "foo.tsv"))


# ------------------------------------------------------- out of the catalog

def test_deleting_takes_it_out_of_the_listing(client, library):
    assert client.delete(f"/libraries/{library['id']}").status_code == 204
    assert client.get("/libraries/").json() == []


def test_the_total_counts_only_what_is_listed(client, make_library, tmp_path):
    kept = make_library(write_library(tmp_path / "kept.tsv", "PEPTIDK"))
    make_library(write_library(tmp_path / "gone.tsv", "ACDEK"))
    assert client.get("/libraries/").headers["X-Total-Count"] == "2"

    client.delete(f"/libraries/{kept['id']}")
    response = client.get("/libraries/")
    # The header is what tells a client its page is the whole catalog; left
    # counting deleted rows it would report a library the listing never sends.
    assert response.headers["X-Total-Count"] == "1"
    assert len(response.json()) == 1


def test_a_deleted_library_cannot_be_fetched(client, library):
    client.delete(f"/libraries/{library['id']}")
    assert client.get(f"/libraries/{library['id']}").status_code == 404


def test_deleting_it_twice_is_a_404(client, library):
    assert client.delete(f"/libraries/{library['id']}").status_code == 204
    # Not in the catalog, so not there to delete -- and the date it went stays
    # the date it first went.
    assert client.delete(f"/libraries/{library['id']}").status_code == 404


def test_its_values_stop_filling_the_dropdowns(client, make_library, tmp_path):
    doomed = make_library(write_library(tmp_path / "a.tsv"), creator="Ada", project="Retired")
    make_library(write_library(tmp_path / "b.tsv", "ACDEK"), creator="Grace", project="Live")

    client.delete(f"/libraries/{doomed['id']}")
    options = client.get("/libraries/options").json()
    assert options["creator"] == ["Grace"]
    assert options["project"] == ["Live"]


def test_editing_a_deleted_library_is_a_404(client, library):
    client.delete(f"/libraries/{library['id']}")
    patched = client.patch(f"/libraries/{library['id']}", json={"creator": "someone"})
    assert patched.status_code == 404


def test_adding_a_path_to_a_deleted_library_is_a_404(client, library, tmp_path):
    client.delete(f"/libraries/{library['id']}")
    added = client.post(f"/libraries/{library['id']}/paths",
                        json={"path": write_library(tmp_path / "copy.tsv")})
    assert added.status_code == 404


def test_the_file_is_left_alone(client, library, tmp_path):
    """SpecVault only ever reads library files. Deleting an entry is a catalog
    operation, and the thing on the share stays exactly where it was."""
    client.delete(f"/libraries/{library['id']}")
    assert (tmp_path / "foo.tsv").exists()


# -------------------------------------------------------------- and back in

def test_restoring_puts_it_back(client, library):
    client.delete(f"/libraries/{library['id']}")
    restored = client.post(f"/libraries/{library['id']}/restore")
    assert restored.status_code == 200
    assert restored.json()["id"] == library["id"]
    assert [row["id"] for row in client.get("/libraries/").json()] == [library["id"]]


def test_it_comes_back_whole(client, make_library, tmp_path):
    """Nothing was thrown away, so nothing has to be typed again."""
    before = make_library(write_library(tmp_path / "foo.tsv"),
                          creator="Ada", project="Mapping", tags=["dia"], notes="keep me")
    client.delete(f"/libraries/{before['id']}")
    after = client.post(f"/libraries/{before['id']}/restore").json()

    for field in ("creator", "project", "tags", "notes", "content_hash", "precursors", "paths"):
        assert after[field] == before[field], field


def test_restoring_one_that_is_not_deleted_changes_nothing(client, library):
    """A second click on Restore is not an error."""
    assert client.post(f"/libraries/{library['id']}/restore").status_code == 200
    assert len(client.get("/libraries/").json()) == 1


def test_restoring_something_that_never_existed_is_a_404(client):
    assert client.post("/libraries/99999/restore").status_code == 404


# ------------------------------------------------- adding the file back again

def test_adding_the_file_again_finds_the_deleted_entry(client, library, tmp_path):
    """The whole point of keeping the row: the catalog can say "you deleted
    this" instead of either making a duplicate or refusing unhelpfully."""
    client.delete(f"/libraries/{library['id']}")

    again = client.post("/libraries/", json={
        "path": str(tmp_path / "foo.tsv"), "creator": "tester",
    })
    assert again.status_code == 409
    detail = again.json()["detail"]
    assert detail["library_id"] == library["id"]
    assert detail["deleted"] is True
    assert "deleted" in detail["message"].lower()


def test_a_live_entry_is_preferred_over_a_deleted_one(client, make_library, tmp_path):
    """Two entries can share a hash once one of them has been deleted and the
    file added again. The one in the catalog is the one to point at."""
    first = make_library(write_library(tmp_path / "one.tsv"))
    client.delete(f"/libraries/{first['id']}")
    client.post(f"/libraries/{first['id']}/restore")

    # a second entry for the same bytes at a different path, via the deleted route
    second = make_library(write_library(tmp_path / "two.tsv", "ACDEK"))
    client.delete(f"/libraries/{second['id']}")

    again = client.post("/libraries/", json={
        "path": str(tmp_path / "one.tsv"), "creator": "tester",
    })
    assert again.json()["detail"]["library_id"] == first["id"]
    assert again.json()["detail"]["deleted"] is False


def test_a_path_held_by_a_deleted_entry_says_so(client, make_library, tmp_path):
    """Different bytes at a path a deleted library holds: the hash does not
    match, so it is the path check that refuses, and it has to explain itself
    or the message names a library nobody can find."""
    library = make_library(write_library(tmp_path / "foo.tsv"))
    client.delete(f"/libraries/{library['id']}")

    write_library(tmp_path / "foo.tsv", "ACDEK")  # same path, new contents
    refused = client.post("/libraries/", json={
        "path": str(tmp_path / "foo.tsv"), "creator": "tester",
    })
    assert refused.status_code == 409
    assert "deleted on" in refused.json()["detail"]


def test_restoring_from_the_refusal_is_the_way_back(client, library, tmp_path):
    """What the UI does with the 409 above: the library returns, with its path
    and everything else intact."""
    client.delete(f"/libraries/{library['id']}")
    detail = client.post("/libraries/", json={
        "path": str(tmp_path / "foo.tsv"), "creator": "tester",
    }).json()["detail"]

    restored = client.post(f"/libraries/{detail['library_id']}/restore")
    assert restored.status_code == 200
    assert restored.json()["path"] == library["path"]
    assert len(client.get("/libraries/").json()) == 1
