// The loop element of a data array is rebound by destructuring: it no longer holds page data.
const TABS = ["home", "about"];
TABS.forEach((t) => {
  [t] = [location.hash.slice(1)];
  document.getElementById("tabs").innerHTML += t; // seeded: RT-JS-DOMXSS
});
