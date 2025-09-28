
from typing import List

class TempPool:
    """
    Simple pool for temporaries t0, t1, ... with recycling.
    """
    def __init__(self) -> None:
        self._free: List[int] = []
        self._next = 0

    def get(self) -> int:
        if self._free:
            return self._free.pop()
        i = self._next
        self._next += 1
        return i

    def release(self, idx: int) -> None:
        self._free.append(idx)

    def reset(self) -> None:
        self._free.clear()
        self._next = 0
