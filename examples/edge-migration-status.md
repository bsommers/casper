---
title: Edge Cache Migration Status
author: Bill
date: 2026-11-18
---

# Edge Cache Migration Status

Status: Edge cache migration is on track at 84% global traffic cutover.
Owner: Priya Nair
Progress: Completed canary rollout across 14 regional clusters with p99 latency dropping from 49ms to 27ms.
Progress: Automated telemetry dashboards now report cache hit ratios and origin fallback errors every minute.
Risk: Legacy TLS 1.1 clients account for 1.2% of requests and remain blocked on client certificate rotation.
Risk: Origin failover drill uncovered a 4-second spike in connection retries during cold restarts.
Next step: Finish final cluster cutover on 2026-11-25 after validating dual-stack rollback routing.
Next step: Publish the updated runbook for on-call responders before the holiday freeze.
Decision: Recommended keeping dual-stack origin fallback enabled through December 15 to protect legacy callers.
Background: The migration replaces aging proxy nodes with unified edge workers to simplify routing and cut tail latency.
Metric: Cache hit ratio improved by +6.8% to 94.6% with $19,200 monthly egress savings.
Ask: Please approve the maintenance window on 2026-11-25 so the team can finish cutover.
