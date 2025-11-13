import os, sys, io
import streamlit as st
from streamlit_ace import st_ace
from antlr4 import InputStream, CommonTokenStream

st.set_page_config(page_title="Compiscript IDE", page_icon="🧪", layout="wide")

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.append(os.path.join(ROOT, "program"))
sys.path.append(os.path.join(ROOT, "src"))

from CompiscriptLexer import CompiscriptLexer
from CompiscriptParser import CompiscriptParser
from semantics.errors import SyntaxErrorListener
from semantics.checker import SemanticChecker
from semantics.treeviz import render_parse_tree_svg

icg_import_error = None
try:
    from semantics.icg import CodeGen as ICG  
except Exception as e:
    ICG = None
    icg_import_error = e  

def _format_tac_fallback(tac) -> str:
    lines = []
    for i, q in enumerate(getattr(tac, "code", [])):
        op = getattr(q, "op", "")
        a1 = getattr(q, "a1", getattr(q, "arg1", ""))
        a2 = getattr(q, "a2", getattr(q, "arg2", ""))
        r  = getattr(q, "r",  getattr(q, "res",  ""))
        a1 = "" if a1 is None else str(a1)
        a2 = "" if a2 is None else str(a2)
        r  = "" if r  is None else str(r)
        lines.append(f"{i:04d}: {op:12} {a1:12} {a2:12} {r}")
    return "\n".join(lines)

try:
    from semantics.ir import format_tac as _format_tac
except Exception:
    _format_tac = _format_tac_fallback

def format_tac(tac) -> str:
    try:
        return _format_tac(tac)
    except Exception:
        return _format_tac_fallback(tac)

def read_bytes_as_text(b: bytes) -> str:
    for enc in ("utf-8", "latin-1", "cp1252"):
        try:
            return b.decode(enc)
        except Exception:
            pass
    return b.decode("utf-8", errors="ignore")

DEFAULT_CODE = """let x: integer = 10;
const PI: integer = 314;
function suma(a: integer, b: integer): integer {
  return a + b;
}
let y: integer;
y = suma(x, 5);
if (y > 10) { print("Mayor a 10"); } else { print("Menor o igual"); }
"""

st.title("Compiscript IDE - Análisis Sintáctico y Semántico")

if icg_import_error:
    st.warning(f"ICG no está disponible (no se pudo importar): {icg_import_error}")

if "code" not in st.session_state:
    st.session_state.code = DEFAULT_CODE

with st.sidebar:
    st.subheader("Opciones")
    gen_tac = st.toggle("Generar TAC", value=True, help="Muestra el código intermedio si no hay errores.")
    st.divider()
    st.subheader("Icono para éxito")
    ok_up = st.file_uploader(
        "Imagen (png/jpg/webp/gif)",
        type=["png","jpg","jpeg","webp","gif"],
        accept_multiple_files=False,
        key="ok_uploader",
    )
    if ok_up is not None:
        st.session_state["ok_icon_bytes"] = ok_up.read()

code = st_ace(
    language="text",
    theme="dracula",
    auto_update=True,
    value=st.session_state.code,
    min_lines=20, max_lines=40, font_size=14, show_gutter=True,
    key="ace"
)

col1, col2 = st.columns([1,1])
run = col1.button("Analizar")

if run:
    st.session_state.code = code or ""
    input_stream = InputStream(st.session_state.code)

    # --- Parsing ---
    lexer = CompiscriptLexer(input_stream)
    tokens = CommonTokenStream(lexer)
    parser = CompiscriptParser(tokens)

    syn = SyntaxErrorListener()
    parser.removeErrorListeners()
    parser.addErrorListener(syn)

    tree = parser.program()

    if syn.has_errors:
        st.error("Errores sintácticos:")
        for e in syn.errors:
            st.write(e)
    else:
        checker = SemanticChecker()
        checker.visit(tree)

        if checker.errors:
            st.error("Errores semánticos:")
            for e in checker.errors:
                st.write(e)
        else:
            st.success("ANÁLISIS SEMÁNTICO NÍTIDO ✅")
            ok_icon = st.session_state.get("ok_icon_bytes")
            if ok_icon:
                st.image(ok_icon, width=64, caption="Semántica OK")

            if gen_tac:
                if ICG is None:
                    st.warning("ICG no está disponible (no se pudo importar). Verifica semantics/icg.py.")
                else:
                    symtab = getattr(checker, "symtab", None)
                    if symtab is None:
                        symtab = getattr(checker, "global_scope", None)

                    try:
                        icg = ICG(symtab)   
                        tac = icg.generate(tree)
                        st.subheader("Código Intermedio (TAC)")
                        st.code(format_tac(tac), language="text")
                    except Exception as ex:
                        st.error("Fallo al generar TAC.")
                        st.exception(ex)

    try:
        svg = render_parse_tree_svg(tree, parser.ruleNames)
        st.subheader("Árbol (Parse Tree)")
        st.image(svg)
    except Exception:
        st.info("No se pudo renderizar el árbol (¿instalaste Graphviz?).")
