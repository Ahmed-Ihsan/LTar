## Summary

Brief description of what this PR changes and why.

## Type of Change

- [ ] Bug fix (non-breaking)
- [ ] New feature (non-breaking)
- [ ] Breaking change (fix or feature that would cause existing functionality not to work as expected)
- [ ] Documentation update
- [ ] Test improvement
- [ ] Refactor (no behavior change)

## Related Issues

Closes #<issue_number>

## OpenSpec

- [ ] Specs reviewed: read relevant `openspec/specs/<capability>/spec.md` before coding
- [ ] Specs validated: `openspec validate --all` passes (0 failures)
- [ ] Change proposal created/updated if behavior changes (see `openspec/changes/`)
- [ ] Delta specs use ADDED/MODIFIED/REMOVED markers with Given/When/Then scenarios

### Linked OpenSpec Change (if applicable)

Change name: `<change-name>` (e.g., `refactor-to-component-architecture`)
- [ ] `proposal.md` written and validated
- [ ] `specs/` delta specs written and validated
- [ ] `design.md` written and validated
- [ ] `tasks.md` written and all tasks checked off
- [ ] Change archived: `openspec archive <change-name>`

If this PR does not modify behavior (pure refactor, test-only, docs-only), explain why no
OpenSpec change is needed:

> _<your explanation here, or "N/A — behavior unchanged">_

## Changes Made

- Change 1
- Change 2

## Testing

- [ ] All existing tests pass: `python -m pytest tests/ -q`
- [ ] Lint passes on changed files: `python -m ruff check <changed files>`
- [ ] Type-check passes: `mypy src/`
- [ ] New tests added for new functionality
- [ ] Manual testing performed (describe below)

### Manual Testing (if applicable)

Describe what you tested manually and the results.

## Checklist

- [ ] Code follows the project's style guidelines (ruff clean on changed files)
- [ ] Self-review completed
- [ ] Comments added for complex logic (only where necessary)
- [ ] Documentation updated (README, AGENTS.md, etc.) if needed
- [ ] No new dependencies without justification
- [ ] OpenSpec specs reflect the current behavior after this PR
