const fallbackImage = "assets/tixly-hero.png";

const categoryIcons = {
  All: '<path d="M4 11.5h16M6 7h12M8 16h8" /><path d="M5 11.5c0 5 2 7.5 7 7.5s7-2.5 7-7.5S17 4 12 4s-7 2.5-7 7.5Z" />',
  Music: '<path d="M9 18V5l10-2v13" /><circle cx="6" cy="18" r="3" /><circle cx="16" cy="16" r="3" />',
  Sports: '<circle cx="12" cy="12" r="8" /><path d="M6.5 7.5c3 1.4 7 1.4 10 0M6.5 16.5c3-1.4 7-1.4 10 0M12 4c-2.3 2-3.4 4.7-3.4 8s1.1 6 3.4 8M12 4c2.3 2 3.4 4.7 3.4 8s-1.1 6-3.4 8" />',
  Conference: '<path d="M5 19V8h14v11" /><path d="M8 8V5h8v3M8 12h8M8 16h5" />',
  Comedy: '<path d="M7 5h10v6c0 4-2 7-5 8-3-1-5-4-5-8V5Z" /><path d="M9 10h.01M15 10h.01M10 14c1.2 1 2.8 1 4 0" />',
  Theater: '<path d="M5 4h14v7c0 5-3.2 8-7 9-3.8-1-7-4-7-9V4Z" /><path d="M9 9h.01M15 9h.01M9 14c2-1 4-1 6 0" />'
};

let selectedCategory = "All";
let events = [];
let selectedEventId = null;
let currentUser = JSON.parse(localStorage.getItem("tixlyUser") || "null");
let currentOrganizer = JSON.parse(localStorage.getItem("tixlyOrganizer") || "null");
let organizerEvents = [];
let editingEventId = null;
let authMode = "login";
let checkoutEvent = null;
let checkoutGuests = 1;
let checkoutDate = "";
let paymentInfo = { method: "Credit or debit card", last4: "1234" };
let lastTicket = null;

const money = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0
});

async function api(path, payload) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(data.error || "Something went wrong.");
    error.status = response.status;
    throw error;
  }
  return data;
}

async function getJson(path) {
  const response = await fetch(path);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(data.error || "Unable to load data.");
    error.status = response.status;
    throw error;
  }
  return data;
}

function setStatus(message, isError = false) {
  const status = document.querySelector("#formStatus");
  status.textContent = message;
  status.style.color = isError ? "#ffd7df" : "rgba(255, 255, 255, 0.84)";
}

function setProfileStatus(message, isError = false) {
  const status = document.querySelector("#profileStatus");
  status.textContent = message;
  status.style.color = isError ? "var(--accent-dark)" : "var(--muted)";
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;"
  })[character]);
}

function showProfile(isVisible = true){
  document.querySelector("#openUserProfileButton").hidden = !isVisible;
}

function showToast(message) {
  const existing = document.querySelector(".toast");
  if (existing) existing.remove();

  const toast = document.createElement("div");
  toast.className = "toast";
  toast.textContent = message;
  document.body.append(toast);
  window.setTimeout(() => toast.classList.add("show"), 20);
  window.setTimeout(() => {
    toast.classList.remove("show");
    window.setTimeout(() => toast.remove(), 180);
  }, 2400);
}

function getEvent(eventId) {
  return events.find((event) => event.id === Number(eventId));
}

function eventDescription(event) {
  return `${event.name} brings Tixly guests together at ${event.venue} in ${event.location}. Pick a date, choose your guest count, and complete the reservation with a short payment review before your ticket is issued.`;
}

function totalsFor(event, guests) {
  const subtotal = event.price * guests;
  const taxes = Math.round(subtotal * 0.1 * 100) / 100;
  return { subtotal, taxes, total: subtotal + taxes };
}

function moneyText(value) {
  return money.format(value);
}

function syncSession() {
  // const label = document.querySelector("#sessionLabel");
  const authNav = document.querySelector("#authNav");
  const sessionNav = document.querySelector("#sessionNav");
  const signOut = document.querySelector("#signOutButton");

  if (currentUser) {
    // label.textContent = `Signed in as ${currentUser.username}`;
    authNav.hidden = true;
    sessionNav.hidden = false;
    signOut.hidden = false;
    showProfile(true);
  } else {
    // label.textContent = "Not signed in";
    authNav.hidden = false;
    sessionNav.hidden = true;
    signOut.hidden = true;
    showProfile(false);
  }
}

function clearSession() {
  currentUser = null;
  localStorage.removeItem("tixlyUser");
  syncSession();
}

async function validateSavedSession() {
  if (!currentUser?.id) {
    clearSession();
    return;
  }

  try {
    const data = await getJson(`/api/users/${currentUser.id}`);
    currentUser = data.user;
    localStorage.setItem("tixlyUser", JSON.stringify(currentUser));
    syncSession();
  } catch (error) {
    clearSession();
  }
}

function openAuth(mode = "login") {
  authMode = mode;
  const modal = document.querySelector("#authModal");
  const title = document.querySelector("#authTitle");
  const subtitle = document.querySelector("#authSubtitle");
  const nameInput = document.querySelector("#nameInput");
  const submit = document.querySelector("#authSubmitButton");

  title.textContent = mode === "signup" ? "Register" : "Log in";
  subtitle.textContent =
    mode === "signup"
      ? "Create your Tixly account and start reserving event tickets."
      : "Log in to reserve tickets and keep orders connected to your account.";
  nameInput.hidden = mode !== "signup";
  nameInput.required = mode === "signup";
  submit.textContent = mode === "signup" ? "Register" : "Log in";
  setStatus("");
  modal.hidden = false;
  document.body.classList.add("modal-open");
  window.setTimeout(() => {
    (mode === "signup" ? nameInput : document.querySelector("#emailInput")).focus();
  }, 30);
}

function closeAuth() {
  document.querySelector("#authModal").hidden = true;
  document.body.classList.remove("modal-open");
}

function renderCategories() {
  const categories = ["All", ...new Set(events.map((event) => event.type))];
  const bar = document.querySelector("#categoryBar");

  bar.innerHTML = categories
    .map(
      (category) => `
        <button class="category-button ${category === selectedCategory ? "active" : ""}" type="button" data-category="${category}">
          <svg viewBox="0 0 24 24" aria-hidden="true">${categoryIcons[category] || categoryIcons.All}</svg>
          <span>${category}</span>
        </button>
      `
    )
    .join("");

  bar.querySelectorAll("button").forEach((button) => {
    button.addEventListener("click", () => {
      selectedCategory = button.dataset.category;
      renderCategories();
      renderEvents();
    });
  });
}

function getFilteredEvents() {
  const locationTerm = document.querySelector("#locationInput").value.trim().toLowerCase();
  const eventTerm = document.querySelector("#eventInput").value.trim().toLowerCase();

  return events.filter((event) => {
    const categoryMatch = selectedCategory === "All" || event.type === selectedCategory;
    const locationMatch = !locationTerm || event.location.toLowerCase().includes(locationTerm);
    const eventMatch =
      !eventTerm ||
      [event.name, event.type, event.venue, event.organizer].some((value) => value.toLowerCase().includes(eventTerm));

    return categoryMatch && locationMatch && eventMatch;
  });
}

function renderEvents() {
  const visibleEvents = getFilteredEvents();
  const grid = document.querySelector("#eventGrid");
  const resultCount = document.querySelector("#resultCount");

  resultCount.textContent = `${visibleEvents.length} event${visibleEvents.length === 1 ? "" : "s"} found`;

  if (!visibleEvents.length) {
    grid.innerHTML = '<p class="empty-state">No events matched your search.</p>';
    renderSpotlight(null);
    return;
  }

  grid.innerHTML = visibleEvents
    .map((event) => {
      const percentSold = Math.round((event.sold / event.capacity) * 100);
      return `
        <article class="event-card">
          <button class="event-card-button" type="button" data-event-id="${event.id}">
            <div class="image-wrap">
              <img src="${event.image}" alt="${event.name} at ${event.venue}" loading="lazy" style="object-position: ${event.imagePosition}" onerror="this.onerror=null;this.src='${fallbackImage}'" />
              <span class="badge">${percentSold}% sold</span>
            </div>
            <div class="event-copy">
              <div class="event-title-row">
                <h3>${event.name}</h3>
                <span class="rating">★ ${event.rating}</span>
              </div>
              <p>${event.location} · ${event.venue}</p>
              <small>${event.date} · Hosted by ${event.organizer}</small>
              <span class="price">${money.format(event.price)} per ticket</span>
            </div>
          </button>
        </article>
      `;
    })
    .join("");

  grid.querySelectorAll("[data-event-id]").forEach((button) => {
    button.addEventListener("click", () => {
      renderSpotlight(Number(button.dataset.eventId));
    });
  });

  renderSpotlight(visibleEvents[0].id);
}

function renderSpotlight(eventId) {
  const event = events.find((item) => item.id === eventId) ?? events[0];
  const spotlight = document.querySelector(".spotlight");
  if (!event) {
    selectedEventId = null;
    spotlight.hidden = true;
    return;
  }
  spotlight.hidden = false;
  selectedEventId = event.id;
  const image = document.querySelector("#spotlightImage");
  image.src = event.image;
  image.alt = event.name;
  image.style.objectPosition = event.imagePosition;
  image.onerror = () => {
    image.onerror = null;
    image.src = fallbackImage;
  };
  document.querySelector("#spotlightTitle").textContent = event.name;
  document.querySelector("#spotlightMeta").textContent =
    `${event.date} at ${event.venue}, ${event.location}. ${event.sold.toLocaleString()} tickets sold from ${event.capacity.toLocaleString()} capacity.`;
  document.querySelector("#spotlightPrice").textContent = money.format(event.price);
}

function openEventDetail(eventId) {
  const event = getEvent(eventId);
  if (!event) return;

  renderSpotlight(event.id);
  document.querySelector("#detailTitle").textContent = event.name;
  document.querySelector("#detailLocation").textContent = `${event.venue} - ${event.location}`;
  document.querySelector("#detailMainImage").src = event.image;
  document.querySelector("#detailMainImage").alt = event.name;
  document.querySelector("#detailMainImage").style.objectPosition = event.imagePosition;
  document.querySelector("#detailSecondImage").src = event.image;
  document.querySelector("#detailSecondImage").alt = event.name;
  document.querySelector("#detailSecondImage").style.objectPosition = "20% 50%";
  document.querySelector("#detailThirdImage").src = event.image;
  document.querySelector("#detailThirdImage").alt = event.name;
  document.querySelector("#detailThirdImage").style.objectPosition = "80% 50%";
  document.querySelector("#detailStats").innerHTML = `
    <div>People's<br />Favorite</div>
    <div>${event.capacity.toLocaleString()}<br />Capacity</div>
    <div>By<br />${event.organizer}</div>
  `;
  document.querySelector("#detailDescription").textContent = eventDescription(event);
  document.querySelector("#detailPrice").textContent = moneyText(event.price);
  document.querySelector("#detailDate").innerHTML = (event.availableDates || [event.dateValue])
    .map((date) => `<option value="${date}">${date}</option>`)
    .join("");
  document.querySelector("#detailDate").value = event.dateValue;
  document.querySelector("#detailGuests").value = "1";
  document.querySelector("#eventDetailModal").hidden = false;
  document.body.classList.add("modal-open");
}

function closeEventDetail() {
  document.querySelector("#eventDetailModal").hidden = true;
  document.body.classList.remove("modal-open");
}

function renderCheckoutSummary() {
  if (!checkoutEvent) return;
  const { subtotal, taxes, total } = totalsFor(checkoutEvent, checkoutGuests);
  document.querySelector("#summaryImage").src = checkoutEvent.image;
  document.querySelector("#summaryImage").alt = checkoutEvent.name;
  document.querySelector("#summaryImage").style.objectPosition = checkoutEvent.imagePosition;
  document.querySelector("#summaryTitle").textContent = checkoutEvent.name;
  document.querySelector("#summaryDetails").innerHTML = `
    <div><dt>Date</dt><dd>${checkoutDate}</dd></div>
    <div><dt>Guests</dt><dd>${checkoutGuests} ${checkoutGuests === 1 ? "adult" : "adults"}</dd></div>
    <div><dt>${checkoutGuests} adult${checkoutGuests === 1 ? "" : "s"} x ${moneyText(checkoutEvent.price)}</dt><dd>${moneyText(subtotal)}</dd></div>
    <div><dt>Taxes</dt><dd>${moneyText(taxes)}</dd></div>
    <div><dt><strong>Total USD</strong></dt><dd><strong>${moneyText(total)}</strong></dd></div>
  `;
}

function renderReview() {
  if (!checkoutEvent) return;
  const { subtotal, taxes, total } = totalsFor(checkoutEvent, checkoutGuests);
  const cardLine = paymentInfo.method === "Credit or debit card" ? `Ends with ${paymentInfo.last4}` : paymentInfo.method;
  document.querySelector("#reviewBody").innerHTML = `
    <div><span><strong>Card</strong>${cardLine}</span></div>
    <div><span><strong>Date</strong>${checkoutDate}</span></div>
    <div><span><strong>Guests</strong>${checkoutGuests} ${checkoutGuests === 1 ? "adult" : "adults"}</span></div>
    <dl>
      <div><dt>${checkoutGuests} adult${checkoutGuests === 1 ? "" : "s"} x ${moneyText(checkoutEvent.price)}</dt><dd>${moneyText(subtotal)}</dd></div>
      <div><dt>Taxes</dt><dd>${moneyText(taxes)}</dd></div>
      <div><dt><strong>Total USD</strong></dt><dd><strong>${moneyText(total)}</strong></dd></div>
    </dl>
  `;
}

function openCheckout(eventId, options = {}) {
  const event = getEvent(eventId);
  if (!event) {
    showToast("Choose an event before reserving.");
    return;
  }

  if (!currentUser) {
    showToast("Log in or register first, then reserve your ticket.");
    openAuth("login");
    return;
  }

  checkoutEvent = event;
  checkoutGuests = Number(options.guests || 1);
  if (checkoutGuests < 1 || checkoutGuests > 10) {
    showToast("Choose between 1 and 10 people.");
    return;
  }
  checkoutDate = options.date || event.dateValue;
  paymentInfo = { method: "Credit or debit card", last4: "1234" };
  document.querySelector("#paymentStep").classList.remove("collapsed");
  document.querySelector("#reviewStep").classList.add("collapsed");
  document.querySelector("#confirmReservationButton").disabled = false;
  document.querySelector("#completionOverlay").hidden = true;
  document.querySelector("#checkoutModal").hidden = false;
  document.body.classList.add("modal-open");
  renderCheckoutSummary();
}

function closeCheckout() {
  document.querySelector("#checkoutModal").hidden = true;
  document.body.classList.remove("modal-open");
}

function paymentMethod() {
  return document.querySelector('input[name="paymentMethod"]:checked')?.value || "Credit or debit card";
}

function goToReviewStep() {
  const method = paymentMethod();
  let last4 = "";
  if (method === "Credit or debit card") {
    const digits = document.querySelector("#cardNumberInput").value.replace(/\D/g, "");
    if (digits.length < 4) {
      showToast("Enter a card number before reviewing.");
      return;
    }
    last4 = digits.slice(-4);
  }

  paymentInfo = { method, last4 };
  document.querySelector("#paymentStep").classList.add("collapsed");
  document.querySelector("#reviewStep").classList.remove("collapsed");
  renderReview();
}

function openTicket(ticket) {
  lastTicket = ticket || lastTicket;
  if (!lastTicket) return;
  const qrImage = document.querySelector("#ticketQrCode");
  if (lastTicket.qrDataUrl) {
    qrImage.src = lastTicket.qrDataUrl;
    qrImage.hidden = false;
  } else {
    qrImage.hidden = true;
  }
  document.querySelector("#ticketEventName").textContent = lastTicket.eventName;
  document.querySelector("#ticketVenue").textContent = lastTicket.venue;
  document.querySelector("#ticketLocation").textContent = lastTicket.location;
  document.querySelector("#ticketDate").textContent = lastTicket.eventDate || checkoutDate;
  document.querySelector("#ticketGuests").textContent = `${lastTicket.guestCount} ${lastTicket.guestCount === 1 ? "guest" : "guests"}`;
  document.querySelector("#ticketOrder").textContent = `Order #${lastTicket.orderId}`;
  document.querySelector("#ticketHolder").textContent = `${lastTicket.holder || currentUser.username} - Adult`;
  document.querySelector("#ticketModal").hidden = false;
  document.body.classList.add("modal-open");
}

function closeTicket() {
  document.querySelector("#ticketModal").hidden = true;
  document.body.classList.remove("modal-open");
}

document.querySelector("#loginForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const payload = {
    username: document.querySelector("#nameInput").value.trim(),
    email: document.querySelector("#emailInput").value.trim(),
    password: document.querySelector("#passwordInput").value
  };

  try {
    setStatus(authMode === "signup" ? "Creating account..." : "Signing in...");
    const data = await api(`/api/${authMode}`, payload);
    currentUser = data.user;
    localStorage.setItem("tixlyUser", JSON.stringify(currentUser));
    syncSession();
    setStatus(authMode === "signup" ? "Account created." : "Welcome back.");
    closeAuth();
    showToast(authMode === "signup" ? "Account created." : "Welcome back.");
  } catch (error) {
    setStatus(error.message, true);
  }
});

document.querySelector("#userProfileForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!currentUser) {
    closeUserProfile();
    openAuth("login");
    return;
  }

  try {
    setProfileStatus("Saving changes...");
    const data = await api("/api/users/update", {
      userId: currentUser.id,
      username: document.querySelector("#profileNameInput").value.trim(),
      password: document.querySelector("#profilePasswordInput").value
    });
    currentUser = data.user;
    localStorage.setItem("tixlyUser", JSON.stringify(currentUser));
    syncSession();
    renderUserDashboard(data);
    setProfileStatus("Profile updated.");
    showToast("Profile updated.");
  } catch (error) {
    if (error.status === 401 || error.status === 404) {
      closeUserProfile();
      clearSession();
      showToast("Your saved login expired. Please log in again.");
      openAuth("login");
      return;
    }
    setProfileStatus(error.message, true);
  }
});

document.querySelector("#searchForm").addEventListener("submit", (event) => {
  event.preventDefault();
  renderEvents();
});

["#locationInput", "#eventInput", "#dateInput"].forEach((selector) => {
  document.querySelector(selector).addEventListener("input", renderEvents);
});

document.querySelector("#reserveButton").addEventListener("click", () => {
  openEventDetail(selectedEventId);
});

document.querySelector("#detailReserveButton").addEventListener("click", () => {
  openCheckout(selectedEventId, {
    date: document.querySelector("#detailDate").value,
    guests: document.querySelector("#detailGuests").value
  });
});

document.querySelector("#paymentNextButton").addEventListener("click", goToReviewStep);

document.querySelector("#confirmReservationButton").addEventListener("click", async () => {
  if (!checkoutEvent) return;
  if (!currentUser) {
    showToast("Log in or register first, then confirm your reservation.");
    openAuth("login");
    return;
  }

  try {
    const data = await api("/api/reserve", {
      userId: currentUser.id,
      eventId: checkoutEvent.id,
      quantity: checkoutGuests,
      method: paymentInfo.method,
      eventDate: checkoutDate
    });
    const ticketId = data.ticketIds?.[0] || data.orderId;
    lastTicket = {
      ticketId,
      orderId: data.orderId,
      eventName: data.eventName,
      venue: checkoutEvent.venue,
      location: checkoutEvent.location,
      eventDate: checkoutDate,
      guestCount: data.guestCount || checkoutGuests,
      holder: currentUser.username,
      qrPayload: data.qrPayload,
      qrDataUrl: data.qrDataUrl
    };
    document.querySelector("#completionTicketNumber").textContent = `Ticket No: ${ticketId}`;
    document.querySelector("#confirmReservationButton").disabled = true;
    document.querySelector("#completionOverlay").hidden = false;
    await loadEvents();
  } catch (error) {
    if (error.status === 401) {
      clearSession();
      closeCheckout();
      showToast("Your saved login expired. Please log in again.");
      openAuth("login");
      return;
    }
    showToast(error.message);
  }
});

document.querySelector("#signOutButton").addEventListener("click", () => {
  clearSession();
  showToast("Signed out.");
});

document.querySelector("#openLoginButton").addEventListener("click", () => openAuth("login"));
document.querySelector("#openSignupButton").addEventListener("click", () => openAuth("signup"));
document.querySelector("#openUserProfileButton").addEventListener("click", openUserProfile);
document.querySelector("#openOrganizerButton").addEventListener("click", openOrganizer);
document.querySelector("#openOrganizerSessionButton").addEventListener("click", openOrganizer);
document.querySelector("#closeAuthButton").addEventListener("click", closeAuth);
document.querySelector("#closeAuthBackdrop").addEventListener("click", closeAuth);
document.querySelector("#closeUserButton").addEventListener("click", closeUserProfile);
document.querySelector("#closeUserBackdrop").addEventListener("click", closeUserProfile);
document.querySelector("#closeDetailButton").addEventListener("click", closeEventDetail);
document.querySelector("#closeDetailBackdrop").addEventListener("click", closeEventDetail);
document.querySelector("#closeCheckoutButton").addEventListener("click", closeCheckout);
document.querySelector("#closeCheckoutBackdrop").addEventListener("click", closeCheckout);
document.querySelector("#checkoutBackButton").addEventListener("click", closeCheckout);
document.querySelector("#seeTicketButton").addEventListener("click", () => openTicket(lastTicket));
document.querySelector("#backToDashboardButton").addEventListener("click", async () => {
  closeCheckout();
  await openUserProfile();
});
document.querySelector("#closeTicketButton").addEventListener("click", closeTicket);
document.querySelector("#closeTicketBackdrop").addEventListener("click", closeTicket);
document.querySelector("#closeOrganizerButton").addEventListener("click", closeOrganizer);
document.querySelector("#closeOrganizerBackdrop").addEventListener("click", closeOrganizer);
document.querySelector("#cancelEventEditButton").addEventListener("click", () => {
  resetEventEditMode();
  setOrganizerStatus("Edit cancelled.");
});
document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  if (!document.querySelector("#ticketModal").hidden) {
    closeTicket();
  } else if (!document.querySelector("#organizerModal").hidden) {
    closeOrganizer();
  } else if (!document.querySelector("#checkoutModal").hidden) {
    closeCheckout();
  } else if (!document.querySelector("#eventDetailModal").hidden) {
    closeEventDetail();
  } else if (!document.querySelector("#authModal").hidden) {
    closeAuth();
  } else if(!document.querySelector("#userModal").hidden){
    closeUserProfile();
  }
});

function setOrganizerStatus(message, isError = false) {
  const status = document.querySelector("#organizerStatus");
  status.textContent = message;
  status.style.color = isError ? "#d90f46" : "var(--muted)";
}

function syncOrganizer() {
  document.querySelector("#organizerAuth").hidden = Boolean(currentOrganizer);
  document.querySelector("#organizerDashboard").hidden = !currentOrganizer;
  document.querySelector("#organizerSessionLabel").textContent = currentOrganizer
    ? `Signed in as ${currentOrganizer.name}`
    : "";
}

async function validateSavedOrganizer() {
  if (!currentOrganizer?.id) {
    currentOrganizer = null;
    localStorage.removeItem("tixlyOrganizer");
    syncOrganizer();
    return;
  }

  try {
    const data = await getJson(`/api/organizers/${currentOrganizer.id}`);
    currentOrganizer = data.organizer;
    localStorage.setItem("tixlyOrganizer", JSON.stringify(currentOrganizer));
    syncOrganizer();
    await loadOrganizerVenues();
    await loadOrganizerEvents();
  } catch (error) {
    currentOrganizer = null;
    localStorage.removeItem("tixlyOrganizer");
    syncOrganizer();
  }
}

function renderUserDashboard(data) {
  const user = data.user || currentUser;
  const reservations = data.reservations || [];

  document.querySelector("#profileSessionLabel").textContent = user.createdAt
    ? `Member since ${String(user.createdAt).slice(0, 10)}`
    : "";
  document.querySelector("#profileNameInput").value = user.username || "";
  document.querySelector("#profileEmailInput").value = user.email || "";
  document.querySelector("#profilePasswordInput").value = "";
  document.querySelector("#profileReservationCount").textContent =
    `${reservations.length} order${reservations.length === 1 ? "" : "s"}`;

  const list = document.querySelector("#profileReservationsList");
  if (!reservations.length) {
    list.innerHTML = '<p class="empty-state">No reservations yet.</p>';
    return;
  }

  list.innerHTML = reservations
    .map(
      (reservation) => `
        <button class="profile-reservation-card" type="button" data-reservation-id="${reservation.id}" aria-label="Open ticket for ${escapeHtml(reservation.event)}">
          <div>
            <h4>${escapeHtml(reservation.event)}</h4>
            <p>${escapeHtml(reservation.venue)} · ${escapeHtml(reservation.location)}</p>
            <small>${escapeHtml(reservation.eventDate || "Date pending")} · ${reservation.tickets} ${reservation.tickets === 1 ? "ticket" : "tickets"}</small>
          </div>
          <div>
            <strong>${moneyText(reservation.total || 0)}</strong>
            <span>${escapeHtml(reservation.status || "Confirmed")}</span>
            <small>Order #${reservation.id}</small>
          </div>
        </button>
      `
    )
    .join("");

  list.querySelectorAll("[data-reservation-id]").forEach((button) => {
    button.addEventListener("click", () => openReservationTicket(button.dataset.reservationId));
  });
}

async function openUserProfile(){
  if (!currentUser) {
    openAuth("login");
    return;
  }

  document.querySelector("#userModal").hidden = false;
  document.body.classList.add("modal-open");
  setProfileStatus("Loading your dashboard...");

  try {
    const data = await getJson(`/api/users/${currentUser.id}`);
    currentUser = data.user;
    localStorage.setItem("tixlyUser", JSON.stringify(currentUser));
    syncSession();
    renderUserDashboard(data);
    setProfileStatus("");
  } catch (error) {
    if (error.status === 401 || error.status === 404) {
      closeUserProfile();
      clearSession();
      showToast("Your saved login expired. Please log in again.");
      openAuth("login");
      return;
    }
    setProfileStatus(error.message, true);
  }
}

function closeUserProfile(){
  document.querySelector("#userModal").hidden = true;
  document.body.classList.remove("modal-open");
}

async function openReservationTicket(orderId) {
  if (!currentUser) {
    openAuth("login");
    return;
  }

  try {
    setProfileStatus("Loading ticket...");
    const data = await getJson(`/api/users/${currentUser.id}/reservations/${orderId}`);
    setProfileStatus("");
    openTicket(data.ticket);
  } catch (error) {
    if (error.status === 401 || error.status === 404) {
      showToast("Could not find that reservation for this account.");
      await openUserProfile();
      return;
    }
    setProfileStatus(error.message, true);
  }
}

async function openOrganizer() {
  document.querySelector("#organizerModal").hidden = false;
  document.body.classList.add("modal-open");
  syncOrganizer();
  if (currentOrganizer){
    loadOrganizerVenues();
    loadOrganizerEvents();
  }
}

function closeOrganizer() {
  document.querySelector("#organizerModal").hidden = true;
  document.body.classList.remove("modal-open");
}

async function organizerAuth(path, payload) {
  try {
    setOrganizerStatus("Working...");
    const data = await api(path, payload);
    currentOrganizer = data.organizer;
    localStorage.setItem("tixlyOrganizer", JSON.stringify(currentOrganizer));
    syncOrganizer();
    await loadOrganizerVenues();
    await loadOrganizerEvents();
    setOrganizerStatus("Organizer account ready.");
  } catch (error) {
    setOrganizerStatus(error.message, true);
  }
}

async function loadOrganizerVenues() {
  if (!currentOrganizer) return;
  const select = document.querySelector("#eventVenueInput");
  try {
    const data = await getJson(`/api/organizers/${currentOrganizer.id}/venues`);
    const venues = data.venues || [];
    select.innerHTML = venues.length
      ? venues.map((venue) => `<option value="${venue.id}">${venue.name} - ${venue.location}</option>`).join("")
      : '<option value="">Register a venue first</option>';
  } catch (error) {
    select.innerHTML = '<option value="">Could not load venues</option>';
  }
}
async function loadOrganizerEvents() {
  const list = document.querySelector("#organizerEventsList");
  if (!currentOrganizer || !list) return;

  try {
    const data = await getJson(`/api/organizers/${currentOrganizer.id}/events`);
    organizerEvents = data.events || [];

    if (!organizerEvents.length) {
      list.innerHTML = '<p class="empty-state">You have not published any events yet.</p>';
      return;
    }

    list.innerHTML = organizerEvents
      .map(
        (event) => `
          <article class="organizer-event-card ${editingEventId === event.id ? "active" : ""}">
            <button class="organizer-event-main" type="button" data-open-event-id="${event.id}">
              <img src="${event.image}" alt="${event.name}" onerror="this.onerror=null;this.src='${fallbackImage}'" />
              <div class="organizer-event-info">
                <h4>${event.name}</h4>
                <p>${event.date} · ${event.startTime} · ${event.venue}</p>
                <small>${event.location} · ${event.type}</small>
                <strong>${moneyText(event.price)} per ticket</strong>
              </div>
            </button>
            <div class="organizer-event-actions">
              <button class="edit-event-button" type="button" data-edit-event-id="${event.id}">
                Open
              </button>
              <button class="delete-event-button" type="button" data-delete-event-id="${event.id}">
                Delete
              </button>
            </div>
          </article>
        `
      )
      .join("");

    list.querySelectorAll("[data-open-event-id]").forEach((button) => {
      button.addEventListener("click", () => {
        startEventEdit(button.dataset.openEventId);
      });
    });

    list.querySelectorAll("[data-edit-event-id]").forEach((button) => {
      button.addEventListener("click", () => {
        startEventEdit(button.dataset.editEventId);
      });
    });

    list.querySelectorAll("[data-delete-event-id]").forEach((button) => {
      button.addEventListener("click", async () => {
        const eventId = Number(button.dataset.deleteEventId);
        const confirmed = window.confirm("Delete this event? This cannot be undone.");

        if (!confirmed) return;

        try {
          setOrganizerStatus("Deleting event...");

          await api("/api/organizer/events/delete", {
            organizerId: currentOrganizer.id,
            eventId
          });

          if (editingEventId === eventId) {
            resetEventEditMode();
          }

          await loadEvents();
          await loadOrganizerEvents();

          setOrganizerStatus("Event deleted.");
        } catch (error) {
          setOrganizerStatus(error.message, true);
        }
      });
    });
  } catch (error) {
    list.innerHTML = `<p class="empty-state">${error.message}</p>`;
  }
}

async function loadOrganizerEventAnalytics(eventId) {
  const panel = document.querySelector("#eventAnalyticsPanel");
  panel.hidden = false;
  document.querySelector("#analyticsEventTitle").textContent = "Loading analytics...";
  document.querySelector("#analyticsSellThrough").textContent = "";
  document.querySelector("#analyticsMetrics").innerHTML = "";
  document.querySelector("#analyticsDateList").innerHTML = "";
  document.querySelector("#analyticsOrderList").innerHTML = "";

  try {
    const data = await getJson(`/api/organizers/${currentOrganizer.id}/events/${eventId}/analytics`);
    const analytics = data.analytics;
    const summary = analytics.summary;

    document.querySelector("#analyticsEventTitle").textContent = analytics.event.name;
    document.querySelector("#analyticsSellThrough").textContent = `${summary.sellThrough}% sold`;
    document.querySelector("#analyticsMetrics").innerHTML = `
      <div><strong>${summary.ticketsSold}</strong><span>Tickets sold</span></div>
      <div><strong>${summary.remaining}</strong><span>Remaining</span></div>
      <div><strong>${summary.orders}</strong><span>Orders</span></div>
      <div><strong>${moneyText(summary.paymentRevenue)}</strong><span>Total revenue</span></div>
      <div><strong>${moneyText(summary.ticketRevenue)}</strong><span>Ticket sales</span></div>
      <div><strong>${moneyText(summary.averageOrder)}</strong><span>Avg order</span></div>
    `;

    const dateList = document.querySelector("#analyticsDateList");
    dateList.innerHTML = analytics.byDate.length
      ? analytics.byDate
          .map(
            (row) => `
              <div class="analytics-row">
                <span>${escapeHtml(row.date)}</span>
                <strong>${row.ticketsSold} tickets</strong>
                <small>${moneyText(row.revenue)}</small>
              </div>
            `
          )
          .join("")
      : '<p class="empty-state">No reservations for this event yet.</p>';

    const orderList = document.querySelector("#analyticsOrderList");
    orderList.innerHTML = analytics.recentOrders.length
      ? analytics.recentOrders
          .map(
            (order) => `
              <div class="analytics-row">
                <span>#${order.id} · ${escapeHtml(order.buyer)}</span>
                <strong>${order.tickets} ${order.tickets === 1 ? "ticket" : "tickets"}</strong>
                <small>${escapeHtml(order.eventDate || "Date pending")} · ${moneyText(order.total)}</small>
              </div>
            `
          )
          .join("")
      : '<p class="empty-state">No orders yet.</p>';

    setOrganizerStatus(`Editing "${analytics.event.name}".`);
  } catch (error) {
    document.querySelector("#analyticsEventTitle").textContent = "Analytics unavailable";
    document.querySelector("#analyticsMetrics").innerHTML = `<p class="empty-state">${escapeHtml(error.message)}</p>`;
    setOrganizerStatus(error.message, true);
  }
}

function resetEventEditMode() {
  editingEventId = null;
  document.querySelector("#eventForm").reset();
  document.querySelector("#eventFormTitle").textContent = "Create event";
  document.querySelector("#eventSubmitButton").textContent = "Publish event";
  document.querySelector("#cancelEventEditButton").hidden = true;
  document.querySelector("#eventAnalyticsPanel").hidden = true;
  document.querySelectorAll(".organizer-event-card.active").forEach((card) => {
    card.classList.remove("active");
  });
}

async function startEventEdit(eventId) {
  const event = organizerEvents.find((item) => item.id === Number(eventId));

  if (!event) {
    setOrganizerStatus("Could not find that event.", true);
    return;
  }

  editingEventId = event.id;

  document.querySelector("#eventFormTitle").textContent = "Edit event";
  document.querySelector("#eventNameInput").value = event.name;
  document.querySelector("#eventVenueInput").value = event.venueId;
  document.querySelector("#eventCategoryInput").value = event.type;
  document.querySelector("#eventDatesInput").value = (event.availableDates || [event.dateValue]).join(", ");
  document.querySelector("#eventStartTimeInput").value = event.startTime;
  document.querySelector("#eventPriceInput").value = event.price;
  document.querySelector("#eventCapacityInput").value = event.capacity;
  document.querySelector("#eventImageInput").value = event.image === fallbackImage ? "" : event.image;

  document.querySelector("#eventSubmitButton").textContent = "Save changes";
  document.querySelector("#cancelEventEditButton").hidden = false;
  document.querySelectorAll(".organizer-event-card").forEach((card) => {
    card.classList.toggle(
      "active",
      card.querySelector("[data-open-event-id]")?.dataset.openEventId === String(event.id)
    );
  });

  document.querySelector(".event-management-panel").scrollIntoView({
    behavior: "smooth",
    block: "start"
  });

  setOrganizerStatus(`Editing "${event.name}" and loading analytics.`);
  await loadOrganizerEventAnalytics(event.id);
}

document.querySelector("#organizerSignupForm").addEventListener("submit", (event) => {
  event.preventDefault();
  organizerAuth("/api/organizer/signup", {
    name: document.querySelector("#organizerSignupName").value.trim(),
    email: document.querySelector("#organizerSignupEmail").value.trim(),
    password: document.querySelector("#organizerSignupPassword").value
  });
});

document.querySelector("#organizerLoginForm").addEventListener("submit", (event) => {
  event.preventDefault();
  organizerAuth("/api/organizer/login", {
    email: document.querySelector("#organizerLoginEmail").value.trim(),
    password: document.querySelector("#organizerLoginPassword").value
  });
});

document.querySelector("#organizerSignOutButton").addEventListener("click", () => {
  currentOrganizer = null;
  localStorage.removeItem("tixlyOrganizer");
  syncOrganizer();
  const list = document.querySelector("#organizerEventsList");
  if (list) {
    list.innerHTML = '<p class="empty-state">No organizer events loaded yet.</p>';
  }
  setOrganizerStatus("Signed out.");
});

document.querySelector("#venueForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!currentOrganizer) return;
  try {
    setOrganizerStatus("Saving venue...");
    await api("/api/organizer/venues", {
      organizerId: currentOrganizer.id,
      name: document.querySelector("#venueNameInput").value.trim(),
      location: document.querySelector("#venueLocationInput").value.trim(),
      capacity: document.querySelector("#venueCapacityInput").value
    });
    event.target.reset();
    await loadOrganizerVenues();
    await loadOrganizerEvents();
    setOrganizerStatus("Venue registered.");
  } catch (error) {
    setOrganizerStatus(error.message, true);
  }
});

document.querySelector("#eventForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!currentOrganizer) return;

  const dates = document
    .querySelector("#eventDatesInput")
    .value
    .split(",")
    .map((date) => date.trim())
    .filter(Boolean);

  const payload = {
    organizerId: currentOrganizer.id,
    name: document.querySelector("#eventNameInput").value.trim(),
    venueId: document.querySelector("#eventVenueInput").value,
    category: document.querySelector("#eventCategoryInput").value,
    dates,
    startTime: document.querySelector("#eventStartTimeInput").value,
    price: document.querySelector("#eventPriceInput").value,
    capacity: document.querySelector("#eventCapacityInput").value,
    imageUrl: document.querySelector("#eventImageInput").value.trim()
  };

  if (editingEventId) {
    payload.eventId = editingEventId;
  }

  try {
    setOrganizerStatus(editingEventId ? "Saving event changes..." : "Publishing event...");

    await api(
      editingEventId ? "/api/organizer/events/update" : "/api/organizer/events",
      payload
    );

    resetEventEditMode();
    await loadEvents();
    await loadOrganizerVenues();
    await loadOrganizerEvents();

    setOrganizerStatus(editingEventId ? "Event updated." : "Event published and added to the homepage.");
  } catch (error) {
    setOrganizerStatus(error.message, true);
  }
});

async function loadEvents() {
  try {
    const data = await getJson("/api/events");
    events = data.events || [];
    if (selectedEventId && !events.some((event) => event.id === selectedEventId)) {
      selectedEventId = null;
    }
    renderCategories();
    renderEvents();
  } catch (error) {
    document.querySelector("#eventGrid").innerHTML = `<p class="empty-state">${error.message}</p>`;
    document.querySelector("#resultCount").textContent = "0 events found";
  }
}

syncSession();
validateSavedSession();
syncOrganizer();
validateSavedOrganizer();
loadEvents();
