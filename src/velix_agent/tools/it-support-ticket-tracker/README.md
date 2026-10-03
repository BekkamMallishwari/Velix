# Mini IT Support Ticket System

A lightweight, local-first ticket tracker for a small organization. Employees can report internal IT issues, while support staff can triage, search, update, and resolve them. Ticket data stays in the current browser's local storage; there is no backend or remote service.

## Features

- Create tickets with a title, requester, category, priority, and description.
- Track ticket status as Open, In Progress, or Resolved.
- See live counts for each status.
- Search by ticket title or requester, and combine the search with status and category filters.
- Clear all filters without changing saved tickets.
- Identify high-priority and unresolved tickets with visible text labels and color.
- Delete an individual ticket only after confirming the action.
- See useful empty and all-tickets-resolved messages.
- Keep tickets across refreshes with browser `localStorage`.
- Use the responsive interface with a keyboard and assistive technology.

## Technology stack

- HTML5
- CSS3
- Vanilla JavaScript
- Browser `localStorage`

No frameworks, external libraries, build tools, backend, database, APIs, or remote resources are used.

## Setup

1. Open `index.html` in a modern browser, or open this folder in an editor and use its static-file preview.
2. Create a ticket using the form. The app stores it in that browser profile.
3. Refresh the page to restore saved tickets.

No installation or build step is required. Clearing the browser's site data removes locally saved tickets. Data is not shared between browsers or devices.

## Manual testing

1. Load the page with no saved data; confirm the zero counts and initial empty state.
2. Submit the form with every field blank, then with a whitespace-only title; confirm validation prevents creation and explains what needs attention.
3. Create a valid ticket; verify it appears with its requester, category, priority, Open status, description, and creation date, and that the Open count increases.
4. Change its status to In Progress and then Resolved; verify each count changes immediately and the unresolved/high-priority labels update as applicable.
5. Add more tickets, then search by a title fragment and requester name (case-insensitively).
6. Combine a search with status and category filters; verify only matching tickets appear. Use Clear filters and confirm all tickets return.
7. Refresh the page and confirm created tickets and their latest statuses persist.
8. Choose Delete and cancel the confirmation; verify the ticket and counts remain unchanged. Delete another ticket and confirm; verify it and its count are removed.
9. Resolve every remaining ticket with no active filters; confirm the all-resolved message. Try a filter with no matches and confirm the no-results message.
10. At desktop and narrow mobile widths, check the form and ticket layout, labels, focus visibility, keyboard navigation, and status text. Try a title containing HTML-like text and verify it is displayed as text, not interpreted as markup.