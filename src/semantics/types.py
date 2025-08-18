from dataclasses import dataclass
from typing import Optional, List

# Tipos
class Type:
    def is_compatible(self, other: 'Type') -> bool:
        return isinstance(other, type(self))

    def __str__(self):
        return self.__class__.__name__.replace('Type','').lower()

class IntegerType(Type): pass
class FloatType(Type): pass
class StringType(Type): pass
class BooleanType(Type): pass
class NullType(Type): pass

@dataclass
class ArrayType(Type):
    elem: Type
    def is_compatible(self, other: 'Type') -> bool:
        return isinstance(other, ArrayType) and self.elem.is_compatible(other.elem)
    def __str__(self): return f"{self.elem}[]"

@dataclass
class ClassType(Type):
    name: str
    def is_compatible(self, other: 'Type') -> bool:
        return isinstance(other, ClassType) and self.name == other.name
    def __str__(self): return self.name

# Helpers
INT = IntegerType()
FLOAT = FloatType()
STR = StringType()
BOOL = BooleanType()
NULL = NullType()

BIN_NUMERIC = { '+', '-', '*', '/' }
BIN_LOGICAL = { '&&', '||' }
UNARY_LOGICAL = { '!' }
COMPARISONS = { '==','!=','<','<=','>','>=' }
