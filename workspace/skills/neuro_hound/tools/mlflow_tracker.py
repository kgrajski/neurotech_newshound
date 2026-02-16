"""
MLflow integration — log parameters, metrics, and artifacts per run.

Wraps the existing UsageTracker data into MLflow experiment tracking,
giving you the MLflow UI for comparing runs over time.

Usage:
    from tools.mlflow_tracker import log_run
    log_run(final_state, tracker, duration, out_dir)
"""
import json
import os
from typing import Any, Dict, List

from tools.llm import UsageTracker


def _safe_import_mlflow():
    """Import mlflow, return None if not installed."""
    try:
        import mlflow
        return mlflow
    except ImportError:
        return None


def log_run(
    final_state: Dict[str, Any],
    tracker: UsageTracker,
    duration: float,
    out_dir: str,
    model: str = "",
    reviewer_model: str = "",
    days: int = 7,
    experiment_name: str = "neurotech-hound",
):
    """
    Log a complete run to MLflow.

    Parameters logged:
        model, reviewer_model, days, max_items, source_count

    Metrics logged:
        raw_count, prefiltered_count, scored_count, alert_count,
        theme_count, tokens_total, tokens_input, tokens_output,
        cost_usd, duration_seconds, llm_calls,
        reviewer_quality_score, categories (per-category counts)

    Artifacts logged:
        report.md, report.html, alerts.json, full.json
    """
    mlflow = _safe_import_mlflow()
    if mlflow is None:
        print("  [skip] MLflow not installed — skipping experiment tracking")
        return

    import datetime as dt
    today = dt.date.today().isoformat()

    # Set experiment
    mlflow.set_experiment(experiment_name)

    scored = final_state.get("scored_items", [])
    alerts = final_state.get("alerts", [])
    themes = final_state.get("themes", [])
    review = final_state.get("review", {})
    errors = final_state.get("errors", [])

    # Category breakdown
    cat_counts = {}
    for item in scored:
        cat = item.get("category", "unknown")
        cat_counts[cat] = cat_counts.get(cat, 0) + 1

    # Source breakdown
    source_counts = {}
    for item in final_state.get("raw_items", []):
        sid = item.get("source_id", item.get("source", "unknown"))
        source_counts[sid] = source_counts.get(sid, 0) + 1

    with mlflow.start_run(run_name=f"hound-{today}"):
        # Parameters
        mlflow.log_param("model", model)
        mlflow.log_param("reviewer_model", reviewer_model)
        mlflow.log_param("days", days)
        mlflow.log_param("max_items", final_state.get("max_items", 40))
        mlflow.log_param("source_count", len(source_counts))
        mlflow.log_param("date", today)

        # Core metrics
        mlflow.log_metric("raw_count", len(final_state.get("raw_items", [])))
        mlflow.log_metric("prefiltered_count", len(final_state.get("prefiltered_items", [])))
        mlflow.log_metric("scored_count", len(scored))
        mlflow.log_metric("alert_count", len(alerts))
        mlflow.log_metric("theme_count", len(themes))
        mlflow.log_metric("error_count", len(errors))

        # Token/cost metrics
        mlflow.log_metric("tokens_input", tracker.input_tokens)
        mlflow.log_metric("tokens_output", tracker.output_tokens)
        mlflow.log_metric("tokens_total", tracker.input_tokens + tracker.output_tokens)
        mlflow.log_metric("llm_calls", tracker.calls)
        mlflow.log_metric("cost_usd", tracker.estimate_cost(model))
        mlflow.log_metric("duration_seconds", duration)

        # Reviewer quality
        quality = review.get("quality_score")
        if quality is not None:
            mlflow.log_metric("reviewer_quality", quality)

        # Per-category counts
        for cat, count in cat_counts.items():
            mlflow.log_metric(f"cat_{cat}", count)

        # Per-source counts
        for sid, count in source_counts.items():
            mlflow.log_metric(f"src_{sid}", count)

        # Log artifacts
        artifact_patterns = [
            (f"{today}.md", "report"),
            (f"{today}.html", "report"),
            (f"{today}.alerts.json", "alerts"),
            (f"{today}.full.json", "results"),
        ]
        for filename, subdir in artifact_patterns:
            filepath = os.path.join(out_dir, filename)
            if os.path.exists(filepath):
                mlflow.log_artifact(filepath, artifact_path=subdir)

    print(f"  [ok] MLflow run logged: {experiment_name}/{today}")
