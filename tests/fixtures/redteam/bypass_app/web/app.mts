const out = document.getElementById("out") as HTMLElement;
out.innerHTML = location.hash.slice(1); // seeded: RT-JS-DOMXSS
