from graphviz import Digraph
from antlr4 import ParserRuleContext, TerminalNode

def _label(node, rule_names):
    if isinstance(node, TerminalNode):
        sym = node.getSymbol()
        return f"'{sym.text}'"
    elif isinstance(node, ParserRuleContext):
        idx = node.getRuleIndex()
        return rule_names[idx]
    return type(node).__name__

def _walk(dot, node, rule_names, idx_gen):
    my_id = next(idx_gen)
    dot.node(str(my_id), _label(node, rule_names))

    for i in range(0, node.getChildCount()):
        child = node.getChild(i)
        child_id = _walk(dot, child, rule_names, idx_gen)
        dot.edge(str(my_id), str(child_id))
    return my_id

def render_parse_tree_svg(tree, rule_names):
    dot = Digraph(comment="ParseTree", format="svg")
    def counter():
        i = 0
        while True:
            yield i
            i += 1
    _walk(dot, tree, rule_names, counter())
    return dot.pipe().decode("utf-8")
