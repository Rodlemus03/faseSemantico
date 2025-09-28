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
    storage: str = "local"     
    width: int = 4             
    offset: int = 0            
    is_param: bool = False
    param_index: int = -1

@dataclass
class ParamSymbol(VarSymbol):
    is_param: bool = True
    storage: str = "param"

@dataclass
class FunctionSymbol(Symbol):
    params: List[ParamSymbol] = field(default_factory=list)
    locals: List[VarSymbol] = field(default_factory=list)
    frame_size: int = 0                
    entry_label: Optional[str] = None
    exit_label: Optional[str] = None

@dataclass
class ClassSymbol(Symbol):
    fields: Dict[str, Symbol] = field(default_factory=dict)
    methods: Dict[str, FunctionSymbol] = field(default_factory=dict)
    base: Optional['ClassSymbol'] = None
