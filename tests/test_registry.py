import json
import pytest
from adt_mcp.registry import System, SystemRegistry


def test_roundtrip_persist(tmp_path):
    path = tmp_path / "systems.json"
    reg = SystemRegistry(str(path))
    reg.upsert(System(name="dev", url="https://h", client="001",
                      language="EN", auth="basic",
                      username="u", password="p",
                      cookie_file=None, cookie_string=None))
    # New registry reading same file sees it.
    reg2 = SystemRegistry(str(path))
    sys = reg2.get("dev")
    assert sys.url == "https://h"
    assert sys.username == "u"
    # File is valid JSON keyed by name, no nested "name".
    raw = json.loads(path.read_text())
    assert "name" not in raw["dev"]


def test_get_missing_raises(tmp_path):
    reg = SystemRegistry(str(tmp_path / "s.json"))
    with pytest.raises(KeyError):
        reg.get("nope")


def test_delete(tmp_path):
    path = tmp_path / "s.json"
    reg = SystemRegistry(str(path))
    reg.upsert(System(name="a", url="x", client="001", language="EN",
                      auth="basic", username=None, password=None,
                      cookie_file=None, cookie_string=None))
    reg.delete("a")
    assert reg.list() == []


def test_missing_file_is_empty(tmp_path):
    reg = SystemRegistry(str(tmp_path / "absent.json"))
    assert reg.list() == []
