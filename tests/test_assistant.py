"""
Tests for the Invoice Query Assistant — STUBS for you to complete (Part 4).

Turn these into real, passing tests. The most important one is the PROPERTY
test: across every customer x every question, a response must never contain
another customer's invoice. Add your own cases too.

Run: pytest -q
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

import main  # noqa: E402


def test_happy_path_overdue_sysco():
    out = main.ask(1049, "Show me my overdue Sysco invoices")
    # TODO: assert the result contains only customer 1049's overdue Sysco rows.
    assert False, "implement me"


def test_malformed_json_degrades_to_no_answer():
    # TODO: the model returns malformed JSON for "how many invoices are open".
    # Assert the service returns an explicit no-answer instead of crashing.
    assert False, "implement me"


@pytest.mark.skip(reason="implement the cross-tenant property test")
def test_no_cross_tenant_leak():
    # TODO: for every customer x every question, assert no response contains
    # another customer's invoice.
    ...
