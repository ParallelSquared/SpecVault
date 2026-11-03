"""Adding a file the catalog already holds.

Two things were wrong with how this went. Nothing said the file was known
until Save, so a whole form could be filled in -- and auto-filled, which means
reading and hashing the library -- before the news arrived. And restoring the
entry it matched threw that form away without saying so, bringing back the
metadata the person had quite possibly just deleted the library to replace.
"""
import os

import pytest

import libraries

AS_ADA = {"X-SpecVault-User": "Ada"}


def write_library(path, peptide="PEPTIDK"):
    """One precursor, two fragments. *peptide* varies the contents, and so
    the hash -- two libraries with the same bytes are one library."""
    return str(libraries.write(path, peptide))


@pytest.fixture
def library(client, tmp_path):
    response = client.post("/libraries/", headers=AS_ADA, json={
        "path": write_library(tmp_path / "foo.tsv"),
        "creator": "Ada", "project": "Mapping", "tags": ["old"], "notes": "as it was",
    })
    assert response.status_code == 201, response.text
    return response.json()


def analyse(client, path):
    response = client.post("/libraries/analyze", json={"path": path})
    assert response.status_code == 200, response.text
    return response.json()


# -------------------------------------------------- said at Auto-fill, not Save

def test_autofill_says_the_file_is_already_catalogued(client, library, tmp_path):
    found = analyse(client, str(tmp_path / "foo.tsv"))["duplicate"]
    assert found["library_id"] == library["id"]
    assert found["deleted"] is False
    assert found["already_recorded"] is True


def test_autofill_says_when_the_entry_was_deleted(client, library, tmp_path):
    client.delete(f"/libraries/{library['id']}")
    found = analyse(client, str(tmp_path / "foo.tsv"))["duplicate"]
    assert found["library_id"] == library["id"]
    assert found["deleted"] is True
    assert "deleted" in found["message"].lower()


def test_autofill_notices_the_same_bytes_at_a_new_path(client, library, tmp_path):
    """The copy case: same file, somewhere the entry does not list yet."""
    copy = write_library(tmp_path / "elsewhere" / "foo.tsv")
    found = analyse(client, copy)["duplicate"]
    assert found["library_id"] == library["id"]
    assert found["already_recorded"] is False


def test_autofill_of_an_unknown_file_says_nothing(client, library, tmp_path):
    other = write_library(tmp_path / "other.tsv", "ACDEK")
    assert analyse(client, other)["duplicate"] is None


def test_autofill_still_analyses_the_file(client, library, tmp_path):
    """A heads-up, not a refusal: everything else still comes back."""
    body = analyse(client, str(tmp_path / "foo.tsv"))
    assert body["precursors"] == 1
    assert body["duplicate"] is not None


# ------------------------------------------------- restoring keeps what it is told

class TestRestoringWithDetails:
    """What the person typed wins, for somebody who deleted a library because
    it was catalogued wrongly and has just filled the form in again."""

    @pytest.fixture
    def deleted(self, client, library):
        client.delete(f"/libraries/{library['id']}", headers=AS_ADA)
        return library

    def test_the_typed_details_replace_the_old(self, client, deleted, tmp_path):
        restored = client.post(f"/libraries/{deleted['id']}/restore", headers=AS_ADA, json={
            "path": str(tmp_path / "foo.tsv"),
            "details": {"creator": "Grace", "project": "Astral", "tags": ["new"]},
        })
        assert restored.status_code == 200
        assert restored.json()["project"] == "Astral"
        assert restored.json()["creator"] == "Grace"
        assert restored.json()["tags"] == ["new"]

    def test_what_was_not_sent_is_left_alone(self, client, deleted, tmp_path):
        """A PATCH-shaped body: absent is not the same as cleared, so a field
        the form never touched keeps what it had."""
        restored = client.post(f"/libraries/{deleted['id']}/restore", headers=AS_ADA, json={
            "path": str(tmp_path / "foo.tsv"), "details": {"project": "Astral"},
        })
        assert restored.json()["notes"] == "as it was"

    def test_it_is_back_in_the_catalog(self, client, deleted, tmp_path):
        client.post(f"/libraries/{deleted['id']}/restore", headers=AS_ADA, json={
            "path": str(tmp_path / "foo.tsv"), "details": {"project": "Astral"},
        })
        assert len(client.get("/libraries/").json()) == 1

    def test_the_history_shows_what_changed(self, client, deleted, tmp_path):
        client.post(f"/libraries/{deleted['id']}/restore", headers=AS_ADA, json={
            "path": str(tmp_path / "foo.tsv"), "details": {"project": "Astral"},
        })
        newest, before = client.get(f"/libraries/{deleted['id']}/history").json()[:2]
        assert newest["event"] == "restored"
        assert before["data"]["project"] == "Mapping"
        assert newest["data"]["project"] == "Astral"


class TestRestoringAsItWas:
    @pytest.fixture
    def deleted(self, client, library):
        client.delete(f"/libraries/{library['id']}", headers=AS_ADA)
        return library

    def test_no_body_keeps_everything(self, client, deleted):
        restored = client.post(f"/libraries/{deleted['id']}/restore", headers=AS_ADA)
        assert restored.status_code == 200
        assert restored.json()["project"] == "Mapping"
        assert restored.json()["notes"] == "as it was"

    def test_a_path_with_no_details_keeps_everything(self, client, deleted, tmp_path):
        restored = client.post(f"/libraries/{deleted['id']}/restore", headers=AS_ADA, json={
            "path": str(tmp_path / "foo.tsv"), "details": None,
        })
        assert restored.json()["project"] == "Mapping"


# ------------------------------------------------- the path is kept either way

class TestWhereTheFileIsNow:
    """The path is a fact about the file, not a judgement about the entry.

    A library is usually re-added because something about it moved, so an
    entry restored pointing only at somewhere the file has left is no use --
    and losing the path the person had just given was the quietest part of
    the old behaviour.
    """

    @pytest.fixture
    def moved(self, client, library, tmp_path):
        """Deleted, and its file now lives somewhere else."""
        client.delete(f"/libraries/{library['id']}", headers=AS_ADA)
        (tmp_path / "foo.tsv").unlink()
        return library, write_library(tmp_path / "moved" / "foo.tsv")

    def test_restoring_as_it_was_still_records_the_new_path(self, client, moved):
        library, now_at = moved
        restored = client.post(f"/libraries/{library['id']}/restore", headers=AS_ADA, json={
            "path": now_at,
        })
        assert now_at in [p["display"] for p in restored.json()["path_details"]]

    def test_restoring_with_details_records_it_too(self, client, moved):
        library, now_at = moved
        restored = client.post(f"/libraries/{library['id']}/restore", headers=AS_ADA, json={
            "path": now_at, "details": {"project": "Astral"},
        })
        assert now_at in [p["display"] for p in restored.json()["path_details"]]

    def test_the_library_is_found_again(self, client, moved):
        """The point of it: restored at the old path alone it would come back
        marked missing, pointing at a file that is not there."""
        library, now_at = moved
        restored = client.post(f"/libraries/{library['id']}/restore", headers=AS_ADA, json={
            "path": now_at,
        })
        assert restored.json()["path_exists"] is True

    def test_a_path_it_already_lists_is_not_doubled(self, client, library, tmp_path):
        client.delete(f"/libraries/{library['id']}", headers=AS_ADA)
        restored = client.post(f"/libraries/{library['id']}/restore", headers=AS_ADA, json={
            "path": str(tmp_path / "foo.tsv"),
        })
        assert len(restored.json()["path_details"]) == 1

    def test_a_path_another_library_owns_is_refused(self, client, library, make_library, tmp_path):
        client.delete(f"/libraries/{library['id']}", headers=AS_ADA)
        theirs = make_library(write_library(tmp_path / "theirs.tsv", "ACDEK"))

        refused = client.post(f"/libraries/{library['id']}/restore", headers=AS_ADA, json={
            "path": theirs["path"],
        })
        assert refused.status_code == 409
        # and nothing happened: not restored, not moved
        assert client.get(f"/libraries/{library['id']}").status_code == 404


# ----------------------------------------- the file is read again on restore

class TestRestoringReadsTheFileAgain:
    """What the file says is worked out from the file, not brought back.

    The counts, mod table and library details are stored when a library is
    catalogued. Restoring used to return exactly what was stored -- so a
    library first catalogued before an improvement to the reading (the
    N-terminal labels FragPipe writes behind an underscore were the case)
    came back without it, however many times it was deleted and re-added.
    """

    @pytest.fixture
    def stale(self, client, tmp_path):
        """A deleted library whose stored reading is out of date, the way one
        catalogued by an older SpecVault would be."""
        path = str(libraries.write(tmp_path / "lib.tsv", "AC(UniMod:4)DEK", "PEPTIDK"))
        created = client.post("/libraries/", headers=AS_ADA,
                              json={"path": path, "creator": "Ada"}).json()

        from app import models
        from app.database import SessionLocal
        with SessionLocal() as session:
            row = session.get(models.Library, created["id"])
            row.mod_details, row.precursors, row.proteins, row.library_stats = [], 999, 999, None
            session.commit()

        client.delete(f"/libraries/{created['id']}", headers=AS_ADA)
        return created["id"], path

    def restore(self, client, library_id, **body):
        response = client.post(f"/libraries/{library_id}/restore", headers=AS_ADA, json=body)
        assert response.status_code == 200, response.text
        return response.json()

    def test_restoring_with_details_reads_it_again(self, client, stale):
        library_id, path = stale
        back = self.restore(client, library_id, path=path, details={"project": "Astral"})
        assert (back["precursors"], back["proteins"]) == (2, 2)
        assert {m["name"] for m in back["mod_details"]} == {"UniMod:4"}
        assert back["library_stats"]

    def test_restoring_as_it_was_reads_it_again_too(self, client, stale):
        """"As it was" is about what people typed. The reading of the file is
        nobody's judgement, so there is no old version of it worth keeping."""
        library_id, path = stale
        back = self.restore(client, library_id, path=path)
        assert back["precursors"] == 2
        assert back["mod_details"]

    def test_with_no_path_given_its_own_paths_are_read(self, client, stale):
        library_id, _ = stale
        assert self.restore(client, library_id)["precursors"] == 2

    def test_a_file_that_is_gone_keeps_the_old_reading(self, client, stale):
        """An unreachable file is no reason to throw away a reading that may
        well be right -- better stale than empty."""
        library_id, path = stale
        os.remove(path)
        assert self.restore(client, library_id)["precursors"] == 999

    def test_only_a_file_with_the_same_bytes_is_read(self, client, stale, tmp_path):
        """A restore says where the library is; a path to some other file is
        not this library's to describe. Its own copy is read instead."""
        library_id, _ = stale
        other = str(libraries.write(tmp_path / "other.tsv", "ELVISLIVESK", "ANDK", "MORK"))
        back = self.restore(client, library_id, path=other)
        assert back["precursors"] == 2
