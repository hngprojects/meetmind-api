## Description

<!-- Provide a clear and concise description of what this PR does. -->

## Type of Change

<!-- Mark the relevant option with an "x" -->

- [ ] `feat` — New feature
- [ ] `fix` — Bug fix
- [ ] `refactor` — Code refactoring (no functional change)
- [ ] `docs` — Documentation update
- [ ] `test` — Adding or updating tests
- [ ] `chore` — Maintenance (dependencies, CI, tooling)

## Related Issue

<!-- Link the issue this PR addresses. Use "Closes #123" to auto-close. -->

Closes #

## Changes Made

<!-- List the specific changes in bullet points. -->

-
-
-

## Proof of Work

<!-- 
REQUIRED: Provide evidence that your changes work correctly.

For API endpoints: paste the JSON request/response below.
For UI changes: attach screenshots.
-->

<details>
<summary>API Response / Screenshots</summary>

```json
// Paste your endpoint response here
// Example:
// POST /api/v1/meetings
// Status: 201 Created
// {
//   "id": "abc-123",
//   "title": "Sprint Planning",
//   "scheduled_at": "2026-05-10T10:00:00Z",
//   "duration_minutes": 30
// }
```

<!-- Or drag and drop screenshots here -->

</details>

## Test Cases

<!-- 
REQUIRED: All PRs must include meaningful test cases.

List the tests you added or updated. Tests must verify behavior, not just existence.
See CONTRIBUTING.md for examples of good tests.
-->

- [ ] Test case 1: `test_<action>_<expected_outcome>_<condition>`
- [ ] Test case 2: `test_<action>_<expected_outcome>_<condition>`

<details>
<summary>Test output</summary>

```bash
# Paste your test run output here
# uv run pytest tests/ -v
```

</details>

## Checklist

- [ ] My branch follows the naming convention (`<type>/<short-description>`)
- [ ] My commits follow [Conventional Commits](https://www.conventionalcommits.org/)
- [ ] I have added meaningful tests that cover success and failure paths
- [ ] All new and existing tests pass locally (`uv run pytest`)
- [ ] I have included proof of work (JSON responses or screenshots)
- [ ] I have updated documentation if needed
- [ ] My code follows the project's style guidelines
