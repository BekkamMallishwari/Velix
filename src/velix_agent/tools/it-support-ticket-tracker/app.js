(() => {
  "use strict";

  const STORAGE_KEY = "mini-it-support-tickets-v1";
  const STATUSES = ["Open", "In Progress", "Resolved"];
  const CATEGORIES = ["Hardware", "Software", "Network", "Access"];
  const PRIORITIES = ["Low", "Medium", "High"];

  const elements = {
    form: document.querySelector("#ticket-form"),
    title: document.querySelector("#ticket-title"),
    requester: document.querySelector("#ticket-requester"),
    category: document.querySelector("#ticket-category"),
    priority: document.querySelector("#ticket-priority"),
    description: document.querySelector("#ticket-description"),
    search: document.querySelector("#ticket-search"),
    statusFilter: document.querySelector("#status-filter"),
    categoryFilter: document.querySelector("#category-filter"),
    clearFilters: document.querySelector("#clear-filters"),
    list: document.querySelector("#ticket-list"),
    emptyState: document.querySelector("#empty-state"),
    emptyTitle: document.querySelector("#empty-title"),
    emptyDescription: document.querySelector("#empty-description"),
    allResolved: document.querySelector("#all-resolved"),
    feedback: document.querySelector("#feedback-message"),
    openCount: document.querySelector("#open-count"),
    progressCount: document.querySelector("#progress-count"),
    resolvedCount: document.querySelector("#resolved-count"),
    total: document.querySelector("#ticket-total")
  };

  let tickets = loadTickets();

  function isValidTicket(ticket) {
    return ticket !== null &&
      typeof ticket === "object" &&
      typeof ticket.id === "string" && ticket.id.length > 0 &&
      typeof ticket.title === "string" && ticket.title.trim().length > 0 &&
      typeof ticket.requester === "string" && ticket.requester.trim().length > 0 &&
      CATEGORIES.includes(ticket.category) &&
      PRIORITIES.includes(ticket.priority) &&
      STATUSES.includes(ticket.status) &&
      typeof ticket.description === "string" &&
      typeof ticket.createdAt === "string";
  }

  function loadTickets() {
    try {
      const storedValue = localStorage.getItem(STORAGE_KEY);
      if (storedValue === null) return [];
      const parsed = JSON.parse(storedValue);
      return Array.isArray(parsed) ? parsed.filter(isValidTicket) : [];
    } catch {
      return [];
    }
  }

  function saveTickets() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(tickets));
      return true;
    } catch {
      showFeedback("Tickets changed in this page, but this browser could not save them. Check your browser storage settings.", "error");
      return false;
    }
  }

  function showFeedback(message, kind = "success") {
    elements.feedback.textContent = message;
    elements.feedback.dataset.kind = kind;
    elements.feedback.hidden = false;
  }

  function clearFeedback() {
    elements.feedback.textContent = "";
    elements.feedback.hidden = true;
    delete elements.feedback.dataset.kind;
  }

  function createElement(tagName, className, text) {
    const element = document.createElement(tagName);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = text;
    return element;
  }

  function createBadge(text, className) {
    return createElement("span", `ticket-badge ${className}`, text);
  }

  function formatDate(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "Date unavailable";
    return new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(date);
  }

  function makeTicketId() {
    if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
      return crypto.randomUUID();
    }
    return `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  }

  function createStatusSelect(ticket) {
    const select = document.createElement("select");
    select.className = "status-select";
    select.setAttribute("aria-label", `Status for ${ticket.title}`);
    STATUSES.forEach((status) => {
      const option = document.createElement("option");
      option.value = status;
      option.textContent = status;
      option.selected = ticket.status === status;
      select.append(option);
    });
    select.addEventListener("change", () => {
      const currentTicket = tickets.find((item) => item.id === ticket.id);
      if (!currentTicket || !STATUSES.includes(select.value)) return;
      currentTicket.status = select.value;
      const saved = saveTickets();
      render();
      if (saved) showFeedback(`Status updated to ${currentTicket.status}.`);
    });
    return select;
  }

  function createDeleteButton(ticket) {
    const button = createElement("button", "delete-button", "Delete");
    button.type = "button";
    button.setAttribute("aria-label", `Delete ${ticket.title}`);
    button.addEventListener("click", () => {
      if (!window.confirm(`Delete "${ticket.title}"? This cannot be undone.`)) return;
      tickets = tickets.filter((item) => item.id !== ticket.id);
      const saved = saveTickets();
      render();
      if (saved) showFeedback("Ticket deleted.");
    });
    return button;
  }

  function createTicketCard(ticket) {
    const card = createElement("article", "ticket-card");
    if (ticket.priority === "High") card.classList.add("priority-high");
    if (ticket.status !== "Resolved") card.classList.add("is-unresolved");

    const topLine = createElement("div", "ticket-topline");
    const heading = createElement("div", "ticket-heading");
    heading.append(createElement("h3", "ticket-title", ticket.title));
    const meta = createElement("div", "ticket-meta");
    meta.append(createElement("span", "", `Requested by ${ticket.requester}`));
    meta.append(createElement("span", "", ticket.category));
    heading.append(meta);

    const actions = createElement("div", "ticket-actions");
    actions.append(createStatusSelect(ticket), createDeleteButton(ticket));
    topLine.append(heading, actions);

    const badges = createElement("div", "ticket-badges");
    const priorityClass = ticket.priority === "High" ? "badge-high" : ticket.priority === "Medium" ? "badge-medium" : "badge-low";
    const statusClass = ticket.status === "Resolved" ? "badge-resolved" : ticket.status === "In Progress" ? "badge-progress" : "badge-open";
    badges.append(createBadge(`${ticket.priority} priority`, priorityClass));
    badges.append(createBadge(ticket.status, statusClass));
    if (ticket.status !== "Resolved") badges.append(createBadge("Unresolved", "badge-open"));

    card.append(topLine, badges);
    card.append(createElement("p", "ticket-description", ticket.description));
    card.append(createElement("time", "ticket-date", `Created ${formatDate(ticket.createdAt)}`));
    card.querySelector("time").dateTime = ticket.createdAt;
    return card;
  }

  function getVisibleTickets() {
    const searchTerm = elements.search.value.trim().toLocaleLowerCase();
    const status = elements.statusFilter.value;
    const category = elements.categoryFilter.value;
    return tickets.filter((ticket) => {
      const matchesSearch = !searchTerm || ticket.title.toLocaleLowerCase().includes(searchTerm) || ticket.requester.toLocaleLowerCase().includes(searchTerm);
      return matchesSearch && (status === "All" || ticket.status === status) && (category === "All" || ticket.category === category);
    });
  }

  function renderCounts() {
    elements.openCount.textContent = String(tickets.filter((ticket) => ticket.status === "Open").length);
    elements.progressCount.textContent = String(tickets.filter((ticket) => ticket.status === "In Progress").length);
    elements.resolvedCount.textContent = String(tickets.filter((ticket) => ticket.status === "Resolved").length);
    elements.total.textContent = String(tickets.length);
  }

  function renderEmptyState(visibleTickets) {
    const hasActiveFilters = elements.search.value.trim() !== "" || elements.statusFilter.value !== "All" || elements.categoryFilter.value !== "All";
    const areAllResolved = tickets.length > 0 && tickets.every((ticket) => ticket.status === "Resolved") && !hasActiveFilters;
    elements.allResolved.hidden = !areAllResolved;
    elements.emptyState.hidden = visibleTickets.length > 0 || areAllResolved;

    if (tickets.length === 0 && !hasActiveFilters) {
      elements.emptyTitle.textContent = "No tickets yet";
      elements.emptyDescription.textContent = "New requests will appear here once they are submitted.";
    } else {
      elements.emptyTitle.textContent = "No matching tickets";
      elements.emptyDescription.textContent = "Try a different search or clear the filters to see more tickets.";
    }
  }

  function render() {
    renderCounts();
    const visibleTickets = getVisibleTickets();
    const fragment = document.createDocumentFragment();
    visibleTickets.forEach((ticket) => fragment.append(createTicketCard(ticket)));
    elements.list.replaceChildren(fragment);
    renderEmptyState(visibleTickets);
  }

  elements.form.addEventListener("submit", (event) => {
    event.preventDefault();
    clearFeedback();

    const title = elements.title.value.trim();
    const requester = elements.requester.value.trim();
    const category = elements.category.value;
    const priority = elements.priority.value;
    const description = elements.description.value.trim();

    if (!title || !requester || !CATEGORIES.includes(category) || !PRIORITIES.includes(priority) || !description) {
      showFeedback("Add a title, requester, category, priority, and description before saving.", "error");
      const firstInvalid = !title ? elements.title : !requester ? elements.requester : !CATEGORIES.includes(category) ? elements.category : !PRIORITIES.includes(priority) ? elements.priority : elements.description;
      firstInvalid.focus();
      return;
    }

    tickets.unshift({ id: makeTicketId(), title, requester, category, priority, description, status: "Open", createdAt: new Date().toISOString() });
    const saved = saveTickets();
    elements.form.reset();
    render();
    if (saved) showFeedback("Ticket created and added to the work queue.");
    elements.title.focus();
  });

  [elements.search, elements.statusFilter, elements.categoryFilter].forEach((control) => {
    control.addEventListener("input", render);
    control.addEventListener("change", render);
  });

  elements.clearFilters.addEventListener("click", () => {
    elements.search.value = "";
    elements.statusFilter.value = "All";
    elements.categoryFilter.value = "All";
    render();
    elements.search.focus();
  });

  render();
})();