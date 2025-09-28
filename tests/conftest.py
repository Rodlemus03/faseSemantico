import os, sys, re, pytest
from antlr4 import InputStream, CommonTokenStream

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.append(os.path.join(ROOT, "program"))
sys.path.append(os.path.join(ROOT, "src"))

from CompiscriptLexer import CompiscriptLexer
from CompiscriptParser import CompiscriptParser
from semantics.errors import SyntaxErrorListener
from semantics.checker import SemanticChecker
from semantics.icg import CodeGen

def _parse(code: str):
    input_stream = InputStream(code)
    lexer = CompiscriptLexer(input_stream)
    tokens = CommonTokenStream(lexer)
    parser = CompiscriptParser(tokens)
    syn = SyntaxErrorListener()
    parser.removeErrorListeners()
    parser.addErrorListener(syn)
    tree = parser.program()
    return tree, parser, syn

def _sema(tree):
    checker = SemanticChecker()
    checker.visit(tree)
    return checker

def gen_icg(code: str):
    """Parse + Semántica + ICG → (prog, codegen)"""
    tree, parser, syn = _parse(code)
    assert not syn.has_errors, f"Errores sintácticos: {syn.errors}"
    checker = _sema(tree)
    assert not checker.errors, f"Errores semánticos: {checker.errors}"
    # Si tu CodeGen espera resolver, pásale checker (tiene resolve/tabla)
    cg = CodeGen(resolver=getattr(checker, "symtab", getattr(checker, "global_scope", None)))
    prog = cg.generate(tree)
    return prog, cg

def tac_lines(prog) -> list[str]:
    # Tu TACProgram tiene .dumps()
    return [line.strip() for line in prog.dumps().splitlines()]

def grep(lines, pat):
    return [i for i,l in enumerate(lines) if pat in l]
