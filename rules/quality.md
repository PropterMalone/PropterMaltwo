---
globs:
  - "**/*"
---
# Quality Standards (v0.2 — 2026-04-26)

> How to measure whether what we're producing is actually good. Apply to **load-bearing claims** — anything a reader (you, future-you, a researcher-AI, a teammate) would act on. Skip casual chat, intermediate planning, throwaway scripts.

## Three axes

### 1. Calibration
When you express confidence ("should work," "high confidence," "this is the right call"), be calibrated: at the rate you assert it, you should be right that often.

- **Hedge with numbers when load-bearing.** "I'm 70% on this" beats "I think so" — the number commits you and can be scored later.
- **Log confident assertions** when they're checkable later. Without a log, drift is silent.
- **Update on miss.** When predicted ≠ actual, name the gap explicitly.
- **Watch for round-number anchoring.** 0.5/0.7/0.9 spikes signal lazy estimation; if you find yourself clustering at 0.7, force a +/- 0.05 perturbation and ask which side feels right.

### 2. Falsifiability
Every load-bearing claim should answer "what would change my mind?" If you can't name a falsifier, the claim is a vibe.

- **State the could-be-wrong-if line** for non-trivial claims.
- **Concrete = a hostile reader can identify (a) what to observe, (b) how to check it, and (c) threshold where applicable.** "If the migration fails on the staging box during dual-write" beats "if there are unforeseen issues."
- **Vague-phrase blocklist** (rejects on review): "unforeseen", "edge cases", "if assumptions are wrong", "if I am wrong", "if the landscape shifts", "if circumstances change". One concrete falsifier beats three vague ones.

### 3. Verification tier (claims about your own work)
Never collapse these three when claiming about your own work:

- **Ran-and-saw-output** — strongest. The thing executed; you saw the result.
- **Read-the-code** — medium. Static reasoning, no runtime.
- **Recalled-from-memory / inferred** — weakest. Likely stale; verify before acting.

(For evidence about *external* artifacts being reviewed — third-party tools, datasets, specs — a project may define a parallel set of tiers in its own schema (e.g. an `evidence_level` field distinguishing artifact-verified vs. static-analysis vs. probe-result vs. hands-on). Don't conflate the two — own-work tier is about whether you ran your code; evidence-level tier is about how you know things about other people's code.)

## When to apply

Default depends on context:

- **Inside project subdirectories that produce or document outward-facing artifacts** (e.g. `takes/`, `methodology/`, `drivers/`, `docs/`, ADR/decision-record folders): load-bearing is the **default**. Per-project, the project's `CLAUDE.md` or `QUALITY.md` should specify which directories qualify and how to opt out per-block.
- **Everywhere else**: opt-in. Apply when it's a "this is correct" claim someone will act on.
- **Always skip**: chit-chat, intermediate scratch, debugging chatter, throwaway scripts.

**Heuristic**: would future-you be annoyed if this turned out wrong and there was no falsifier or confidence note? If yes, apply.

## Cross-references
- **3-strike rule** (CLAUDE.md): if 3 fixes haven't resolved it, your model of the problem is wrong — calibrate down, escalate.
- **Verification rule** (CLAUDE.md): never claim something passes without running it and seeing output. The verification-tier rule, in operational form.

## Self-conformance

This doc makes load-bearing claims. Per its own standard:

- **Claim**: the three axes (calibration, falsifiability, verification tier) capture the dominant quality dimensions for software/AI work.
  - Confidence: 0.7 | Tier: read-the-code
  - Could-be-wrong-if: a fourth axis turns out to be load-bearing in practice — e.g. *reproducibility* (could other people get the same answer with these inputs?) or *independence* (was the claim formed before the conclusion was desired?). Either would warrant a v0.3 expansion. Concrete signal: in /retro spot-audits, ≥2 quality misses are traceable to an axis not listed here.

- **Claim**: applying the discipline only to load-bearing claims is the right scope.
  - Confidence: 0.65 | Tier: read-the-code
  - Could-be-wrong-if: in motivated cases, "load-bearing" is consistently downgraded (>30% of borderline calls go to non-load-bearing in /retro spot-audits). Default-inversion for project areas is the first attempt to stop that — if it fails, the scope rule needs broader inversion.

- **Claim**: the framework should be revised when calibration drift, falsifier vacuity, scope abuse, or friction-kill triggers fire (per project QUALITY.md).
  - Confidence: 0.75 | Tier: read-the-code
  - Could-be-wrong-if: any of those triggers turn out unmeasurable in practice — e.g., we never resolve enough claims to compute a hit-rate. Concrete signal: 6 months in, no calibration scoring has actually been done.
