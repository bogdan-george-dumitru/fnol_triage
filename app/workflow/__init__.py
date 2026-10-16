"""The business-owned workflow configuration.

`schema`  - the config contract (taxonomy, routing, flags, templates, thresholds).
`seed`    - a realistic starter config a claims-intake lead would recognise.

Versioned persistence (save / activate / rollback) lives in the SQLite adapter
(`app.persistence.sqlite.config`), behind the repository port.

Everything here is meant to be edited by a non-technical team through the config
UI (Stage 5), previewed against the sample set, versioned, and rolled back.
"""
