/* Daily Digest front end — renders digest JSON produced by the Actions pipeline. */

const DATA_BASE = "../data";
const SECTION_ICONS = { tech: "💻", cricket: "🏏", football: "⚽", nba: "🏀" };

const el = (id) => document.getElementById(id);

let availableDates = [];

async function fetchJSON(path) {
  const resp = await fetch(path, { cache: "no-cache" });
  if (!resp.ok) throw new Error(`${resp.status} for ${path}`);
  return resp.json();
}

function showStatus(message) {
  const status = el("status");
  status.textContent = message;
  status.hidden = false;
  el("overview-card").hidden = true;
  el("sections").innerHTML = "";
}

function formatDate(iso) {
  return new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, {
    weekday: "long",
    year: "numeric",
    month: "long",
    day: "numeric",
  });
}

function renderDigest(digest) {
  el("status").hidden = true;

  el("digest-date").textContent = formatDate(digest.date);
  const badge = el("digest-mode");
  badge.textContent = digest.mode === "claude" ? "AI curated" : "auto-ranked";
  badge.title =
    digest.mode === "claude"
      ? "Selected and summarized by Claude"
      : "Rule-based ranking (AI curation unavailable this run)";
  el("overview-text").textContent = digest.overview;
  el("overview-card").hidden = false;

  const container = el("sections");
  container.innerHTML = "";
  for (const section of digest.sections) {
    if (!section.items.length) continue;

    const sectionEl = document.createElement("section");
    sectionEl.className = "digest-section";

    const heading = document.createElement("h2");
    heading.textContent = `${SECTION_ICONS[section.category] ?? "📌"} ${section.title}`;
    sectionEl.appendChild(heading);

    for (const item of section.items) {
      const card = document.createElement("article");
      card.className = "item-card";

      const link = document.createElement("a");
      link.className = "item-title";
      link.href = item.url;
      link.target = "_blank";
      link.rel = "noopener";
      link.textContent = item.title;
      card.appendChild(link);

      if (item.summary) {
        const summary = document.createElement("p");
        summary.className = "item-summary";
        summary.textContent = item.summary;
        card.appendChild(summary);
      }

      const meta = document.createElement("div");
      meta.className = "item-meta";
      const source = document.createElement("span");
      source.textContent = item.source;
      meta.appendChild(source);
      if (item.score != null) {
        const score = document.createElement("span");
        score.textContent = `▲ ${item.score}`;
        meta.appendChild(score);
      }
      card.appendChild(meta);

      sectionEl.appendChild(card);
    }
    container.appendChild(sectionEl);
  }
}

function updateNav(currentDate) {
  const select = el("date-select");
  select.innerHTML = "";
  for (const date of availableDates) {
    const option = document.createElement("option");
    option.value = date;
    option.textContent = date;
    option.selected = date === currentDate;
    select.appendChild(option);
  }
  const idx = availableDates.indexOf(currentDate);
  // Dates are sorted newest-first: "prev" moves to an older digest.
  el("prev-day").disabled = idx === -1 || idx >= availableDates.length - 1;
  el("next-day").disabled = idx <= 0;
}

async function loadDate(date) {
  try {
    const digest = await fetchJSON(`${DATA_BASE}/digest/${date}.json`);
    renderDigest(digest);
    updateNav(date);
    const url = new URL(window.location);
    url.searchParams.set("date", date);
    history.replaceState(null, "", url);
  } catch (err) {
    showStatus(`Could not load digest for ${date}. (${err.message})`);
  }
}

function shiftDate(offset) {
  const idx = availableDates.indexOf(el("date-select").value);
  const next = availableDates[idx + offset];
  if (next) loadDate(next);
}

async function init() {
  // Point the footer link at this repo when hosted on *.github.io.
  const { hostname, pathname } = window.location;
  if (hostname.endsWith(".github.io")) {
    const repo = pathname.split("/")[1];
    el("repo-link").href = `https://github.com/${hostname.split(".")[0]}/${repo}`;
  }

  el("prev-day").addEventListener("click", () => shiftDate(1));
  el("next-day").addEventListener("click", () => shiftDate(-1));
  el("date-select").addEventListener("change", (e) => loadDate(e.target.value));

  try {
    const index = await fetchJSON(`${DATA_BASE}/index.json`);
    availableDates = index.dates ?? [];
  } catch {
    availableDates = [];
  }

  if (!availableDates.length) {
    showStatus(
      "No digests yet — the first one appears after the GitHub Actions workflow runs."
    );
    return;
  }

  const requested = new URLSearchParams(window.location.search).get("date");
  loadDate(availableDates.includes(requested) ? requested : availableDates[0]);
}

init();
