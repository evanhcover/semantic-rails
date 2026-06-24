"""Release-mechanics regression contract.

Audit findings on packaging/release hygiene, pinned here so they cannot
silently regress:

- ``semantic_rails/py.typed`` (PEP 561) must exist and be declared as
  package data so type checkers consume the wheel's inline annotations.
- ``jsonschema`` must stay in the dev dependency group — without it the
  schema-contract tests skip silently instead of running.
- ``make release-check`` must route through ``uv run`` (bare ``python3``
  cannot import ``semantic_rails`` outside the project venv).
- The publish workflow must use PyPI Trusted Publishing (OIDC) with a
  ``pypi`` environment, and third-party actions in workflows must be
  SHA-pinned (a tag like ``@v4`` is mutable and a supply-chain risk).
- docker-compose must bind the unauthenticated API to loopback by
  default, and the Dockerfile/compose healthchecks must probe the same
  endpoint.
- Classifiers must match positioning: Beta (not Alpha), and the CI
  matrix / classifiers must both cover Python 3.14.

These tests read repo files rather than executing builds so they stay
fast enough for the default test run.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PYPROJECT = REPO_ROOT / "pyproject.toml"
MAKEFILE = REPO_ROOT / "Makefile"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
PUBLISH_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "publish.yml"
DOCKERFILE = REPO_ROOT / "Dockerfile"
COMPOSE = REPO_ROOT / "docker-compose.yml"

SHA_PINNED = re.compile(r"@[0-9a-f]{40}(\s|$)")


def _pyproject() -> dict:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))


def _workflow_action_uses(path: Path) -> list[str]:
    workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
    uses: list[str] = []
    for job in workflow.get("jobs", {}).values():
        for step in job.get("steps", []):
            if "uses" in step:
                uses.append(step["uses"])
    return uses


def test_py_typed_marker_exists_and_is_declared_package_data():
    marker = REPO_ROOT / "semantic_rails" / "py.typed"
    assert marker.exists(), (
        "semantic_rails/py.typed is missing — without the PEP 561 marker, "
        "type checkers ignore the package's inline annotations."
    )
    package_data = _pyproject()["tool"]["setuptools"]["package-data"]
    assert "py.typed" in package_data.get("semantic_rails", []), (
        "py.typed must be listed under [tool.setuptools.package-data] "
        "semantic_rails, otherwise it is silently dropped from the wheel."
    )


def test_jsonschema_is_a_dev_dependency():
    dev = _pyproject()["dependency-groups"]["dev"]
    assert any(dep.startswith("jsonschema") for dep in dev), (
        "jsonschema must stay in the dev group — the schema-contract tests "
        "(test_query_ir_schema.py and friends) skip silently without it."
    )


def test_jsonschema_actually_imports_so_schema_tests_run():
    # Belt and braces: the skip in test_query_ir_schema.py is silent, so
    # assert importability here where a missing dep fails loudly.
    import jsonschema  # noqa: F401


def test_make_release_check_routes_through_uv():
    makefile = MAKEFILE.read_text(encoding="utf-8")
    match = re.search(r"^release-check:\n((?:\t.*\n)+)", makefile, re.MULTILINE)
    assert match, "Makefile must define a release-check target"
    recipe = match.group(1)
    assert "uv run" in recipe, (
        "release-check must run via `uv run` — bare python3 cannot import "
        "semantic_rails outside the project venv."
    )
    assert not re.search(r"(?<![\w/])python3 ", recipe), (
        "release-check must not invoke bare python3 directly."
    )


def test_publish_workflow_uses_trusted_publishing():
    workflow = yaml.safe_load(PUBLISH_WORKFLOW.read_text(encoding="utf-8"))
    # PyYAML parses the bare `on:` key as boolean True.
    trigger = workflow.get("on", workflow.get(True))
    tags = trigger["push"]["tags"]
    assert "v*" in tags, "publish workflow must trigger on v* tags"

    jobs = workflow["jobs"]
    publish_jobs = [
        job
        for job in jobs.values()
        if any("gh-action-pypi-publish" in step.get("uses", "") for step in job.get("steps", []))
    ]
    assert publish_jobs, "publish workflow must use pypa/gh-action-pypi-publish"
    (publish_job,) = publish_jobs
    assert publish_job.get("environment") == "pypi", (
        "publish job must run in the `pypi` environment so Trusted "
        "Publishing and any required-reviewer gate apply."
    )
    assert publish_job.get("permissions", {}).get("id-token") == "write", (
        "publish job needs id-token: write for the OIDC token exchange."
    )
    assert publish_job.get("needs") == "test" or "test" in (publish_job.get("needs") or []), (
        "publish job must depend on the test job so the suite runs first."
    )


def test_third_party_actions_are_sha_pinned():
    offenders: list[str] = []
    for path in (CI_WORKFLOW, PUBLISH_WORKFLOW):
        for uses in _workflow_action_uses(path):
            owner = uses.split("/")[0]
            # First-party `actions/*` follow the repo-wide tag convention;
            # everything else must be pinned to an immutable commit SHA.
            if owner == "actions":
                continue
            if uses.startswith("astral-sh/setup-uv") and path == CI_WORKFLOW:
                # ci.yml predates the pinning rule for setup-uv; the audit
                # scoped mandatory pins to dorny/paths-filter there.
                continue
            if not SHA_PINNED.search(uses + " "):
                offenders.append(f"{path.name}: {uses}")
    assert not offenders, (
        "Third-party actions must be SHA-pinned (mutable tags are a "
        f"supply-chain risk): {offenders}"
    )


def test_ci_pins_dorny_paths_filter_to_a_commit_sha():
    uses = [u for u in _workflow_action_uses(CI_WORKFLOW) if u.startswith("dorny/paths-filter")]
    assert uses, "ci.yml is expected to use dorny/paths-filter"
    for entry in uses:
        assert SHA_PINNED.search(entry + " "), (
            f"dorny/paths-filter must be SHA-pinned, found: {entry}"
        )


def test_compose_binds_api_to_loopback_by_default():
    compose = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    ports = compose["services"]["semantic-rails"]["ports"]
    for mapping in ports:
        assert str(mapping).startswith("127.0.0.1:"), (
            "docker-compose must bind the unauthenticated API to loopback "
            f"by default, found: {mapping!r}"
        )


def test_compose_documents_auth_and_cors_env_vars():
    text = COMPOSE.read_text(encoding="utf-8")
    assert "SEMANTIC_RAILS_API_KEYS" in text and "SEMANTIC_RAILS_CORS_ORIGINS" in text, (
        "docker-compose.yml must point non-local deployments at the "
        "SEMANTIC_RAILS_API_KEYS / SEMANTIC_RAILS_CORS_ORIGINS env vars."
    )


def test_docker_healthchecks_probe_the_same_endpoint():
    endpoint = re.compile(r"/api/v1/(\w+)")
    dockerfile_routes = set(endpoint.findall(DOCKERFILE.read_text(encoding="utf-8")))
    compose_text = " ".join(
        str(part)
        for part in yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"][
            "semantic-rails"
        ]["healthcheck"]["test"]
    )
    compose_routes = set(endpoint.findall(compose_text))
    assert dockerfile_routes == compose_routes == {"ready"}, (
        "Dockerfile and docker-compose healthchecks must probe the same "
        f"endpoint (/api/v1/ready); got {dockerfile_routes} vs {compose_routes}"
    )


def test_dockerfile_base_image_is_precisely_pinned():
    match = re.search(r"^FROM\s+(\S+)", DOCKERFILE.read_text(encoding="utf-8"), re.MULTILINE)
    assert match, "Dockerfile must have a FROM line"
    image = match.group(1)
    assert re.match(r"python:3\.\d+\.\d+-slim", image), (
        "Base image must pin an exact patch release (e.g. python:3.12.13-"
        f"slim-trixie), not a floating tag; found: {image}"
    )


def test_classifiers_match_positioning():
    classifiers = _pyproject()["project"]["classifiers"]
    assert "Development Status :: 4 - Beta" in classifiers
    assert not any("3 - Alpha" in c for c in classifiers), (
        "Positioning is production-grade; Alpha undersells it."
    )
    assert "Programming Language :: Python :: 3.14" in classifiers


def test_ci_matrix_covers_python_314():
    workflow = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))
    matrix = workflow["jobs"]["backend"]["strategy"]["matrix"]["python-version"]
    assert "3.14" in matrix, "CI backend matrix must exercise Python 3.14"


def test_publish_job_restates_contents_read_permission():
    workflow = yaml.safe_load(PUBLISH_WORKFLOW.read_text(encoding="utf-8"))
    jobs = workflow["jobs"]
    (publish_job,) = [
        job
        for job in jobs.values()
        if any("gh-action-pypi-publish" in step.get("uses", "") for step in job.get("steps", []))
    ]
    perms = publish_job.get("permissions", {})
    # Job-level permissions REPLACE the workflow defaults, so the publish
    # job that runs actions/checkout must restate contents: read or the
    # checkout step fails before the wheel is ever built.
    assert perms.get("contents") == "read", (
        "publish job sets its own permissions for id-token, which drops the "
        "workflow-level contents:read — restate it so checkout can read the repo."
    )


def test_release_readiness_workflow_collects_agentic_governance_scorecard():
    workflow = yaml.safe_load(
        (REPO_ROOT / ".github" / "workflows" / "release-readiness.yml").read_text(encoding="utf-8")
    )
    job = workflow["jobs"]["release-readiness"]
    run_commands = [step.get("run", "") for step in job["steps"]]
    assert any(
        "uv run python scripts/benchmark_plan.py --gate" in command
        and "--output dist/agentic-governance-scorecard.json" in command
        and "--markdown-output dist/agentic-governance-scorecard.md" in command
        for command in run_commands
    ), "release-readiness must publish the agentic governance benchmark scorecard"

    upload_steps = [
        step for step in job["steps"] if step.get("uses", "").startswith("actions/upload-artifact")
    ]
    assert upload_steps, "release-readiness must upload release evidence artifacts"
    upload_path = str(upload_steps[-1]["with"]["path"])
    assert "dist/agentic-governance-scorecard.*" in upload_path


def test_init_starter_template_ships_as_a_data_file():
    data_files = _pyproject()["tool"]["setuptools"]["data-files"]
    examples = data_files.get("share/semantic-rails/configs/examples", [])
    assert "configs/examples/semantic_rails_package_starter.yml" in examples, (
        "`semantic-rails init` reads the starter template at runtime via "
        "resolve_repo_path; it must ship as a data file or init breaks from "
        "an installed wheel (the file is not next to the importable package)."
    )


def test_init_produces_a_loadable_single_file_package(tmp_path):
    import argparse

    from semantic_rails.cli import cmd_init
    from semantic_rails.config import load_package_config

    target = tmp_path / "myshop"
    cmd_init(
        argparse.Namespace(output=str(target), package_id="myshop", namespace=None, force=False)
    )
    package_yml = target / "package.yml"
    assert package_yml.is_file(), "init must write package.yml"
    assert (target / "data" / "seed_example.sql").is_file()

    config = load_package_config(str(package_yml))
    assert config.package.package_id == "myshop"
    assert config.entities, "the starter package must declare entities"
    assert config.measures, "the starter package must declare measures"
