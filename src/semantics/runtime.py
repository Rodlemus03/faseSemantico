
from dataclasses import dataclass, field
from typing import Dict, List, Optional

@dataclass
class VarInfo:
    name: str
    size: int = 1
    offset: int = 0     

@dataclass
class FrameLayout:
    func_name: str
    params: Dict[str, VarInfo] = field(default_factory=dict)
    locals: Dict[str, VarInfo] = field(default_factory=dict)
    frame_size: int = 0  # total locals size (positive integer)

    def add_param(self, name: str, size: int = 1) -> None:
        # Example convention: params at positive offsets (starting at +2 to skip RA, DL)
        base = 2
        idx = len(self.params)
        self.params[name] = VarInfo(name=name, size=size, offset=base + idx)

    def add_local(self, name: str, size: int = 1) -> None:
        # Locals grow negatively from FP-1, FP-2, ...
        self.frame_size += size
        self.locals[name] = VarInfo(name=name, size=size, offset=-self.frame_size)

@dataclass
class RuntimeLayouts:
    frames: Dict[str, FrameLayout] = field(default_factory=dict)

    def frame(self, func_name: str) -> FrameLayout:
        if func_name not in self.frames:
            self.frames[func_name] = FrameLayout(func_name)
        return self.frames[func_name]
