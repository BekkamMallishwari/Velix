# Project Engineering Rules

## Technology and structure
- Use only HTML, CSS, and vanilla JavaScript.
- Keep HTML, CSS, and JavaScript in separate files.
- Do not introduce frameworks, external libraries, build tools, or APIs.

## Coding standards
- Use clear, descriptive names.
- Prefer small functions with a single responsibility.
- Avoid duplicated logic and unnecessary complexity.
- Add comments only when they explain non-obvious behavior.

## Functional requirements
- Reject empty or whitespace-only ticket titles.
- Validate required fields before saving.
- Update status counts whenever tickets change.
- Persist ticket changes to localStorage.
- Handle missing, malformed, or invalid stored data without crashing.
- Confirm destructive actions such as deleting a ticket.

## Quality and accessibility
- Use semantic HTML and accessible labels.
- Support keyboard interaction and visible focus states.
- Make the interface responsive on desktop and mobile.
- Never use unsafe HTML injection to display user-entered values.
- Use readable text labels as well as colors to communicate priority and status.

## Working practices
- Inspect existing files before modifying them.
- Explain the implementation plan before broad changes.
- Preserve working behavior when adding features.
- Test main user flows where possible.
- Never claim a test passed unless it was actually executed.
- Summarize changes, assumptions, test results, and remaining verification.

## Design
- Use a blue-and-white theme.
- Do not use red as the primary UI color.
- Communicate priority and status using text labels as well as color.