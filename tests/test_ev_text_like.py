from __future__ import annotations

from worker.pipeline.noo_rules import _ev_is_text_like


def test_ev_is_text_like_filters_codey_text():
    codey = """services:
  api:
    build: .
    environment:
      - DATABASE_URL=postgresql://..."""
    assert _ev_is_text_like(codey) is False


def test_ev_is_text_like_accepts_russian_sentence():
    text = "Цель урока: сформировать представление об алгоритме и научить применять его на практике."
    assert _ev_is_text_like(text) is True
