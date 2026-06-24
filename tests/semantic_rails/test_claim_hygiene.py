from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _text(*paths: str) -> str:
    return "\n".join((REPO_ROOT / path).read_text(encoding="utf-8") for path in paths)


def test_cloud_ready_docs_do_not_repeat_pre_server_claims():
    text = _text(
        "README.md",
        "docs/MCP_INTERFACE.md",
        "docs/CAPABILITIES.md",
        "docs/PACKAGE_AUTHORING.md",
    )

    assert "does not ship a production MCP server" not in text
    assert "does not define a stdio/SSE/HTTP transport command" not in text
    assert "Snow CLI is the supported connection kind" not in text
    assert "snowflake_native" in text
    assert "semantic-rails mcp stdio" in text
    assert "semantic-rails mcp http" in text


def test_website_cloud_claims_stay_bounded():
    text = _text(
        "website/index.html",
        "website/solutions.html",
        "website/comparisons.html",
        "website/pricing.html",
        "website/docs/api-reference.html",
        "website/docs/getting-started.html",
    ).lower()

    forbidden_positive_claims = [
        "hosted cloud is included",
        "managed acceleration is included",
        "full enterprise auth is included",
        "universal planner",
        "osi open source",
    ]
    for claim in forbidden_positive_claims:
        assert claim not in text
    assert "apache-2.0" in text or "apache 2.0" in text
    assert "open-source" in text or "open source" in text
    assert "docker" in text
    assert "mcp" in text
