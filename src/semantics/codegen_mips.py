
TREGS = [f"$t{i}" for i in range(10)]  # $t0..$t9

def gen_program_from_tac(prog):
    out = []
    emit = out.append

    # ---------- helpers básicos ----------
    def is_int(s):
        if s is None:
            return False
        s = str(s)
        return s.isdigit() or (s.startswith('-') and s[1:].isdigit())

    reg_map = {}
    next_reg = 0

    def get_reg(operand):
        nonlocal next_reg
        if operand is None:
            return None
        s = str(operand)

        if is_int(s):
            r = "$t9"  # scratch
            emit(f"li {r}, {s}")
            return r

        if s.startswith("t") and s[1:].isdigit():
            if s not in reg_map:
                r = TREGS[next_reg % len(TREGS)]
                next_reg += 1
                reg_map[s] = r
            return reg_map[s]

        if s not in reg_map:
            r = TREGS[next_reg % len(TREGS)]
            next_reg += 1
            reg_map[s] = r
        return reg_map[s]

    def binop(op, a, b, d):
        if op == "ADD": emit(f"addu {d}, {a}, {b}")
        elif op == "SUB": emit(f"subu {d}, {a}, {b}")
        elif op == "MUL": emit(f"mul {d}, {a}, {b}")
        elif op == "DIV":
            emit(f"div {a}, {b}"); emit(f"mflo {d}")
        elif op == "MOD":
            emit(f"div {a}, {b}"); emit(f"mfhi {d}")

    labels = set()
    for ins in prog.code:
        if ins.op == "LABEL":
            lbl = ins.res if ins.res else ins.a1
            if lbl:
                labels.add(str(lbl))

    emit(".text")
    emit(".globl main")
    emit("main:")

    if "func_main" in labels:
        emit("jal func_main")
    elif "program_start" in labels:
        emit("j program_start")

    current_frame_size = 0
    pending_params = []  

    for ins in prog.code:
        op, a1, a2, rs = ins.op, ins.a1, ins.a2, ins.res

        if op == "LABEL":
            lbl = rs if rs is not None else a1
            emit(f"{lbl}:")
            continue

        if op == "ENTER":
            try:
                current_frame_size = int(str(a1)) if a1 is not None else 0
            except:
                current_frame_size = 0
            if current_frame_size > 0:
                emit(f"addi $sp, $sp, -{current_frame_size}")
                emit(f"sw $ra, 0($sp)")
            continue

        if op == "LEAVE":
            if current_frame_size > 0:
                emit("lw $ra, 0($sp)")
                emit(f"addi $sp, $sp, {current_frame_size}")
            current_frame_size = 0
            continue

        if op == "RET":
            if a1:
                r = get_reg(a1)
                emit(f"move $v0, {r}")
            emit("jr $ra")
            continue

        if op == "JUMP":
            emit(f"j {rs}")
            continue

        if op in ("IFZ", "IFNZ"):
            r = get_reg(a1)
            emit("li $t8, 0")
            if op == "IFZ":
                emit(f"beq {r}, $t8, {rs}")
            else:
                emit(f"bne {r}, $t8, {rs}")
            continue

        if op in ("ADD", "SUB", "MUL", "DIV", "MOD"):
            d = get_reg(rs)
            ra = get_reg(a1)
            rb = get_reg(a2)
            binop(op, ra, rb, d)
            continue

        if op == "NEG":
            d = get_reg(rs)
            ra = get_reg(a1)
            emit(f"subu {d}, $zero, {ra}")
            continue

        if op == "NOT":
            d = get_reg(rs)
            ra = get_reg(a1)
            emit(f"sltu {d}, {ra}, 1")
            continue

        if op.startswith("CMP"):
            d = get_reg(rs)
            ra = get_reg(a1)
            rb = get_reg(a2)
            if   op == "CMP==": emit(f"seq {d}, {ra}, {rb}")
            elif op == "CMP!=": emit(f"sne {d}, {ra}, {rb}")
            elif op == "CMP<":  emit(f"slt {d}, {ra}, {rb}")
            elif op == "CMP<=":
                emit(f"slt {d}, {rb}, {ra}")  # d = rb<ra
                emit(f"xori {d}, {d}, 1")     # d = !(rb<ra)
            elif op == "CMP>":
                emit(f"slt {d}, {rb}, {ra}")
            elif op == "CMP>=":
                emit(f"slt {d}, {ra}, {rb}")  # d = ra<rb
                emit(f"xori {d}, {d}, 1")     # d = !(ra<rb)
            continue

        if op == "MOV":
            d = get_reg(rs)
            ra = get_reg(a1)
            emit(f"move {d}, {ra}")
            continue

        if op == "PRINT":
            ra = get_reg(a1)
            emit(f"move $a0, {ra}")
            emit("li $v0, 1")  # print_int
            emit("syscall")
            # newline
            emit("li $a0, 10")
            emit("li $v0, 11")
            emit("syscall")
            continue

        if op == "PARAM":
            pending_params.append(a1)
            continue

        if op == "CALL":
            func_label = str(a1) if a1 else ""
            nargs = len(pending_params)

            extras = []
            if nargs > 4:
                extras = pending_params[0:nargs-4]
            regs_args = pending_params[nargs-4:nargs]

            for p in extras[::-1]:
                if is_int(p):
                    emit("addi $sp,$sp,-4")
                    emit(f"li $t9,{p}")
                    emit("sw $t9,0($sp)")
                else:
                    r = get_reg(p)
                    emit("addi $sp,$sp,-4")
                    emit(f"sw {r},0($sp)")

            for i, p in enumerate(regs_args):
                if is_int(p):
                    emit(f"li $a{i}, {p}")
                else:
                    r = get_reg(p)
                    emit(f"move $a{i}, {r}")

            emit(f"jal {func_label}")

            if extras:
                emit(f"addi $sp,$sp,{len(extras)*4}")

            if rs:
                d = get_reg(rs)
                emit(f"move {d}, $v0")

            pending_params.clear()
            continue

        emit(f"# op no soportada: {op}")

    emit("li $v0, 10")
    emit("syscall")
    return "\n".join(out)
