<!-- EXAMPLE filled calibration log (fictional). Append-only. Each entry pairs a
     confident, checkable prediction with the later outcome, so over time you can
     see whether "I'm 80% sure" is actually right 80% of the time. See rules/quality.md. -->

# Calibration log

## 2026-01-12 — "the N+1 query is the bottleneck"
- **Claim:** the slow `/dashboard` endpoint is an N+1 in the orders loader; fixing it
  gets us under 200ms. Confidence: 0.75. Tier: read-the-code (didn't profile yet).
- **Could-be-wrong-if:** the time is actually in JSON serialization, not the queries.
- **Outcome (2026-01-13):** PARTLY RIGHT. The N+1 was real (-40%), but serialization
  was the bigger half. Landed at 240ms, not <200. Lesson: I asserted a profiling
  result from static reading — should have profiled first. Downgrade "read-the-code"
  perf claims to ~0.5 until measured.

## 2026-01-15 — "the re-entrant submit guard fixes the double-charge"
- **Claim:** disabling submit during the in-flight request eliminates the double
  charge. Confidence: 0.9. Tier: ran (reproduced the bug, then the fix locally).
- **Outcome:** RIGHT. Reproduced 3/3 before, 0/20 after. High confidence was earned
  because it was ran-and-saw, not reasoned.
