#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import venv
from pathlib import Path
from zipfile import ZipFile

REPO_ROOT = Path(__file__).resolve().parent.parent

REQUIRED_WHEEL_MEMBERS = {
    "semantic_rails/__init__.py",
    "semantic_rails/compiler_parts/__init__.py",
    "semantic_rails/config_parts/__init__.py",
    "semantic_rails/metadata_parts/__init__.py",
    "semantic_rails/runtime_parts/__init__.py",
}

REQUIRED_WHEEL_SUFFIXES = {
    "share/semantic-rails/configs/semantic_rails/jaffle_shop/package.yml",
    "share/semantic-rails/configs/semantic_rails/jaffle_shop/examples/core.yml",
    "share/semantic-rails/configs/semantic_rails/jaffle_shop/models/core/orders.yml",
    "share/semantic-rails/configs/semantic_rails/jaffle_shop/metrics/core/core_metrics.yml",
    "share/semantic-rails/configs/semantic_rails/jaffle_shop/segments/core.yml",
    # data/jaffle_shop.duckdb is intentionally NOT shipped in the wheel. The
    # runtime seeds it from raw_*.csv + seed_jaffle.sql on first use, so
    # bundling the file would (a) bloat the wheel and (b) break the build on
    # a clean git checkout where the file is gitignored.
    "share/semantic-rails/data/jaffle_csv/raw_orders.csv",
    "share/semantic-rails/data/seed_jaffle.sql",
}


def _run(
    cmd: list[str], *, cwd: Path, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(cmd, cwd=cwd, env=env, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        print(f"Command failed: {' '.join(cmd)}")
        if result.stdout.strip():
            print("stdout:")
            print(result.stdout)
        if result.stderr.strip():
            print("stderr:")
            print(result.stderr)
        raise SystemExit(result.returncode)
    return result


def _venv_python(venv_dir: Path) -> Path:
    unix = venv_dir / "bin" / "python"
    if unix.exists():
        return unix
    return venv_dir / "Scripts" / "python.exe"


def _build_wheel(output_dir: Path) -> Path:
    _run(["uv", "build", "--wheel", "--out-dir", str(output_dir)], cwd=REPO_ROOT)
    # The PyPI distribution is `semantic-rails` (wheel name `semantic_rails`),
    # while the import package is `semantic_rails`. Match either form to stay
    # compatible if the dist is renamed in the future.
    wheels = sorted(
        list(output_dir.glob("semantic_rails-*.whl"))
        + list(output_dir.glob("semantic_rails-*.whl")),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not wheels:
        print("Package distribution check failed:")
        print(" - uv build completed but no semantic-rails wheel was produced")
        raise SystemExit(1)
    return wheels[0]


def _assert_wheel_contents(wheel: Path) -> None:
    with ZipFile(wheel) as archive:
        names = set(archive.namelist())

    missing = sorted(REQUIRED_WHEEL_MEMBERS - names)
    missing_suffixes = sorted(
        suffix
        for suffix in REQUIRED_WHEEL_SUFFIXES
        if not any(name.endswith(suffix) for name in names)
    )
    if missing or missing_suffixes:
        print("Package distribution check failed:")
        print(f" - wheel is missing required package files: {wheel.name}")
        for member in missing:
            print(f"   - {member}")
        for suffix in missing_suffixes:
            print(f"   - *{suffix}")
        raise SystemExit(1)


def _assert_installed_wheel(wheel: Path, work_dir: Path) -> None:
    venv_dir = work_dir / "venv"
    venv.EnvBuilder(with_pip=True).create(venv_dir)
    python = _venv_python(venv_dir)
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)

    _run([str(python), "-m", "pip", "install", str(wheel)], cwd=work_dir, env=env)

    packages = _run([str(python), "-m", "semantic_rails", "packages"], cwd=work_dir, env=env)
    package_payload = json.loads(packages.stdout)
    if "jaffle_shop" not in package_payload.get("packages", []):
        print("Package distribution check failed:")
        print(" - installed wheel did not register built-in jaffle_shop package")
        raise SystemExit(1)

    catalog = _run(
        [str(python), "-m", "semantic_rails", "catalog", "--package", "jaffle_shop"],
        cwd=work_dir,
        env=env,
    )
    catalog_payload = json.loads(catalog.stdout)
    package_id = (
        catalog_payload.get("catalog", {}).get("meta", {}).get("package", {}).get("package_id")
    )
    if package_id != "jaffle_shop":
        print("Package distribution check failed:")
        print(" - installed wheel catalog did not load jaffle_shop")
        raise SystemExit(1)

    query = {
        "version": 1,
        "select": [{"expression": {"measure": "measure.jaffle.order_count"}, "as": "order_count"}],
        "limit": 1,
    }
    result = _run(
        [
            str(python),
            "-m",
            "semantic_rails",
            "query",
            "--package",
            "jaffle_shop",
            "--query-json",
            json.dumps(query),
        ],
        cwd=work_dir,
        env=env,
    )
    result_payload = json.loads(result.stdout)
    if not result_payload.get("rows"):
        print("Package distribution check failed:")
        print(" - installed wheel query returned no rows for jaffle_shop")
        raise SystemExit(1)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="semantic-rails-dist-") as tmp:
        work_dir = Path(tmp)
        wheel = _build_wheel(work_dir / "dist")
        _assert_wheel_contents(wheel)
        _assert_installed_wheel(wheel, work_dir)

    print(f"Package distribution check passed: {wheel.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
