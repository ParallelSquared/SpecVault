"""Every change to a library is recorded, with who says they made it.

A snapshot of the typed fields per event, so comparing two neighbours gives
what changed. The point is the old value: it is the one thing an edit destroys
that nothing else in the catalog can recover.

Who is self-reported -- there are no accounts -- so these tests are about it
being carried and kept, not about it being true.
"""
import pytest

import libraries

AS_ADA = {"X-SpecVault-User": "Ada"}
AS_GRACE = {"X-SpecVault-User": "Grace"}


def write_library(path, peptide="PEPTIDK"):
    """One precursor, two fragments. *peptide* varies the contents, and so
    the hash -- two libraries with the same bytes are one library."""
    return str(libraries.write(path, peptide))


@pytest.fixture
def library(client, tmp_path):
    response = client.post("/libraries/", headers=AS_ADA, json={
        "path": write_library(tmp_path / "foo.tsv"), "creator": "Ada", "project": "Mapping",
    })
    assert response.status_code == 201, response.text
    return response.json()


def history(client, library_id):
    response = client.get(f"/libraries/{library_id}/history")
    assert response.status_code == 200, response.text
    return response.json()


# ------------------------------------------------------------- what is kept

def test_cataloguing_is_the_first_entry(client, library):
    rows = history(client, library["id"])
    assert len(rows) == 1
    assert rows[0]["event"] == "catalogued"
    assert rows[0]["changed_by"] == "Ada"
    assert rows[0]["data"]["creator"] == "Ada"
    assert rows[0]["data"]["project"] == "Mapping"


def test_an_edit_keeps_the_value_it_replaced(client, library):
    """The whole reason for the table: after this, "Mapping" exists nowhere
    else in the catalog."""
    client.patch(f"/libraries/{library['id']}", headers=AS_GRACE,
                 json={"project": "Astral"})

    newest, first = history(client, library["id"])
    assert newest["event"] == "edited"
    assert newest["changed_by"] == "Grace"
    assert newest["data"]["project"] == "Astral"
    assert first["data"]["project"] == "Mapping"


def test_newest_comes_first(client, library):
    for project in ("One", "Two", "Three"):
        client.patch(f"/libraries/{library['id']}", json={"project": project})
    assert [row["data"]["project"] for row in history(client, library["id"])] == [
        "Three", "Two", "One", "Mapping",
    ]


def test_where_the_library_is_is_part_of_the_snapshot(client, library, tmp_path):
    client.post(f"/libraries/{library['id']}/paths", headers=AS_ADA,
                json={"path": write_library(tmp_path / "copy.tsv")})

    newest = history(client, library["id"])[0]
    assert newest["event"] == "path added"
    assert len(newest["data"]["paths"]) == 2


def test_deleting_and_restoring_are_part_of_the_story(client, library):
    client.delete(f"/libraries/{library['id']}", headers=AS_GRACE)
    client.post(f"/libraries/{library['id']}/restore", headers=AS_ADA)

    rows = history(client, library["id"])
    assert [(row["event"], row["changed_by"]) for row in rows] == [
        ("restored", "Ada"), ("deleted", "Grace"), ("catalogued", "Ada"),
    ]


def test_the_history_of_a_deleted_library_is_still_readable(client, library):
    """It is no longer in the catalog, but "who took this out, and when" is
    exactly the question someone will have about it."""
    client.delete(f"/libraries/{library['id']}", headers=AS_GRACE)
    assert client.get(f"/libraries/{library['id']}").status_code == 404
    assert history(client, library["id"])[0]["event"] == "deleted"


def test_pointing_an_entry_at_another_file_is_its_own_event(client, library, tmp_path):
    """An edit that changes the bytes is not housekeeping: every count
    recorded before it was about a different file."""
    other = write_library(tmp_path / "other.tsv", "ACDEK")
    client.patch(f"/libraries/{library['id']}", json={"path": other})
    assert history(client, library["id"])[0]["event"] == "file changed"


def test_moving_to_the_same_bytes_elsewhere_is_an_ordinary_edit(client, library, tmp_path):
    same = write_library(tmp_path / "moved.tsv")  # same contents, new place
    client.patch(f"/libraries/{library['id']}", json={"path": same})
    assert history(client, library["id"])[0]["event"] == "edited"


# -------------------------------------------------------- what is not kept

def test_an_edit_that_changes_nothing_is_not_recorded(client, library):
    """Saving a form without touching it is not an event, and a history full
    of those is one nobody reads."""
    client.patch(f"/libraries/{library['id']}", json={"project": "Mapping"})
    client.patch(f"/libraries/{library['id']}", json={})
    assert len(history(client, library["id"])) == 1


def test_restoring_something_that_is_not_deleted_is_not_recorded(client, library):
    client.post(f"/libraries/{library['id']}/restore")
    assert len(history(client, library["id"])) == 1


def test_a_refused_edit_leaves_no_trace(client, library, tmp_path, make_library):
    """The history row and the change it describes go together or not at
    all."""
    other = make_library(write_library(tmp_path / "taken.tsv", "ACDEK"))
    refused = client.patch(f"/libraries/{library['id']}", json={"path": other["path"]})
    assert refused.status_code == 409
    assert len(history(client, library["id"])) == 1


def test_a_refused_save_records_nothing(client, library, tmp_path):
    again = client.post("/libraries/", json={
        "path": str(tmp_path / "foo.tsv"), "creator": "someone",
    })
    assert again.status_code == 409
    assert len(history(client, library["id"])) == 1


# ------------------------------------------------------------------- who

NO_NAME = {"X-SpecVault-User": ""}


def test_cataloguing_without_a_name_is_allowed(client, tmp_path):
    """Adding a library overwrites nothing, and `creator` already names a
    person -- so a bulk import is not locked out of the one job it has."""
    created = client.post("/libraries/", headers=NO_NAME, json={
        "path": write_library(tmp_path / "anon.tsv"), "creator": "Ada",
    })
    assert created.status_code == 201
    assert history(client, created.json()["id"])[0]["changed_by"] is None


class TestChangingSomethingNeedsAName:
    """Altering an entry that already exists is refused without one.

    An edit destroys the value it replaces, and that value survives only in
    the history -- which is worth little if half of it says "someone". The
    refusal is about a request saying nothing, not about it being true: there
    are no accounts, and this is not pretending to be one.
    """

    def test_an_edit_is_refused(self, client, library):
        refused = client.patch(f"/libraries/{library['id']}", headers=NO_NAME,
                               json={"project": "Astral"})
        assert refused.status_code == 400
        assert "recorded against a name" in refused.json()["detail"]

    def test_the_edit_did_not_happen(self, client, library):
        client.patch(f"/libraries/{library['id']}", headers=NO_NAME,
                     json={"project": "Astral"})
        assert client.get(f"/libraries/{library['id']}").json()["project"] == "Mapping"
        assert len(history(client, library["id"])) == 1

    def test_a_delete_is_refused(self, client, library):
        refused = client.delete(f"/libraries/{library['id']}", headers=NO_NAME)
        assert refused.status_code == 400
        assert len(client.get("/libraries/").json()) == 1

    def test_a_restore_is_refused(self, client, library):
        client.delete(f"/libraries/{library['id']}")
        refused = client.post(f"/libraries/{library['id']}/restore", headers=NO_NAME)
        assert refused.status_code == 400

    def test_adding_a_path_is_refused(self, client, library, tmp_path):
        refused = client.post(f"/libraries/{library['id']}/paths", headers=NO_NAME,
                              json={"path": write_library(tmp_path / "copy.tsv")})
        assert refused.status_code == 400

    def test_removing_a_path_is_refused(self, client, library, tmp_path):
        client.post(f"/libraries/{library['id']}/paths",
                    json={"path": write_library(tmp_path / "copy.tsv")})
        extra = client.get(f"/libraries/{library['id']}").json()["path_details"][1]
        refused = client.delete(f"/libraries/{library['id']}/paths/{extra['id']}",
                                headers=NO_NAME)
        assert refused.status_code == 400

    def test_a_name_of_only_spaces_counts_as_nothing(self, client, library):
        refused = client.patch(f"/libraries/{library['id']}",
                               headers={"X-SpecVault-User": "   "},
                               json={"project": "Astral"})
        assert refused.status_code == 400


def test_a_blank_name_on_a_create_is_the_same_as_none(client, tmp_path):
    created = client.post("/libraries/", headers={"X-SpecVault-User": "   "}, json={
        "path": write_library(tmp_path / "blank.tsv"), "creator": "Ada",
    })
    assert history(client, created.json()["id"])[0]["changed_by"] is None


def test_a_long_name_is_cut_rather_than_refused(client, tmp_path):
    """Nobody is kept out by the name field -- it only has to be readable."""
    created = client.post("/libraries/", headers={"X-SpecVault-User": "n" * 500}, json={
        "path": write_library(tmp_path / "long.tsv"), "creator": "Ada",
    })
    assert len(history(client, created.json()["id"])[0]["changed_by"]) == 60


def test_the_history_of_a_library_that_never_existed_is_a_404(client):
    assert client.get("/libraries/99999/history").status_code == 404


# ------------------------------------------------------------ what it covers

def test_every_field_someone_can_edit_is_snapshotted(client, library):
    """A field added to the form but missing from the snapshot would be
    editable with no record of what it used to be -- which is the one failure
    this table exists to prevent, and the one that cannot be fixed later."""
    from app import schemas
    from app.routers.libraries import VERSIONED_FIELDS

    editable = set(schemas.LibraryUpdate.model_fields) - {"path"}
    assert editable == set(VERSIONED_FIELDS)
    assert set(history(client, library["id"])[0]["data"]) == editable | {"paths"}


class TestPathsReadAsPaths:
    """The history shows paths the way the asking machine writes them.

    They are stored share-relative, so a history left raw reads
    "JMod/.../lib.parquet" -- a path nobody can open, and not the one that was
    pasted in.
    """

    WINDOWS_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    MAC_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"

    @pytest.fixture
    def on_share(self, client, tmp_path, monkeypatch):
        from app import share
        monkeypatch.setattr(share, "CONFIG", share.ShareConfig(
            server_root=str(tmp_path),
            mounts=[share.Mount(share.WINDOWS, "L:"),
                    share.Mount(share.MAC, "/Volumes/Lab")],
        ))
        write_library(tmp_path / "Libraries" / "foo.tsv")
        response = client.post("/libraries/", headers={**AS_ADA, "User-Agent": self.WINDOWS_UA},
                               json={"path": r"L:\Libraries\foo.tsv", "creator": "Ada"})
        assert response.status_code == 201, response.text
        return response.json()

    def test_windows_sees_a_windows_path(self, client, on_share):
        rows = client.get(f"/libraries/{on_share['id']}/history",
                          headers={"User-Agent": self.WINDOWS_UA}).json()
        assert rows[0]["data"]["paths"] == [r"L:\Libraries\foo.tsv"]

    def test_a_mac_sees_a_mac_path(self, client, on_share):
        rows = client.get(f"/libraries/{on_share['id']}/history",
                          headers={"User-Agent": self.MAC_UA}).json()
        assert rows[0]["data"]["paths"] == ["/Volumes/Lab/Libraries/foo.tsv"]

    def test_the_stored_snapshot_keeps_the_canonical_spelling(self, client, on_share):
        """Rendering happens on the way out. Stored canonical is what makes a
        snapshot comparable whatever machine wrote it."""
        from app.database import SessionLocal
        from app import models
        with SessionLocal() as session:
            row = session.query(models.LibraryVersion).first()
            assert row.data["paths"] == ["Libraries/foo.tsv"]
