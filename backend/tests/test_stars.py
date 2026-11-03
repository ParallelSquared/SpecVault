"""Stars: somebody saying "I use this one".

One per name per library. What they answer is which of a few hundred
libraries people actually use -- and, through who gave them, who to ask about
one. Nothing double-checks the name; a stray star changes nothing.
"""
import pytest

ZC = {"X-SpecVault-User": "ZC"}
HS = {"X-SpecVault-User": "HS"}
NO_NAME = {"X-SpecVault-User": ""}


@pytest.fixture
def library(make_library):
    return make_library()


def star(client, library_id, who):
    response = client.put(f"/libraries/{library_id}/star", headers=who)
    assert response.status_code == 200, response.text
    return response.json()


def unstar(client, library_id, who):
    response = client.delete(f"/libraries/{library_id}/star", headers=who)
    assert response.status_code == 200, response.text
    return response.json()


def test_a_new_library_has_none(library):
    assert library["stars"] == 0
    assert library["starred_by"] == []


def test_starring_counts_and_names_who(client, library):
    body = star(client, library["id"], ZC)
    assert body["stars"] == 1
    assert body["starred_by"] == ["ZC"]


def test_each_person_counts_once(client, library):
    star(client, library["id"], ZC)
    body = star(client, library["id"], ZC)
    assert body["stars"] == 1


def test_people_are_listed_in_the_order_they_starred(client, library):
    star(client, library["id"], ZC)
    body = star(client, library["id"], HS)
    assert body["starred_by"] == ["ZC", "HS"]


def test_unstarring_takes_only_your_own(client, library):
    star(client, library["id"], ZC)
    star(client, library["id"], HS)
    body = unstar(client, library["id"], ZC)
    assert body["starred_by"] == ["HS"]


def test_unstarring_what_you_never_starred_is_fine(client, library):
    """PUT and DELETE rather than a toggle: sending either twice leaves the
    star where it was meant to be."""
    assert unstar(client, library["id"], ZC)["stars"] == 0


def test_the_listing_carries_them(client, library):
    star(client, library["id"], ZC)
    listed = client.get("/libraries/").json()[0]
    assert (listed["stars"], listed["starred_by"]) == (1, ["ZC"])


def test_a_star_needs_a_name(client, library):
    assert client.put(f"/libraries/{library['id']}/star", headers=NO_NAME).status_code == 400


def test_a_star_is_not_history(client, library):
    """Nothing about the library changed. Recorded there, stars would bury
    the edits the history exists for."""
    star(client, library["id"], ZC)
    history = client.get(f"/libraries/{library['id']}/history").json()
    assert [row["event"] for row in history] == ["catalogued"]


def test_a_deleted_library_cannot_be_starred(client, library):
    client.delete(f"/libraries/{library['id']}")
    assert client.put(f"/libraries/{library['id']}/star", headers=ZC).status_code == 404


def test_restoring_brings_its_stars_back(client, library):
    """Deleting keeps everything, stars included."""
    star(client, library["id"], ZC)
    star(client, library["id"], HS)
    client.delete(f"/libraries/{library['id']}")
    restored = client.post(f"/libraries/{library['id']}/restore").json()
    assert restored["starred_by"] == ["ZC", "HS"]


def test_an_unknown_library_is_a_404(client):
    assert client.put("/libraries/99999/star", headers=ZC).status_code == 404
