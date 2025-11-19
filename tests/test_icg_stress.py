
import os
import re
import sys
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DRIVER = REPO_ROOT / "program" / "Driver.py"
SAMPLES = REPO_ROOT / "samples"

def run_compiler(sample_path: Path, timeout=15):
    cmd = [sys.executable, str(DRIVER), str(sample_path)]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, text=True)
    return proc.returncode, proc.stdout, proc.stderr

def assert_no_semantic_errors(out: str, err: str):
    assert "error" not in out.lower(), f"STDOUT contiene 'error':\\n{out}"
    assert "error" not in err.lower(), f"STDERR contiene 'error':\\n{err}"
    assert "ok" in out.lower() or "semantic" in out.lower(), f"Salida no sugiere éxito:\\n{out}\\n---\\n{err}"

def assert_has_tac_patterns(out: str):
    tacs = re.findall(r"\\bt\\d+\\b\\s*=.*", out)
    labels = re.findall(r"\\bL\\d+:\\b", out)
    assert len(tacs) + len(labels) >= 1, "No se detectan patrones de TAC en la salida. Ajusta el Driver para imprimir el IR/TAC."

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
    labels = re.findall(r"\\bL\\d+:\\b", out)
    assert len(labels) >= 2, "Se esperaban múltiples etiquetas por control de flujo."

def test_err_list_heterogeneous():
    p = SAMPLES / "err_list_heterogeneous.cps"
    rc, out, err = run_compiler(p)
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
