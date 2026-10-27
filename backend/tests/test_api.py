"""Tests for the /libraries API surface.

Each test runs against a temporary SQLite database (see conftest.py), never the
developer's real catalog.
"""
import hashlib

import pytest

TOTAL_HEADER = "X-Total-Count"


def seed(make_library, count, start=0):
    return [make_library(f"D:/libs/lib {i:04d}.tsv") for i in range(start, start + count)]


# ---------------------------------------------------------------- paging

def test_listing_reports_the_true_total(client, make_library):
    seed(make_library, 3)
    response = client.get("/libraries/")
    assert response.status_code == 200
    assert response.headers[TOTAL_HEADER] == "3"


def test_more_than_one_hundred_libraries_are_all_returned(client, make_library):
    """Regression: the endpoint defaulted to limit=100 and applied it silently,
    so a catalog of 120 libraries was indistinguishable from one of 100."""
    seed(make_library, 120)
    response = client.get("/libraries/")
    assert len(response.json()) == 120
    assert response.headers[TOTAL_HEADER] == "120"


def test_total_header_is_independent_of_page_size(client, make_library):
    seed(make_library, 25)
    response = client.get("/libraries/?limit=10")
    assert len(response.json()) == 10
    assert response.headers[TOTAL_HEADER] == "25"


def test_walking_pages_yields_every_row_exactly_once(client, make_library):
    seed(make_library, 25)
    collected, skip = [], 0
    while True:
        page = client.get(f"/libraries/?skip={skip}&limit=10").json()
        collected.extend(page)
        if len(page) < 10:
            break
        skip += 10
    ids = [row["id"] for row in collected]
    assert len(ids) == 25
    assert len(set(ids)) == 25


def test_pages_are_returned_in_a_stable_order(client, make_library):
    """Without an ORDER BY, OFFSET/LIMIT may repeat or skip rows between pages."""
    seed(make_library, 25)
    ids = [row["id"] for row in client.get("/libraries/?limit=25").json()]
    assert ids == sorted(ids)


@pytest.mark.parametrize(
    "query, reason",
    [
        ("?limit=99999", "above MAX_PAGE_SIZE"),
        ("?limit=0", "below one"),
        ("?skip=-1", "negative offset"),
    ],
)
def test_out_of_range_paging_is_rejected(client, query, reason):
    assert client.get(f"/libraries/{query}").status_code == 422, reason


def test_total_header_is_exposed_to_the_browser(client):
    """A header the browser cannot read is no use to the frontend."""
    response = client.get("/libraries/", headers={"Origin": "http://localhost:5173"})
    exposed = response.headers.get("access-control-expose-headers", "").lower()
    assert TOTAL_HEADER.lower() in exposed


# ---------------------------------------------------------------- CRUD

def test_create_returns_the_stored_library(client):
    response = client.post("/libraries/", json={"path": "D:/libs/a.tsv", "creator": "ZC"})
    assert response.status_code == 201
    body = response.json()
    assert body["path"] == "D:/libs/a.tsv"
    assert body["creator"] == "ZC"
    assert body["id"] > 0


def test_duplicate_path_is_a_conflict(client, make_library):
    make_library("D:/libs/same.tsv")
    response = client.post("/libraries/", json={"path": "D:/libs/same.tsv", "creator": "ZC"})
    assert response.status_code == 409


def test_get_by_id_round_trips(client, make_library):
    created = make_library("D:/libs/one.tsv")
    assert client.get(f"/libraries/{created['id']}").json()["path"] == "D:/libs/one.tsv"


def test_patch_updates_only_supplied_fields(client, make_library):
    created = make_library("D:/libs/one.tsv", creator="ZC", species="human")
    response = client.patch(f"/libraries/{created['id']}", json={"species": "mouse"})
    assert response.status_code == 200
    body = response.json()
    assert body["species"] == "mouse"
    assert body["creator"] == "ZC"


def test_delete_removes_the_library(client, make_library):
    created = make_library("D:/libs/gone.tsv")
    assert client.delete(f"/libraries/{created['id']}").status_code == 204
    assert client.get(f"/libraries/{created['id']}").status_code == 404


@pytest.mark.parametrize("method", ["get", "delete"])
def test_unknown_id_is_not_found(client, method):
    assert getattr(client, method)("/libraries/999999").status_code == 404


def test_options_route_is_not_parsed_as_an_id(client, make_library):
    """/options must stay declared above /{library_id} or it 422s as an int."""
    make_library("D:/libs/a.tsv", creator="ZC", species="human")
    response = client.get("/libraries/options")
    assert response.status_code == 200
    assert response.json()["creator"] == ["ZC"]


def test_options_flattens_list_valued_fields(client, make_library):
    make_library("D:/libs/a.tsv", tags=["SILAC"], tissues=["liver", "lung"])
    make_library("D:/libs/b.tsv", tags=["LF"], tissues=["liver"])
    options = client.get("/libraries/options").json()
    assert options["tags"] == ["LF", "SILAC"]
    assert options["tissues"] == ["liver", "lung"]


# ---------------------------------------------------------------- paths

def test_path_with_spaces_is_stored_verbatim(client):
    path = "D:/Shared Drive/My Libs/lib one.tsv"
    assert client.post("/libraries/", json={"path": path, "creator": "ZC"}).json()["path"] == path


@pytest.mark.parametrize("wrapper", ['"', "'"])
def test_surrounding_quotes_are_stripped_but_inner_spaces_kept(client, wrapper):
    raw = f"  {wrapper}D:/Shared Drive/lib.tsv{wrapper}  "
    response = client.post("/libraries/", json={"path": raw, "creator": "ZC"})
    assert response.json()["path"] == "D:/Shared Drive/lib.tsv"


def test_missing_file_is_reported_as_not_found(client, make_library):
    assert make_library("D:/libs/definitely-absent.tsv")["path_exists"] is False


def test_existing_file_reports_size_and_format(client, tmp_path):
    real = tmp_path / "real library.tsv"
    real.write_text("Modified.Sequence\nAK\n", encoding="utf-8")
    body = client.post("/libraries/", json={"path": str(real), "creator": "ZC"}).json()
    assert body["path_exists"] is True
    assert body["file_format"] == "TSV"
    assert body["file_size"] == real.stat().st_size


# ---------------------------------------------------------------- analyze

def write_library(path):
    path.write_text(
        "Modified.Sequence\tStripped.Sequence\tProtein.Group\tPrecursor.Charge\n"
        "AC(UniMod:4)DEK\tACDEK\tP1;P2\t2\n"
        "AC(UniMod:4)DEK\tACDEK\tP1;P2\t3\n"
        "PEPTIDK\tPEPTIDK\tP3\t2\n",
        encoding="utf-8",
    )
    return path


def test_analyze_fills_in_metadata_from_the_file(client, tmp_path):
    path = write_library(tmp_path / "lib.tsv")
    body = client.post("/libraries/analyze", json={"path": str(path)}).json()
    assert body["precursors"] == 3
    assert body["proteins"] == 3
    assert body["carbamidomethylated"] is True
    assert body["ptms"] == []
    assert body["content_hash"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert body["warning"] is None


def test_analyze_warns_about_missing_columns(client, tmp_path):
    path = tmp_path / "partial.tsv"
    path.write_text("Modified.Sequence\tPrecursor.Charge\nAK\t2\n", encoding="utf-8")
    body = client.post("/libraries/analyze", json={"path": str(path)}).json()
    assert "Protein.Group" in body["warning"]
    assert body["proteins"] is None


def test_analyze_rejects_a_path_that_does_not_exist(client):
    response = client.post("/libraries/analyze", json={"path": "D:/libs/nope.tsv"})
    assert response.status_code == 400


def test_analyze_accepts_a_quoted_path(client, tmp_path):
    path = write_library(tmp_path / "lib.tsv")
    response = client.post("/libraries/analyze", json={"path": f'"{path}"'})
    assert response.status_code == 200


def test_hash_file_matches_analyze(client, tmp_path):
    path = write_library(tmp_path / "lib.tsv")
    assert (
        client.post("/libraries/hash-file", json={"path": str(path)}).json()["content_hash"]
        == client.post("/libraries/analyze", json={"path": str(path)}).json()["content_hash"]
    )


def test_hash_file_reports_a_missing_file(client):
    assert "error" in client.post("/libraries/hash-file", json={"path": "D:/nope.tsv"}).json()
