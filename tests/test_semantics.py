
from pathlib import Path
from typing import List, Tuple

from antlr4 import InputStream, CommonTokenStream
from antlr4.error.ErrorListener import ErrorListener

# Rutas para importar el lexer/parser y el checker
ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.append(str(ROOT / "program"))
sys.path.append(str(ROOT / "src"))

from CompiscriptLexer import CompiscriptLexer
from CompiscriptParser import CompiscriptParser
from semantics.errors import SyntaxErrorListener
from semantics.checker import SemanticChecker


def parse_and_check(code: str) -> Tuple[List[str], List[str]]:
    """Devuelve (syntax_errors, semantic_errors)"""
    input_stream = InputStream(code)
    lexer = CompiscriptLexer(input_stream)
    tokens = CommonTokenStream(lexer)
    parser = CompiscriptParser(tokens)

    syn = SyntaxErrorListener()
    parser.removeErrorListeners()
    parser.addErrorListener(syn)

    tree = parser.program()
    if syn.has_errors:
        return syn.errors, []

    checker = SemanticChecker()
    checker.visit(tree)
    return [], checker.errors



CASES = [

#  Sistema de Tipos 
("tipos/aritmetica_ok", "OK", """
let a: integer = 1 + 2 * 3;
let b: float = 2.5 * 4 - 1.0;
""", []),

("tipos/aritmetica_err", "ERR", """
let a: integer = true + 3;
""", ["Suma/resta requiere", "operandos numéricos"]),

("tipos/logica_ok", "OK", """
let a: boolean = true && (false || !false);
""", []),

("tipos/logica_err1", "ERR", """
let a: boolean = 1 && true;
""", ["Operación lógica requiere booleanos"]),

("tipos/logica_err2", "ERR", """
let a: boolean = !5;
""", ["Negación lógica requiere", "boolean"]),

("tipos/comparacion_ok", "OK", """
let a: boolean = 3 < 5;
let b: boolean = 2.0 >= 1.5;
let c: boolean = 10 == 10;
""", []),

("tipos/comparacion_err_eq", "ERR", """
let a: boolean = 1 == "x";
""", ["Comparación entre tipos incompatibles"]),

("tipos/comparacion_err_rel", "ERR", """
let a: boolean = "x" < 5;
""", ["Comparación relacional requiere números"]),

("tipos/asignacion_ok", "OK", """
let a: integer;
a = 10;
""", []),

("tipos/asignacion_err", "ERR", """
let a: integer;
a = "hola";
""", ["Asignación incompatible", "variable 'a' es integer", "expresión es string"]),

("tipos/const_ok", "OK", """
const PI: integer = 314;
""", []),

("tipos/const_mal_tipo", "ERR", """
const PI: integer = "x";
""", ["Constante 'PI' declarada como integer", "inicializa con string"]),

("tipos/const_reasignacion", "ERR", """
const PI: integer = 3;
PI = 4;
""", ["No se puede asignar a constante", "PI"]),

# Listas y estructuras
("listas/homogenea_ok", "OK", """
let xs: integer[] = [1,2,3];
let x: integer = xs[0];
""", []),

("listas/heterogenea_err", "ERR", """
let xs: integer[] = [1, true];
""", ["Arreglo con elementos de tipos incompatibles"]),

("listas/indice_tipo_err", "ERR", """
let xs: integer[] = [1,2,3];
let a: integer = xs[true];
""", ["índice de un arreglo debe ser integer"]),

("listas/indexar_no_arreglo_err", "ERR", """
let s: integer = 5;
let a: integer = s[0];
""", ["Indexación requiere un arreglo"]),

# Ámbitos
("ambito/uso_no_declarada", "ERR", """
x = 1;
""", ["Variable no declarada: x"]),

("ambito/redeclaracion_mismo_ambito", "ERR", """
let x: integer = 1;
let x: integer = 2;
""", ["Redeclaración en el mismo ámbito: x"]),

("ambito/sombras_ok", "OK", """
let x: integer = 1;
{ let x: integer = 2; }
""", []),

("ambito/usar_var_interna_fuera", "ERR", """
{ let y: integer = 2; }
y = 3;
""", ["Variable no declarada: y"]),

# Funciones y procedimientos
("func/llamada_ok", "OK", """
function f(a: integer, b: integer): integer { return a + b; }
let r: integer = f(1, 2);
""", []),

("func/llamada_arity_err", "ERR", """
function f(a: integer, b: integer): integer { return a + b; }
let r: integer = f(1);
""", ["espera 2 argumentos", "recibió 1"]),

("func/llamada_tipo_err", "ERR", """
function f(a: integer, b: integer): integer { return a + b; }
let r: integer = f(1, true);
""", ["Argumento 2 de 'f' debe ser integer", "recibió boolean"]),

("func/return_tipo_err", "ERR", """
function g(): integer { return "x"; }
""", ["return", "devuelve string", "función retorna integer"]),

("func/return_fuera_err", "ERR", """
return 1;
""", ["'return' solo se permite dentro de una función"]),

("func/recursion_ok", "OK", """
function fact(n: integer): integer {
  if (n < 2) { return 1; }
  else { return n * fact(n - 1); }
}
""", []),

("func/anidada_ok", "OK", """
function outer(a: integer): integer {
  function inner(b: integer): integer { return a + b; }
  return inner(3);
}
""", []),

("func/duplicadas_err", "ERR", """
function f(): integer { return 1; }
function f(): integer { return 2; }
""", ["Redeclaración en el mismo ámbito: f"]),

("func/llamar_no_funcion_err", "ERR", """
let x: integer = 10;
x(2);
""", ["Llamada aplicada a algo que no es función declarada"]),

# Control de flujo
("flujo/conds_boolean_ok", "OK", """
if (true) { }
while (false) { break; }
do { } while (true);
for (; true; ) { break; }
""", []),

("flujo/if_cond_err", "ERR", """
if (1) { }
""", ["condición de 'if' debe ser boolean"]),

("flujo/while_cond_err", "ERR", """
while (1) { }
""", ["condición de 'while' debe ser boolean"]),

("flujo/do_while_cond_err", "ERR", """
do { } while (1);
""", ["condición de 'do-while' debe ser boolean"]),

("flujo/for_cond_err", "ERR", """
for (; 1; ) { }
""", ["condición de 'for' debe ser boolean"]),

("flujo/break_outside_err", "ERR", """
break;
""", ["'break' solo se permite dentro de bucles"]),

("flujo/continue_outside_err", "ERR", """
continue;
""", ["'continue' solo se permite dentro de bucles"]),

("flujo/switch_cond_err", "ERR", """
switch (1) { default: }
""", ["expresión de 'switch' debe ser boolean"]),

# Clases y objetos
("clases/campos_metodos_ok", "OK", """
class Point {
  let x: integer;
  let y: integer;
  function setX(v: integer): integer { this.x = v; return this.x; }
  function getX(): integer { return this.x; }
}
let p: Point = new Point();
p.setX(3);
let t: integer = p.getX();
""", []),

("clases/campo_inexistente_err", "ERR", """
class C { let x: integer; }
let o: C = new C();
let a: integer = o.y;
""", ["no tiene miembro 'y'"]),

("clases/metodo_arity_err", "ERR", """
class C { function m(a: integer): integer { return a; } }
let o: C = new C();
let x: integer = o.m();
""", ["espera 1 argumentos", "recibió 0"]),

("clases/this_fuera_err", "ERR", """
let y: integer = this.x;
""", ["'this' solo puede usarse dentro de métodos de clase"]),

("clases/asignacion_campo_tipo_err", "ERR", """
class C { let x: integer; }
let o: C = new C();
o.x = true;
""", ["Asignación incompatible: campo 'x' es integer", "expresión es boolean"]),

("clases/asignacion_campo_const_err", "ERR", """
class C { const z: integer = 1; }
let o: C = new C();
o.z = 2;
""", ["No se puede asignar al campo constante 'z'"]),

# Generales
("generales/codigo_muerto_err", "ERR", """
function dead(): integer {
  return 1;
  let zzz: integer = 2;
}
""", ["Código inalcanzable"]),
]


# ------------------------------
# Harness
# ------------------------------
GREEN = "\033[92m"
RED   = "\033[91m"
RESET = "\033[0m"

def ensure_samples():
    outdir = ROOT / "samples"
    outdir.mkdir(exist_ok=True)
    for name, _, code, _ in CASES:
        if any(tag in name for tag in ["aritmetica_", "listas/", "clases/campos", "generales/codigo_muerto"]):
            p = outdir / (name.replace("/", "_") + ".cps")
            try:
                p.write_text(code.strip() + "\n", encoding="utf-8")
            except Exception:
                pass
    print(f"Se generaron ejemplos en: {outdir}")

def run():
    ensure_samples()
    passed = 0
    failed = 0
    for name, expect, code, must in CASES:
        syn, sem = parse_and_check(code)
        ok = True
        detail_lines = []

        if syn:
            ok = False
            detail_lines.extend(syn)
            status = "synerr"
        else:
            if expect == "OK":
                ok = len(sem) == 0
                status = "OK" if ok else "semerr"
            else:
                ok = len(sem) > 0 and all(any(m in e for e in sem) for m in must)
                status = "ERR" if ok else "semok?"

        if ok:
            passed += 1
            print(f"{GREEN}PASS{RESET}: {name} / {status}")
        else:
            failed += 1
            print(f"{RED}FAIL{RESET}: {name} / {status} (esperado={expect})")
            for e in (sem if sem else syn):
                print(f"   -> {e}")

    print(f"\nResumen: {passed} PASS, {failed} FAIL")


if __name__ == "__main__":
    run()
