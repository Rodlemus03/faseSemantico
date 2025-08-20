from typing import List, Optional
from unicodedata import name
from antlr4 import ParseTreeVisitor, TerminalNode
from antlr4 import ParserRuleContext
from .scope import Scope
from .symbols import VarSymbol, ParamSymbol, FunctionSymbol, ClassSymbol
from .types import *


class SemanticChecker(ParseTreeVisitor):
    def __init__(self):
        self.global_scope = Scope()
        self.scope = self.global_scope
        self.errors: List[str] = []
        self.loop_depth = 0
        self.current_function: Optional[FunctionSymbol] = None
        self.class_table = {}
        self.current_class = None

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

    def visitChildren(self, node):
        res = None
        n = node.getChildCount()
        for i in range(n):
            child = node.getChild(i)
            r = child.accept(self) if hasattr(child, "accept") else None
            if r is not None:
                res = r
        return res

    def visitTerminal(self, node: TerminalNode):
        t = node.getText()

        # string
        if len(t) >= 2 and t[0] == '"' and t[-1] == '"':
            return STR

        # Boolean
        if t == "true" or t == "false":
            return BOOL
        if t == "null":
            return NULL

        # integer
        if t.isdigit():
            return INT

        sym = self.scope.resolve(t)
        if sym is not None and hasattr(sym, "type"):
            return sym.type

        return None

    def err(self, ctx: ParserRuleContext, message: str):
        tok = ctx.start
        line, col = tok.line, tok.column
        self.errors.append(f"[SemanticError] L{line}:C{col} {message}")
        # --------- Helpers de TIPOS ---------

    def _type_from_annotation(self, ann):
 
        if ann is None:
            return None
        tctx = ann.type_() if hasattr(ann, "type_") and callable(ann.type_) else ann
        return self._type_from_type(tctx)

    def _type_from_type(self, tctx):

        if tctx is None:
            return NULL
        txt = getattr(tctx, "getText", lambda: "")()
        if not txt:
            return NULL

        if txt.endswith("[]"):
            base = txt[:-2]
            elem = self._primitive_by_name(base) or ClassType(base)
            try:
                return ArrayType(elem)
            except Exception:
                return NULL

        # primitivos
        prim = self._primitive_by_name(txt)
        if prim is not None:
            return prim

        if txt == "void":
            return NULL

        return ClassType(txt)

    def _primitive_by_name(self, name: str):
        n = (name or "").lower()
        if n in ("int", "integer"):
            return INT
        if n in ("float", "double", "number"):
            return FLOAT
        if n in ("string", "str"):
            return STR
        if n in ("bool", "boolean"):
            return BOOL
        if n in ("null", "nil", "none"):
            return NULL
        return None

    def _infer_type(self, expr_ctx):
        try:
            t = self.visit(expr_ctx)
            return t if t is not None else NULL
        except Exception:
            return NULL

    def _is_terminal_stmt(self, st):
        getters = (
            "returnStatement",
            "breakStatement",
            "continueStatement",
        )
        for g in getters:
            if hasattr(st, g) and getattr(st, g)():
                return True
        return False

    def visitProgram(self, ctx):
        for st in ctx.statement():
            self.visit(st)
        return None

    def visitVariableDeclaration(self, ctx):
        name = ctx.Identifier().getText()
        declared_type = self._type_from_annotation(ctx.typeAnnotation())
        init_expr = self._expr_child(ctx.initializer(), 0) if ctx.initializer() else None

        if declared_type:
            vtype = declared_type
        elif init_expr:
            vtype = self._infer_type(init_expr)
        else:
            self.err(ctx, f"No se puede inferir el tipo de '{name}' sin anotación ni inicializador.")
            vtype = NULL

        try:
            self.scope.define(VarSymbol(name=name, type=vtype, is_const=False, initialized=bool(init_expr)))
        except ValueError as ex:
            self.err(ctx, str(ex))

        if init_expr:
            et = self.visit(init_expr) or NULL
            if not vtype.is_compatible(et):
                self.err(ctx, f"Asignación incompatible: variable '{name}' es {vtype} pero expresión es {et}.")
        return None

    # Const declaracion
    def visitConstantDeclaration(self, ctx):
        name = ctx.Identifier().getText()
        declared_type = self._type_from_annotation(ctx.typeAnnotation())
        expr = self._expr_child(ctx, 0)
        et = self.visit(expr) if expr is not None else NULL

        vtype = declared_type if declared_type else et
        if declared_type and not declared_type.is_compatible(et):
            self.err(ctx, f"Constante '{name}' declarada como {declared_type} pero inicializa con {et}.")

        try:
            self.scope.define(VarSymbol(name=name, type=vtype, is_const=True, initialized=True))
        except ValueError as ex:
            self.err(ctx, str(ex))
        return None

    def visitAssignment(self, ctx):
        # Caso: x = expr;
        if ctx.getChildCount() >= 2 and getattr(ctx.getChild(1), "getText", lambda: "")() == "=":
            ident = ctx.Identifier()
            if isinstance(ident, list):
                name = ident[0].getText()
            else:
                name = ident.getText() if ident else "<unknown>"

            sym = self.scope.resolve(name)
            if sym is None:
                self.err(ctx, f"Variable no declarada: {name}")
                return None
            if isinstance(sym, VarSymbol) and sym.is_const:
                self.err(ctx, f"No se puede asignar a constante '{name}'.")

            rhs_node = self._expr_child(ctx, 0)
            et = self.visit(rhs_node) if rhs_node is not None else NULL

            if not sym.type.is_compatible(et):
                self.err(ctx, f"Asignación incompatible: variable '{name}' es {sym.type} pero expresión es {et}.")
            if isinstance(sym, VarSymbol):
                sym.initialized = True
            return None

        # Caso: obj.prop = expr;
        exprs = self._expr_all(ctx)
        obj_node = exprs[0] if len(exprs) >= 1 else None
        rhs_node = exprs[1] if len(exprs) >= 2 else None

        ident = ctx.Identifier()
        if isinstance(ident, list):
            prop_name = ident[-1].getText() if ident else None
        else:
            prop_name = ident.getText() if ident else None

        obj_t = self.visit(obj_node) if obj_node else NULL
        rhs_t = self.visit(rhs_node) if rhs_node else NULL

        if not isinstance(obj_t, ClassType):
            self.err(ctx, "La asignación de propiedad requiere un objeto.")
            return None

        cls = self.class_table.get(obj_t.name)
        if not cls:
            self.err(ctx, f"Clase '{obj_t.name}' no declarada.")
            return None

        # >>>>>>>>>>>>>> CAMBIO: lookup respetando herencia
        field = self._lookup_field_in_hierarchy(cls, prop_name)
        if field is None:
            self.err(ctx, f"La clase '{obj_t.name}' no tiene campo '{prop_name}'.")
            return None
        # <<<<<<<<<<<<<<

        if getattr(field, "is_const", False):
            self.err(ctx, f"No se puede asignar al campo constante '{prop_name}'.")

        if not field.type.is_compatible(rhs_t):
            self.err(ctx, f"Asignación incompatible: campo '{prop_name}' es {field.type} pero expresión es {rhs_t}.")
        return None

    def visitExpressionStatement(self, ctx):
        self.visit(ctx.expression())

    def visitPrintStatement(self, ctx):
        self.visit(ctx.expression())

    def visitIfStatement(self, ctx):
        cond_t = self.visit(ctx.expression())
        if not isinstance(cond_t, BooleanType):
            self.err(ctx, "La condición de 'if' debe ser boolean.")
        self.visit(ctx.block(0))
        if ctx.block(1):
            self.visit(ctx.block(1))

    def visitWhileStatement(self, ctx):
        cond_t = self.visit(ctx.expression())
        if not isinstance(cond_t, BooleanType):
            self.err(ctx, "La condición de 'while' debe ser boolean.")
        self.loop_depth += 1
        self.visit(ctx.block())
        self.loop_depth -= 1

    def visitDoWhileStatement(self, ctx):
        self.loop_depth += 1
        self.visit(ctx.block())
        self.loop_depth -= 1
        cond_t = self.visit(ctx.expression())
        if not isinstance(cond_t, BooleanType):
            self.err(ctx, "La condición de 'do-while' debe ser boolean.")

    def visitForStatement(self, ctx):
        self.loop_depth += 1

        # inicializador: puede ser declaración, asignación o ';'
        first = ctx.getChild(2) if ctx.getChildCount() > 2 else None
        if hasattr(first, "accept"):
            self.visit(first)

        exprs = ctx.expression()
        if exprs:
            cond_t = self.visit(exprs[0])
            if not isinstance(cond_t, BooleanType):
                self.err(ctx, "La condición de 'for' debe ser boolean.")
            if len(exprs) > 1:
                self.visit(exprs[1])

        self.visit(ctx.block())
        self.loop_depth -= 1

    def visitForeachStatement(self, ctx):
        arr_t = self.visit(ctx.expression())
        if not isinstance(arr_t, ArrayType):
            self.err(ctx, "El 'foreach' requiere iterar sobre un arreglo.")
            elem_t = NULL
        else:
            elem_t = arr_t.elem

        old = self.scope
        self.scope = Scope(parent=old)
        try:
            self.scope.define(VarSymbol(name=ctx.Identifier().getText(), type=elem_t, initialized=True))
        except ValueError as ex:
            self.err(ctx, str(ex))

        self.loop_depth += 1
        self.visit(ctx.block())
        self.loop_depth -= 1
        self.scope = old

    def visitBreakStatement(self, ctx):
        if self.loop_depth <= 0:
            self.err(ctx, "'break' solo se permite dentro de bucles.")

    def visitContinueStatement(self, ctx):
        if self.loop_depth <= 0:
            self.err(ctx, "'continue' solo se permite dentro de bucles.")

    def visitReturnStatement(self, ctx):
        if self.current_function is None:
            self.err(ctx, "'return' solo se permite dentro de una función.")
            return None
        expr = ctx.expression()
        et = self.visit(expr) if expr else NULL
        if not self.current_function.type.is_compatible(et):
            self.err(ctx, f"El 'return' devuelve {et} pero la función retorna {self.current_function.type}.")

    # Blocks y scope
    def visitBlock(self, ctx):
        old = self.scope
        self.scope = Scope(parent=old)
        saw_terminal = False
        for st in ctx.statement():
            if saw_terminal:
                self.err(st, "Código inalcanzable después de una instrucción de terminación.")
            self.visit(st)
            if self._is_terminal_stmt(st):
                saw_terminal = True
        self.scope = old
        return None

    # Funciones
    def visitFunctionDeclaration(self, ctx):
        name = ctx.Identifier().getText()

        ret_ctx_getter = getattr(ctx, "type_", None)
        ret_ctx = ret_ctx_getter() if callable(ret_ctx_getter) else None
        ret = self._type_from_type(ret_ctx) if ret_ctx is not None else NULL

        params = []
        if ctx.parameters():
            for p in ctx.parameters().parameter():
                p_name = p.Identifier().getText()
                p_type_getter = getattr(p, "type_", None)
                p_type_ctx = p_type_getter() if callable(p_type_getter) else None
                p_type = self._type_from_type(p_type_ctx) if p_type_ctx is not None else NULL
                params.append(ParamSymbol(name=p_name, type=p_type))

        func_sym = FunctionSymbol(name=name, type=ret, params=params)
        try:
            self.scope.define(func_sym)
        except ValueError as ex:
            self.err(ctx, str(ex))

        # Nuevo scope para el cuerpo
        old_scope = self.scope
        self.scope = Scope(parent=old_scope)
        for param in params:
            try:
                self.scope.define(param)
            except ValueError as ex:
                self.err(ctx, str(ex))

        old_func = self.current_function
        self.current_function = func_sym
        self.visit(ctx.block())
        self.current_function = old_func
        self.scope = old_scope
        return None

    # --------- LOOKUP con herencia ---------
    def _lookup_field_in_hierarchy(self, cls_sym, name):
        cur = cls_sym
        while cur:
            if name in cur.fields:
                return cur.fields[name]
            cur = getattr(cur, "base", None)
        return None

    def _lookup_method_in_hierarchy(self, cls_sym, name):
        cur = cls_sym
        while cur:
            if name in cur.methods:
                return cur.methods[name]
            cur = getattr(cur, "base", None)
        return None

    # --------- Clases ---------
    def visitClassDeclaration(self, ctx):
        # Nombre de la clase
        name = ctx.Identifier(0).getText()
        cls_sym = ClassSymbol(name=name, type=ClassType(name))

        # Registrar clase en el scope y en la tabla de clases
        try:
            self.scope.define(cls_sym)
        except ValueError as ex:
            self.err(ctx, str(ex))
        self.class_table[name] = cls_sym

        # ----- ENLACE DE CLASE BASE (herencia) -----
        try:
            if ctx.getChildCount() >= 3 and ctx.getChild(1).getText() == ":":
                base_name = ctx.Identifier(1).getText()
                base_sym = self.class_table.get(base_name)
                if base_sym is None:
                    self.err(ctx, f"Clase base '{base_name}' no declarada.")
                else:
                    cls_sym.base = base_sym
        except Exception:
            pass

        # ----- RECOLECCIÓN DE MIEMBROS (campos y firmas de métodos) -----
        for m in ctx.classMember():
            if m.variableDeclaration():
                v = m.variableDeclaration()
                vname = v.Identifier().getText()
                vtype = self._type_from_annotation(v.typeAnnotation()) or NULL
                if vname in cls_sym.fields:
                    self.err(v, f"Campo duplicado en clase '{name}': {vname}")
                else:
                    cls_sym.fields[vname] = VarSymbol(
                        name=vname,
                        type=vtype,
                        initialized=bool(v.initializer())
                    )

            elif m.constantDeclaration():
                c = m.constantDeclaration()
                cname = c.Identifier().getText()
                ctype = self._type_from_annotation(c.typeAnnotation()) or (self.visit(c.expression()) or NULL)
                if cname in cls_sym.fields:
                    self.err(c, f"Campo duplicado en clase '{name}': {cname}")
                else:
                    cls_sym.fields[cname] = VarSymbol(
                        name=cname,
                        type=ctype,
                        is_const=True,
                        initialized=True
                    )

            elif m.functionDeclaration():
                f = m.functionDeclaration()
                fname = f.Identifier().getText()
                rt = NULL
                if f.type_():
                    rt = self._type_from_type(f.type_())
                ps = []
                if f.parameters():
                    for p in f.parameters().parameter():
                        pt = self._type_from_type(p.type_()) if p.type_() else NULL
                        ps.append(ParamSymbol(name=p.Identifier().getText(), type=pt))
                if fname in cls_sym.methods:
                    self.err(f, f"Método duplicado en clase '{name}': {fname}")
                cls_sym.methods[fname] = FunctionSymbol(name=fname, type=rt, params=ps)

        # ----- CHEQUEO DE CUERPOS DE MÉTODOS -----
        for m in ctx.classMember():
            if m.functionDeclaration():
                f = m.functionDeclaration()
                fname = f.Identifier().getText()
                fn = cls_sym.methods[fname]

                old_scope, old_func, old_cls = self.scope, self.current_function, self.current_class
                self.scope = Scope(parent=old_scope)
                self.current_function = fn
                self.current_class = cls_sym

                # 'this' del tipo de la clase actual
                self.scope.define(VarSymbol(name="this", type=ClassType(name), initialized=True))

                # parámetros
                for p in fn.params:
                    try:
                        self.scope.define(p)
                    except ValueError as ex:
                        self.err(f, str(ex))

                self.visit(f.block())

                self.scope, self.current_function, self.current_class = old_scope, old_func, old_cls

        return None

    # --------- Expresiones ---------

    def visitAssignExpr(self, ctx):
        rhs_t = self.visit(ctx.assignmentExpr())
        return rhs_t

    def visitPropertyAssignExpr(self, ctx):
        return self.visit(ctx.assignmentExpr())

    def visitExprNoAssign(self, ctx):
        return self.visit(ctx.conditionalExpr())

    # ternario
    def visitTernaryExpr(self, ctx):
        has_q = any(
            hasattr(ctx.getChild(i), "getText") and ctx.getChild(i).getText() == "?"
            for i in range(ctx.getChildCount())
        )
        cond_t = self.visit(ctx.logicalOrExpr())
        if not has_q:
            return cond_t
        try:
            e1_ctx = ctx.expression(0)
            e2_ctx = ctx.expression(1)
        except Exception:
            self.err(ctx, "Forma de operador ternario no reconocida por la gramática.")
            return NULL
        e1_t = self.visit(e1_ctx)
        e2_t = self.visit(e2_ctx)
        if not isinstance(cond_t, BooleanType):
            self.err(ctx, "El predicado del operador ternario debe ser boolean.")
        if not e1_t.is_compatible(e2_t):
            self.err(ctx, "Ambas ramas del operador ternario deben tener el mismo tipo.")
        return e1_t

    def visitLogicalOrExpr(self, ctx):
        if len(ctx.children) == 1:
            return self.visit(ctx.logicalAndExpr(0))
        for i in range(len(ctx.logicalAndExpr())):
            et = self.visit(ctx.logicalAndExpr(i))
            if not isinstance(et, BooleanType):
                self.err(ctx, "Operación lógica requiere booleanos.")
        return BOOL

    def visitLogicalAndExpr(self, ctx):
        if len(ctx.children) == 1:
            return self.visit(ctx.equalityExpr(0))
        for i in range(len(ctx.equalityExpr())):
            et = self.visit(ctx.equalityExpr(i))
            if not isinstance(et, BooleanType):
                self.err(ctx, "Operación lógica requiere booleanos.")
        return BOOL

    def visitEqualityExpr(self, ctx):
        if len(ctx.children) == 1:
            return self.visit(ctx.relationalExpr(0))
        n = len(ctx.relationalExpr())
        t0 = self.visit(ctx.relationalExpr(0))
        for i in range(1, n):
            ti = self.visit(ctx.relationalExpr(i))
            if not t0.is_compatible(ti):
                self.err(ctx, "Comparación entre tipos incompatibles.")
            t0 = ti
        return BOOL

    def visitRelationalExpr(self, ctx):
        if len(ctx.children) == 1:
            return self.visit(ctx.additiveExpr(0))
        n = len(ctx.additiveExpr())
        t0 = self.visit(ctx.additiveExpr(0))
        for i in range(1, n):
            ti = self.visit(ctx.additiveExpr(i))
            if not (isinstance(t0, (IntegerType, FloatType)) and isinstance(ti, (IntegerType, FloatType))):
                self.err(ctx, "Comparación relacional requiere números.")
            t0 = ti
        return BOOL

    def visitAdditiveExpr(self, ctx):
        # Un solo término
        if len(ctx.children) == 1:
            return self.visit(ctx.multiplicativeExpr(0))

        # Operadores y términos
        ops = [ctx.getChild(i).getText() for i in range(1, ctx.getChildCount(), 2)]
        terms = [self.visit(ctx.multiplicativeExpr(i)) for i in range(len(ctx.multiplicativeExpr()))]

        # ¿Hay strings? -> concatenación solo con '+'
        has_str = any(isinstance(t, StringType) for t in terms)
        if has_str:
            if all(op == '+' for op in ops):
                return STR
            self.err(ctx, "Operación aditiva con string solo permite '+'.")
            return NULL

        # Numérica
        all_numeric = all(isinstance(t, (IntegerType, FloatType)) for t in terms)
        if all_numeric:
            return FLOAT if any(isinstance(t, FloatType) for t in terms) else INT

        self.err(ctx, "Suma/resta requiere operandos numéricos (integer/float).")
        return NULL
