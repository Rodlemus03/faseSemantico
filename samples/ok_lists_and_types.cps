// Objetivo: listas homogéneas, acceso y uso en expresiones
var L = [1, 2, 3, 4];
var M = [true, false, true];
var sum = 0;
var i = 0;

while (i < 4) {
    sum = sum + L[i];
    i = i + 1;
}

if (M[1] == false) {
    sum = sum + 100;
}
