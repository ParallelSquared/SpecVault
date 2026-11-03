"""Which computer a change came from.

On the shared remote desktops everyone uses one Windows account, so the
browser there remembers one name for everybody who sits down. The name in the
history says who the browser thought it was; the machine says where the change
was made -- which is what lets "ZC did this" be doubted when it came from a
desk ZC is not at.
"""
import socket

import pytest

from app.routers import libraries as lib


@pytest.fixture(autouse=True)
def fresh_lookups(monkeypatch):
    """Each test starts with nothing looked up."""
    monkeypatch.setattr(lib, "_MACHINES", {})
    monkeypatch.setattr(lib, "_PENDING", {})


# ------------------------------------------------------------ the lookup

def test_a_machine_with_a_name_is_recorded_by_name(monkeypatch):
    monkeypatch.setattr(socket, "gethostbyaddr", lambda a: ("GUAC-03", [], [a]))
    assert lib._machine_name("10.0.0.5") == "GUAC-03"


def test_a_machine_without_one_is_recorded_by_address(monkeypatch):
    def nothing(address):
        raise socket.herror("no name")
    monkeypatch.setattr(socket, "gethostbyaddr", nothing)
    assert lib._machine_name("10.0.0.5") == "10.0.0.5"


def test_a_slow_lookup_does_not_hold_the_change_up(monkeypatch):
    """A reverse lookup that finds nothing can take seconds on a Windows
    network. The change goes ahead with the address; the name is there for
    next time."""
    import threading
    release = threading.Event()

    def slow(address):
        release.wait(5)
        return ("GUAC-03", [], [address])

    monkeypatch.setattr(socket, "gethostbyaddr", slow)
    monkeypatch.setattr(lib, "_LOOKUP_WAIT", 0.05)
    assert lib._machine_name("10.0.0.5") == "10.0.0.5"

    release.set()
    for _ in range(100):  # let the lookup finish in the background
        if lib._MACHINES.get("10.0.0.5") == "GUAC-03":
            break
        threading.Event().wait(0.02)
    assert lib._machine_name("10.0.0.5") == "GUAC-03"


def test_a_slow_lookup_is_not_started_twice_or_waited_on_twice(monkeypatch):
    """Changes arriving while a lookup is under way neither queue another nor
    wait on it: each would have cost half a second, for nothing."""
    import threading
    import time
    release = threading.Event()
    calls = []

    def slow(address):
        calls.append(address)
        release.wait(5)
        return ("GUAC-03", [], [address])

    monkeypatch.setattr(socket, "gethostbyaddr", slow)
    monkeypatch.setattr(lib, "_LOOKUP_WAIT", 0.2)
    lib._machine_name("10.0.0.5")  # starts it, waits its 0.2 s

    started = time.monotonic()
    for _ in range(5):
        assert lib._machine_name("10.0.0.5") == "10.0.0.5"
    assert time.monotonic() - started < 0.1
    assert calls == ["10.0.0.5"]
    release.set()


def test_each_address_is_looked_up_once(monkeypatch):
    calls = []

    def counted(address):
        calls.append(address)
        return ("GUAC-03", [], [address])

    monkeypatch.setattr(socket, "gethostbyaddr", counted)
    for _ in range(3):
        lib._machine_name("10.0.0.5")
    assert calls == ["10.0.0.5"]


# ------------------------------------------------------------ the history

@pytest.fixture
def named(monkeypatch):
    monkeypatch.setattr(socket, "gethostbyaddr", lambda a: ("GUAC-03", [], [a]))


def test_cataloguing_records_the_machine(client, make_library, named):
    library = make_library()
    history = client.get(f"/libraries/{library['id']}/history").json()
    assert history[0]["changed_from"] == "GUAC-03"


def test_every_kind_of_change_records_it(client, make_library, library_file, named):
    library = make_library()
    client.patch(f"/libraries/{library['id']}", json={"project": "Astral"})
    client.post(f"/libraries/{library['id']}/paths", json={"path": library_file()})
    client.delete(f"/libraries/{library['id']}")
    client.post(f"/libraries/{library['id']}/restore")

    history = client.get(f"/libraries/{library['id']}/history").json()
    assert [row["event"] for row in history] == [
        "restored", "deleted", "path added", "edited", "catalogued",
    ]
    assert {row["changed_from"] for row in history} == {"GUAC-03"}
