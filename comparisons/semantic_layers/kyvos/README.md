# Kyvos Comparison Notes

Kyvos is represented as a documentation-backed proprietary reference. This repo
does not contain a Kyvos instance, exported model, license-backed setup, or local
query runner, so no Kyvos row is included in output-consistency validation.

## Evidence Basis

Public Kyvos materials used for this comparison:

- Unified Semantic Foundation:
  https://www.kyvosinsights.com/semantic-layer/unified-semantic-foundation/
- Semantic Data Models:
  https://www.kyvosinsights.com/semantic-layer/widest-deepest-semantic-data-models/
- Data Interoperability:
  https://www.kyvosinsights.com/semantic-layer/unified-semantic-foundation/data-interoperability/
- Data and AI Governance:
  https://www.kyvosinsights.com/semantic-layer/unified-semantic-foundation/data-and-ai-governance/
- BI Performance:
  https://www.kyvosinsights.com/semantic-layer/bi-performance/
- Multidimensional Analytics:
  https://www.kyvosinsights.com/semantic-layer/multidimensional-analytics/
- Kyvos 2026.5 documentation overview:
  https://docs.support.kyvosinsights.com/wiki/spaces/KD20265/overview

Those sources describe a centrally governed semantic foundation with metrics,
dimensions, relationships, hierarchies, calculations, security, lineage, APIs,
MCP, LangChain connectivity, and standard BI/query interfaces. They do not
provide enough public detail to claim this benchmark's temporal-validity,
conversion-window, same-store, or metric-predicate primitives as executed or
first-class Kyvos semantics.

## Baseline Question Evidence

| Question | Status | Evidence basis |
| --- | --- | --- |
| q01_orders_by_month | doc_backed | Public materials describe centrally defined metrics, dimensions, hierarchies, time intelligence, and SQL/MDX/DAX query support. |
| q02_revenue_by_store_by_month | doc_backed | Public materials describe one definition for metrics, dimensions, relationships, and shared business logic across BI and AI tools. |
| q03_item_revenue_by_product_type_by_month | doc_backed | Public materials describe multidimensional models with measures, dimensions, attributes, and high-grain analysis. |
| q04_aov_by_store | doc_backed | Public materials describe calculations, derived semantics, and complex/semi-additive calculations. |
| q05_orders_and_item_revenue_by_store_by_month | doc_backed | Public materials describe unified semantic models, relationships, and hierarchies, but local mixed-grain aggregate locality is not executed. |
| q06_new_customer_orders_by_month | doc_backed | Public materials describe reusable calculations and governed business logic, but the new-customer predicate is not executed. |
| q07_delivered_revenue_by_month | doc_backed | Public materials describe time intelligence and complex calculations, but delivered-time revenue is not executed in this repo. |

## Stretch Question Evidence

| Question | Status | Reason |
| --- | --- | --- |
| q08_revenue_by_customer_segment_as_of_order_time | unsupported | Public materials do not establish a temporal-valid as-of join primitive equivalent to the benchmark requirement. |
| q09_session_to_order_conversion_7d | unsupported | Public materials do not establish a first-class event-pair conversion-window metric primitive. |
| q10_orders_from_customers_with_10plus_orders_in_month | unsupported | Public materials do not establish reusable aggregate-on-aggregate metric predicates. |
| q11_repeat_customer_orders_by_store_by_month | unsupported | Public materials do not establish the metric-predicate behavior this benchmark scores. |
| q12_orders_by_month_with_lifetime_spend_500_filter | unsupported | Public materials do not establish query-time metric-predicate filtering equivalent to this question. |
| q13_daily_orders_from_customers_with_10plus_orders_in_month | unsupported | Public materials do not establish preserving a monthly aggregate predicate while querying at day grain. |
| q14_revenue_from_customers_with_10plus_orders_same_store_month | unsupported | Public materials do not establish contextual same-store aggregate predicates equivalent to this question. |
| q15_same_store_session_to_order_conversion_7d | unsupported | Public materials do not establish same-store constrained conversion-window semantics. |
| q16_revenue_by_customer_segment_as_of_delivered_time | unsupported | Public materials do not establish a delivered-time temporal-valid join primitive equivalent to the benchmark requirement. |

## Reproduction Status

There is no local reproduction command for Kyvos in this pack. To promote Kyvos
from doc-backed to executed, the repo needs a reproducible setup path, sample
Kyvos model artifacts, query definitions, generated SQL or query logs where
available, normalized result artifacts, and output-consistency validation
against the shared comparison dataset.
