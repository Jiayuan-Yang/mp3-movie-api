import logging
import os

import pandas as pd
from fastapi import FastAPI, File, HTTPException, Query, UploadFile

from data_pipeline import create_cleaning_report, process_data, validate_dataframe
from src import MovieCache, MovieStorage, MovieUploadInfo, MovieDataResponse, MovieProcessingReport, ProcessConfig
from src import HealthResponse, log_requests, setup_logging
from src.storage import MOVIE_COLUMNS
from src.utils import parse_movie_csv

setup_logging(verbose=True)
logger = logging.getLogger(__name__)
app = FastAPI(title="Movie Collection API", version="1.0.0")
app.middleware("http")(log_requests)
storage = MovieStorage(os.environ.get("MOVIE_DB_PATH", "data/movies.db"))

cache = MovieCache()


@app.get("/health", response_model=HealthResponse)
def health():
    return HealthResponse(status="ok", version=app.version)


@app.post("/upload", response_model=MovieUploadInfo)
async def upload_movies(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only .csv files are supported")
    try:
        df = parse_movie_csv(await file.read())
    except (ValueError, UnicodeDecodeError, pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid CSV: {exc}") from exc
    finally:
        await file.close()
    storage.save(df)
    cache.invalidate()
    logger.info("Uploaded movies: filename=%s, rows=%s", file.filename, len(df))
    return MovieUploadInfo(filename=file.filename, rows=len(df), columns=len(df.columns), column_names=list(df.columns))


@app.get("/movies", response_model=MovieDataResponse)
def get_movies(limit: int = Query(default=100, ge=1)):
    cached = cache.get(limit)
    if cached is not None:
        logger.info("Movie cache hit: limit=%s", limit)
        return cached
    data = storage.select_columns(MOVIE_COLUMNS, limit)
    total = storage.count_movies()
    logger.info("Retrieved movies: rows=%s", len(data))
    response = {"data": data, "total_rows": total}
    cache.set(limit, response)
    return response


@app.get("/movies/search", response_model=list[dict])
def query_movies(columns: list[str] = Query(default=["title"]),
                 min_rating: float = Query(default=0, ge=0, le=10),
                 limit: int = Query(default=100, ge=1)):
    try:
        data = storage.query_movies(columns, min_rating, limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    logger.info("Queried movies: columns=%s, min_rating=%s, returned_rows=%s", columns, min_rating, len(data))
    return data


@app.post("/movies/process", response_model=MovieProcessingReport)
def process_movies(config: ProcessConfig):
    df = storage.get()
    if df.empty:
        raise HTTPException(status_code=400, detail="No movies to process")
    try:
        settings = config.model_dump()
        validation = settings["validation"]
        validated = validate_dataframe(
            df, validation["required_columns"], validation["numeric_columns"]
        )
        removed = len(df) - len(validated)
        logger.info("Validated movies: validation_removed=%s, rows=%s", removed, len(validated))
        before = validated.copy(deep=True)
        processed = process_data(validated, settings)
        report = create_cleaning_report(before, processed)
        # The SQL schema remains fixed even if MP2's pipeline drops a column.
        storage.save(processed.reindex(columns=MOVIE_COLUMNS))
        cache.invalidate()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    logger.info("Processed movies: validation_rows_removed=%s, cleaning_report=%s", removed, report)
    return {"validation_rows_removed": removed, "cleaning_report": report}
