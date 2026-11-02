"""Read-only BigQuery cost tools. Costs are USD for the month in the data."""

from ..data import get_data_source


def query_saving(q: dict) -> float:
    """Estimated monthly saving if the suggested fix is applied."""
    return q["cost"] * q["est_saving_pct"] / 100


def get_bigquery_expensive_queries(limit: int = 5) -> dict:
    """Most expensive BigQuery queries with the problem found and the suggested fix.

    Args:
        limit: How many queries to return (default 5).
    """
    data = get_data_source().get_bigquery_queries()
    queries = sorted(data["queries"], key=lambda q: -q["cost"])[: max(1, limit)]
    rows = [{**q, "estimated_monthly_saving": round(query_saving(q), 2)} for q in queries]
    return {
        "status": "ok",
        "month": data["month"],
        "pricing_model": data["pricing_model"],
        "estimate": True,
        "assumptions": "Saving = query cost x expected reduction once the suggested fix is applied.",
        "expensive_queries": rows,
        "total_estimated_monthly_saving": round(sum(r["estimated_monthly_saving"] for r in rows), 2),
    }
