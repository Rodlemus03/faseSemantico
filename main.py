
from antlr4 import FileStream, CommonTokenStream
from program.CompiscriptLexer import CompiscriptLexer
from program.CompiscriptParser import CompiscriptParser
from src.semantics.icg import CodeGen
from src.semantics.codegen_mips import gen_program_from_tac
import os

def compile_file(filepath: str):
    print(f"Compilando {filepath}...")

    input_stream = FileStream(filepath, encoding='utf-8')
    lexer = CompiscriptLexer(input_stream)
    tokens = CommonTokenStream(lexer)
    parser = CompiscriptParser(tokens)

    tree = parser.program()
    if parser.getNumberOfSyntaxErrors() > 0:
        print("❌ Error de sintaxis")
        return

    # 2️⃣ Generar código intermedio (TAC)
    cg = CodeGen()
    tac_program = cg.generate(tree)
    os.makedirs("build", exist_ok=True)

    tac_path = os.path.join("build", "tac.txt")
    with open(tac_path, "w", encoding="utf-8") as f:
        for ins in tac_program.code:
            if ins.op == "LABEL":
                label = ins.res if ins.res else ins.a1
                f.write(f"{label}:\n")
            else:
                a1 = ins.a1 or ""
                a2 = ins.a2 or ""
                res = ins.res or ""
                f.write(f"{ins.op}\t{a1}\t{a2}\t{res}\n")

    print(f"✅ TAC generado: {tac_path}")

    try:
        asm = gen_program_from_tac(tac_program)
        asm_path = os.path.join("build", "output.s")
        with open(asm_path, "w", encoding="utf-8") as f:
            f.write(asm)
        print(f"✅ ASM MIPS generado: {asm_path}")
    except Exception as e:
        print("⚠️ No se pudo generar MIPS (backend no disponible o error interno).")
        print(e)

if __name__ == "__main__":
    compile_file("samples/tipos_aritmetica_ok.cps")
