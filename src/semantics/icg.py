
from typing import Optional, List
from antlr4 import ParserRuleContext, TerminalNode
from antlr4 import ParseTreeVisitor


from .ir import TACProgram
from .temp import TempPool
from .runtime import RuntimeLayouts

class CodeGen(ParseTreeVisitor):
    """
    A reasonably grammar-agnostic ICG for Compiscript that relies on a few helper
    methods expected to exist on the grammar contexts, similar to the user's SemanticChecker.
    """
    def __init__(self, resolver=None):
        self.prog = TACProgram()
        self.temps = TempPool()
        self.layouts = RuntimeLayouts()
        self.current_function: Optional[str] = None
        self.resolver = resolver  # object with .resolve(name)->symbol (optional)

    # ---------- utilities reused from the user's style ----------
    def _expr_child(self, ctx, idx=0):
        if ctx is None or not hasattr(ctx, "expression"):
            return None
        ex = ctx.expression()
        if isinstance(ex, list):
            return ex[idx] if idx < len(ex) else None
        return ex if idx == 0 else None

    def _expr_all(self, ctx):
        if ctx is None or not hasattr(ctx, "expression"):
            return []
        ex = ctx.expression()
        return ex if isinstance(ex, list) else [ex]

    # ---------- entry points ----------
    def generate(self, tree) -> TACProgram:
        self.visit(tree)
        return self.prog

    # ---------- program / statements ----------
    def visitProgram(self, ctx):
        # emit an entry label for clarity
        self.prog.label("program_start")
        for st in getattr(ctx, "statement", lambda: [])():
            self.visit(st)
        self.prog.label("program_end")
        return None

    def visitExpressionStatement(self, ctx):
        self._gen_expr(ctx.expression())
        return None

    def visitPrintStatement(self, ctx):
        t = self._gen_expr(ctx.expression())
        self.prog.emit("PRINT", self.prog.new_temp(t) if isinstance(t, int) else t)
        self._release_if_temp(t)
        return None

    def visitVariableDeclaration(self, ctx):
        # let x [:type] = expr
        name = ctx.Identifier().getText()
        init = None
        if hasattr(ctx, "initializer") and ctx.initializer():
            init = self._expr_child(ctx.initializer(), 0)
        if init is not None:
            v = self._gen_expr(init)
            self.prog.emit("MOV", self._as_operand(v), None, name)
            self._release_if_temp(v)
        # else: uninitialized -> nothing to emit
        return None

    def visitAssignment(self, ctx):
        # x = expr
        if ctx.getChildCount() >= 2 and getattr(ctx.getChild(1), "getText", lambda: "")() == "=":
            ident = ctx.Identifier()
            if isinstance(ident, list) and ident:
                name = ident[0].getText()
            else:
                name = ident.getText() if ident else "<unknown>"
            rhs = self._expr_child(ctx, 0)
            v = self._gen_expr(rhs)
            self.prog.emit("MOV", self._as_operand(v), None, name)
            self._release_if_temp(v)
            return None
        # obj.prop = expr -> desugar as MOV obj.prop, rhs
        exprs = self._expr_all(ctx)
        if exprs and len(exprs) >= 2:
            # NOTE: object properties lowering is IR-design dependent.
            # We encode as MOV <obj>.<prop>, <val>
            rhs_node = exprs[-1]
            obj_node = exprs[0]
            prop_name = None
            ids = ctx.Identifier() if hasattr(ctx, "Identifier") else None
            if isinstance(ids, list) and ids:
                prop_name = ids[-1].getText()
            elif ids:
                prop_name = ids.getText()
            val = self._gen_expr(rhs_node)
            obj = self._gen_expr(obj_node)
            self.prog.emit("MOVP", self._as_operand(val), prop_name, self._as_operand(obj))
            self._release_if_temp(val)
            self._release_if_temp(obj)
        return None

    def visitIfStatement(self, ctx):
        cond = self._gen_expr(ctx.expression())
        L_else = self.prog.label()  # reserve name only
        L_end  = self.prog.label()
        # remove the immediate emission: label() also emits, but we just need names; workaround:
        # We'll generate fresh names instead:
        L_else = self._fresh_label()
        L_end  = self._fresh_label()

        self.prog.emit("IFZ", self._as_operand(cond), None, L_else)
        self._release_if_temp(cond)
        self.visit(ctx.block(0))
        self.prog.emit("JUMP", L_end)
        self.prog.emit("LABEL", L_else)
        if ctx.block(1):
            self.visit(ctx.block(1))
        self.prog.emit("LABEL", L_end)
        return None

    def visitWhileStatement(self, ctx):
        L_cond = self._fresh_label()
        L_end  = self._fresh_label()
        self.prog.emit("LABEL", L_cond)
        cond = self._gen_expr(ctx.expression())
        self.prog.emit("IFZ", self._as_operand(cond), None, L_end)
        self._release_if_temp(cond)
        self.visit(ctx.block())
        self.prog.emit("JUMP", L_cond)
        self.prog.emit("LABEL", L_end)
        return None

    def visitReturnStatement(self, ctx):
        v = None
        if hasattr(ctx, "expression") and ctx.expression():
            v = self._gen_expr(ctx.expression())
            self.prog.emit("RET", self._as_operand(v))
            self._release_if_temp(v)
        else:
            self.prog.emit("RET")
        return None

    # ---------- expressions ----------
    def visitExprNoAssign(self, ctx):
        return self._gen_expr(ctx.conditionalExpr())

    def visitTernaryExpr(self, ctx):
        # cond ? e1 : e2
        cond_t = self._gen_expr(ctx.logicalOrExpr())
        L_false = self._fresh_label()
        L_end   = self._fresh_label()
        self.prog.emit("IFZ", self._as_operand(cond_t), None, L_false)
        self._release_if_temp(cond_t)

        t1 = self._gen_expr(ctx.expression(0))
        res_idx = self.temps.get()
        res = self._temp_name(res_idx)
        self.prog.emit("MOV", self._as_operand(t1), None, res)
        self._release_if_temp(t1)
        self.prog.emit("JUMP", L_end)

        self.prog.emit("LABEL", L_false)
        t2 = self._gen_expr(ctx.expression(1))
        self.prog.emit("MOV", self._as_operand(t2), None, res)
        self._release_if_temp(t2)

        self.prog.emit("LABEL", L_end)
        return res_idx

    def visitAdditiveExpr(self, ctx):
        # supports + and - with left-associativity
        terms = [self._gen_expr(ctx.multiplicativeExpr(i)) for i in range(len(ctx.multiplicativeExpr()))]
        ops = [ctx.getChild(i).getText() for i in range(1, ctx.getChildCount(), 2)]
        if not ops:
            return terms[0]
        acc = terms[0]
        for op, rhs in zip(ops, terms[1:]):
            acc = self._emit_bin(op, acc, rhs)
        return acc

    def visitRelationalExpr(self, ctx):
        # Lower <, <=, >, >=, ==, != into CMP+conditional set (represented as op with two args -> temp)
        exprs = [self._gen_expr(ctx.additiveExpr(i)) for i in range(len(ctx.additiveExpr()))]
        ops = [ctx.getChild(i).getText() for i in range(1, ctx.getChildCount(), 2)]
        if not ops:
            return exprs[0]
        acc = exprs[0]
        for op, rhs in zip(ops, exprs[1:]):
            acc = self._emit_cmp(op, acc, rhs)
        return acc

    def visitLogicalAndExpr(self, ctx):
        # short-circuit: a && b
        if len(ctx.children) == 1:
            return self.visit(ctx.equalityExpr(0))
        res_idx = self.temps.get()
        res = self._temp_name(res_idx)
        L_false = self._fresh_label()
        L_end   = self._fresh_label()

        left = self.visit(ctx.equalityExpr(0))
        self.prog.emit("IFZ", self._as_operand(left), None, L_false)
        self._release_if_temp(left)
        right = self.visit(ctx.equalityExpr(1))
        self.prog.emit("MOV", self._as_operand(right), None, res)
        self._release_if_temp(right)
        self.prog.emit("JUMP", L_end)
        self.prog.emit("LABEL", L_false)
        self.prog.emit("MOV", "0", None, res)
        self.prog.emit("LABEL", L_end)
        return res_idx

    def visitLogicalOrExpr(self, ctx):
        # short-circuit: a || b
        if len(ctx.children) == 1:
            return self.visit(ctx.logicalAndExpr(0))
        res_idx = self.temps.get()
        res = self._temp_name(res_idx)
        L_true = self._fresh_label()
        L_end  = self._fresh_label()

        left = self.visit(ctx.logicalAndExpr(0))
        # if left != 0 goto L_true
        self.prog.emit("IFNZ", self._as_operand(left), None, L_true)
        self._release_if_temp(left)
        right = self.visit(ctx.logicalAndExpr(1))
        self.prog.emit("MOV", self._as_operand(right), None, res)
        self._release_if_temp(right)
        self.prog.emit("JUMP", L_end)
        self.prog.emit("LABEL", L_true)
        self.prog.emit("MOV", "1", None, res)
        self.prog.emit("LABEL", L_end)
        return res_idx

    # ---------- primaries / function calls ----------
    def visitLeftHandSide(self, ctx):
        # Handle chained . and () and [] similar to SemanticChecker but produce temps
        # For now, only simple identifiers and function calls are lowered.
        pa = ctx.primaryAtom()
        ident_node = None
        if hasattr(pa, "Identifier") and pa.Identifier():
            ident_node = pa.Identifier()
            name = ident_node[0].getText() if isinstance(ident_node, list) else ident_node.getText()
            return name  # variable name as operand
        # literals go through visitTerminal
        return self.visit(pa)

    def visitTerminal(self, node: TerminalNode):
        t = node.getText()
        # Keep literals as immediates
        return t

    def visitFunctionDeclaration(self, ctx):
        name = ctx.Identifier().getText()
        self.prog.emit("LABEL", f"func_{name}")
        self.current_function = name

        # Build basic frame layout: params then locals (discovered during walk)
        # Params
        if ctx.parameters():
            for p in ctx.parameters().parameter():
                self.layouts.frame(name).add_param(p.Identifier().getText())

        # Visit body; locals will be added by variableDeclaration inside functions
        self.visit(ctx.block())

        self.prog.emit("RET")  # implicit return if none
        self.current_function = None
        return None

    def visitBlock(self, ctx):
        # In a real implementation, we'd open a scope. For IR we only care about locals allocation.
        for st in getattr(ctx, "statement", lambda: [])():
            self.visit(st)
        return None

    # ---------- helpers ----------
    def _emit_bin(self, op, left, right):
        idx = self.temps.get()
        res = self._temp_name(idx)
        ir_op = {"+": "ADD", "-": "SUB", "*": "MUL", "/": "DIV"}.get(op, f"BIN_{op}")
        self.prog.emit(ir_op, self._as_operand(left), self._as_operand(right), res)
        self._release_if_temp(left)
        self._release_if_temp(right)
        return idx

    def _emit_cmp(self, op, left, right):
        idx = self.temps.get()
        res = self._temp_name(idx)
        self.prog.emit(f"CMP{op}", self._as_operand(left), self._as_operand(right), res)
        self._release_if_temp(left)
        self._release_if_temp(right)
        return idx

    def _as_operand(self, x):
        if isinstance(x, int):
            return self._temp_name(x)
        return str(x)

    def _temp_name(self, idx: int) -> str:
        return f"t{idx}"

    def _release_if_temp(self, x):
        if isinstance(x, int):
            self.temps.release(x)

    def _fresh_label(self) -> str:
        # piggyback on TACProgram counter by emitting a dummy label name
        n = len([i for i in self.prog.code if i.op == "LABEL"])
        return f"L{n}"
