from __future__ import annotations

import ast
from pathlib import Path


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def _find_function(tree: ast.AST, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"function {name} not found")


def test_jobs_get_job_requires_chat_id_parameter():
    src = _read("api/routers/jobs.py")
    tree = ast.parse(src)
    fn = _find_function(tree, "get_job")
    arg_names = [a.arg for a in fn.args.args]
    assert arg_names == ["job_id", "chat_id"]


def test_artifacts_list_requires_chat_id_parameter():
    src = _read("api/routers/artifacts.py")
    tree = ast.parse(src)
    fn = _find_function(tree, "list_artifacts")
    arg_names = [a.arg for a in fn.args.args]
    assert arg_names == ["doc_id", "chat_id"]


def test_bot_api_client_passes_chat_id_to_job_endpoint():
    src = _read("bot/services/api_client.py")
    assert '/v1/jobs/{job_id}?chat_id={chat_id}' in src


def test_smoke_and_ci_use_chat_scoped_job_endpoint():
    smoke = _read("scripts/smoke_test.ps1")
    ci = _read("scripts/ci_smoke.py")
    assert '/v1/jobs/${jobId}?chat_id=$ChatId' in smoke
    assert '/v1/jobs/{job_id}?chat_id={chat_id}' in ci

