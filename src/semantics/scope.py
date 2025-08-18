from dataclasses import dataclass, field
from typing import Optional, Dict
from .symbols import Symbol

@dataclass
class Scope:
    parent: Optional['Scope'] = None
    symbols: Dict[str, Symbol] = field(default_factory=dict)

    def define(self, sym: Symbol):
        if sym.name in self.symbols:
            raise ValueError(f"Redeclaración en el mismo ámbito: {sym.name}")
        self.symbols[sym.name] = sym

    def resolve(self, name: str) -> Optional[Symbol]:
        cur = self
        while cur:
            if name in cur.symbols:
                return cur.symbols[name]
            cur = cur.parent
        return None
