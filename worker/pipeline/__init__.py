"""Worker pipeline helpers.

We keep pipeline stages small and testable. Each stage consumes/produces plain
Python dicts that can be stored in DB / JSON artifacts.
"""
