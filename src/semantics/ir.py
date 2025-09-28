
from dataclasses import dataclass, field
from typing import List, Optional

@dataclass
class TACInstr:
    op: str
    a1: Optional[str] = None
    a2: Optional[str] = None
    res: Optional[str] = None
    comment: str = ""

    def __str__(self) -> str:
        parts = [self.op]
        if self.res is not None:
            parts.append(self.res)
        if self.a1 is not None:
            parts.append(self.a1)
        if self.a2 is not None:
            parts.append(self.a2)
        s = " ".join(parts)
        if self.comment:
            s += f"    # {self.comment}"
        return s

@dataclass
class TACProgram:
    code: List[TACInstr] = field(default_factory=list)
    _label_counter: int = 0

    def emit(self, op: str, a1=None, a2=None, res=None, comment: str = "") -> TACInstr:
        ins = TACInstr(op, a1, a2, res, comment)
        self.code.append(ins)
        return ins

    def label(self, name: Optional[str] = None) -> str:
        if name is None:
            name = f"L{self._label_counter}"
            self._label_counter += 1
        self.emit("LABEL", name)
        return name

    def new_temp(self, idx: int) -> str:
        return f"t{idx}"

    def dumps(self) -> str:
        return "\n".join(str(i) for i in self.code)
