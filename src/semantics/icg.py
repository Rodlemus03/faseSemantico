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
        exprs = self._expr_all(ctx)
        idents = ctx.Identifier() if hasattr(ctx, "Identifier") else None
        
        if not idents:
            return None
        
        ident_list = idents if isinstance(idents, list) else [idents]
        
        # Caso 1: Asignación simple (x = valor;)
        if len(ident_list) == 1 and len(exprs) == 1:
            name = ident_list[0].getText()
            rhs = exprs[0]
            v = self._gen_expr(rhs)
            self.prog.emit("MOV", self._as_operand(v), None, name)
            self._release_if_temp(v)
            return None
        
        # Caso 2: Asignación a propiedad (expr.prop = valor;)
        if len(exprs) >= 2 and len(ident_list) >= 1:
            obj_node = exprs[0]
            rhs_node = exprs[-1]
            prop_name = ident_list[-1].getText()
            
            val = self._gen_expr(rhs_node)
            obj = self._gen_expr(obj_node)
            self.prog.emit("MOVP", self._as_operand(val), self._as_operand(obj), prop_name)
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
        self.prog.label(L_else)

        if ctx.block(1):
            self.visit(ctx.block(1))

        self.prog.label(L_end)
        return None

    def visitWhileStatement(self, ctx):
        L_cond = self._fresh_label()
        L_end = self._fresh_label()

        self.prog.label(L_cond)
        cond = self._gen_expr(ctx.expression())
        self.prog.emit("IFZ", self._as_operand(cond), None, L_end)
        self._release_if_temp(cond)

        self.visit(ctx.block())
        self.prog.emit("JUMP", L_cond)
        self.prog.label(L_end)
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

        self.prog.label(entry_lbl)

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

        self.prog.label(exit_lbl)
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

    def visitAssignExpr(self, ctx):
        """lhs = assignmentExpr"""
        lhs_result = self.visit(ctx.lhs)
        rhs_result = self.visit(ctx.assignmentExpr())
        
        if isinstance(lhs_result, str):
            self.prog.emit("MOV", self._as_operand(rhs_result), None, lhs_result)
        
        self._release_if_temp(rhs_result)
        return rhs_result

    def visitPropertyAssignExpr(self, ctx):
        """lhs.Identifier = assignmentExpr"""
        obj_result = self.visit(ctx.lhs)
        prop_name = ctx.Identifier().getText()
        val_result = self.visit(ctx.assignmentExpr())
        
        self.prog.emit("MOVP", self._as_operand(val_result), self._as_operand(obj_result), prop_name)
        self._release_if_temp(val_result)
        self._release_if_temp(obj_result)
        return val_result

    def visitExprNoAssign(self, ctx):
        return self.visit(ctx.conditionalExpr())

    def visitTernaryExpr(self, ctx):
        log_or = ctx.logicalOrExpr()
        
        if not ctx.expression() or len(ctx.expression()) < 2:
            return self.visit(log_or)
        
        cond_t = self.visit(log_or)
        L_false = self._fresh_label()
        L_end = self._fresh_label()

        self.prog.emit("IFZ", self._as_operand(cond_t), None, L_false)
        self._release_if_temp(cond_t)

        t1 = self.visit(ctx.expression(0))
        res_idx = self.temps.get()
        res = self._temp_name(res_idx)
        self.prog.emit("MOV", self._as_operand(t1), None, res)
        self._release_if_temp(t1)
        self.prog.emit("JUMP", L_end)

        self.prog.label(L_false)
        t2 = self.visit(ctx.expression(1))
        self.prog.emit("MOV", self._as_operand(t2), None, res)
        self._release_if_temp(t2)

        self.prog.label(L_end)
        return res_idx

    def visitMultiplicativeExpr(self, ctx):
        terms = [self.visit(u) for u in ctx.unaryExpr()]
        if not terms:
            return None
        if len(terms) == 1:
            return terms[0]
        
        ops = [ctx.getChild(i).getText() for i in range(1, ctx.getChildCount(), 2)]
        acc = terms[0]
        for op, rhs in zip(ops, terms[1:]):
            acc = self._emit_bin(op, acc, rhs)
        return acc

    def visitAdditiveExpr(self, ctx):
        terms = [self.visit(m) for m in ctx.multiplicativeExpr()]
        if not terms:
            return None
        if len(terms) == 1:
            return terms[0]
        
        ops = [ctx.getChild(i).getText() for i in range(1, ctx.getChildCount(), 2)]
        acc = terms[0]
        for op, rhs in zip(ops, terms[1:]):
            acc = self._emit_bin(op, acc, rhs)
        return acc

    def visitEqualityExpr(self, ctx):
        exprs = [self.visit(r) for r in ctx.relationalExpr()]
        if not exprs:
            return None
        if len(exprs) == 1:
            return exprs[0]
        
        ops = [ctx.getChild(i).getText() for i in range(1, ctx.getChildCount(), 2)]
        acc = exprs[0]
        for op, rhs in zip(ops, exprs[1:]):
            acc = self._emit_cmp(op, acc, rhs)
        return acc

    def visitRelationalExpr(self, ctx):
        exprs = [self.visit(a) for a in ctx.additiveExpr()]
        if not exprs:
            return None
        if len(exprs) == 1:
            return exprs[0]
        
        ops = [ctx.getChild(i).getText() for i in range(1, ctx.getChildCount(), 2)]
        acc = exprs[0]
        for op, rhs in zip(ops, exprs[1:]):
            acc = self._emit_cmp(op, acc, rhs)
        return acc

    def visitLogicalAndExpr(self, ctx):
        if len(ctx.equalityExpr()) == 1:
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
        self.prog.label(L_false)
        self.prog.emit("MOV", "0", None, res)
        self.prog.label(L_end)
        return res_idx

    def visitLogicalOrExpr(self, ctx):
        if len(ctx.logicalAndExpr()) == 1:
            return self.visit(ctx.logicalAndExpr(0))
        
        res_idx = self.temps.get()
        res = self._temp_name(res_idx)
        L_true = self._fresh_label()
        L_end = self._fresh_label()

        left = self.visit(ctx.logicalAndExpr(0))
        self.prog.emit("IFNZ", self._as_operand(left), None, L_true)
        self._release_if_temp(left)

        right = self.visit(ctx.logicalAndExpr(1))
        self.prog.emit("MOV", self._as_operand(right), None, res)
        self._release_if_temp(right)

        self.prog.emit("JUMP", L_end)
        self.prog.label(L_true)
        self.prog.emit("MOV", "1", None, res)
        self.prog.label(L_end)
        return res_idx

    def visitUnaryExpr(self, ctx):
        if ctx.unaryExpr():
            op = ctx.getChild(0).getText()
            val = self.visit(ctx.unaryExpr())
            idx = self.temps.get()
            res = self._temp_name(idx)
            if op == '-':
                self.prog.emit("NEG", self._as_operand(val), None, res)
            elif op == '!':
                self.prog.emit("NOT", self._as_operand(val), None, res)
            self._release_if_temp(val)
            return idx
        else:
            return self.visit(ctx.primaryExpr())

    def visitPrimaryExpr(self, ctx):
        if ctx.literalExpr():
            return self.visit(ctx.literalExpr())
        elif ctx.leftHandSide():
            return self.visit(ctx.leftHandSide())
        elif ctx.expression():
            return self.visit(ctx.expression())
        return None

    def visitLiteralExpr(self, ctx):
        if ctx.Literal():
            return ctx.Literal().getText()
        return ctx.getText()

    def visitLeftHandSide(self, ctx):

        primary = ctx.primaryAtom()
        suffix_ops = ctx.suffixOp() if hasattr(ctx, 'suffixOp') else []
        
        if not suffix_ops and ctx.getChildCount() > 1:
            suffix_ops = []
            for i in range(1, ctx.getChildCount()):
                child = ctx.getChild(i)
                if hasattr(child, 'getRuleIndex'):
                    suffix_ops.append(child)
        
        if not suffix_ops:
            return self.visit(primary)
        
        return self._process_chain(primary, suffix_ops)

    def _process_chain(self, primary, suffixes):
        current = self.visit(primary)
        current_name = None
        base_obj = current  
        
        if isinstance(current, str):
            current_name = current
        
        for i, suffix in enumerate(suffixes):
            if self._is_property_access(suffix):
                prop = suffix.Identifier().getText()
                idx = self.temps.get()
                res = self._temp_name(idx)
                self.prog.emit("GETP", self._as_operand(current), prop, res)
                
                if current != base_obj:
                    self._release_if_temp(current)
                    
                current = idx
                current_name = prop
            
            elif self._is_call(suffix):
                args = []
                if suffix.arguments():
                    for arg_expr in suffix.arguments().expression():
                        arg_val = self.visit(arg_expr)
                        args.append(arg_val)
                
                idx = self.temps.get()
                res = self._temp_name(idx)
                
                is_method = False
                for j in range(i):
                    if self._is_property_access(suffixes[j]):
                        is_method = True
                        break
                
                if is_method and i > 0 and self._is_property_access(suffixes[i-1]):
                    if i == 1:
                        self.prog.emit("PARAM", self._as_operand(base_obj))
                    else:
                        prev_obj = self._get_object_before_method(primary, suffixes[:i-1])
                        self.prog.emit("PARAM", self._as_operand(prev_obj))
                        if isinstance(prev_obj, int):
                            self.temps.release(prev_obj)
                    
                    for arg in args:
                        self.prog.emit("PARAM", self._as_operand(arg))
                        self._release_if_temp(arg)
                    
                    self.prog.emit("CALL", f"func_{current_name}", None, res)
                else:
                    for arg in args:
                        self.prog.emit("PARAM", self._as_operand(arg))
                        self._release_if_temp(arg)
                    
                    func_name = current if isinstance(current, str) else current_name or "unknown"
                    self.prog.emit("CALL", f"func_{func_name}", None, res)
                
                self._release_if_temp(current)
                current = idx
                current_name = None
            
            elif self._is_index(suffix):
                index_val = self.visit(suffix.expression())
                idx = self.temps.get()
                res = self._temp_name(idx)
                self.prog.emit("INDEX", self._as_operand(current), self._as_operand(index_val), res)
                self._release_if_temp(current)
                self._release_if_temp(index_val)
                current = idx
        
        return current

    def _get_object_before_method(self, primary, suffixes_before):
        if not suffixes_before:
            return self.visit(primary)
        
        current = self.visit(primary)
        for suffix in suffixes_before:
            if self._is_property_access(suffix):
                prop = suffix.Identifier().getText()
                idx = self.temps.get()
                res = self._temp_name(idx)
                self.prog.emit("GETP", self._as_operand(current), prop, res)
                self._release_if_temp(current)
                current = idx
        
        return current

    def _is_property_access(self, ctx):
        if hasattr(ctx, 'Identifier') and ctx.Identifier():
            if not hasattr(ctx, 'arguments'):
                return True
            if ctx.getChildCount() > 1:
                for i in range(ctx.getChildCount()):
                    if ctx.getChild(i).getText() == '(':
                        return False
            return True
        
        if ctx.getChildCount() >= 2:
            if ctx.getChild(0).getText() == '.' and hasattr(ctx, 'Identifier'):
                return True
        
        return False

    def _is_call(self, ctx):
        if hasattr(ctx, 'arguments'):
            return True
        return ctx.getChildCount() >= 2 and ctx.getChild(0).getText() == '('

    def _is_index(self, ctx):
        return (hasattr(ctx, 'expression') and 
                ctx.getChildCount() >= 2 and 
                ctx.getChild(0).getText() == '[')

    def visitIdentifierExpr(self, ctx):
        return ctx.Identifier().getText()

    def visitNewExpr(self, ctx):
        class_name = ctx.Identifier().getText()
        
        args = []
        if ctx.arguments():
            args = [self.visit(e) for e in ctx.arguments().expression()]
        
        obj_idx = self.temps.get()
        obj_temp = self._temp_name(obj_idx)
        self.prog.emit("NEW", class_name, None, obj_temp)
        
        self.prog.emit("PARAM", obj_temp)
        for arg in args:
            self.prog.emit("PARAM", self._as_operand(arg))
            self._release_if_temp(arg)
        
        self.prog.emit("CALL", "func_constructor", None, None)
        return obj_idx

    def visitThisExpr(self, ctx):
        return "this"

    def _emit_bin(self, op, left, right):
        idx = self.temps.get()
        res = self._temp_name(idx)
        ir_op = {
            "+": "ADD", 
            "-": "SUB", 
            "*": "MUL", 
            "/": "DIV",
            "%": "MOD"
        }.get(op, f"BIN_{op}")
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
        n = len([i for i in self.prog.code if i.op == "LABEL"])
        return f"L{n}"