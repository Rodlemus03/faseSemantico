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

