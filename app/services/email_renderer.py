"""Simple Jinja2 email template renderer."""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"

env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
)


def render_template(template_name: str, **context) -> str:
    """Render a template from the app/templates folder.

    Args:
        template_name: Template path relative to app/templates
        (e.g. "emails/reset_password.html").
        context: Variables passed to the template.

    Returns:
        Rendered HTML as a string.
    """
    template = env.get_template(template_name)
    return template.render(**context)
