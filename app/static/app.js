const uploadForm = document.getElementById("upload-form");
const analyseButton = document.getElementById("analyse-button");
const errorBanner = document.getElementById("error-banner");
let dashboardData = null;

function showError(message) {
  errorBanner.textContent = message;
  errorBanner.hidden = false;
}

function clearError() {
  errorBanner.textContent = "";
  errorBanner.hidden = true;
}

function addTextElement(parent, tagName, className, text) {
  const element = document.createElement(tagName);
  if (className) {
    element.className = className;
  }
  element.textContent = text;
  parent.appendChild(element);
  return element;
}

function renderCards(cards) {
  const container = document.getElementById("cards");
  container.replaceChildren();
  const items = [
    ["Total analysed", cards.total_analysed],
    ["Positive", `${cards.positive_percent}%`],
    ["Neutral", `${cards.neutral_percent}%`],
    ["Negative", `${cards.negative_percent}%`],
    ["Needs reply", cards.needs_reply],
  ];
  for (const [label, value] of items) {
    const card = document.createElement("article");
    card.className = "card";
    addTextElement(card, "span", "card-label", label);
    addTextElement(card, "strong", "card-value", String(value));
    container.appendChild(card);
  }
}

function renderThemes(elementId, themes) {
  const list = document.getElementById(elementId);
  list.replaceChildren();
  if (!themes || themes.length === 0) {
    addTextElement(list, "li", "", "No themes available");
    return;
  }
  for (const theme of themes) {
    addTextElement(
      list,
      "li",
      "",
      `${theme.theme} (${theme.count})`,
    );
  }
}

function populateProductFilter(reviews) {
  const select = document.getElementById("product-filter");
  const oldValue = select.value;
  select.replaceChildren();
  const allOption = document.createElement("option");
  allOption.value = "";
  allOption.textContent = "All products";
  select.appendChild(allOption);

  const products = new Set(
    reviews
      .map((review) => review.product)
      .filter((product) => typeof product === "string" && product),
  );
  for (const product of Array.from(products).sort()) {
    const option = document.createElement("option");
    option.value = product;
    option.textContent = product;
    select.appendChild(option);
  }
  if (Array.from(products).includes(oldValue)) {
    select.value = oldValue;
  }
}

function createBadge(review) {
  const badge = document.createElement("span");
  if (review.status === "analysis_failed") {
    badge.className = "badge badge-failed";
    badge.textContent = "analysis_failed";
    return badge;
  }
  const sentiment = review.sentiment || "unknown";
  badge.className = `badge badge-${sentiment}`;
  badge.textContent = sentiment;
  return badge;
}

async function suggestReply(reviewId, button, panel) {
  button.disabled = true;
  button.textContent = "Loading...";
  panel.replaceChildren();

  try {
    const response = await fetch(`/api/reviews/${encodeURIComponent(reviewId)}/reply`, {
      method: "POST",
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || "Could not suggest a reply");
    }

    panel.hidden = false;
    addTextElement(panel, "p", "reply-text", data.reply);

    const copyButton = addTextElement(
      panel,
      "button",
      "copy-button",
      "Copy",
    );
    copyButton.type = "button";
    copyButton.addEventListener("click", async () => {
      await navigator.clipboard.writeText(data.reply);
      copyButton.textContent = "Copied";
    });
  } catch (error) {
    panel.hidden = false;
    addTextElement(panel, "p", "reply-text", error.message);
  } finally {
    button.disabled = false;
    button.textContent = "Suggest reply";
  }
}

function createReviewRow(review) {
  const row = document.createElement("tr");
  if (review.status === "analysis_failed") {
    row.className = "failed-row";
  }

  addTextElement(row, "td", "", review.id);
  addTextElement(row, "td", "", review.product || "Unknown");
  addTextElement(
    row,
    "td",
    "",
    review.rating == null ? "n/a" : String(review.rating),
  );

  const sentimentCell = document.createElement("td");
  sentimentCell.appendChild(createBadge(review));
  if (review.rating_mismatch === true) {
    const mismatch = document.createElement("span");
    mismatch.className = "mismatch";
    mismatch.textContent = "Mismatch";
    mismatch.title = "Rating does not agree with analysed sentiment";
    sentimentCell.appendChild(mismatch);
  }
  row.appendChild(sentimentCell);

  addTextElement(
    row,
    "td",
    "",
    Array.isArray(review.topics) ? review.topics.join(", ") : "n/a",
  );

  if (review.status === "analysis_failed") {
    addTextElement(row, "td", "", "Analysis failed");
  } else {
    addTextElement(
      row,
      "td",
      "",
      review.summary || review.text || "",
    );
  }

  const replyCell = document.createElement("td");
  if (review.status === "ok" && review.needs_reply === true) {
    const replyButton = addTextElement(
      replyCell,
      "button",
      "reply-button",
      "Suggest reply",
    );
    replyButton.type = "button";
    const panel = document.createElement("div");
    panel.className = "reply-panel";
    panel.hidden = true;
    replyButton.addEventListener("click", () => {
      suggestReply(review.id, replyButton, panel);
    });
    replyCell.appendChild(panel);
  } else {
    addTextElement(replyCell, "span", "", "—");
  }
  row.appendChild(replyCell);

  return row;
}

function getFilteredReviews() {
  if (!dashboardData) {
    return [];
  }
  const product = document.getElementById("product-filter").value;
  const sentiment = document.getElementById("sentiment-filter").value;
  const topic = document.getElementById("topic-filter").value;
  const needsReply = document.getElementById("reply-filter").checked;

  return dashboardData.reviews.filter((review) => {
    if (product && review.product !== product) {
      return false;
    }
    if (sentiment && review.sentiment !== sentiment) {
      return false;
    }
    if (topic && !(review.topics || []).includes(topic)) {
      return false;
    }
    if (needsReply && review.needs_reply !== true) {
      return false;
    }
    return true;
  });
}

function renderReviews() {
  const tbody = document.getElementById("reviews-body");
  tbody.replaceChildren();
  const filtered = getFilteredReviews();
  document.getElementById("review-count").textContent =
    `${filtered.length} of ${dashboardData.reviews.length} reviews`;

  for (const review of filtered) {
    tbody.appendChild(createReviewRow(review));
  }
}

function renderDashboard(data) {
  dashboardData = data;
  renderCards(data.cards);
  renderThemes("complaints", data.top_complaints);
  renderThemes("praises", data.top_praises);
  populateProductFilter(data.reviews);

  const metrics = data.metrics || {};
  document.getElementById("metrics-line").textContent =
    `AI calls: ${metrics.ai_calls || 0} · Cache hits: ${metrics.cache_hits || 0} · ` +
    `Time: ${metrics.total_seconds || 0}s · Agreement: ${data.agreement_percentage || 0}%`;
  renderReviews();
}

async function loadDashboard() {
  clearError();
  const response = await fetch("/api/dashboard");
  if (!response.ok) {
    throw new Error("Could not load the dashboard");
  }
  const data = await response.json();
  renderDashboard(data);
}

uploadForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  clearError();
  const file = document.getElementById("csv-file").files[0];
  if (!file) {
    showError("Choose a CSV file first.");
    return;
  }

  const formData = new FormData();
  formData.append("file", file);
  analyseButton.disabled = true;
  analyseButton.textContent = "Analysing...";

  try {
    const response = await fetch("/api/upload", {
      method: "POST",
      body: formData,
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || "Upload failed");
    }
    await loadDashboard();
  } catch (error) {
    showError(error.message);
  } finally {
    analyseButton.disabled = false;
    analyseButton.textContent = "Analyse";
  }
});

for (const filterId of [
  "product-filter",
  "sentiment-filter",
  "topic-filter",
  "reply-filter",
]) {
  document.getElementById(filterId).addEventListener("change", renderReviews);
}

loadDashboard().catch((error) => showError(error.message));
