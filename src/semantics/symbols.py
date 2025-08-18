from dataclasses import dataclass, field
from typing import Dict, List, Optional
from .types import Type

@dataclass
class Symbol:
    name: str
    type: Type

@dataclass
class VarSymbol(Symbol):
    is_const: bool = False
    initialized: bool = False

@dataclass
class ParamSymbol(Symbol):
    pass

@dataclass
class FunctionSymbol(Symbol):
    params: List[ParamSymbol] = field(default_factory=list)

@dataclass
class ClassSymbol(Symbol):
    fields: Dict[str, Symbol] = field(default_factory=dict)
    methods: Dict[str, FunctionSymbol] = field(default_factory=dict)
    base: Optional['ClassSymbol'] = None
