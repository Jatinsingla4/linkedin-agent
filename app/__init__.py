"""LinkedIn Agent — autonomous content pipeline.

A clean, layered package:
  - config / models / strings / logging_config : foundations
  - core    : http session, state store, scheduling
  - services: gemini, topics, images, pdf, telegram, linkedin
  - pipelines: one class per post type (regular / story / poll / carousel)
  - orchestrator + reporting: top-level coordination
"""

__version__ = "2.0.0"
