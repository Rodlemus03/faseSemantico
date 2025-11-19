// Objetivo: recursión con parámetros y returns (factorial)
fun fact(n) {
    if (n <= 1) {
        return 1;
    } else {
        return n * fact(n - 1);
    }
}

var r = fact(6);
