# This script creates a bundle of challenging test programs (.cps) and a pytest suite
# to stress–test the intermediate code generation (TAC) and semantics of the user's
# Compiscript compiler. The files are written under /mnt/data so the user can download
# them and drop them into their repo (e.g., into samples/ and tests/).

import os, textwrap, json, zipfile, pathlib

root = "/mnt/data/icg_stress_tests"
samples_dir = os.path.join(root, "samples")
tests_dir = os.path.join(root, "tests")
os.makedirs(samples_dir, exist_ok=True)
os.makedirs(tests_dir, exist_ok=True)

def w(path, content):
    with open(path, "w", encoding="utf-8") as f:
        f.write(textwrap.dedent(content).lstrip())

# --- Challenging .cps programs ---
programs = {
"ok_expr_precedence.cps": r"""
// Objetivo: forzar mucha temporales y precedencia correcta
var a = 3;
var b = 7;
var c = 11;
var d = 2;
var e = 5;
var f = 13;
var g = 4;
var h = 9;
var k = 6;

// Resultado esperado (aritmético, no exacto del TAC): 
// a = (b + c) - d * e + f / g - h % k;  // precedencia: * / % > + -  (izq a der)
a = (b + c) - d * e + f / g - h % k;

// Expresión anidada con paréntesis para cambiar orden
var x = 10;
var y = 2;
var z = 3;
// x = ((x + y) * (z + b)) - ((c - d) / (e - 1));
x = ((x + y) * (z + b)) - ((c - d) / (e - 1));
""",

"ok_boolean_short_circuit.cps": r"""
// Objetivo: verificar short-circuit (AND/OR) y generación de saltos
var a = 0;
var b = 1;
var c = 2;
var flag1 = false;
var flag2 = true;

// if con && y || mezclados
if ( (a < c) && (b == 1) || flag2 ) {
    a = a + 1;
} else {
    a = a - 1;
}

// while que depende de short-circuit (debería terminar)
while ( (a < 5) && (flag2 || (b > 10)) ) {
    a = a + 1;
}
""",

"ok_functions_recursion.cps": r"""
// Objetivo: recursión con parámetros y returns (factorial)
fun fact(n) {
    if (n <= 1) {
        return 1;
    } else {
        return n * fact(n - 1);
    }
}

var r = fact(6);  // 720
""",

"ok_scope_shadowing.cps": r"""
// Objetivo: sombreado de variables y preservación de entornos
var x = 5;

fun foo(x) {
    // x parámetro debe sombrear a x global
    var y = x + 1;
    if (y > 5) {
        var x = y * 2; // nuevo x local en bloque if (si el lenguaje lo permite)
        y = x + 3;
    }
    return y;
}

var g1 = foo(4);  // espera 6 u 11 según reglas de bloque; sirve para stress de entornos
var g2 = x;       // x global debe permanecer 5
""",

"ok_lists_and_types.cps": r"""
// Objetivo: listas homogéneas, acceso y uso en expresiones
var L = [1, 2, 3, 4];      // homogénea int
var M = [true, false, true]; // homogénea bool
var sum = 0;
var i = 0;

while (i < 4) {
    sum = sum + L[i];
    i = i + 1;
}

// if con lectura booleana de lista
if (M[1] == false) {
    sum = sum + 100;
}
""",

"err_list_heterogeneous.cps": r"""
// ERROR: lista heterogénea (tipos mezclados) si el lenguaje lo prohíbe
var Bad = [1, true, 3];
""",

"err_undeclared_var.cps": r"""
// ERROR: uso de variable no declarada
a = 10; // 'a' no declarada si el lenguaje lo exige
""",

"err_redeclared_symbol.cps": r"""
// ERROR: redeclaración en el mismo scope
var x = 1;
var x = 2;  // debería fallar
""",

"err_wrong_arg_count.cps": r"""
// ERROR: número de argumentos incorrecto
fun add(a, b) {
    return a + b;
}
var r1 = add(1);        // falta un argumento
var r2 = add(1, 2, 3);  // argumento extra
""",

"ok_control_flow_labels.cps": r"""
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
""",
}

for name, code in programs.items():
    w(os.path.join(samples_dir, name), code)

# --- pytest suite ---
test_code = r"""
import os
import re
import sys
import subprocess
from pathlib import Path

# Ajusta estas rutas si tu layout difiere:
REPO_ROOT = Path(__file__).resolve().parents[1]
DRIVER = REPO_ROOT / "program" / "Driver.py"
SAMPLES = REPO_ROOT / "samples"

def run_compiler(sample_path: Path, timeout=15):
    """Ejecuta el compilador (Driver.py) contra sample_path y retorna (rc, out, err)."""
    cmd = [sys.executable, str(DRIVER), str(sample_path)]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, text=True)
    return proc.returncode, proc.stdout, proc.stderr

def have_graphviz():
    try:
        import graphviz  # noqa
        return True
    except Exception:
        return False

def assert_no_semantic_errors(out: str, err: str):
    # Ajusta a tu formato real. Heurística:
    assert "error" not in out.lower(), f"STDOUT contiene 'error':\\n{out}"
    assert "error" not in err.lower(), f"STDERR contiene 'error':\\n{err}"
    assert "ok" in out.lower() or "semantic" in out.lower(), f"Salida no sugiere éxito:\\n{out}\\n---\\n{err}"

def assert_has_tac_patterns(out: str):
    # Busca indicios de TAC: temporales t\d+ y etiquetas L\d+
    tacs = re.findall(r"\\bt\\d+\\b\\s*=.*", out)
    labels = re.findall(r"\\bL\\d+:\\b", out)
    # No todos tus prints quizá muestren el TAC; ajusta si tu Driver imprime a archivo.
    assert len(tacs) + len(labels) >= 1, "No se detectan patrones de TAC en la salida. Ajusta el Driver para imprimir el IR/TAC."

def write_tmp(sample_name: str, content: str) -> Path:
    tmp = SAMPLES / sample_name
    tmp.write_text(content, encoding="utf-8")
    return tmp

def test_ok_expr_precedence():
    p = SAMPLES / "ok_expr_precedence.cps"
    rc, out, err = run_compiler(p)
    assert rc == 0, f"RC={rc}\\n{out}\\n{err}"
    assert_no_semantic_errors(out, err)
    assert_has_tac_patterns(out)

def test_ok_boolean_short_circuit():
    p = SAMPLES / "ok_boolean_short_circuit.cps"
    rc, out, err = run_compiler(p)
    assert rc == 0, f"RC={rc}\\n{out}\\n{err}"
    assert_no_semantic_errors(out, err)
    # Heurística: short-circuit debe generar etiquetas/saltos
    assert re.search(r"\\bL\\d+:\\b", out) or "goto" in out.lower(), "No se observan saltos/etiquetas para short-circuit."

def test_ok_functions_recursion():
    p = SAMPLES / "ok_functions_recursion.cps"
    rc, out, err = run_compiler(p, timeout=25)
    assert rc == 0, f"RC={rc}\\n{out}\\n{err}"
    assert_no_semantic_errors(out, err)

def test_ok_scope_shadowing():
    p = SAMPLES / "ok_scope_shadowing.cps"
    rc, out, err = run_compiler(p)
    assert rc == 0, f"RC={rc}\\n{out}\\n{err}"
    assert_no_semantic_errors(out, err)

def test_ok_lists_and_types():
    p = SAMPLES / "ok_lists_and_types.cps"
    rc, out, err = run_compiler(p)
    assert rc == 0, f"RC={rc}\\n{out}\\n{err}"
    assert_no_semantic_errors(out, err)

def test_control_flow_labels():
    p = SAMPLES / "ok_control_flow_labels.cps"
    rc, out, err = run_compiler(p)
    assert rc == 0, f"RC={rc}\\n{out}\\n{err}"
    assert_no_semantic_errors(out, err)
    # Debe haber varias etiquetas por if/else + while
    labels = re.findall(r"\\bL\\d+:\\b", out)
    assert len(labels) >= 2, "Se esperaban múltiples etiquetas por control de flujo."

def test_err_list_heterogeneous():
    p = SAMPLES / "err_list_heterogeneous.cps"
    rc, out, err = run_compiler(p)
    # Debe fallar semánticamente
    assert rc != 0 or "error" in (out+err).lower(), "Se esperaba error por lista heterogénea."
    assert "list" in (out+err).lower() or "heterog" in (out+err).lower() or "type" in (out+err).lower()

def test_err_undeclared_var():
    p = SAMPLES / "err_undeclared_var.cps"
    rc, out, err = run_compiler(p)
    assert rc != 0 or "error" in (out+err).lower(), "Se esperaba error por variable no declarada."
    assert "undeclared" in (out+err).lower() or "declar" in (out+err).lower() or "not defined" in (out+err).lower()

def test_err_redeclared_symbol():
    p = SAMPLES / "err_redeclared_symbol.cps"
    rc, out, err = run_compiler(p)
    assert rc != 0 or "error" in (out+err).lower(), "Se esperaba error por redeclaración."
    assert "redecl" in (out+err).lower() or "already" in (out+err).lower()

def test_err_wrong_arg_count():
    p = SAMPLES / "err_wrong_arg_count.cps"
    rc, out, err = run_compiler(p)
    assert rc != 0 or "error" in (out+err).lower(), "Se esperaba error por número de argumentos incorrecto."
    assert "argument" in (out+err).lower() or "arity" in (out+err).lower()
"""

w(os.path.join(tests_dir, "test_icg_stress.py"), test_code)

readme = r"""
# ICG Stress Tests (Compiscript)

Este paquete incluye **programas desafiantes** (`samples/*.cps`) y un **pytest** (`tests/test_icg_stress.py`) para estresar tu fase de **Generación de Código Intermedio (TAC)** y tu **análisis semántico**.

## Cómo usar

1. Copia los `.cps` de `samples/` dentro de tu carpeta `samples/` del repo.
2. Copia `tests/test_icg_stress.py` dentro de tu carpeta `tests/` del repo (o ejecútalo desde aquí ajustando `REPO_ROOT` en el archivo).
3. Ejecuta:
   ```bash
   pytest -q
