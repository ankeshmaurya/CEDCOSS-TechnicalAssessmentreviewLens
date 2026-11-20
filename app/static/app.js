const form = document.getElementById("upload-form");
const message = document.getElementById("message");

function listItems(elementId, items) {
  const element = document.getElementById(elementId);
  element.replaceChildren();
  for (const item of items) {
    const li = document.createElement("li");
    li.textContent = `${item.theme}: ${item.count}`;
    element.appendChild(li);
  }
}

async function loadDashboard() {
  const response = await fetch("/api/dashboard");
  if (!response.ok) {
    throw new Error("Could not load dashboard");
  }
  const data = await response.json();

  const cards = document.getElementById("cards");
  cards.replaceChildren();
  for (const [label, value] of Object.entries(data.cards)) {
    const card = document.createElement("div");
    card.className = "card";
    card.textContent = `${label}: ${value}`;
    cards.appendChild(card);
  }

  listItems("complaints", data.top_complaints);
  listItems("praises", data.top_praises);

  const reviews = document.getElementById("reviews");
  reviews.replaceChildren();
  for (const review of data.reviews) {
    const item = document.createElement("article");
    item.className = "review";
    item.innerHTML = `<strong>${review.id}</strong> — ${review.summary || review.text}`;
    reviews.appendChild(item);
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const file = document.getElementById("csv-file").files[0];
  if (!file) {
    return;
  }
  const formData = new FormData();
  formData.append("file", file);
  message.textContent = "Uploading...";
  const response = await fetch("/api/upload", {
    method: "POST",
    body: formData,
  });
  if (!response.ok) {
    const error = await response.json();
    message.textContent = error.detail || "Upload failed";
    return;
  }
  message.textContent = "Upload analysed.";
  await loadDashboard();
});

loadDashboard().catch((error) => {
  message.textContent = error.message;
});
