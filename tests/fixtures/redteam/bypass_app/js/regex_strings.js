// A quote or a backtick inside a regular expression literal opens no string.
const TICK = /`/g;
function show(msg) {
  document.getElementById("out").innerHTML = msg; // seeded: RT-JS-DOMXSS
}
show(location.hash.slice(1));
const strip = (s) => s.replace(/'/g, ""); eval(strip(q)); // seeded: RT-JS-EVAL
