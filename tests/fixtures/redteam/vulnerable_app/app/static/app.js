// The loans page.
// A commented-out sink is not a finding: el.innerHTML = location.hash;

function showLoan(loan) {
  const detail = document.getElementById("detail");
  detail.innerHTML = "<h2>" + loan.title + "</h2>"; // seeded: RT-JS-DOMXSS
}

function applyFilter(expression) {
  return eval(expression); // seeded: RT-JS-EVAL
}

function clearDetail() {
  document.getElementById("detail").innerHTML = "";
}
