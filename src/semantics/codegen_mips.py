from typing import Dict, List, Optional
from .ir import TACProgram, TACInstr

# ============================================================
#  REGISTROS Y CONSTANTES
# ============================================================

TEMP_REGS = [f"$t{i}" for i in range(8)]      # $t0-$t7
SAVED_REGS = [f"$s{i}" for i in range(8)]     # $s0-$s7
ARG_REGS = [f"$a{i}" for i in range(4)]       # $a0-$a3

WORD_SIZE = 4

# Campos de objetos Persona / Estudiante
FIELD_OFFSETS = {
    "nombre": 0,
    "edad": 4,
    "color": 8,
    "grado": 12,
}

# ============================================================
#  DATA SECTION (STRINGS)
# ============================================================

class DataSection:
    def __init__(self):
        self.str_to_label: Dict[str, str] = {"": "str_0"}
        self.counter = 1

    def add_string(self, literal: str) -> str:
        """
        Recibe algo como "\"Hola\"" y devuelve el label str_k correspondiente.
        """
        if literal is None:
            literal = ""
        s = str(literal)
        if s.startswith('"') and s.endswith('"'):
            s = s[1:-1]

        if s in self.str_to_label:
            return self.str_to_label[s]

        label = f"str_{self.counter}"
        self.counter += 1
        self.str_to_label[s] = label
        return label

    def generate_lines(self) -> List[str]:
        if not self.str_to_label:
            return []
        lines = [".data"]
        for s, label in self.str_to_label.items():
            esc = (
                s.replace("\\", "\\\\")
                 .replace('"', '\\"')
                 .replace("\n", "\\n")
            )
            lines.append(f'{label}: .asciiz "{esc}"')
        lines.append("")
        return lines

# ============================================================
#  REGISTER ALLOCATOR MUY SIMPLE (SIN SPILLS)
# ============================================================

class SimpleRegisterAllocator:
    def __init__(self):
        self.var_to_reg: Dict[str, str] = {}
        self.reg_to_var: Dict[str, Optional[str]] = {}
        for r in TEMP_REGS + SAVED_REGS:
            self.reg_to_var[r] = None

    # -------- utilidades internas --------

    def _is_literal(self, op: Optional[str]) -> bool:
        if op is None:
            return False
        s = str(op)
        return s.isdigit() or (s.startswith('-') and s[1:].isdigit())

    def _is_string_literal(self, op: Optional[str]) -> bool:
        if op is None:
            return False
        s = str(op)
        return s.startswith('"') and s.endswith('"')

    # -------- API principal --------

    def get_reg_for_var(self, var: str, for_write: bool = False) -> str:
        # Si ya tiene registro, se reutiliza
        if var in self.var_to_reg:
            return self.var_to_reg[var]

        # Primero intenta en temporales
        for r in TEMP_REGS:
            if self.reg_to_var[r] is None:
                self.reg_to_var[r] = var
                self.var_to_reg[var] = r
                return r

        # Luego en saved
        for r in SAVED_REGS:
            if self.reg_to_var[r] is None:
                self.reg_to_var[r] = var
                self.var_to_reg[var] = r
                return r

        victim = TEMP_REGS[0]
        old_var = self.reg_to_var[victim]
        if old_var is not None and old_var in self.var_to_reg:
            del self.var_to_reg[old_var]
        self.reg_to_var[victim] = var
        self.var_to_reg[var] = victim
        return victim

    def ensure_in_reg(self, operand: str, emitter, data_section: DataSection) -> str:

        if operand is None:
            emitter.emit("    # WARNING: ensure_in_reg llamado con None, usando $zero")
            return "$zero"

        if operand == "this":
            return "$s7"


        if operand == "nombre":
            return "$t0"
        if operand == "edad":
            return "$t1"
        if operand == "grado":
            return "$t2"

        # literales numéricos
        if self._is_literal(operand):
            emitter.emit(f"    li $at, {operand}")
            return "$at"

        # literales string
        if self._is_string_literal(operand):
            lbl = data_section.add_string(operand)
            emitter.emit(f"    la $at, {lbl}")
            return "$at"

        if operand == "log":
            emitter.emit("    la $at, str_0")  
            return "$at"

        if operand.startswith("param"):
            try:
                idx = int(operand.replace("param", ""))
                if idx == 0:
                    return "$t0"
                elif idx == 1:
                    return "$t1"
                elif idx == 2:
                    return "$t2"
                else:
                    return f"$a{idx}"
            except ValueError:
                pass

        # variable normal: asignar registro con el allocator
        return self.get_reg_for_var(operand, for_write=False)





# ============================================================
#  INSTRUCTION EMITTER
# ============================================================

class InstructionEmitter:
    def __init__(self, reg_alloc: SimpleRegisterAllocator, data_section: DataSection):
        self.reg_alloc = reg_alloc
        self.data_section = data_section
        self.output: List[str] = []
        self.pending_params: List[str] = []
        self.string_vars = set()
        self.current_func: Optional[str] = None

    def emit(self, line: str):
        self.output.append(line)

    def emit_label(self, label: str):
        self.output.append(f"{label}:")

    def get_output(self) -> List[str]:
        return self.output

    # -------- utilidades --------

    def _is_literal(self, op: Optional[str]) -> bool:
        if op is None:
            return False
        s = str(op)
        return s.isdigit() or (s.startswith('-') and s[1:].isdigit())

    def _is_string_literal(self, op: Optional[str]) -> bool:
        if op is None:
            return False
        s = str(op)
        return s.startswith('"') and s.endswith('"')

    def _ensure(self, op: str) -> str:
        return self.reg_alloc.ensure_in_reg(op, self, self.data_section)

    # -------- control de flujo --------

    def emit_ifz(self, cond: str, label: str):
        rc = self._ensure(cond)
        self.emit(f"    beq {rc}, $zero, {label}")

    def emit_ifnz(self, cond: str, label: str):
        rc = self._ensure(cond)
        self.emit(f"    bne {rc}, $zero, {label}")

    def emit_jump(self, label: str):
        self.emit(f"    j {label}")

    # -------- aritmética --------

    def emit_add(self, a1: str, a2: str, res: str):
        # Detectar si alguno de los operandos es string (literal o variable marcada)
        is_str1 = a1 is not None and (self._is_string_literal(a1) or a1 in self.string_vars)
        is_str2 = a2 is not None and (self._is_string_literal(a2) or a2 in self.string_vars)

        if is_str1 or is_str2:
            # "Concatenación" de strings:
            # solo imprimimos los operandos y devolvemos la cadena vacía en res
            if a1 is not None:
                self.emit_print(a1)
            if a2 is not None:
                self.emit_print(a2)

            if res is not None:
                rd = self.reg_alloc.get_reg_for_var(res, for_write=True)
                self.emit("    la $at, str_0")
                self.emit(f"    move {rd}, $at")
                self.string_vars.add(res)
            return

        # === Caso normal: suma entera ===
        r1 = self._ensure(a1)
        r2 = self._ensure(a2)
        rd = self.reg_alloc.get_reg_for_var(res, for_write=True)
        self.emit(f"    addu {rd}, {r1}, {r2}")



    def emit_sub(self, a1: str, a2: str, res: str):
        r1 = self._ensure(a1)
        r2 = self._ensure(a2)
        rd = self.reg_alloc.get_reg_for_var(res, for_write=True)
        self.emit(f"    subu {rd}, {r1}, {r2}")

    def emit_mul(self, a1: str, a2: str, res: str):
        r1 = self._ensure(a1)
        r2 = self._ensure(a2)
        rd = self.reg_alloc.get_reg_for_var(res, for_write=True)
        self.emit(f"    mul {rd}, {r1}, {r2}")

    def emit_div(self, a1: str, a2: str, res: str):
        r1 = self._ensure(a1)
        r2 = self._ensure(a2)
        rd = self.reg_alloc.get_reg_for_var(res, for_write=True)
        self.emit(f"    div {r1}, {r2}")
        self.emit(f"    mflo {rd}")

    def emit_mod(self, a1: str, a2: str, res: str):
        r1 = self._ensure(a1)
        r2 = self._ensure(a2)
        rd = self.reg_alloc.get_reg_for_var(res, for_write=True)
        self.emit(f"    div {r1}, {r2}")
        self.emit(f"    mfhi {rd}")

    def emit_neg(self, a1: str, res: str):
        r1 = self._ensure(a1)
        rd = self.reg_alloc.get_reg_for_var(res, for_write=True)
        self.emit(f"    subu {rd}, $zero, {r1}")

    def emit_not(self, a1: str, res: str):
        r1 = self._ensure(a1)
        rd = self.reg_alloc.get_reg_for_var(res, for_write=True)
        self.emit(f"    sltiu {rd}, {r1}, 1")

    # -------- comparaciones --------

    def emit_cmp_eq(self, a1: str, a2: str, res: str):
        r1 = self._ensure(a1)
        r2 = self._ensure(a2)
        rd = self.reg_alloc.get_reg_for_var(res, for_write=True)
        self.emit(f"    xor {rd}, {r1}, {r2}")
        self.emit(f"    sltiu {rd}, {rd}, 1")

    def emit_cmp_ne(self, a1: str, a2: str, res: str):
        r1 = self._ensure(a1)
        r2 = self._ensure(a2)
        rd = self.reg_alloc.get_reg_for_var(res, for_write=True)
        self.emit(f"    xor {rd}, {r1}, {r2}")
        self.emit(f"    sltu {rd}, $zero, {rd}")

    def emit_cmp_lt(self, a1: str, a2: str, res: str):
        r1 = self._ensure(a1)
        r2 = self._ensure(a2)
        rd = self.reg_alloc.get_reg_for_var(res, for_write=True)
        self.emit(f"    slt {rd}, {r1}, {r2}")

    def emit_cmp_le(self, a1: str, a2: str, res: str):
        r1 = self._ensure(a1)
        r2 = self._ensure(a2)
        rd = self.reg_alloc.get_reg_for_var(res, for_write=True)
        self.emit(f"    slt {rd}, {r2}, {r1}")
        self.emit(f"    sltiu {rd}, {rd}, 1")

    def emit_cmp_gt(self, a1: str, a2: str, res: str):
        r1 = self._ensure(a1)
        r2 = self._ensure(a2)
        rd = self.reg_alloc.get_reg_for_var(res, for_write=True)
        self.emit(f"    slt {rd}, {r2}, {r1}")

    def emit_cmp_ge(self, a1: str, a2: str, res: str):
        r1 = self._ensure(a1)
        r2 = self._ensure(a2)
        rd = self.reg_alloc.get_reg_for_var(res, for_write=True)
        self.emit(f"    slt {rd}, {r1}, {r2}")
        self.emit(f"    sltiu {rd}, {rd}, 1")

    # -------- MOV --------

    def emit_mov(self, src: str, dest: str):
        # Si no hay destino, no generamos nada
        if dest is None:
            self.emit("    # WARNING: MOV con destino None ignorado")
            return

        if self._is_literal(src):
            rd = self.reg_alloc.get_reg_for_var(dest, for_write=True)
            self.emit(f"    li {rd}, {src}")
            # dest NO es string, no lo marcamos
        elif self._is_string_literal(src):
            rd = self.reg_alloc.get_reg_for_var(dest, for_write=True)
            lbl = self.data_section.add_string(src)
            self.emit(f"    la {rd}, {lbl}")
            # dest es un string
            self.string_vars.add(dest)
        else:
            rs = self._ensure(src)
            rd = self.reg_alloc.get_reg_for_var(dest, for_write=True)
            self.emit(f"    move {rd}, {rs}")
            # Si src ya era string, dest también es string
            if src in self.string_vars:
                self.string_vars.add(dest)



    def emit_print(self, operand: str):
        """
        Política nueva:
        - Si es literal de string -> syscall 4 (imprime string).
        - Si la variable está marcada como string -> syscall 4.
        - En cualquier otro caso -> SE IMPRIME COMO ENTERO (syscall 1).
        Así nunca hacemos syscall 4 con un entero random como 0x20020000.
        """
        if operand is None:
            self.emit("    # WARNING: PRINT llamado con None, ignorado")
            return

        # 1) Literal de string: "Hola", "...\n", etc
        if self._is_string_literal(operand):
            lbl = self.data_section.add_string(operand)
            self.emit(f"    la $a0, {lbl}")
            self.emit("    li $v0, 4")   # print string
            self.emit("    syscall")
            return

        # 2) Variable que sabemos que es string (movida desde un literal)
        if operand in self.string_vars:
            r = self._ensure(operand)
            self.emit(f"    move $a0, {r}")
            self.emit("    li $v0, 4")   # print string
            self.emit("    syscall")
            return

        # 3) Resto de casos: tratamos el valor como ENTERO
        r = self._ensure(operand)
        self.emit(f"    move $a0, {r}")
        self.emit("    li $v0, 1")       # print int
        self.emit("    syscall")




    # -------- Objetos (NEW / GETP / MOVP) --------

    def emit_new(self, class_name: str, res: str):
        """
        Reserva 16 bytes (Persona/Estudiante) y los inicializa a 0.
        """
        rd = self.reg_alloc.get_reg_for_var(res, for_write=True)
        self.emit(f"    # NEW {class_name}")
        self.emit(f"    li $a0, 16")
        self.emit(f"    li $v0, 9")
        self.emit(f"    syscall")
        self.emit(f"    move {rd}, $v0")
        for off in range(0, 16, 4):
            self.emit(f"    sw $zero, {off}({rd})")

    def emit_getp(self, obj: str, field: str, res: str):
        # CORRECCIÓN: Si obj es "this", usar $s7 (donde guardamos this)
        if obj == "this":
            base = "$s7"
        else:
            base = self._ensure(obj)

        rd = self.reg_alloc.get_reg_for_var(res, for_write=True)
        off = FIELD_OFFSETS.get(field, 0)
        self.emit(f"    # GETP {obj}.{field} -> {res}")
        self.emit(f"    lw {rd}, {off}({base})")

        # Marcar como string si el campo es nombre o color
        if off == 0 or off == 8:
            self.string_vars.add(res)

    def emit_setp(self, value: str, obj: str, field: str):
        rv = self._ensure(value)

        # CORRECCIÓN: Si obj es "this", usar $s7
        if obj == "this":
            base = "$s7"
        else:
            base = self._ensure(obj)

        off = FIELD_OFFSETS.get(field, 0)
        self.emit(f"    # SETP {obj}.{field} = {value}")
        self.emit(f"    sw {rv}, {off}({base})")
        # -------- FUNCIONES / LLAMADAS --------

    def emit_enter(self, frame_size: int):
        """
        Prólogo: guarda $ra, $fp y parámetros $a0-$a3
        """
        self.emit(f"    addi $sp, $sp, -24")
        self.emit(f"    sw $ra, 20($sp)")
        self.emit(f"    sw $fp, 16($sp)")
        self.emit(f"    sw $a0, 12($sp)")
        self.emit(f"    sw $a1, 8($sp)")
        self.emit(f"    sw $a2, 4($sp)")
        self.emit(f"    sw $a3, 0($sp)")
        self.emit(f"    move $fp, $sp")

        # CORRECCIÓN CRÍTICA: Guardar $a0 antes de mover parámetros
        # porque en constructores y métodos, $a0 es 'this' y lo necesitamos
        self.emit(f"    # Guardar this en $s7 (registro saved)")
        self.emit(f"    move $s7, $a0")

        # Mover parámetros a registros temporales que tu TAC espera
        self.emit(f"    move $t0, $a1")  # primer parámetro (después de this)
        self.emit(f"    move $t1, $a2")  # segundo parámetro
        self.emit(f"    move $t2, $a3")  # tercer parámetro

    def emit_leave(self):
        self.emit(f"    move $sp, $fp")
        self.emit(f"    lw $a3, 0($sp)")
        self.emit(f"    lw $a2, 4($sp)")
        self.emit(f"    lw $a1, 8($sp)")
        self.emit(f"    lw $a0, 12($sp)")
        self.emit(f"    lw $fp, 16($sp)")
        self.emit(f"    lw $ra, 20($sp)")
        self.emit(f"    addi $sp, $sp, 24")

    def emit_ret(self, retval: Optional[str]):
        if retval is not None:
            r = self._ensure(retval)
            self.emit(f"    move $v0, {r}")
        self.emit_leave()
        self.emit(f"    jr $ra")

    def emit_param(self, operand: str):
        self.pending_params.append(operand)

    def emit_call(self, func_label: str, res: Optional[str]):
        """
        Llamada de función con manejo especial de constructores
        """
        base_name = func_label
        if base_name.startswith("func_"):
            base_name = base_name[5:]

        # === printString ===
        if base_name == "printString":
            arg = self.pending_params[0] if self.pending_params else None
            if arg is not None:
                r = self._ensure(arg)
                self.emit(f"    move $a0, {r}")
                self.emit("    li $v0, 4")
                self.emit("    syscall")
                if res is not None:
                    rd = self.reg_alloc.get_reg_for_var(res, for_write=True)
                    self.emit(f"    move {rd}, $a0")
                    self.string_vars.add(res)
            self.pending_params.clear()
            return

        # === printInteger ===
        if base_name == "printInteger":
            arg = self.pending_params[0] if self.pending_params else None
            if arg is not None:
                r = self._ensure(arg)
                self.emit(f"    move $a0, {r}")
                self.emit("    li $v0, 1")
                self.emit("    syscall")
                if res is not None:
                    rd = self.reg_alloc.get_reg_for_var(res, for_write=True)
                    self.emit(f"    move {rd}, $a0")
            self.pending_params.clear()
            return

        # === toString ===
        if base_name == "toString":
            if res is not None:
                rd = self.reg_alloc.get_reg_for_var(res, for_write=True)
                self.emit("    la $at, str_0")
                self.emit(f"    move {rd}, $at")
                self.string_vars.add(res)
            self.pending_params.clear()
            return

        # === CASO GENERAL ===

        # CORRECCIÓN CRÍTICA: Para constructores, guardar $a0 antes de la llamada
        is_constructor = "_constructor" in base_name
        saved_this_reg = None

        if is_constructor and self.pending_params:
            # El primer parámetro es 'this' (el objeto)
            # Guardarlo temporalmente antes de configurar parámetros
            this_param = self.pending_params[0]
            saved_this_reg = self._ensure(this_param)
            # Guardar en un registro temporal que no se sobreescribirá
            self.emit(f"    move $s7, {saved_this_reg}")

        # Pasar parámetros a $a0-$a3
        reg_params = self.pending_params[:4]
        for i, op in enumerate(reg_params):
            if op is not None:
                r = self._ensure(op)
                self.emit(f"    move $a{i}, {r}")

        self.emit(f"    jal {func_label}")

        # Manejar valor de retorno
        if res is not None:
            rd = self.reg_alloc.get_reg_for_var(res, for_write=True)

            if is_constructor:
                # Los constructores "retornan" el objeto (this)
                # que guardamos en $s7
                self.emit(f"    move {rd}, $s7")
            else:
                # Funciones normales retornan en $v0
                self.emit(f"    move {rd}, $v0")

                # Marcar como string si es necesario
                if base_name in ("saludar", "estudiar", "incrementarEdad"):
                    self.string_vars.add(res)

        self.pending_params.clear()


# ============================================================
#  MIPS CODE GENERATOR
# ============================================================

class MIPSCodeGen:
    def __init__(self):
        self.data_section = DataSection()
        self.reg_alloc = SimpleRegisterAllocator()
        self.emitter = InstructionEmitter(self.reg_alloc, self.data_section)
        self.output: List[str] = []

    def generate(self, tac_program: TACProgram) -> str:
        self.output.clear()

        # .text y main
        self.output.append(".text")
        self.output.append(".globl main")
        self.output.append("main:")

        has_program_start = any(
            ins.op == "LABEL" and ins.res == "program_start"
            for ins in tac_program.code
        )
        if has_program_start:
            self.output.append("    j program_start")

        for ins in tac_program.code:
            self._translate_instruction(ins)

        self.output.extend(self.emitter.get_output())

        # ========= DATA =========
        final_lines: List[str] = []

        data_lines = self.data_section.generate_lines()
        final_lines.extend(data_lines)

        final_lines.extend(self.output)
        return "\n".join(final_lines)


    # ---------------------------

    def _translate_instruction(self, ins: TACInstr):
        op = ins.op
        a1 = str(ins.a1) if ins.a1 is not None else None
        a2 = str(ins.a2) if ins.a2 is not None else None
        res = str(ins.res) if ins.res is not None else None

        # LABEL
        if op == "LABEL":
            label = res if res else a1
            self.emitter.emit_label(label)


            if label == "program_start" or label.startswith("func_"):
                # Limpiar info de strings
                self.emitter.string_vars.clear()
                self.emitter.pending_params.clear()

                # Resetear asignación de registros
                self.reg_alloc.var_to_reg.clear()
                self.reg_alloc.reg_to_var = {r: None for r in TEMP_REGS + SAVED_REGS}

            self.emitter.current_func = label

            if label == "program_end":
                self.emitter.emit("")
                self.emitter.emit("# Exit program")
                self.emitter.emit("    li $v0, 10")
                self.emitter.emit("    syscall")
            return

        # CONTROL FLOW
        if op == "JUMP":
            self.emitter.emit_jump(a1 or res)
            return
        if op == "IFZ":
            self.emitter.emit_ifz(a1, res)
            return
        if op == "IFNZ":
            self.emitter.emit_ifnz(a1, res)
            return

        # ARITH
        if op == "ADD":
            self.emitter.emit_add(a1, a2, res)
            return
        if op == "SUB":
            self.emitter.emit_sub(a1, a2, res)
            return
        if op == "MUL":
            self.emitter.emit_mul(a1, a2, res)
            return
        if op == "DIV":
            self.emitter.emit_div(a1, a2, res)
            return
        if op == "MOD":
            self.emitter.emit_mod(a1, a2, res)
            return
        if op == "NEG":
            self.emitter.emit_neg(a1, res)
            return
        if op == "NOT":
            self.emitter.emit_not(a1, res)
            return

        # COMPARISONS
        if op == "CMP==":
            self.emitter.emit_cmp_eq(a1, a2, res)
            return
        if op == "CMP!=":
            self.emitter.emit_cmp_ne(a1, a2, res)
            return
        if op == "CMP<":
            self.emitter.emit_cmp_lt(a1, a2, res)
            return
        if op == "CMP<=":
            self.emitter.emit_cmp_le(a1, a2, res)
            return
        if op == "CMP>":
            self.emitter.emit_cmp_gt(a1, a2, res)
            return
        if op == "CMP>=":
            self.emitter.emit_cmp_ge(a1, a2, res)
            return

        # MOV / PRINT
        if op == "MOV":
            self.emitter.emit_mov(a1, res)
            return
        if op == "PRINT":
            self.emitter.emit_print(a1)
            return

        # FUNCIONES
        if op == "ENTER":
            frame_size = int(a1) if a1 and a1.isdigit() else 0
            self.emitter.emit_enter(frame_size)
            return
        if op == "LEAVE":
            # en este diseño, LEAVE no hace nada especial
            # (el RET ya llama a emit_leave)
            return
        if op == "RET":
            self.emitter.emit_ret(a1)
            return
        if op == "PARAM":
            self.emitter.emit_param(a1)
            return
        if op == "CALL":
            self.emitter.emit_call(a1, res)
            return

        # OBJETOS
        if op == "NEW":
            self.emitter.emit_new(a1, res)
            return
        if op == "GETP":
            self.emitter.emit_getp(a1, a2, res)
            return
        if op == "MOVP":
            self.emitter.emit_setp(a1, a2, res)
            return

        # Si algo no está soportado, solo comenta
        self.emitter.emit(f"    # Unsupported TAC op: {op}")

# ============================================================
#  API PÚBLICA
# ============================================================

def generate_mips_from_tac(tac_program: TACProgram) -> str:
    cg = MIPSCodeGen()
    return cg.generate(tac_program)