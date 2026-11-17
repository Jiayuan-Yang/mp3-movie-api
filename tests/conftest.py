import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Avoid creating the application's default database when tests import main.
_import_db = tempfile.TemporaryDirectory()
os.environ.setdefault('MOVIE_DB_PATH', str(Path(_import_db.name) / 'import.db'))
import main
from src import MovieCache, MovieStorage


@pytest.fixture
def storage(tmp_path, monkeypatch):
    value = MovieStorage(tmp_path / 'movies.db')
    monkeypatch.setattr(main, 'storage', value)
    return value


@pytest.fixture
def client(storage, monkeypatch):
    monkeypatch.setattr(main, "cache", MovieCache())
    with TestClient(main.app) as value:
        yield value


@pytest.fixture
def sample():
    return (Path(__file__).resolve().parents[1] / 'fixtures/sample_movies.csv').read_bytes()


@pytest.fixture
def test_storage(storage):
    return storage


@pytest.fixture
def sample_csv_bytes(sample):
    return sample


@pytest.fixture
def uploaded_movies(client, sample_csv_bytes):
    response = client.post("/upload", files={"file": ("sample_movies.csv", sample_csv_bytes, "text/csv")})
    assert response.status_code == 200
    return response.json()


@pytest.fixture
def processing_body():
    return {
        "validation": {"required_columns": ["title", "release_year", "rating", "genre"],
                       "numeric_columns": ["release_year", "rating"]},
        "processing": {"remove_duplicates": True,
                       "missing": {"enabled": True, "axis": "rows"},
                       "outliers": {"enabled": True, "columns": ["rating"],
                                    "method": "iqr", "threshold": 1.5}}
    }
