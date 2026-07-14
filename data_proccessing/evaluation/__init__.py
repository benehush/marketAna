"""Evaluation helpers for the standalone pipeline."""

from data_proccessing.evaluation.metrics import calculate_metrics
from data_proccessing.evaluation.runner import evaluate_dataset

__all__ = ["calculate_metrics", "evaluate_dataset"]
