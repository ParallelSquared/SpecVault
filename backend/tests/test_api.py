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
    assert body["warning"] is None
    assert "content_hash" not in body  # hashing is Save's job now


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


def test_hash_lookup_finds_what_saving_stored(client, tmp_path):
    """The filter bar's search by file only works if it hashes the way Save does."""
    path = write_library(tmp_path / "lib.tsv")
    saved = client.post("/libraries/", json={"path": str(path), "creator": "ZC"}).json()
    looked_up = client.post("/libraries/hash-file", json={"path": str(path)}).json()
    assert looked_up["content_hash"] == saved["content_hash"]
    assert saved["content_hash"] == hashlib.sha256(path.read_bytes()).hexdigest()


def test_hash_file_reports_a_missing_file(client):
    assert "error" in client.post("/libraries/hash-file", json={"path": "D:/nope.tsv"}).json()


# ---------------------------------------------------------------- the mod table

import re  # noqa: E402

from app.routers import libraries as lib_module  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_mod_tables(monkeypatch):
    """Each test starts with nothing remembered from an earlier Auto-fill."""
    monkeypatch.setattr(lib_module, "_MOD_TABLES", lib_module._PerFile())
    monkeypatch.setattr(lib_module, "_HASHES", lib_module._PerFile())
    monkeypatch.setattr(lib_module, "_STATS", lib_module._PerFile())


@pytest.fixture
def hashes(monkeypatch):
    """How many times a file is hashed."""
    count = {"n": 0}
    real = lib_module._hash_file

    def counting(path):
        count["n"] += 1
        return real(path)

    monkeypatch.setattr(lib_module, "_hash_file", counting)
    return count


@pytest.fixture
def reads(monkeypatch):
    """How many times a library file is parsed."""
    count = {"n": 0}
    real = lib_module._read_library_df

    def counting(path):
        count["n"] += 1
        return real(path)

    monkeypatch.setattr(lib_module, "_read_library_df", counting)
    return count


def write_mods(path, *sequences):
    lines = ["Modified.Sequence\tStripped.Sequence\tProtein.Group\tPrecursor.Charge"]
    for seq in sequences:
        stripped = re.sub(r"\([^()]*\)", "", seq)
        lines.append(f"{seq}\t{stripped}\tP1\t2")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def table_names(body):
    return {d["name"] for d in body["mod_details"] or []}


def test_saving_builds_the_mod_table_without_auto_fill(client, tmp_path):
    path = write_mods(tmp_path / "lib.tsv", "AC(UniMod:4)DEK", "PEPTIDEK")
    body = client.post("/libraries/", json={"path": str(path), "creator": "ZC"}).json()
    assert table_names(body) == {"UniMod:4"}


def test_saving_straight_after_auto_fill_does_not_read_the_file_again(client, tmp_path, reads):
    path = write_mods(tmp_path / "lib.tsv", "AC(UniMod:4)DEK")
    client.post("/libraries/analyze", json={"path": str(path)})
    assert reads["n"] == 1
    body = client.post("/libraries/", json={"path": str(path), "creator": "ZC"}).json()
    assert reads["n"] == 1
    assert table_names(body) == {"UniMod:4"}


def test_a_different_path_after_auto_fill_gets_its_own_table(client, tmp_path):
    """Auto-fill on one file, then a different path typed in before saving --
    the saved library used to inherit the first file's table."""
    first = write_mods(tmp_path / "first.tsv", "AC(UniMod:4)DEK")
    second = write_mods(tmp_path / "second.tsv", "PEPM(UniMod:35)TIDEK")
    client.post("/libraries/analyze", json={"path": str(first)})
    body = client.post("/libraries/", json={"path": str(second), "creator": "ZC"}).json()
    assert table_names(body) == {"UniMod:35"}


def test_a_file_rewritten_after_auto_fill_is_analysed_again(client, tmp_path):
    path = write_mods(tmp_path / "lib.tsv", "AC(UniMod:4)DEK")
    client.post("/libraries/analyze", json={"path": str(path)})
    write_mods(path, "PEPM(UniMod:35)TIDEK", "AC(UniMod:4)DEK", "ELVISK")
    body = client.post("/libraries/", json={"path": str(path), "creator": "ZC"}).json()
    assert table_names(body) == {"UniMod:4", "UniMod:35"}


def test_a_table_sent_with_the_request_is_ignored(client, tmp_path):
    path = write_mods(tmp_path / "lib.tsv", "AC(UniMod:4)DEK")
    fake = [{"name": "invented", "site": "K", "precursors": 1}]
    body = client.post("/libraries/", json={"path": str(path), "creator": "ZC", "mod_details": fake}).json()
    assert table_names(body) == {"UniMod:4"}


def test_an_unreachable_path_still_saves_without_a_table(client):
    response = client.post("/libraries/", json={"path": "D:/libs/not-mounted.tsv", "creator": "ZC"})
    assert response.status_code == 201
    assert response.json()["mod_details"] is None


def test_changing_the_path_rebuilds_the_table(client, tmp_path):
    first = write_mods(tmp_path / "first.tsv", "AC(UniMod:4)DEK")
    second = write_mods(tmp_path / "second.tsv", "PEPM(UniMod:35)TIDEK")
    created = client.post("/libraries/", json={"path": str(first), "creator": "ZC"}).json()
    body = client.patch(f"/libraries/{created['id']}", json={"path": str(second)}).json()
    assert table_names(body) == {"UniMod:35"}


def test_the_table_cannot_be_set_by_patch(client, tmp_path):
    path = write_mods(tmp_path / "lib.tsv", "AC(UniMod:4)DEK")
    created = client.post("/libraries/", json={"path": str(path), "creator": "ZC"}).json()
    fake = [{"name": "invented", "site": "K", "precursors": 1}]
    body = client.patch(f"/libraries/{created['id']}", json={"mod_details": fake}).json()
    assert table_names(body) == {"UniMod:4"}


# ---------------------------------------------------------------- the hash

def sha256_of(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_saving_hashes_the_file_without_auto_fill(client, tmp_path):
    path = write_mods(tmp_path / "lib.tsv", "AC(UniMod:4)DEK")
    body = client.post("/libraries/", json={"path": str(path), "creator": "ZC"}).json()
    assert body["content_hash"] == sha256_of(path)


def test_auto_fill_does_not_wait_for_the_hash_and_save_does_not_redo_it(client, tmp_path, hashes):
    """Auto-fill sets the hash going and returns; Save collects that same hash
    instead of reading the file a second time."""
    path = write_mods(tmp_path / "lib.tsv", "AC(UniMod:4)DEK")
    client.post("/libraries/analyze", json={"path": str(path)})
    assert lib_module._file_identity(str(path)) in lib_module._HASHES._items  # under way
    body = client.post("/libraries/", json={"path": str(path), "creator": "ZC"}).json()
    assert hashes["n"] == 1
    assert body["content_hash"] == sha256_of(path)


def test_a_different_path_after_auto_fill_gets_its_own_hash(client, tmp_path):
    """Auto-fill on one file, then another path typed in: the saved library used
    to carry the first file's hash, so a search by file found the wrong entry."""
    first = write_mods(tmp_path / "first.tsv", "AC(UniMod:4)DEK")
    second = write_mods(tmp_path / "second.tsv", "PEPM(UniMod:35)TIDEK")
    client.post("/libraries/analyze", json={"path": str(first)})
    body = client.post("/libraries/", json={"path": str(second), "creator": "ZC"}).json()
    assert body["content_hash"] == sha256_of(second)


def test_a_file_rewritten_after_auto_fill_is_hashed_again(client, tmp_path):
    path = write_mods(tmp_path / "lib.tsv", "AC(UniMod:4)DEK")
    client.post("/libraries/analyze", json={"path": str(path)})
    write_mods(path, "PEPM(UniMod:35)TIDEK", "AC(UniMod:4)DEK", "ELVISK")
    body = client.post("/libraries/", json={"path": str(path), "creator": "ZC"}).json()
    assert body["content_hash"] == sha256_of(path)


def test_a_hash_sent_with_the_request_is_ignored(client, tmp_path):
    path = write_mods(tmp_path / "lib.tsv", "AC(UniMod:4)DEK")
    body = client.post("/libraries/", json={"path": str(path), "creator": "ZC",
                                            "content_hash": "not-a-real-hash"}).json()
    assert body["content_hash"] == sha256_of(path)


def test_changing_the_path_rehashes(client, tmp_path):
    first = write_mods(tmp_path / "first.tsv", "AC(UniMod:4)DEK")
    second = write_mods(tmp_path / "second.tsv", "PEPM(UniMod:35)TIDEK")
    created = client.post("/libraries/", json={"path": str(first), "creator": "ZC"}).json()
    body = client.patch(f"/libraries/{created['id']}", json={"path": str(second)}).json()
    assert body["content_hash"] == sha256_of(second)


def test_an_unreachable_path_saves_without_a_hash(client):
    body = client.post("/libraries/", json={"path": "D:/libs/not-mounted.tsv", "creator": "ZC"}).json()
    assert body["content_hash"] is None


# ---------------------------------------------------------------- library details

@pytest.fixture
def stat_builds(monkeypatch):
    """How many times the library details are worked out."""
    count = {"n": 0}
    real = lib_module._build_library_stats

    def counting(path):
        count["n"] += 1
        return real(path)

    monkeypatch.setattr(lib_module, "_build_library_stats", counting)
    return count


def write_im_library(path, im):
    rows = [
        "Modified.Sequence\tStripped.Sequence\tPrecursor.Charge\tPrecursor.Mz\tIM\tDecoy\tFragment.Type",
        f"PEPTIDEK\tPEPTIDEK\t2\t465.24\t{im}\t0\ty",
        f"PEPTIDEK\tPEPTIDEK\t2\t465.24\t{im}\t0\tb",
        f"KEDITPEP\tKEDITPEP\t2\t465.24\t{im}\t1\ty",
    ]
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


def test_saving_builds_the_library_details(client, tmp_path):
    path = write_im_library(tmp_path / "lib.tsv", 0.9)
    body = client.post("/libraries/", json={"path": str(path), "creator": "ZC"}).json()
    assert body["library_stats"]["fragments"]["per_precursor"]["max"] == 2
    assert body["ion_mobility"] is True
    assert body["decoys"] == 1


def test_a_library_without_ion_mobility_says_so(client, tmp_path):
    path = write_im_library(tmp_path / "lib.tsv", 0.0)
    assert client.post("/libraries/", json={"path": str(path), "creator": "ZC"}).json()["ion_mobility"] is False


def test_auto_fill_starts_the_details_and_save_collects_them(client, tmp_path, stat_builds):
    path = write_im_library(tmp_path / "lib.tsv", 0.9)
    client.post("/libraries/analyze", json={"path": str(path)})
    assert lib_module._file_identity(str(path)) in lib_module._STATS._items  # under way
    body = client.post("/libraries/", json={"path": str(path), "creator": "ZC"}).json()
    assert stat_builds["n"] == 1
    assert body["decoys"] == 1


def test_changing_the_path_rebuilds_the_details(client, tmp_path):
    first = write_im_library(tmp_path / "first.tsv", 0.9)
    second = write_im_library(tmp_path / "second.tsv", 0.0)
    created = client.post("/libraries/", json={"path": str(first), "creator": "ZC"}).json()
    body = client.patch(f"/libraries/{created['id']}", json={"path": str(second)}).json()
    assert body["ion_mobility"] is False


def test_an_unreachable_path_saves_without_details(client):
    body = client.post("/libraries/", json={"path": "D:/libs/not-mounted.tsv", "creator": "ZC"}).json()
    assert body["library_stats"] is None and body["ion_mobility"] is None

