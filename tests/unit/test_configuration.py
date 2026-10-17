from pathlib import Path

from dotenv import dotenv_values

from nordtrace.core.config import Settings


def test_data_directory_derives_database_path(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_PATH", raising=False)
    configured = Settings(_env_file=None, data_dir=str(tmp_path / "custom-data"))
    assert Path(configured.database_path) == tmp_path / "custom-data" / "nordtrace.db"


def test_explicit_database_path_takes_precedence(tmp_path):
    database = tmp_path / "explicit.db"
    configured = Settings(_env_file=None, data_dir=str(tmp_path / "other"), database_path=str(database))
    assert Path(configured.database_path) == database


def test_environment_database_path_overrides_derived_data_directory(tmp_path, monkeypatch):
    database = tmp_path / "environment.db"
    monkeypatch.setenv("DATABASE_PATH", str(database))
    configured = Settings(_env_file=None, data_dir=str(tmp_path / "different-data"))
    assert Path(configured.database_path) == database


def test_every_active_environment_example_name_is_consumed():
    example = Path(__file__).resolve().parents[2] / ".env.example"
    names = set(dotenv_values(example))
    supported = {name.upper() for name in Settings.model_fields}
    assert names <= supported, names - supported


def test_default_storage_follows_runtime_directory_not_package_install(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DATA_DIR", raising=False)
    monkeypatch.delenv("DATABASE_PATH", raising=False)
    configured = Settings(_env_file=None)
    assert Path(configured.data_dir) == tmp_path / "data"
    assert Path(configured.database_path) == tmp_path / "data" / "nordtrace.db"
