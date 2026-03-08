"""
Unit tests for codecontext.core.markdown_renderer.

Validates that FLOWS.md and SUMMARY.md rendering handles all node types
(FlowStep, FlowFork) without crashing and produces correct output.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Literal, Union
from unittest.mock import MagicMock

import pytest

from codecoverage.core.markdown_renderer import render_flows_markdown, render_summary_markdown
from codecoverage.web.flow_tracer import EntryPoint, FlowStep, FlowFork


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_entry_point(
    kind: Literal["http", "task", "signal", "command"] = "http",
    label: str = "MyView",
    call_chain=None,
    decoupled_flows=None,
    http_methods=None,
    url_path: str = "/api/test/",
) -> EntryPoint:
    return EntryPoint(
        kind=kind,
        label=label,
        description="A test entry point.",
        file="payments/views.py",
        http_methods=http_methods or ["POST"],
        url_path=url_path,
        call_chain=call_chain or [],
        decoupled_flows=decoupled_flows or [],
    )


def _make_step(name: str = "do_thing", file: str = "payments/service.py") -> FlowStep:
    return FlowStep(name=name, file=file, signature="", docstring="")


def _make_fork(*names: str) -> FlowFork:
    return FlowFork(
        alternatives=[FlowStep(name=n, file=f"{n}.py", signature="", docstring="") for n in names]
    )


# ---------------------------------------------------------------------------
# render_flows_markdown
# ---------------------------------------------------------------------------

class TestRenderFlowsMarkdown:

    def test_empty_entry_points_returns_string(self):
        result = render_flows_markdown([], "my-project", doc_cache=None)
        assert isinstance(result, str)

    def test_includes_project_name(self):
        result = render_flows_markdown([], "my-project", doc_cache=None)
        assert "my-project" in result

    def test_renders_http_entry_point(self):
        ep = _make_entry_point(kind="http", label="PaymentView", url_path="/api/pay/")
        result = render_flows_markdown([ep], "proj", doc_cache=None)
        assert "PaymentView" in result

    def test_renders_task_entry_point(self):
        ep = _make_entry_point(kind="task", label="send_email_task", http_methods=[], url_path="")
        result = render_flows_markdown([ep], "proj", doc_cache=None)
        assert "send_email_task" in result

    def test_renders_flowstep_in_call_chain(self):
        step = _make_step("process_payment", "payments/service.py")
        ep = _make_entry_point(call_chain=[step])
        result = render_flows_markdown([ep], "proj", doc_cache=None)
        assert "process_payment" in result

    def test_renders_flowfork_without_crashing(self):
        """FlowFork must not cause AttributeError ('name' missing)."""
        fork = _make_fork("ServiceA", "ServiceB")
        ep = _make_entry_point(call_chain=[fork])
        # Must not raise
        result = render_flows_markdown([ep], "proj", doc_cache=None)
        assert isinstance(result, str)

    def test_flowfork_shows_alternatives(self):
        fork = _make_fork("StrategyA", "StrategyB")
        ep = _make_entry_point(call_chain=[fork])
        result = render_flows_markdown([ep], "proj", doc_cache=None)
        assert "StrategyA" in result
        assert "StrategyB" in result

    def test_mixed_steps_and_forks_render(self):
        chain = [
            _make_step("validate"),
            _make_fork("GatewayA", "GatewayB"),
            _make_step("save_result"),
        ]
        ep = _make_entry_point(call_chain=chain)
        result = render_flows_markdown([ep], "proj", doc_cache=None)
        assert "validate" in result
        assert "GatewayA" in result
        assert "save_result" in result

    def test_fork_marked_as_fork(self):
        fork = _make_fork("X", "Y")
        ep = _make_entry_point(call_chain=[fork])
        result = render_flows_markdown([ep], "proj", doc_cache=None)
        assert "fork" in result.lower()

    def test_multiple_entry_points_all_rendered(self):
        eps = [
            _make_entry_point(label="ViewA"),
            _make_entry_point(label="ViewB"),
        ]
        result = render_flows_markdown(eps, "proj", doc_cache=None)
        assert "ViewA" in result
        assert "ViewB" in result

    def test_doc_cache_summary_shown_as_blockquote(self):
        doc_cache = MagicMock()
        doc_cache.get_summary.return_value = "Processes the payment request."
        ep = _make_entry_point(label="PayView")
        result = render_flows_markdown([ep], "proj", doc_cache=doc_cache)
        assert "Processes the payment request." in result


# ---------------------------------------------------------------------------
# render_summary_markdown
# ---------------------------------------------------------------------------

class TestRenderSummaryMarkdown:

    def _make_cache_with(self, entries: dict):
        """Create a minimal DocCache-like object."""
        cache = MagicMock()
        cache._data = entries
        cache.get_entry = lambda rel_file, func: entries.get(f"{rel_file}::{func}")
        return cache

    def test_empty_cache_returns_string(self):
        cache = self._make_cache_with({})
        result = render_summary_markdown(cache, "proj")
        assert isinstance(result, str)

    def test_includes_project_name(self):
        cache = self._make_cache_with({})
        result = render_summary_markdown(cache, "my-proj")
        assert "my-proj" in result

    def test_renders_function_summary(self):
        cache = self._make_cache_with({
            "payments/gateway.py::process": {
                "summary": "Processes a payment through the gateway.",
                "args": [],
                "returns": "dict",
            }
        })
        result = render_summary_markdown(cache, "proj")
        assert "process" in result
        assert "Processes a payment" in result

    def test_renders_multiple_functions(self):
        cache = self._make_cache_with({
            "payments/gateway.py::create": {"summary": "Creates a payment.", "args": [], "returns": ""},
            "payments/gateway.py::refund": {"summary": "Refunds a payment.", "args": [], "returns": ""},
        })
        result = render_summary_markdown(cache, "proj")
        assert "create" in result
        assert "refund" in result

    def test_skips_entries_without_double_colon(self):
        """Keys not in rel_file::func format should be ignored gracefully."""
        cache = self._make_cache_with({"malformed_key": {"summary": "ignored"}})
        result = render_summary_markdown(cache, "proj")
        assert isinstance(result, str)

    def test_test_refs_shown_when_present(self):
        cache = self._make_cache_with({
            "payments/gateway.py::process": {"summary": "Processes.", "args": [], "returns": ""},
        })
        # test_refs format: list of {"file": str, "tests": [str, ...]}
        test_refs_map = {
            "payments/gateway.py::process": [
                {"file": "tests/test_gateway.py", "tests": ["test_process"]}
            ]
        }
        result = render_summary_markdown(cache, "proj", test_refs_map=test_refs_map)
        assert "test_gateway.py" in result or "test_process" in result
