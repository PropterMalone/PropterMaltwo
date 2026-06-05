---
globs:
  - "**/*.test.ts"
  - "**/*.test.tsx"
  - "**/*.spec.ts"
---
# Testing Standards

- **Coverage**: Test business logic, edge cases, error paths. Don't chase percentage on UI glue or trivial pass-throughs.
- **TDD**: Write the test first, watch it fail, then implement. Tests written after implementation are biased by it.
- **Colocate**: `foo.ts` → `foo.test.ts`
- **Mock boundaries**: Mock unmanaged dependencies (third-party HTTP APIs, SMTP). Real instances for managed deps (own DB, own filesystem). Create thin wrappers around third-party libs, mock the wrapper.
- **Errors**: Return explicitly (avoid throwing for expected failures).
- **New projects**: Add `--passWithNoTests` to vitest config.
