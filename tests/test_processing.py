import pandas as pd
import pytest

from data_pipeline import create_cleaning_report, process_data, validate_dataframe
from src import ProcessConfig


def test_defaults_are_independent():
    first, second = ProcessConfig(), ProcessConfig()
    first.validation.numeric_columns.append("score")
    first.processing.outliers.columns.append("score")
    first.processing.missing.enabled = False
    assert second.validation.numeric_columns == []
    assert second.processing.outliers.columns == []
    assert second.processing.missing.enabled is True


@pytest.mark.parametrize("method,threshold", [("iqr", 1.5), ("zscore", 1.5)])
def test_outliers(method, threshold):
    source = pd.DataFrame({"score": [10, 10, 11, 11, 1000]})
    config = ProcessConfig.model_validate({"processing": {
        "remove_duplicates": False,
        "outliers": {"enabled": True, "columns": ["score"], "method": method,
                     "threshold": threshold},
    }})
    result = process_data(source, config.model_dump())
    assert result["score"].tolist() == [10, 10, 11, 11]
    assert len(source) == 5


def test_missing_columns_and_validation_copy():
    source = pd.DataFrame({"score": ["80", "bad", None], "optional": [1, 2, 3]})
    original = source.copy(deep=True)
    validated = validate_dataframe(source, ["score"], ["score"])
    assert len(validated) == 2
    pd.testing.assert_frame_equal(source, original)
    config = ProcessConfig.model_validate({"processing": {"missing": {"axis": "columns"}}})
    result = process_data(validated, config.model_dump())
    assert result.columns.tolist() == ["optional"]
    assert create_cleaning_report(validated, result) == {
        "rows_before": 2, "rows_after": 2, "rows_removed": 0,
        "columns_before": 2, "columns_after": 1, "columns_removed": 1,
    }
