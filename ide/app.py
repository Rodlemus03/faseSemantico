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

# IMPORTAR ICG 
icg_import_error = None
try:
    from semantics.icg import CodeGen as ICG  
except Exception as e:
    ICG = None
    icg_import_error = e

# IMPORTAR GENERADOR MIPS
mips_import_error = None
try:
    from semantics.codegen_mips import generate_mips_from_tac
    MIPS_AVAILABLE = True
except Exception as e:
    generate_mips_from_tac = None
    MIPS_AVAILABLE = False
    mips_import_error = e

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
print(y);
if (y > 10) { 
  print(1); 
} else { 
  print(0); 
}
"""

st.title("🧪 Compiscript IDE - Compilador Completo")

# WARNINGS DE IMPORTACIÓN 
if icg_import_error:
    st.warning(f"⚠️ ICG no disponible: {icg_import_error}")

if mips_import_error:
    st.warning(f"⚠️ Generador MIPS no disponible: {mips_import_error}")

if "code" not in st.session_state:
    st.session_state.code = DEFAULT_CODE

# SIDEBAR CON OPCIONES 
with st.sidebar:
    st.header("⚙️ Opciones de Compilación")
    
    gen_tac = st.toggle(
        "📋 Generar TAC", 
        value=True, 
        help="Muestra el código intermedio (Three-Address Code)"
    )
    
    gen_mips = st.toggle(
        "💾 Generar MIPS", 
        value=True, 
        help="Genera código assembly MIPS32",
        disabled=not MIPS_AVAILABLE
    )
    
    st.divider()
    
    st.subheader("🎨 Personalización")
    ok_up = st.file_uploader(
        "Icono de éxito (png/jpg/webp/gif)",
        type=["png","jpg","jpeg","webp","gif"],
        accept_multiple_files=False,
        key="ok_uploader",
    )
    if ok_up is not None:
        st.session_state["ok_icon_bytes"] = ok_up.read()
    
    st.divider()
    st.caption("Compiscript Compiler v1.0")
    st.caption("Diseño de Compiladores - UVG")

# EDITOR DE CÓDIGO 
code = st_ace(
    language="text",
    theme="dracula",
    auto_update=True,
    value=st.session_state.code,
    min_lines=20, 
    max_lines=40, 
    font_size=14, 
    show_gutter=True,
    key="ace"
)

#  BOTÓN DE COMPILAR 
col1, col2, col3 = st.columns([1,1,2])
run = col1.button("🚀 Compilar", type="primary", use_container_width=True)

if run:
    st.session_state.code = code or ""
    input_stream = InputStream(st.session_state.code)

    # --- ANÁLISIS LÉXICO Y SINTÁCTICO ---
    lexer = CompiscriptLexer(input_stream)
    tokens = CommonTokenStream(lexer)
    parser = CompiscriptParser(tokens)

    syn = SyntaxErrorListener()
    parser.removeErrorListeners()
    parser.addErrorListener(syn)

    tree = parser.program()

    if syn.has_errors:
        st.error("Errores Sintácticos:")
        for e in syn.errors:
            st.code(e, language="text")
    else:
        # ANÁLISIS SEMÁNTICO
        checker = SemanticChecker()
        checker.visit(tree)

        if checker.errors:
            st.error("Errores Semánticos:")
            for e in checker.errors:
                st.code(e, language="text")
        else:
            # ÉXITO 
            st.success("✅ ANÁLISIS SEMÁNTICO EXITOSO")
            
            ok_icon = st.session_state.get("ok_icon_bytes")
            if ok_icon:
                col1, col2, col3 = st.columns([1,1,1])
                with col2:
                    st.image(ok_icon, width=128, caption="¡Código válido!")

            # GENERAR TAC 
            tac_program = None
            
            if gen_tac or gen_mips:  # Necesitamos TAC para MIPS
                if ICG is None:
                    st.warning("⚠️ No se puede generar TAC (ICG no disponible)")
                else:
                    try:
                        # Resolver el symbol table del checker
                        resolver = getattr(checker, "symtab", None)
                        if resolver is None:
                            resolver = getattr(checker, "global_scope", None)
                        
                        # Generar TAC
                        icg = ICG(resolver=resolver)
                        tac_program = icg.generate(tree)
                        
                        if gen_tac:
                            st.subheader("📋 Código Intermedio (TAC)")
                            tac_text = format_tac(tac_program)
                            st.code(tac_text, language="text", line_numbers=True)
                            
                            # Botón para descargar TAC
                            st.download_button(
                                label="💾 Descargar TAC",
                                data=tac_text,
                                file_name="program.tac",
                                mime="text/plain"
                            )
                    
                    except Exception as ex:
                        st.error("❌ Error al generar TAC")
                        st.exception(ex)
            
            # GENERAR MIPS 
            if gen_mips and tac_program is not None:
                if not MIPS_AVAILABLE:
                    st.warning("⚠️ Generador MIPS no disponible")
                else:
                    try:
                        st.subheader("💾 Código Assembly MIPS")
                        
                        with st.spinner("Generando código MIPS..."):
                            mips_code = generate_mips_from_tac(tac_program)
                        
                        # Mostrar el código MIPS
                        st.code(mips_code, language="mipsasm", line_numbers=True)
                        
                        # Métricas del código generado
                        col1, col2, col3 = st.columns(3)
                        with col1:
                            st.metric("Líneas MIPS", len(mips_code.split('\n')))
                        with col2:
                            st.metric("Instrucciones TAC", len(tac_program.code))
                        with col3:
                            ratio = len(mips_code.split('\n')) / max(len(tac_program.code), 1)
                            st.metric("Expansión", f"{ratio:.1f}x")
                        
                        # Botones de descarga
                        col1, col2 = st.columns(2)
                        with col1:
                            st.download_button(
                                label="💾 Descargar .asm",
                                data=mips_code,
                                file_name="program.asm",
                                mime="text/plain",
                                use_container_width=True
                            )
                        with col2:
                            # También ofrecer el TAC
                            if tac_program:
                                st.download_button(
                                    label="📋 Descargar .tac",
                                    data=format_tac(tac_program),
                                    file_name="program.tac",
                                    mime="text/plain",
                                    use_container_width=True
                                )
                    except Exception as ex:
                        st.error(" Error al generar código MIPS")
                        st.exception(ex)
                        
                        # Debug info
                        with st.expander("🔍 Información de Debug"):
                            st.write("TAC Program:", tac_program)
                            if hasattr(tac_program, 'code'):
                                st.write("Instrucciones TAC:")
                                for i, ins in enumerate(tac_program.code[:10]):  
                                    st.write(f"{i}: {ins}")

    # PARSE TREE 
    with st.expander("Ver Árbol de Sintaxis (Parse Tree)"):
        try:
            svg = render_parse_tree_svg(tree, parser.ruleNames)
            st.image(svg, use_column_width=True)
        except Exception as e:
            st.info("No se pudo renderizar el árbol (¿Graphviz instalado?)")
            st.caption(f"Error: {e}")

