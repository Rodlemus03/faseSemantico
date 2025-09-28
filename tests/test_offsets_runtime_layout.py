from conftest import gen_icg

def test_param_positive_local_negative_offsets():
    src = """
    function h(a: integer, b: integer): integer {
      let x: integer;
      let y: integer;
      return a + b + x + y;
    }
    """
    prog, cg = gen_icg(src)
    fl = cg.layouts.frame("h")
    assert "a" in fl.params and "b" in fl.params
    assert "x" in fl.locals and "y" in fl.locals
    assert fl.params["a"].offset > 0 and fl.params["b"].offset > 0
    assert fl.locals["x"].offset < 0 and fl.locals["y"].offset < 0
    assert fl.frame_size >= 8
