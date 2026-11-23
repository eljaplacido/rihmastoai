// Code from text, reached without a bare `eval(` or `new Function(`.
function run(code, cb, expr) {
  window.eval(code); // seeded: RT-JS-EVAL
  (0, eval)(code); // seeded: RT-JS-EVAL
  Function("return (" + expr + ")")(); // seeded: RT-JS-EVAL
  setTimeout(cb + "()", 0); // seeded: RT-JS-EVAL
  eval(code); // seeded: RT-JS-EVAL
}
