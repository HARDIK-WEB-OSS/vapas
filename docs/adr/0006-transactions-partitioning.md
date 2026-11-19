# ADR 0006: Partition the transactions table by month of txn_date, from the start

Status: accepted (M0.5, 19 Nov 2026)

## Context
At 100k users the table grows by about 80 million rows (about 33 GB) per month and reaches about 790 GB after 2 years without retention (system_design.md section 2.3). Matching only looks at one user's transactions in a short date window. Retention and data minimisation require deleting old rows in bulk. Converting a large table to a partitioned one later requires a full rewrite.

## Options
1. One plain table with indexes; add partitioning when it starts to hurt.
2. Hash partitioning by user_id.
3. Range partitioning by month of `txn_date`.

## Decision
Option 3, built in M1/M3. Primary and unique keys include `txn_date`. A maintenance job creates partitions ahead of time; a DEFAULT partition catches out-of-range rows and raises an alert. RLS policies are defined on the parent table, and the app roles have no direct grants on partitions. Findings keep an encrypted snapshot of the facts they need, so dropping a partition never breaks a finding or a case.

## Consequences
- Queries with a date range prune to one or two partitions.
- Retention is a `DROP` of a partition: instant, with no vacuum storm.
- Every unique constraint and foreign key that references transactions must include `txn_date`, which makes keys wider.
- Partition maintenance is one more scheduled job that must be monitored.
- Hash partitioning by user is not chosen: it does not help retention, and the per-user index already serves per-user lookups.
