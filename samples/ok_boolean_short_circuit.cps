// Objetivo: verificar short-circuit (AND/OR) y generación de saltos
var a = 0;
var b = 1;
var c = 2;
var flag1 = false;
var flag2 = true;

if ( (a < c) && (b == 1) || flag2 ) {
    a = a + 1;
} else {
    a = a - 1;
}

while ( (a < 5) && (flag2 || (b > 10)) ) {
    a = a + 1;
}
