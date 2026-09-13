"""Data acquisition layer: one connector per public source, plus a shared fetcher.

Connectors are deliberately independent modules (NFR-05, "modular connectors"). If one public
source changes its format or goes away, only that connector changes; the rest of the pipeline
does not care where an event came from, only that it arrives as a validated ``Event`` with a
``Source``.
"""
