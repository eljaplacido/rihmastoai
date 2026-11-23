// Near misses of the sinks and evaluations the JavaScript rules look for.
const out = document.getElementById("out");
const pattern = /["'`]+/g;
out.textContent = location.hash.slice(1);
out.innerHTML = escapeHtml(location.hash.slice(1));
out.innerHTML = _.escape(new URLSearchParams(location.search).get("q"));
out["innerHTML"] = "";
const current = $("#out").html();
$("#out").text(location.hash.slice(1));
Object.assign(out.style, { color: "red" });
setTimeout(() => refresh(), 1000);
setTimeout(refresh, 1000);
setInterval(function () { tick(); }, 500);
calculator.eval(expression);

class Interpreter {
  eval(node) {
    return node.value;
  }
}
