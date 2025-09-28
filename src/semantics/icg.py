from typing import Optional, List
from antlr4 import ParserRuleContext, TerminalNode
from antlr4 import ParseTreeVisitor

from .ir import TACProgram
from .temp import TempPool
from .runtime import RuntimeLayouts
from .symbols import FunctionSymbol, VarSymbol, ParamSymbol


class CodeGen(ParseTreeVisitor):

    def __init__(self, resolver=None):
        self.prog = TACProgram()
        self.temps = TempPool()
        self.layouts = RuntimeLayouts()
        self.current_function: Optional[str] = None
        self.resolver = resolver  
        self.func_ret_idx: Optional[int] = None  

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

    def _gen_expr(self, ctx):
        return self.visit(ctx)

    def generate(self, tree) -> TACProgram:
        self.visit(tree)
        return self.prog

    def visitProgram(self, ctx):
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
        name = ctx.Identifier().getText()

        if self.current_function:
            sym = None
            if self.resolver:
                try:
                    sym = self.resolver.resolve(name)
                except Exception:
                    sym = None
            if sym is None:
                sym = VarSymbol(name=name, type=None)
            self.layouts.frame(self.current_function).add_local(sym)

        init = None
        if hasattr(ctx, "initializer") and ctx.initializer():
            init = self._expr_child(ctx.initializer(), 0)
        if init is not None:
            v = self._gen_expr(init)
            self.prog.emit("MOV", self._as_operand(v), None, name)
            self._release_if_temp(v)
        return None

    def visitAssignment(self, ctx):
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

        exprs = self._expr_all(ctx)
        if exprs and len(exprs) >= 2:
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
        L_else = self._fresh_label()
        L_end = self._fresh_label()

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
        L_end = self._fresh_label()

        self.prog.emit("LABEL", L_cond)
        cond = self._gen_expr(ctx.expression())
        self.prog.emit("IFZ", self._as_operand(cond), None, L_end)
        self._release_if_temp(cond)

        self.visit(ctx.block())
        self.prog.emit("JUMP", L_cond)
        self.prog.emit("LABEL", L_end)
        return None

    def visitFunctionDeclaration(self, ctx):
        name = ctx.Identifier().getText()
        self.current_function = name

        func_sym: Optional[FunctionSymbol] = None
        if self.resolver:
            try:
                func_sym = self.resolver.resolve(name)
            except Exception:
                func_sym = None

        entry_lbl = f"func_{name}"
        exit_lbl = f"{name}_exit"
        if func_sym:
            func_sym.entry_label = entry_lbl
            func_sym.exit_label = exit_lbl

        self.prog.emit("LABEL", entry_lbl)

        fl = self.layouts.frame(name)

        if ctx.parameters():
            for i, p in enumerate(ctx.parameters().parameter()):
                p_name = p.Identifier().getText()
                sym = None
                if self.resolver:
                    try:
                        sym = self.resolver.resolve(p_name)
                    except Exception:
                        sym = None
                if isinstance(sym, VarSymbol):
                    sym.is_param = True
                    sym.param_index = i
                fl.add_param(sym if sym else VarSymbol(name=p_name, type=None))

        enter_idx = len(self.prog.code)
        self.prog.emit("ENTER", 0)  

        self.func_ret_idx = None

        self.visit(ctx.block())

        fl.finalize()
        if func_sym:
            func_sym.frame_size = fl.frame_size
        self.prog.code[enter_idx].a1 = str(fl.frame_size)

        self.prog.emit("LABEL", exit_lbl)
        self.prog.emit("LEAVE")

        if self.func_ret_idx is not None:
            self.prog.emit("RET", f"t{self.func_ret_idx}")
            self.temps.release(self.func_ret_idx)
        else:
            self.prog.emit("RET")

        self.current_function = None
        self.func_ret_idx = None
        return None

    def visitReturnStatement(self, ctx):
        if hasattr(ctx, "expression") and ctx.expression():
            v = self._gen_expr(ctx.expression())
            if self.func_ret_idx is None:
                self.func_ret_idx = self.temps.get()
            ret_name = self._temp_name(self.func_ret_idx)
            self.prog.emit("MOV", self._as_operand(v), None, ret_name)
            self._release_if_temp(v)
            self.prog.emit("JUMP", f"{self.current_function}_exit")
        else:
            self.prog.emit("JUMP", f"{self.current_function}_exit")
        return None

    def visitExprNoAssign(self, ctx):

        node = None
        if hasattr(ctx, "conditionalExpr"):
            try:
                node = ctx.conditionalExpr()
            except Exception:
                node = None
        if node is None and hasattr(ctx, "logicalOrExpr"):
            try:
                node = ctx.logicalOrExpr()
            except Exception:
                node = None
        if node is None:
            return None
        return self._gen_expr(node)


    def visitTernaryExpr(self, ctx):

        e0 = None
        e1 = None
        try:
            e0 = ctx.expression(0)
            e1 = ctx.expression(1)
        except Exception:
            e0 = e1 = None

        if e0 is None or e1 is None:
            if hasattr(ctx, "logicalOrExpr"):
                return self._gen_expr(ctx.logicalOrExpr())
            return None

        cond_node = None
        if hasattr(ctx, "logicalOrExpr"):
            cond_node = ctx.logicalOrExpr()
        else:
            return self._gen_expr(e0) 

        cond_t = self._gen_expr(cond_node)
        L_false = self._fresh_label()
        L_end   = self._fresh_label()

        self.prog.emit("IFZ", self._as_operand(cond_t), None, L_false)
        self._release_if_temp(cond_t)

        t1 = self._gen_expr(e0)
        res_idx = self.temps.get()
        res = self._temp_name(res_idx)
        self.prog.emit("MOV", self._as_operand(t1), None, res)
        self._release_if_temp(t1)
        self.prog.emit("JUMP", L_end)

        self.prog.emit("LABEL", L_false)
        t2 = self._gen_expr(e1)
        self.prog.emit("MOV", self._as_operand(t2), None, res)
        self._release_if_temp(t2)

        self.prog.emit("LABEL", L_end)
        return res_idx


    def visitAdditiveExpr(self, ctx):
        mlist = []
        try:
            mlist = ctx.multiplicativeExpr()
        except Exception:
            mlist = []
        terms = [self._gen_expr(m) for m in mlist] if mlist else []
        if not terms:
            return None if not hasattr(ctx, "multiplicativeExpr") else self._gen_expr(ctx.multiplicativeExpr(0))
        ops = [ctx.getChild(i).getText() for i in range(1, ctx.getChildCount(), 2)]
        if not ops:
            return terms[0]
        acc = terms[0]
        for op, rhs in zip(ops, terms[1:]):
            acc = self._emit_bin(op, acc, rhs)
        return acc

    def visitRelationalExpr(self, ctx):
        alist = []
        try:
            alist = ctx.additiveExpr()
        except Exception:
            alist = []
        exprs = [self._gen_expr(a) for a in alist] if alist else []
        if not exprs:
            return None
        ops = [ctx.getChild(i).getText() for i in range(1, ctx.getChildCount(), 2)]
        if not ops:
            return exprs[0]
        acc = exprs[0]
        for op, rhs in zip(ops, exprs[1:]):
            acc = self._emit_cmp(op, acc, rhs)
        return acc


    def visitLogicalAndExpr(self, ctx):
        if len(ctx.children) == 1:
            return self.visit(ctx.equalityExpr(0))
        res_idx = self.temps.get()
        res = self._temp_name(res_idx)
        L_false = self._fresh_label()
        L_end = self._fresh_label()

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
        # corto circuito: a || b
        if len(ctx.children) == 1:
            return self.visit(ctx.logicalAndExpr(0))
        res_idx = self.temps.get()
        res = self._temp_name(res_idx)
        L_true = self._fresh_label()
        L_end = self._fresh_label()

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
        # Por ahora: identificadores simples y literales via visitTerminal
        pa = ctx.primaryAtom()
        ident_node = None
        if hasattr(pa, "Identifier") and pa.Identifier():
            ident_node = pa.Identifier()
            name = ident_node[0].getText() if isinstance(ident_node, list) else ident_node.getText()
            return name  # nombre de variable como operando
        return self.visit(pa)

    def visitTerminal(self, node: TerminalNode):
        # literales como inmediatos
        return node.getText()

    # ---------- binarios / comparaciones ----------
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

    # ---------- utilidades ----------
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
        # Nombre nuevo basado en la cantidad de LABEL ya emitidos
        n = len([i for i in self.prog.code if i.op == "LABEL"])
        return f"L{n}"
