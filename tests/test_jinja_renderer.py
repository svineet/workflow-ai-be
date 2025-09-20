from __future__ import annotations

from app.blocks.base import Block
import pytest
from jinja2 import UndefinedError


def test_render_simple_upstream():
    b = Block(settings={})
    tmpl = "Hi {{ user.name }}"
    upstream = {"user": {"name": "Alice"}}
    assert b.render_expression(tmpl, upstream=upstream) == "Hi Alice"


def test_render_missing_variables_raise():
    b = Block(settings={})
    tmpl = "X {{ nope.foo }} Y"
    with pytest.raises(UndefinedError):
        b.render_expression(tmpl, upstream={})


def test_render_settings_and_trigger():
    b = Block(settings={"company": "Acme"})
    tmpl = "{{ settings.company }} - {{ trigger.id }}"
    result = b.render_expression(tmpl, upstream={}, extra={"settings": b.settings, "trigger": {"id": 123}})
    assert result == "Acme - 123"


def test_render_non_string_template():
    b = Block(settings={})
    assert b.render_expression(123, upstream={}) == "123" 