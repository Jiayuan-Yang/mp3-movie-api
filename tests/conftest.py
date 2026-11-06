import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Avoid creating the application's default database when tests import main.
_import_db = tempfile.TemporaryDirectory()
os.environ.setdefault('MOVIE_DB_PATH', str(Path(_import_db.name) / 'import.db'))
import main
from src import MovieStorage


@pytest.fixture
def storage(tmp_path, monkeypatch):
    value = MovieStorage(tmp_path / 'movies.db')
    monkeypatch.setattr(main, 'storage', value)
    return value


@pytest.fixture
def client(storage):
    with TestClient(main.app) as value:
        yield value


@pytest.fixture
def sample():
    return (Path(__file__).resolve().parents[1] / 'fixtures/sample_movies.csv').read_bytes()
