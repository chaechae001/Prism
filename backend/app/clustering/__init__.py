"""Local Clusterer implementation; importing it does not load DB configuration."""

from .adapter import NewsClusterer, run_batch

__all__ = ['NewsClusterer', 'run_batch']
