# Decision Memo

## Recommendation
Recommended keeping dual-stack origin fallback enabled through December 15 to protect legacy callers.

## Risks
Legacy TLS 1.1 clients account for 1.2% of requests and remain blocked on client certificate rotation.

## Next Steps & Asks
Finish final cluster cutover on 2026-11-25 after validating dual-stack undo change routing.

## Context
Edge cache migration is on track at 84% global traffic cutover.

## Evidence
Completed canary rollout across 14 regional clusters with p99 response time dropping from 49ms to 27ms.
