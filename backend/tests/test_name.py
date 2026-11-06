"""A library's optional name, shown above its path when browsing."""


def test_a_name_is_saved(make_library):
    assert make_library(name="3M HYE library")["name"] == "3M HYE library"


def test_no_name_is_none(make_library):
    """The browser shows the folder and file instead."""
    assert make_library()["name"] is None


def test_a_blank_name_is_no_name(make_library):
    assert make_library(name="   ")["name"] is None


def test_stray_whitespace_goes(make_library):
    assert make_library(name="  3M   HYE  ")["name"] == "3M HYE"


def test_a_name_can_be_changed_and_cleared(client, make_library):
    library = make_library(name="old")
    renamed = client.patch(f"/libraries/{library['id']}", json={"name": " new "})
    assert renamed.json()["name"] == "new"
    cleared = client.patch(f"/libraries/{library['id']}", json={"name": None})
    assert cleared.json()["name"] is None


def test_renaming_is_in_the_history(client, make_library):
    library = make_library(name="old")
    client.patch(f"/libraries/{library['id']}", json={"name": "new"})
    newest = client.get(f"/libraries/{library['id']}/history").json()[0]
    assert newest["event"] == "edited"
    assert newest["data"]["name"] == "new"
