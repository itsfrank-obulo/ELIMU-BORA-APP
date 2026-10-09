import { apiRequest } from "./api.js";

const escapeHTML = (value) => String(value ?? "").replace(/[&<>"']/g, (character) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
}[character]));

function formatDate(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value : new Intl.DateTimeFormat("en-KE", { dateStyle: "medium" }).format(date);
}

function showStudent(user) {
  const name = `${user.firstName} ${user.lastName}`;
  document.querySelectorAll(".portal-user").forEach((element) => {
    const avatar = element.querySelector(".user-avatar");
    if (avatar) avatar.textContent = `${user.firstName[0] || ""}${user.lastName[0] || ""}`.toUpperCase();
    const labels = element.querySelectorAll(".hidden strong, strong");
    if (labels[0]) labels[0].textContent = name;
    if (labels[1]) labels[1].textContent = [user.constituency, "Constituency"].filter(Boolean).join(" ");
  });
  const welcome = document.querySelector(".page-heading h1");
  if (welcome && location.pathname.toLowerCase().endsWith("dashboard.html")) {
    welcome.textContent = `Welcome back, ${user.firstName}`;
  }
  const profileName = document.querySelector(".profile-intro h2");
  if (profileName) profileName.textContent = name;
  const profileForm = document.querySelector("#profile-form");
  if (profileForm) {
    const values = {
      firstName: user.firstName,
      lastName: user.lastName,
      phone: user.phone,
      email: user.email,
      idNumber: user.idNumberMasked,
      dateOfBirth: user.dateOfBirth,
      county: user.county,
      constituency: user.constituency,
      ward: user.ward,
      institution: user.institution,
      educationLevel: user.educationLevel,
      village: user.village,
    };
    Object.entries(values).forEach(([key, value]) => {
      const input = profileForm.elements.namedItem(key);
      if (input) input.value = value || "";
    });
  }
}

function showApplications(applications, user) {
  const dashboard = document.querySelector(".dashboard-grid");
  const summaries = document.querySelector(".summary-grid");
  const mpMessage = document.querySelector(".mp-message");
  if (dashboard && applications.length === 0) {
    if (summaries) summaries.hidden = true;
    if (mpMessage) mpMessage.hidden = true;
    dashboard.innerHTML = '<section class="panel"><p class="eyebrow">Bursary applications</p><h2>No applications yet</h2><p>Your application history and progress will appear here after you apply.</p></section>';
    return;
  }
  if (dashboard && applications[0]) {
    const app = applications[0];
    const eligibility = dashboard.querySelector(".eligibility-card");
    if (eligibility) eligibility.hidden = true;
    const cards = document.querySelectorAll(".summary-card");
    if (cards[0]) cards[0].querySelectorAll("strong, p")[0].textContent = app.status;
    if (cards[0]) cards[0].querySelector("p").textContent = `Submitted ${formatDate(app.submittedAt)}`;
    if (cards[1]) cards[1].querySelectorAll("strong, p")[0].textContent = app.awardAmount ? `KSh ${Number(app.awardAmount).toLocaleString("en-KE")}` : "Pending review";
    if (cards[1] && !app.awardAmount) cards[1].querySelector("p").textContent = "Award decision not yet recorded";
    if (cards[2]) cards[2].querySelectorAll("strong, p")[0].textContent = app.reference;
    if (cards[2]) cards[2].querySelector("p").textContent = `${app.cycle} bursary cycle`;
    const details = dashboard.querySelectorAll(".detail-list dd");
    if (details[0]) details[0].textContent = `${user.firstName} ${user.lastName}`;
    if (details[1]) details[1].textContent = user.institution;
    if (details[2]) details[2].textContent = user.educationLevel;
    if (details[3]) details[3].textContent = user.constituency;
    if (details[4]) details[4].textContent = formatDate(app.submittedAt);
    if (details[5]) details[5].textContent = app.admissionNumber;
    const status = dashboard.querySelector(".status-badge");
    if (status) status.textContent = app.status;
  }
  const table = document.querySelector(".application-table-wrap");
  const eligibilityBanner = document.querySelector(".eligibility-banner");
  const ruleNote = document.querySelector(".rule-note");
  if (eligibilityBanner) eligibilityBanner.hidden = true;
  if (ruleNote) ruleNote.hidden = true;
  if (table) {
    if (applications.length === 0) {
      table.innerHTML = '<p class="p-5 text-sm text-slate-500">No bursary applications have been submitted from this account.</p>';
      const count = document.querySelector(".panel-heading h2");
      if (count) count.textContent = "No previous applications";
    } else {
      const body = table.querySelector("tbody");
      if (body) body.innerHTML = applications.map((app) => `<tr><td><strong>${escapeHTML(app.reference)}</strong><small>Submitted ${escapeHTML(formatDate(app.submittedAt))}</small></td><td>${escapeHTML(app.cycle)}</td><td>—</td><td>${app.awardAmount ? `KSh ${Number(app.awardAmount).toLocaleString("en-KE")}` : "Pending"}</td><td><span class="status-badge">${escapeHTML(app.status)}</span></td><td><a href="./tracking.html?reference=${encodeURIComponent(app.reference)}">View details</a></td></tr>`).join("");
    }
  }
  const timeline = document.querySelector(".timeline");
  if (timeline) {
    const successBanner = document.querySelector(".success-banner");
    if (successBanner) successBanner.hidden = true;
    const reference = new URLSearchParams(location.search).get("reference");
    const app = applications.find((item) => item.reference === reference) || applications[0];
    if (!app) {
      location.replace("./applications.html");
      return;
    }
    apiRequest(`/applications/${encodeURIComponent(app.reference)}`).then(({ application }) => {
      const eyebrow = document.querySelector(".page-heading .eyebrow");
      if (eyebrow) eyebrow.textContent = `Reference ${application.reference}`;
      const badge = document.querySelector(".page-heading .status-badge");
      if (badge) badge.textContent = application.status;
      timeline.innerHTML = application.timeline.map((event) => `<li class="complete"><span>✓</span><div><h3>${escapeHTML(event.title)}</h3><p>${escapeHTML(event.description)}</p><small>${escapeHTML(formatDate(event.occurred_at))}</small></div></li>`).join("");
      const count = document.querySelector(".timeline-count");
      if (count) count.textContent = `${application.timeline.length} ${application.timeline.length === 1 ? "event" : "events"}`;
    }).catch(() => location.replace("./applications.html"));
  }
}

const form = document.querySelector("#profile-form");
if (form) {
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const notice = document.querySelector("#save-notice");
    notice.classList.add("hidden");
    const values = Object.fromEntries(new FormData(form).entries());
    try {
      const { user } = await apiRequest("/me/profile", { method: "PATCH", body: JSON.stringify(values) });
      showStudent(user);
      notice.textContent = "Your profile changes have been saved.";
      notice.classList.remove("hidden");
    } catch (error) {
      notice.textContent = error.message;
      notice.classList.remove("hidden");
    }
  });
}

document.querySelectorAll(".logout-link").forEach((link) => {
  link.addEventListener("click", async (event) => {
    event.preventDefault();
    try { await apiRequest("/auth/logout", { method: "POST", body: "{}" }); } finally { location.href = "./login.html"; }
  });
});

try {
  const [{ user }, { applications }] = await Promise.all([
    apiRequest("/me"),
    apiRequest("/applications"),
  ]);
  showStudent(user);
  showApplications(applications, user);
} catch {
  location.replace("./login.html");
}
