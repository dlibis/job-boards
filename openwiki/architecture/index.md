# Files

- [Ashby Jobs Output and Persistence Model](data-model.md) - Documents the scraper's CSV and JSON row shape, SQLite jobs table, upsert rules, and posting lifecycle semantics for first_seen, last_seen, and closed_at.
- [Ashby Jobs Runtime Architecture](overview.md) - Explains the two-phase architecture of the Ashby public job scraper, including board discovery, concurrent job scanning, output generation, and SQLite persistence.
