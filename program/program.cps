// Programa de ejemplo para Compiscript
let x: integer = "10";
const PI: integer = 314;

function suma(a: integer, b: integer): integer {
  return a + b;
}

let y: integer;
y = suma(x, 5);

if (y > 10) {
  print("Mayor a 10");
} else {
  print("Menor o igual");
}
