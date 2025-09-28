# tests/test_temp_pressure.py
import re
from conftest import gen_icg, tac_lines

def test_temp_pressure_reuse():
    expr = " + ".join(str(i) for i in range(30))
    src = f"""
    function main(): integer {{
      let x: integer = {expr};
      return x;
    }}
    """
    prog, cg = gen_icg(src)
    lines = tac_lines(prog)
    # contar apariciones de tN
    temps = set()
    for l in lines:
        temps.update(re.findall(r"\bt(\d+)\b", l))
    # no exigimos un número exacto, pero no debería ser 30 distintos
    assert len(temps) < 25
