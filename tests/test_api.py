import sqlite3

import pandas as pd
import pytest

from src import MovieStorage
from src.storage import MOVIE_COLUMNS


def upload(client, content, filename='sample_movies.csv'):
    return client.post('/upload', files={'file': (filename, content, 'text/csv')})


def test_sample_upload_and_get(client, sample):
    assert upload(client, sample).json() == {
        'filename': 'sample_movies.csv', 'rows': 20, 'columns': 4,
        'column_names': MOVIE_COLUMNS,
    }
    response = client.get('/movies', params={'limit': 2})
    assert response.status_code == 200
    assert response.json() == {'data': [
        {'id': 1, 'title': 'Movie A', 'release_year': 2020, 'rating': 8.0, 'genre': 'Drama'},
        {'id': 2, 'title': 'Movie B', 'release_year': 2021, 'rating': 8.5, 'genre': 'Comedy'},
    ], 'total_rows': 20}


def test_search_sort_and_projection(client, sample):
    upload(client, sample)
    params = [('min_rating', 8.5), ('limit', 2)]
    assert client.get('/movies/search', params=params).json() == [
        {'id': 4, 'title': 'Movie C'}, {'id': 2, 'title': 'Movie B'}]
    assert client.get('/movies/search', params=params + [('columns', 'title'), ('columns', 'rating')]).json() == [
        {'id': 4, 'title': 'Movie C', 'rating': 9.0},
        {'id': 2, 'title': 'Movie B', 'rating': 8.5}]
    assert client.get('/movies/search', params={'min_rating': 10}).json() == []
    assert client.get('/movies/search', params={'min_rating': 8.5}).json()[1:3] == [
        {'id': 2, 'title': 'Movie B'}, {'id': 3, 'title': 'Movie B'}]


def test_replacement_and_persistence(client, storage, sample):
    upload(client, sample)
    upload(client, sample)
    reopened = MovieStorage(storage.db_path)
    assert reopened.count_movies() == 20
    assert reopened.select_columns(['title'], 1) == [{'id': 1, 'title': 'Movie A'}]


@pytest.mark.parametrize('content,filename', [
    (b'anything', 'file.txt'), (b'', 'file.csv'),
    (b'title,release_year,rating,genre\n', 'file.csv'),
    (b'title,rating\nA,8\n', 'file.csv'),
    (b'title,release_year,rating,genre,extra\nA,2020,8,Drama,x\n', 'file.csv'),
    (b'title,title,rating,genre\nA,2020,8,Drama\n', 'file.csv'),
    (b'title,release_year,rating,genre\n"unfinished', 'file.csv'),
    (b'\xff\xfe', 'file.csv'),
])
def test_invalid_upload_preserves_collection(client, sample, content, filename):
    upload(client, sample)
    assert upload(client, content, filename).status_code == 400
    assert client.get('/movies').json()['total_rows'] == 20
    assert client.get('/health').json() == {'status': 'ok', 'version': '1.0.0'}


@pytest.mark.parametrize('url,status', [
    ('/movies?limit=0', 422), ('/movies/search?limit=-1', 422),
    ('/movies/search?min_rating=11', 422), ('/movies/search?min_rating=-1', 422),
    ('/movies/search?columns=title%3BDROP%20TABLE%20movies', 400),
])
def test_invalid_queries(client, url, status):
    assert client.get(url).status_code == status


def test_empty_collection(client, storage):
    assert client.get('/movies').json() == {'data': [], 'total_rows': 0}
    assert client.get('/movies/search').json() == []
    assert list(storage.get().columns) == MOVIE_COLUMNS
    assert client.post('/movies/process', json={}).status_code == 400


def test_reordered_columns_and_nulls(client, storage):
    response = upload(client, b'genre,rating,title,release_year\nDrama,,A,2020\n')
    assert response.status_code == 200
    assert response.json()['column_names'] == MOVIE_COLUMNS
    assert client.get('/movies').json()['data'][0]['rating'] is None
    connection = sqlite3.connect(storage.db_path)
    try:
        assert connection.execute('SELECT rating IS NULL FROM movies').fetchone()[0] == 1
    finally:
        connection.close()


def test_process_sample(client, sample):
    upload(client, sample)
    response = client.post('/movies/process', json={})
    assert response.status_code == 200
    assert response.json() == {'validation_rows_removed': 0, 'cleaning_report': {
        'rows_before': 20, 'rows_after': 18, 'rows_removed': 2,
        'columns_before': 4, 'columns_after': 4, 'columns_removed': 0}}
    assert client.get('/movies').json()['total_rows'] == 18
    assert client.post('/movies/process', json={}).json()['cleaning_report']['rows_removed'] == 0


def test_processing_validation_and_config(client):
    upload(client, b'title,release_year,rating,genre\nA,2020,8,Drama\nB,2020,bad,Drama\nC,bad,8,Drama\nD,2021,,Comedy\n')
    result = client.post('/movies/process', json={
        'validation': {'required_columns': MOVIE_COLUMNS,
                       'numeric_columns': ['release_year', 'rating']}
    }).json()
    assert result['validation_rows_removed'] == 2
    assert result['cleaning_report']['rows_removed'] == 1
    assert client.get('/movies').json()['data'][0]['title'] == 'A'


def test_processing_can_keep_missing_and_duplicates(client, sample):
    upload(client, sample)
    response = client.post('/movies/process', json={'processing': {
        'remove_duplicates': False, 'missing': {'enabled': False}}})
    assert response.json()['cleaning_report']['rows_after'] == 20


def test_save_rollback(storage):
    storage.save(pd.DataFrame([['Original', 2020, 8, 'Drama']], columns=MOVIE_COLUMNS))
    broken = pd.DataFrame([['New', 2021, 9, 'Comedy'], ['Bad', 2022, {'invalid': True}, 'Drama']], columns=MOVIE_COLUMNS)
    with pytest.raises(sqlite3.Error):
        storage.save(broken)
    assert storage.select_columns(['title']) == [{'id': 1, 'title': 'Original'}]


@pytest.mark.parametrize('columns', [[], ['id'], ['title; DROP TABLE movies']])
def test_storage_column_validation(storage, columns):
    with pytest.raises(ValueError):
        storage.select_columns(columns)
    with pytest.raises(ValueError):
        storage.query_movies(columns, 0, 100)
    assert storage.count_movies() == 0


@pytest.mark.parametrize('failure', ['required', 'numeric', 'method', 'axis'])
def test_processing_failure_preserves_movies(client, sample, failure):
    upload(client, sample)
    before = client.get('/movies').json()
    config = {'validation': {}, 'processing': {}}
    if failure in ('required', 'numeric'):
        config['validation'][f'{failure}_columns'] = ['absent']
    elif failure == 'method':
        config['processing']['outliers'] = {'enabled': True, 'method': 'unsupported'}
    else:
        config['processing']['missing'] = {'axis': 'unsupported'}
    response = client.post('/movies/process', json=config)
    assert response.status_code == 400
    assert client.get('/movies').json() == before


@pytest.mark.parametrize('method', ['iqr', 'zscore'])
def test_api_outliers(client, sample, method):
    upload(client, sample)
    response = client.post('/movies/process', json={
        'validation': {'numeric_columns': ['rating']},
        'processing': {'outliers': {'enabled': True, 'columns': ['rating'],
                                    'method': method, 'threshold': 1.5}}})
    assert response.status_code == 200
    assert response.json()['cleaning_report']['rows_after'] == 16
    assert all(row['rating'] > 1 for row in client.get('/movies').json()['data'])


def test_missing_column_processing_keeps_fixed_sql_schema(client):
    upload(client, b'title,release_year,rating,genre\nA,2020,,Drama\nB,2021,8,Comedy\n')
    response = client.post('/movies/process', json={'processing': {'missing': {'axis': 'columns'}}})
    assert response.status_code == 200
    assert response.json()['cleaning_report']['columns_removed'] == 1
    rows = client.get('/movies').json()['data']
    assert len(rows) == 2
    assert all(row['rating'] is None for row in rows)


def test_request_ids_and_error_response(client, storage, monkeypatch):
    first = client.get('/health')
    second = client.get('/health')
    assert len(first.headers['X-Request-ID']) == 8
    assert first.headers['X-Request-ID'] != second.headers['X-Request-ID']

    def fail(*args):
        raise RuntimeError('private details')

    monkeypatch.setattr(storage, 'select_columns', fail)
    response = client.get('/movies')
    assert response.status_code == 500
    assert response.json() == {'detail': 'Internal server error'}
    assert response.headers['X-Request-ID']


@pytest.mark.parametrize('body', [None, [], {'validation': {'numeric_columns': 'rating'}}])
def test_invalid_processing_body(client, sample, body):
    upload(client, sample)
    assert client.post('/movies/process', json=body).status_code == 422
