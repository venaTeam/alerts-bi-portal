"""Read-only review portal (design section 7.10).

Internal readers see every team's published weekly reviews, follow them over time, and
inspect individual alerts. They cannot start runs, publish, record decisions or change data.

The package is laid out by responsibility:

* :mod:`~alerts_bi_portal.app` - the application factory: GET-only routes, the network allowlist,
  security headers
* :mod:`~alerts_bi_portal.queries` - everything it reads, only through the ``portal_*`` views
* :mod:`~alerts_bi_portal.pages` - the server-rendered HTML
* :mod:`~alerts_bi_shared.ui.explain` - plain-language reasons, next steps and decision questions
* :mod:`~alerts_bi_shared.ui.charts` - the weekly history charts, as inline SVG
* :mod:`~alerts_bi_shared.ui.assets` - the one stylesheet
* :mod:`~alerts_bi_portal.server` - running it under uvicorn

It deliberately imports nothing from :mod:`alerts_bi_runs.api`, :mod:`alerts_bi_runs.run`, :mod:`alerts_bi_runs.es`,
:mod:`alerts_bi_runs.llm` or :mod:`alerts_bi_operations.review`: there is no path from a reader's request to the run
pipeline, the unauthenticated run endpoint, Elasticsearch, the model, or an operator write.
"""
