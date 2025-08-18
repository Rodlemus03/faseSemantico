from typing import List, Optional
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

    # Devuelve el hijo expression(idx)
    def _expr_child(self, ctx, idx=0):
        if ctx is None or not hasattr(ctx, "expression"):
            return None
        ex = ctx.expression()
        if isinstance(ex, list):
            return ex[idx] if idx < len(ex) else None
        # no es lista: único nodo
        return ex if idx == 0 else None

    # Devuelve una lista de todos los hijos expression (si existen)
    def _expr_all(self, ctx):
        if ctx is None or not hasattr(ctx, "expression"):
            return []
        ex = ctx.expression()
        return ex if isinstance(ex, list) else [ex] 
     
    # Visita hijos de un nodo y devuelve el último tipo no-NULL encontrado.
    def visitChildren(self, node):
        res = None
        n = node.getChildCount()
        for i in range(n):
            child = node.getChild(i)
            r = child.accept(self) if hasattr(child, "accept") else None
            if r is not None:
                res = r
        return res
    
    # Clasifica tokens terminales: números, strings, booleanos, null, id.
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

        field = cls.fields.get(prop_name)
        if field is None:
            self.err(ctx, f"La clase '{obj_t.name}' no tiene campo '{prop_name}'.")
            return None

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
        # foreach
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
        if expr:
            et = self.visit(expr)
        else:
            et = NULL
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


    # Classes
    def visitClassDeclaration(self, ctx):
        name = ctx.Identifier(0).getText()
        cls_sym = ClassSymbol(name=name, type=ClassType(name))
        # registra clase en ámbito y en tabla
        try:
            self.scope.define(cls_sym)
        except ValueError as ex:
            self.err(ctx, str(ex))
        self.class_table[name] = cls_sym

        # recolecta miembros (campos y métodos con firmas)
        for m in ctx.classMember():
            if m.variableDeclaration():
                v = m.variableDeclaration()
                vname = v.Identifier().getText()
                vtype = self._type_from_annotation(v.typeAnnotation()) or NULL
                if vname in cls_sym.fields:
                    self.err(v, f"Campo duplicado en clase '{name}': {vname}")
                else:
                    cls_sym.fields[vname] = VarSymbol(name=vname, type=vtype, initialized=bool(v.initializer()))
            elif m.constantDeclaration():
                c = m.constantDeclaration()
                cname = c.Identifier().getText()
                ctype = self._type_from_annotation(c.typeAnnotation()) or (self.visit(c.expression()) or NULL)
                if cname in cls_sym.fields:
                    self.err(c, f"Campo duplicado en clase '{name}': {cname}")
                else:
                    cls_sym.fields[cname] = VarSymbol(name=cname, type=ctype, is_const=True, initialized=True)
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

        # chequear los cuerpos de los métodos con 'this' y los params
        for m in ctx.classMember():
            if m.functionDeclaration():
                f = m.functionDeclaration()
                fname = f.Identifier().getText()
                fn = cls_sym.methods[fname]

                old_scope, old_func, old_cls = self.scope, self.current_function, self.current_class
                self.scope = Scope(parent=old_scope)
                self.current_function = fn
                self.current_class = cls_sym
                self.scope.define(VarSymbol(name="this", type=ClassType(name), initialized=True))
                for p in fn.params:
                    try:
                        self.scope.define(p)
                    except ValueError as ex:
                        self.err(f, str(ex))
                self.visit(f.block())
                self.scope, self.current_function, self.current_class = old_scope, old_func, old_cls
        return None

   
    # Expresiones

    def visitAssignExpr(self, ctx):
        rhs_t = self.visit(ctx.assignmentExpr())
        return rhs_t

    def visitPropertyAssignExpr(self, ctx):
        return self.visit(ctx.assignmentExpr())

    def visitExprNoAssign(self, ctx):
        return self.visit(ctx.conditionalExpr())

    # logicalOrExpr
    def visitTernaryExpr(self, ctx):
        has_q = any(
            hasattr(ctx.getChild(i), "getText") and ctx.getChild(i).getText() == "?"
            for i in range(ctx.getChildCount())
        )

        # Tipo de la condición
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
        t = BOOL
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
        if len(ctx.children) == 1:
            return self.visit(ctx.multiplicativeExpr(0))
        a = self.visit(ctx.multiplicativeExpr(0))
        b = self.visit(ctx.multiplicativeExpr(1))
        if isinstance(a, (IntegerType, FloatType)) and isinstance(b, (IntegerType, FloatType)):
            return FLOAT if isinstance(a, FloatType) or isinstance(b, FloatType) else INT
        self.err(ctx, "Suma/resta requiere operandos numéricos (integer/float).")
        return NULL
    
    
    def visitMultiplicativeExpr(self, ctx):
        if len(ctx.children) == 1:
            return self.visit(ctx.unaryExpr(0))
        a = self.visit(ctx.unaryExpr(0))
        b = self.visit(ctx.unaryExpr(1))
        if isinstance(a, (IntegerType, FloatType)) and isinstance(b, (IntegerType, FloatType)):
            return FLOAT if isinstance(a, FloatType) or isinstance(b, FloatType) else INT
        self.err(ctx, "Multiplicación/división requiere números.")
        return NULL

    def visitUnaryExpr(self, ctx):
        if ctx.getChildCount() == 1:
            return self.visit(ctx.primaryExpr())

        op_text = ctx.getChild(0).getText()
        operand_t = self.visit(ctx.unaryExpr())

        if op_text == '!':
            if not isinstance(operand_t, BooleanType):
                self.err(ctx, "Negación lógica requiere boolean.")
                return NULL
            return BOOL

        if op_text in ('+', '-'):
            if isinstance(operand_t, (IntegerType, FloatType)):
                return operand_t
            self.err(ctx, "Operador unario numérico requiere operandos numéricos.")
            return NULL

        return operand_t

    def visitPrimaryExpr(self, ctx):
        
        if ctx.literalExpr():
            return self.visit(ctx.literalExpr())
        if ctx.leftHandSide():
            return self.visit(ctx.leftHandSide())
        if hasattr(ctx, "expression") and ctx.expression():
            return self.visit(ctx.expression())
        return NULL

    # clasifica literales
    def visitLiteralExpr(self, ctx):
        txt = ctx.getText()

        # String
        if len(txt) >= 2 and txt[0] == '"' and txt[-1] == '"':
            return STR

        # Booleanos
        if txt == "true" or txt == "false":
            return BOOL

        # null
        if txt == "null":
            return NULL

        # Array literal
        if hasattr(ctx, "arrayLiteral") and ctx.arrayLiteral():
            elems = ctx.arrayLiteral().expression()
            if not elems:
                return ArrayType(NULL)
            first_t = self.visit(elems[0]) or NULL
            for e in elems[1:]:
                if not first_t.is_compatible(self.visit(e) or NULL):
                    self.err(ctx, "Arreglo con elementos de tipos incompatibles.")
                    return ArrayType(NULL)
            return ArrayType(first_t)
        if all(ch.isdigit() or ch=='.' for ch in txt) and ('.' in txt):
         return FLOAT
        # Entero
        if txt.isdigit():
            return INT

        return NULL

    
    def visitLeftHandSide(self, ctx):
        base_sym = None
        pa = ctx.primaryAtom()
        t = None

        if hasattr(pa, "Identifier") and pa.Identifier():
            name = pa.Identifier().getText()
            sym = self.scope.resolve(name)
            if sym is None:
                self.err(pa, f"Identificador no declarado: {name}")
                t = NULL
            else:
                base_sym = sym
                t = getattr(sym, "type", NULL)

        elif pa.getText() == "this":
            if self.current_class is None:
                self.err(pa, "'this' solo puede usarse dentro de métodos de clase.")
                t = NULL
            else:
                t = ClassType(self.current_class.name)

        elif pa.getChildCount() >= 2 and pa.getChild(0).getText() == "new":
            cname = pa.getChild(1).getText()
            t = ClassType(cname)

        else:
            t = self.visit(pa)

        # aplicar sufijos
        for op in ctx.suffixOp():
            first_txt = op.getChild(0).getText() if op.getChildCount() > 0 else ""

            if first_txt == "(":
                # recolectar argumentos
                arg_nodes = []
                if hasattr(op, "arguments") and op.arguments():
                    arg_nodes = self._expr_all(op.arguments())
                else:
                    arg_nodes = self._expr_all(op)
                arg_types = [self.visit(e) for e in arg_nodes]

                fn = None
                if isinstance(base_sym, FunctionSymbol):
                    fn = base_sym
                elif isinstance(t, ClassType) and False:
                    pass
                elif isinstance(base_sym, VarSymbol) and isinstance(base_sym.type, ClassType):
                    pass

                if fn is not None:
                    if len(arg_types) != len(fn.params):
                        self.err(op, f"La función '{fn.name}' espera {len(fn.params)} argumentos, pero recibió {len(arg_types)}.")
                    else:
                        for i, (pt, at) in enumerate(zip([p.type for p in fn.params], arg_types)):
                            if not pt.is_compatible(at):
                                self.err(op, f"Argumento {i+1} de '{fn.name}' debe ser {pt}, pero recibió {at}.")
                    t = fn.type
                    base_sym = None
                    continue

                if isinstance(base_sym, FunctionSymbol):
                    pass
                else:
                    self.err(op, "Llamada aplicada a algo que no es función declarada.")
                    t = NULL

            # indexación
            elif first_txt == "[":
                # índice
                idx_node = None
                if hasattr(op, "expression"):
                    xs = op.expression()
                    idx_node = xs[0] if isinstance(xs, list) and xs else (xs if xs else None)
                if not isinstance(t, ArrayType):
                    self.err(op, "Indexación requiere un arreglo.")
                    t = NULL
                else:
                    if idx_node is not None:
                        it = self.visit(idx_node)
                        if not isinstance(it, IntegerType):
                            self.err(op, "El índice de un arreglo debe ser integer.")
                    t = t.elem
                base_sym = None

            # acceso a propiedad: '.' Identifier
            elif first_txt == ".":
                if not isinstance(t, ClassType):
                    self.err(op, "Acceso a propiedad sobre algo que no es objeto/clase.")
                    t = NULL
                    base_sym = None
                    continue

                member = op.getChild(1).getText()
                cls = self.class_table.get(t.name)
                if not cls:
                    self.err(op, f"Clase '{t.name}' no declarada.")
                    t = NULL
                    base_sym = None
                    continue

                if member in cls.fields:
                    t = cls.fields[member].type
                    base_sym = None
                elif member in cls.methods:
                    base_sym = cls.methods[member]
                    t = base_sym.type
                else:
                    self.err(op, f"'{t.name}' no tiene miembro '{member}'.")
                    t = NULL
                    base_sym = None

        return t
    
    
    def visitPrimaryAtom(self, ctx):
        if hasattr(ctx, "Identifier") and ctx.Identifier():
            name = ctx.Identifier().getText()
            sym = self.scope.resolve(name)
            if sym is None:
                self.err(ctx, f"Identificador no declarado: {name}")
                return NULL
            return getattr(sym, "type", NULL)

        if ctx.getText() == "this":
            if self.current_class is None:
                self.err(ctx, "'this' solo puede usarse dentro de métodos de clase.")
                return NULL
            return ClassType(self.current_class.name)

        if ctx.getChildCount() >= 2 and ctx.getChild(0).getText() == "new":
            return ClassType(ctx.getChild(1).getText())

        return NULL


    def visitCallExpr(self, ctx):
        return NULL

    def visitIndexExpr(self, ctx):
        arr_t = self.visit(ctx.expression())
        if not isinstance(arr_t, ArrayType):
            self.err(ctx, "Indexación requiere un arreglo.")
            return NULL
        return arr_t.elem

    def visitPropertyAccessExpr(self, ctx):
        return NULL

    # Helpers
    def _type_from_annotation(self, ann):
        """Obtiene el tipo desde una anotación de la gramática (typeAnnotation)."""
        if ann is None:
            return None
        tctx = getattr(ann, "type_", None)
        if callable(tctx):
            tctx = tctx()
        if tctx is None and hasattr(ann, "type"):
            try:
                tctx = ann.type()
            except Exception:
                tctx = None
        if tctx is None and hasattr(ann, "baseType"):
            try:
                tctx = ann.baseType()
            except Exception:
                tctx = None
        return self._type_from_typectx(tctx)

    # Compatibilidad con nombre antiguo
    def _type_from_type(self, tctx):
        return self._type_from_typectx(tctx)
    
    # Normaliza el texto del contexto de tipo, incluyendo arreglos 
    def _type_from_typectx(self, tctx):
        if tctx is None:
            return NULL
        txt = tctx.getText()
        dims = 0
        while txt.endswith("[]"):
            dims += 1
            txt = txt[:-2]
        base = {
            "integer": INT,
            "float":   FLOAT,
            "string":  STR,
            "boolean": BOOL,
            "null":    NULL
        }.get(txt, ClassType(txt))
        for _ in range(dims):
            base = ArrayType(base)
        return base

    def _infer_type(self, expr_ctx):
        if expr_ctx is None: return NULL
        return self.visit(expr_ctx)
    def visitSwitchStatement(self, ctx):
        cond_t = self.visit(ctx.expression())
        if not isinstance(cond_t, BooleanType):
            self.err(ctx, "La expresión de 'switch' debe ser boolean.")
        for sc in ctx.switchCase():
            for st in sc.statement():
                self.visit(st)
        if ctx.defaultCase():
            for st in ctx.defaultCase().statement():
                self.visit(st)
    def _is_terminal_stmt(self, st):
            try:
                return bool(st.returnStatement() or st.breakStatement() or st.continueStatement())
            except Exception:
                return False
