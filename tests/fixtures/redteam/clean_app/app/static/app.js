// The loans page.

function escapeHtml(text) {
  return String(text).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function showLoan(loan) {
  const heading = document.createElement("h2");
  heading.textContent = loan.title;
  document.getElementById("detail").replaceChildren(heading);
}

function showOwner(loan) {
  document.getElementById("owner").innerHTML = `<b>${escapeHtml(loan.owner)}</b>`;
}

function applyFilter(text) {
  return JSON.parse(text);
}

function clearDetail() {
  document.getElementById("detail").innerHTML = "";
}
