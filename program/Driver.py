import sys, os
from antlr4 import FileStream, CommonTokenStream
from antlr4.error.ErrorListener import ErrorListener

# Generated names: CompiscriptLexer.py, CompiscriptParser.py
from CompiscriptLexer import CompiscriptLexer
from CompiscriptParser import CompiscriptParser

# Make src importable
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from src.semantics.errors import SyntaxErrorListener, SemanticError
from src.semantics.checker import SemanticChecker
from src.semantics.treeviz import render_parse_tree_svg

def main():
    if len(sys.argv) < 2:
        print("Usage: python Driver.py <file.cps>")
        sys.exit(1)

    filename = sys.argv[1]
    input_stream = FileStream(filename, encoding='utf-8')

    # Lexing & Parsing
    lexer = CompiscriptLexer(input_stream)
    token_stream = CommonTokenStream(lexer)
    parser = CompiscriptParser(token_stream)

    syntax_listener = SyntaxErrorListener()
    parser.removeErrorListeners()
    parser.addErrorListener(syntax_listener)

    tree = parser.program()

    if syntax_listener.has_errors:
        for e in syntax_listener.errors:
            print(e)
        sys.exit(1)

    # Semantic checking
    checker = SemanticChecker()
    checker.visit(tree)

    if checker.errors:
        for err in checker.errors:
            print(err)
        sys.exit(1)

    # Optional: write parse tree SVG next to source
    try:
        svg = render_parse_tree_svg(tree, parser.ruleNames)
        out_svg = os.path.splitext(filename)[0] + "_parsetree.svg"
        with open(out_svg, "w", encoding="utf-8") as f:
            f.write(svg)
    except Exception as ex:
        # Graphviz not installed or other non-critical issues
        pass

    print("Semantic OK")

if __name__ == "__main__":
    main()
