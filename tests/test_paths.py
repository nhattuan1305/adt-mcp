import os

from adt_mcp import paths


REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_project_root_is_the_checkout_when_running_from_source(monkeypatch):
    monkeypatch.delenv("ADT_MCP_HOME", raising=False)
    assert os.path.normcase(paths.project_root()) == os.path.normcase(REPO)


def test_adt_mcp_home_overrides_project_root(monkeypatch, tmp_path):
    monkeypatch.setenv("ADT_MCP_HOME", str(tmp_path))
    assert os.path.normcase(paths.project_root()) == os.path.normcase(
        str(tmp_path))


def test_project_root_falls_back_to_cwd_when_package_is_installed_flat(
        monkeypatch, tmp_path):
    """A non-editable `pip install .` puts the package in site-packages, so
    three levels up is not the project; the CWD (run.bat cd's there) is."""
    monkeypatch.delenv("ADT_MCP_HOME", raising=False)
    monkeypatch.setattr(paths, "_SRC_LAYOUT_ROOT", str(tmp_path / "nowhere"))
    monkeypatch.chdir(tmp_path)
    assert os.path.normcase(paths.project_root()) == os.path.normcase(
        str(tmp_path))


def test_systems_path_defaults_under_project_root(monkeypatch, tmp_path):
    monkeypatch.delenv("ADT_MCP_SYSTEMS", raising=False)
    monkeypatch.setenv("ADT_MCP_HOME", str(tmp_path))
    assert paths.systems_path() == os.path.join(str(tmp_path), "systems.json")


def test_adt_mcp_systems_overrides_systems_path(monkeypatch, tmp_path):
    target = tmp_path / "elsewhere.json"
    monkeypatch.setenv("ADT_MCP_SYSTEMS", str(target))
    assert paths.systems_path() == str(target)


def test_web_dir_and_cookies_dir_sit_under_project_root(monkeypatch, tmp_path):
    monkeypatch.setenv("ADT_MCP_HOME", str(tmp_path))
    assert paths.web_dir() == os.path.join(str(tmp_path), "web")
    assert paths.cookies_dir() == os.path.join(str(tmp_path), "cookies")
    assert os.path.isdir(paths.cookies_dir())  # created on demand
