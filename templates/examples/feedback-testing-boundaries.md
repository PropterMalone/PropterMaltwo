<!-- EXAMPLE filled feedback memory (fictional). This is the body-level shape the
     memory system uses: frontmatter + rule-first + Why + How-to-apply. Lead with
     the rule; the Why lets future-you judge edge cases instead of following blindly. -->
---
name: feedback-testing-boundaries
description: Mock only unmanaged third-party boundaries, never our own DB — burned us once
metadata:
  type: feedback
---

Mock unmanaged dependencies (third-party HTTP APIs, SMTP) by wrapping them in a thin
local adapter and mocking the adapter. Use a real instance for managed dependencies
(our own database, our own filesystem).

**Why:** Last quarter a suite of fully-mocked tests went green while the production
migration was broken — the mocks encoded our *assumption* of the DB's behavior, not
its actual behavior, so the divergence was invisible until prod. A real test DB would
have failed loudly.

**How to apply:** When you're about to `vi.mock()` something, ask "do we own this?"
If yes, stand up a real instance in the test instead. If no, check there's a thin
wrapper to mock rather than mocking the SDK directly. See [[feedback-test-db-setup]]
for the docker-compose test-DB pattern.
