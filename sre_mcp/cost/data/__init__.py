import os

from .base import DataSource


def get_data_source() -> DataSource:
    """Pick the data source from COST_DATA_SOURCE: mock (default) or bigquery (billing export)."""
    kind = os.getenv("COST_DATA_SOURCE", "mock").lower()
    if kind == "mock":
        from .mock_source import MockDataSource

        return MockDataSource()
    if kind == "bigquery":
        from .bigquery_source import BigQueryDataSource

        return BigQueryDataSource()
    raise NotImplementedError(f"COST_DATA_SOURCE='{kind}' is not built yet. Use 'mock' or 'bigquery'.")
