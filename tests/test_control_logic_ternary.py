from conftest import gen_icg, tac_lines

def test_if_while_labels_and_branches():
    src = """
    function main(): integer {
      let i: integer = 0;
      let n: integer = 3;
      if (i < n) { i = i + 1; } else { i = n; }
      while (i < n) { i = i + 1; }
      return i;
    }
    """
    prog, cg = gen_icg(src)
    lines = tac_lines(prog)
    assert any("LABEL" in l for l in lines)
    assert any("IFZ" in l for l in lines)
    assert any("JUMP" in l for l in lines)

def test_logic_and_or_and_ternary():
    src = """
    function f(a: integer, b: integer): integer {
      let x: integer = (a < b) && (b != 0) ? a : b;
      let y: integer = (a < b) || (a == 0) ? b : a;
      return x + y;
    }
    """
    prog, cg = gen_icg(src)
    lines = tac_lines(prog)
    assert any("IFZ" in l for l in lines)
    assert any("MOV" in l for l in lines)  
