from conftest import gen_icg, tac_lines, grep

def test_enter_leave_ret_without_locals():
    src = """
    function f(a: integer): integer { 
      return a; 
    }
    """
    prog, cg = gen_icg(src)
    lines = tac_lines(prog)
    assert any("LABEL func_f" in l for l in lines)
    assert any(l.startswith("ENTER") for l in lines)
    assert any("LABEL f_exit" in l for l in lines)
    assert any(l.startswith("LEAVE") for l in lines)
    assert any(l.startswith("RET") for l in lines)
    enter_lines = [l for l in lines if l.startswith("ENTER")]
    assert len(enter_lines) == 1
    size = int(enter_lines[0].split()[1])
    assert size == 8

def test_enter_backpatched_with_locals():
    src = """
    function g(a: integer, b: integer): integer {
      let x: integer;
      let y: integer;
      if (a < b) { let t: integer; }
      return a + b;
    }
    """
    prog, cg = gen_icg(src)
    lines = tac_lines(prog)
    enter_lines = [l for l in lines if l.startswith("ENTER")]
    assert len(enter_lines) == 1
    size = int(enter_lines[0].split()[1])
    assert size > 8
    assert any(l.startswith("LEAVE") for l in lines)
    assert any(l.startswith("RET") for l in lines)
