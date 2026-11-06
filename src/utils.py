"""CSV parsing and shared application logging configuration."""
import csv
import logging
from io import StringIO

import pandas as pd

from .storage import MOVIE_COLUMNS


def parse_movie_csv(content):
    text = content.decode("utf-8-sig")
    # Inspect the raw header too: pandas may rename duplicate column names.
    header = next(csv.reader(StringIO(text)), [])
    if len(header) != len(MOVIE_COLUMNS) or set(header) != set(MOVIE_COLUMNS):
        raise ValueError(f"CSV must contain exactly these columns: {MOVIE_COLUMNS}")
    df = pd.read_csv(StringIO(text), on_bad_lines="error")
    if df.empty:
        raise ValueError("CSV must contain at least one data row")
    return df[MOVIE_COLUMNS]


def setup_logging(verbose: bool = False) -> None:
    """Configure console logging, enabling DEBUG output in verbose mode."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
        datefmt="%H:%M:%S",
        force=True,
    )
