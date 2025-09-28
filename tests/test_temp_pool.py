
from semantics.temp import TempPool

def test_temp_pool_alloc_release():
    p = TempPool()
    a = p.get()
    b = p.get()
    assert a == 0 and b == 1
    p.release(a)
    c = p.get()
    assert c == a  # recycled
    d = p.get()
    assert d == 2  # new
