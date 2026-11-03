"""Saving a library whose file the server cannot read.

Two different things, with two different answers.

**No hash, no entry.** The hash is the library's identity: it is how the same
file is recognised somewhere else, how a duplicate is matched, how a deleted
entry is offered back, and what a check that a library has not been altered
compares against. Nothing re-reads a file once it is catalogued, so an entry
saved without one can never acquire one -- a row that looks like a library and
is not one. That is refused outright.

**A file that will not parse** has been read: it is really there and it has a
hash, so the entry can still be recognised later. What it costs is everything
the library itself would have said. That is worth a question, not a refusal --
a format SpecVault does not know yet is not the same as a file that is gone.
"""
import pytest

READABLE = (
    "Modified.Sequence\tStripped.Sequence\tProtein.Group\tPrecursor.Charge\n"
    "AC(UniMod:4)DEK\tACDEK\tP1\t2\n"
)


@pytest.fixture
def nowhere(tmp_path):
    """A path with nothing behind it."""
    return str(tmp_path / "not-mounted.tsv")


@pytest.fixture
def gibberish(tmp_path):
    """A real file that is not a spectral library."""
    path = tmp_path / "notes.tsv"
    path.write_text("just some notes I left here", encoding="utf-8")
    return str(path)


def save(client, path, **extra):
    return client.post("/libraries/", json={"path": path, "creator": "ZC", **extra})


# ----------------------------------------------------------- no file, no entry

def test_a_path_with_no_file_is_refused(client, nowhere):
    refused = save(client, nowhere)
    assert refused.status_code == 400
    assert "no file at" in refused.json()["detail"]


def test_the_refusal_says_why_it_matters(client, nowhere):
    """Not "that path is wrong" -- the path may be perfectly right and the
    share simply away. What cannot be done is catalogue it."""
    assert "hash" in save(client, nowhere).json()["detail"]


def test_nothing_is_catalogued(client, nowhere):
    save(client, nowhere)
    assert client.get("/libraries/").json() == []


def test_it_cannot_be_confirmed_past(client, nowhere):
    """The one refusal in the save path with no way through. An entry with no
    hash would stay that way for good."""
    assert save(client, nowhere, save_unreadable=True).status_code == 400


# -------------------------------------------------- a file that will not parse

def test_an_unparseable_file_asks_first(client, gibberish):
    refused = save(client, gibberish)
    assert refused.status_code == 409
    detail = refused.json()["detail"]
    assert detail["unreadable"] is True
    assert "could not be read as a spectral library" in detail["message"]


def test_it_says_what_the_entry_will_not_hold(client, gibberish):
    detail = save(client, gibberish).json()["detail"]
    assert detail["missing"]
    assert any("counts" in line for line in detail["missing"])


def test_nothing_is_catalogued_until_it_is_answered(client, gibberish):
    save(client, gibberish)
    assert client.get("/libraries/").json() == []


def test_confirming_saves_it(client, gibberish):
    saved = save(client, gibberish, save_unreadable=True)
    assert saved.status_code == 201
    assert saved.json()["precursors"] is None
    assert saved.json()["mod_details"] is None


def test_the_entry_still_has_an_identity(client, gibberish):
    """Why this one is allowed at all: the file is real and hashed, so it can
    be recognised again even though nothing could be read out of it."""
    saved = save(client, gibberish, save_unreadable=True).json()
    assert saved["content_hash"]
    assert saved["path_exists"] is True


def test_the_same_file_is_still_caught_as_a_duplicate(client, gibberish, tmp_path):
    """The hash does its job, which is the whole argument for allowing it."""
    save(client, gibberish, save_unreadable=True)

    copy = tmp_path / "copy.tsv"
    copy.write_text("just some notes I left here", encoding="utf-8")
    again = save(client, str(copy), save_unreadable=True)
    assert again.status_code == 409
    assert again.json()["detail"]["library_id"] == 1


def test_it_is_recorded_like_any_other_save(client, gibberish):
    saved = save(client, gibberish, save_unreadable=True).json()
    history = client.get(f"/libraries/{saved['id']}/history").json()
    assert history[0]["event"] == "catalogued"


# ------------------------------------------------------- a readable file is fine

def test_a_readable_library_needs_no_confirming(client, tmp_path):
    path = tmp_path / "real.tsv"
    path.write_text(READABLE, encoding="utf-8")
    saved = save(client, str(path))
    assert saved.status_code == 201
    assert saved.json()["precursors"] == 1


def test_confirming_a_readable_one_changes_nothing(client, tmp_path):
    """save_unreadable is an answer to a question, not a mode: it does not
    stop the file being read when the file can be read."""
    path = tmp_path / "real.tsv"
    path.write_text(READABLE, encoding="utf-8")
    saved = save(client, str(path), save_unreadable=True)
    assert saved.json()["precursors"] == 1
    assert saved.json()["mod_details"]


def test_a_file_that_goes_away_afterwards_keeps_its_entry(client, tmp_path):
    """The rule is about cataloguing, not about staying catalogued. A library
    that moves is something to notice, not something to lose."""
    path = tmp_path / "real.tsv"
    path.write_text(READABLE, encoding="utf-8")
    saved = save(client, str(path)).json()

    path.unlink()
    after = client.get(f"/libraries/{saved['id']}").json()
    assert after["path_exists"] is False
    assert after["content_hash"] == saved["content_hash"]
