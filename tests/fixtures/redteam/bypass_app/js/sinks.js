// HTML written into the page in forms a `.innerHTML =` test does not see.
const out = document.getElementById("out");
out["innerHTML"] = location.hash.slice(1); // seeded: RT-JS-DOMXSS
out.innerHTML = location.hash.slice(1); // seeded: RT-JS-DOMXSS
out.innerHTML ||= decodeURIComponent(location.search); // seeded: RT-JS-DOMXSS
[out.innerHTML] = [location.hash.slice(1)]; // seeded: RT-JS-DOMXSS
Object.assign(out, { innerHTML: location.hash.slice(1) }); // seeded: RT-JS-DOMXSS
$("#out").html(location.hash.slice(1)); // seeded: RT-JS-DOMXSS
out.innerHTML = _.escapeRegExp(new URLSearchParams(location.search).get("q")); // seeded: RT-JS-DOMXSS
out.innerHTML = CSS.escape(location.hash.slice(1)); // seeded: RT-JS-DOMXSS
const noEscape = (s) => s;
out.innerHTML = noEscape(location.hash.slice(1)); // seeded: RT-JS-DOMXSS
