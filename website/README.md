# Semantic Rails Website

This directory contains the restored static marketing site for Semantic Rails.

## Positioning

The site keeps the historical visual system and multi-page structure, but the content reflects
the active direction of the repo:

- semantic layer engine
- graph-first package authoring
- guided query APIs
- planner-backed explainability
- dated comparison evidence
- evidence-gated relation-pipeline wording

It no longer presents the repo as a broader action or governance platform than the current runtime
actually supports, and it does not present arbitrary relation pipelines as shipped runtime
capability.

## Pages

- `index.html`
  Homepage with comparison-led evidence and Semantic Rails positioning.
- `solutions.html`
  Practical use cases: package authoring, agent query builders, and semantic debugging.
- `pricing.html`
  Repurposed licensing and adoption page aligned to the repo's actual license posture.
- `robots.txt` and `sitemap.xml`
  Crawl discovery files for the canonical extensionless public routes.
- `docs/`
  Static docs hub rewritten around the active CLI, package contract, guardrails,
  and `/api/v1/*` surface.

## Proof Sources

The site links directly to repo-backed evidence:

- `../comparisons/semantic_layers/`
- `../docs/README.md`
- `../docs/QUERY_API.md`
- `../docs/CAPABILITIES.md`

## Notes

- The site is static HTML/CSS/JS with no build step.
- Internal styling and layout were intentionally preserved to minimize surface churn.
- The comparison evidence pack remains standalone rather than being rebuilt inside this site.
