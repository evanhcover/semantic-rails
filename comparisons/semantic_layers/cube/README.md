# Cube Comparison Project

Pinned packages:

- `@cubejs-backend/server@1.6.32`
- `@cubejs-backend/duckdb-driver@1.6.32`
- `cubejs-cli@1.6.32`

This project uses the shared `comparison_*` views inside `comparisons/semantic_layers/shared/data/jaffle_comparison.duckdb`.

Install and run:

```bash
npm_config_cache=/tmp/codex-npm-cache npm install
npm run dev
```

Then execute the comparison capture:

```bash
uv run python comparisons/semantic_layers/cube/scripts/run_questions.py
```

Artifacts are written under `comparisons/semantic_layers/shared/results/cube/`.

Notes:

- `docker` is not installed in this environment, so this comparison uses the local Node/Cube Core path instead of a Docker launch.
- `customer_history` and `storefront_sessions` are modeled with explicit SQL joins / calculated measures, which is intentional evidence for the “workaround-heavy but possible” side of the comparison.
