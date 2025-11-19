// Objetivo: if/else anidados + while para verificar etiquetas coherentes
var a = 0;
var b = 10;

if (b > 5) {
    if (a == 0) {
        a = a + 2;
    } else {
        a = a - 1;
    }
} else {
    a = b;
}

while (a < 20) {
    if (a % 2 == 0) {
        a = a + 3;
    } else {
        a = a + 1;
    }
}
