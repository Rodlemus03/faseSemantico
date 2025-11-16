// Objetivo: sombreado de variables y preservación de entornos
var x = 5;

fun foo(x) {
    var y = x + 1;
    if (y > 5) {
        var x = y * 2;
        y = x + 3;
    }
    return y;
}

var g1 = foo(4);
var g2 = x;
