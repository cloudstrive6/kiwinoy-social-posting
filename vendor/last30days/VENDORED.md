# Vendored: last30days skill (scripts only)

Source: https://github.com/mvanhorn/last30days-skill (MIT, by mvanhorn)
Version: 3.3.2

Only `scripts/` is vendored (the CLI + lib). We call `last30days.py --emit json`
directly as the research data engine (free sources, deterministic plan). See
`core/last30days.py`. Original skill docs/agents/assets are not vendored.
