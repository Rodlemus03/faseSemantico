from dataclasses import dataclass, field
from typing import Dict, List, Optional

def size_of(t) -> int:
    name = getattr(t, "name", "").lower()
    if name in ("integer", "int", "bool", "boolean"): return 4
    if name in ("float", "double"): return 8
    if name in ("string",): return 8  
    return 4

def align_to(n: int, k: int) -> int:
    r = n % k
    return n if r == 0 else n + (k - r)

@dataclass
class VarInfo:
    name: str
    size: int = 4         
    offset: int = 0       

@dataclass
class FrameLayout:
    func_name: str
    params: Dict[str, VarInfo] = field(default_factory=dict)  
    locals: Dict[str, VarInfo] = field(default_factory=dict)  
    params_size: int = 0
    locals_size: int = 0
    frame_size: int = 0  

    def add_param(self, sym) -> None:
        base = 8
        off = base + sum(v.size for v in self.params.values())
        w = getattr(sym, "width", None) or size_of(getattr(sym, "type", None))
        sym.width = w
        sym.is_param = True
        sym.storage = "param"
        sym.offset = off
        self.params[sym.name] = VarInfo(name=sym.name, size=w, offset=off)

    def add_local(self, sym) -> None:
        w = getattr(sym, "width", None) or size_of(getattr(sym, "type", None))
        sym.width = w
        sym.storage = "local"
        self.locals_size += w
        sym.offset = -self.locals_size
        self.locals[sym.name] = VarInfo(name=sym.name, size=w, offset=sym.offset)

    def finalize(self) -> None:
        self.params_size = sum(v.size for v in self.params.values())
        self.frame_size = align_to(self.locals_size + 8, 8)

@dataclass
class RuntimeLayouts:
    frames: Dict[str, FrameLayout] = field(default_factory=dict)

    def frame(self, func_name: str) -> FrameLayout:
        if func_name not in self.frames:
            self.frames[func_name] = FrameLayout(func_name)
        return self.frames[func_name]
