"""Taking back one of the places a library is recorded.

A library's file is often copied, and a copy that is moved or deleted leaves
the entry claiming it is still there. Without a way to say "that one is gone",
the files panel marks it missing forever.

Nothing on the share is touched: a path is only ever a record of where a file
was.
"""
import pytest

import libraries


def write_library(path, peptide="PEPTIDK"):
    """One precursor, two fragments. *peptide* varies the contents, and so
    the hash -- two libraries with the same bytes are one library."""
    return str(libraries.write(path, peptide))


@pytest.fixture
def two_places(client, make_library, tmp_path):
    """One library, recorded in two places, the second of which has gone."""
    lib = make_library(write_library(tmp_path / "foo.tsv"))
    gone = write_library(tmp_path / "archive" / "foo-copy.tsv")
    client.post(f"/libraries/{lib['id']}/paths", json={"path": gone})
    (tmp_path / "archive" / "foo-copy.tsv").unlink()
    return client.get(f"/libraries/{lib['id']}").json()


def paths_of(client, library_id):
    return client.get(f"/libraries/{library_id}").json()["path_details"]


# --------------------------------------------------------------- removing one

def test_the_missing_copy_can_go(client, two_places):
    missing = next(p for p in two_places["path_details"] if not p["exists"])
    removed = client.delete(f"/libraries/{two_places['id']}/paths/{missing['id']}")

    assert removed.status_code == 200
    assert [p["path"] for p in removed.json()["path_details"]] == [two_places["path"]]


def test_the_entry_stops_looking_broken(client, two_places):
    """The point of it: one copy gone meant a permanent warning on a library
    that is perfectly fine."""
    missing = next(p for p in two_places["path_details"] if not p["exists"])
    client.delete(f"/libraries/{two_places['id']}/paths/{missing['id']}")

    after = client.get(f"/libraries/{two_places['id']}").json()
    assert after["path_exists"] is True
    assert all(p["exists"] for p in after["path_details"])


def test_the_file_that_is_still_there_is_untouched(client, two_places, tmp_path):
    missing = next(p for p in two_places["path_details"] if not p["exists"])
    client.delete(f"/libraries/{two_places['id']}/paths/{missing['id']}")
    assert (tmp_path / "foo.tsv").exists()


def test_a_path_that_does_exist_can_also_go(client, make_library, tmp_path):
    """Not restricted to missing files. A path pasted by mistake may point at
    something real, and that is exactly the one worth taking back."""
    lib = make_library(write_library(tmp_path / "foo.tsv"))
    wrong = write_library(tmp_path / "somebody-elses.tsv", "ACDEK")
    client.post(f"/libraries/{lib['id']}/paths", json={"path": wrong})

    extra = paths_of(client, lib["id"])[1]
    assert extra["exists"] is True
    assert client.delete(f"/libraries/{lib['id']}/paths/{extra['id']}").status_code == 200


def test_the_path_is_free_for_another_library(client, two_places, tmp_path):
    """It was unique across the catalog while it was recorded; letting go of
    it has to let go of that too."""
    missing = next(p for p in two_places["path_details"] if not p["exists"])
    client.delete(f"/libraries/{two_places['id']}/paths/{missing['id']}")

    freed = write_library(tmp_path / "archive" / "foo-copy.tsv", "ACDEK")
    again = client.post("/libraries/", json={"path": freed, "creator": "tester"})
    assert again.status_code == 201


# ------------------------------------------------------------ what cannot go

def test_the_only_path_cannot_go(client, make_library, tmp_path):
    """An entry with no paths says nothing about where its library is, and is
    the shape that broke the listing once already."""
    lib = make_library(write_library(tmp_path / "foo.tsv"))
    only = paths_of(client, lib["id"])[0]

    refused = client.delete(f"/libraries/{lib['id']}/paths/{only['id']}")
    assert refused.status_code == 409
    assert "only place" in refused.json()["detail"]
    assert len(paths_of(client, lib["id"])) == 1


def test_the_only_path_cannot_go_even_when_its_file_is_missing(
        client, make_library, tmp_path):
    """The tempting case, and still no: an entry pointing at a file that has
    moved is something to fix, not something to empty out."""
    lib = make_library(write_library(tmp_path / "foo.tsv"))
    (tmp_path / "foo.tsv").unlink()
    only = paths_of(client, lib["id"])[0]
    assert client.delete(f"/libraries/{lib['id']}/paths/{only['id']}").status_code == 409


def test_another_librarys_path_is_not_removable_here(client, make_library, tmp_path):
    """Path ids are global, so the endpoint has to check the path belongs to
    the library in the URL rather than trusting the number."""
    mine = make_library(write_library(tmp_path / "mine.tsv"))
    yours = make_library(write_library(tmp_path / "yours.tsv", "ACDEK"))
    client.post(f"/libraries/{mine['id']}/paths",
                json={"path": write_library(tmp_path / "mine-copy.tsv")})

    theirs = paths_of(client, yours["id"])[0]
    refused = client.delete(f"/libraries/{mine['id']}/paths/{theirs['id']}")
    assert refused.status_code == 404
    assert len(paths_of(client, yours["id"])) == 1


def test_a_path_that_never_existed_is_a_404(client, two_places):
    assert client.delete(f"/libraries/{two_places['id']}/paths/99999").status_code == 404


def test_a_deleted_library_has_no_paths_to_remove(client, two_places):
    missing = next(p for p in two_places["path_details"] if not p["exists"])
    client.delete(f"/libraries/{two_places['id']}")
    removed = client.delete(f"/libraries/{two_places['id']}/paths/{missing['id']}")
    assert removed.status_code == 404


# ------------------------------------------------------------------- recorded

def test_it_goes_in_the_history(client, two_places):
    missing = next(p for p in two_places["path_details"] if not p["exists"])
    client.delete(f"/libraries/{two_places['id']}/paths/{missing['id']}")

    newest = client.get(f"/libraries/{two_places['id']}/history").json()[0]
    assert newest["event"] == "path removed"
    assert newest["changed_by"] == "tester"


def test_the_history_says_which_path_went(client, two_places):
    """What makes this safe to allow for any path rather than only missing
    ones: the snapshot either side says what was taken away."""
    missing = next(p for p in two_places["path_details"] if not p["exists"])
    client.delete(f"/libraries/{two_places['id']}/paths/{missing['id']}")

    newest, before = client.get(f"/libraries/{two_places['id']}/history").json()[:2]
    assert missing["path"] in before["data"]["paths"]
    assert missing["path"] not in newest["data"]["paths"]


def test_a_refused_removal_records_nothing(client, make_library, tmp_path):
    lib = make_library(write_library(tmp_path / "foo.tsv"))
    only = paths_of(client, lib["id"])[0]
    client.delete(f"/libraries/{lib['id']}/paths/{only['id']}")
    assert len(client.get(f"/libraries/{lib['id']}/history").json()) == 1
