from typing import Dict, List, Optional, Set, Tuple
from .ir import TACProgram, TACInstr

# ==================== CONSTANTES MIPS ====================

TEMP_REGS = [f"$t{i}" for i in range(8)]  
SAVED_REGS = [f"$s{i}" for i in range(8)]  
ARG_REGS = [f"$a{i}" for i in range(4)]   

REG_V0 = "$v0"
REG_RA = "$ra"
REG_SP = "$sp"
REG_FP = "$fp"
REG_ZERO = "$zero"
REG_T8 = "$t8"
REG_T9 = "$t9"

WORD_SIZE = 4

FIELD_OFFSETS = {
    "nombre": 0,
    "edad": 4,
    "color": 8,
    "grado": 12,
}


# ==================== REGISTER ALLOCATOR ====================

class RegisterDescriptor:
    def __init__(self):
        self.reg_contents: Dict[str, Optional[str]] = {}
        self.var_location: Dict[str, Optional[str]] = {}
        for reg in TEMP_REGS + SAVED_REGS:
            self.reg_contents[reg] = None
    
    def is_free(self, reg: str) -> bool:
        return self.reg_contents.get(reg) is None
    
    def allocate(self, var: str, reg: str):
        if self.reg_contents[reg] is not None:
            old_var = self.reg_contents[reg]
            self.var_location[old_var] = None
        self.reg_contents[reg] = var
        self.var_location[var] = reg
    
    def free_register(self, reg: str):
        if reg in self.reg_contents:
            var = self.reg_contents[reg]
            if var:
                self.var_location[var] = None
            self.reg_contents[reg] = None
    
    def get_location(self, var: str) -> Optional[str]:
        return self.var_location.get(var)
    
    def clear_all_temps(self):
        for reg in TEMP_REGS:
            self.free_register(reg)


class RegisterAllocator:
    def __init__(self, frame_manager):
        self.descriptor = RegisterDescriptor()
        self.frame_manager = frame_manager
        self.lru_counter = 0
        self.reg_last_use: Dict[str, int] = {}
        self.output: List[str] = []
    
    def emit(self, instruction: str):
        self.output.append(instruction)
    
    def get_reg(self, var: str, for_write: bool = False) -> str:
        existing = self.descriptor.get_location(var)
        if existing:
            self._update_lru(existing)
            return existing
        
        is_temp = var.startswith('t') and var[1:].isdigit()
        free_reg = self._find_free_temp() if is_temp else self._find_free_saved()
        
        if free_reg:
            self.descriptor.allocate(var, free_reg)
            self._update_lru(free_reg)
            if not for_write:
                self._load_from_memory(var, free_reg)
            return free_reg
        
        victim_reg = self._select_victim(is_temp)
        self._spill_register(victim_reg)
        self.descriptor.allocate(var, victim_reg)
        self._update_lru(victim_reg)
        if not for_write:
            self._load_from_memory(var, victim_reg)
        return victim_reg
    
    def _find_free_temp(self) -> Optional[str]:
        for reg in TEMP_REGS:
            if self.descriptor.is_free(reg):
                return reg
        return None
    
    def _find_free_saved(self) -> Optional[str]:
        for reg in SAVED_REGS:
            if self.descriptor.is_free(reg):
                return reg
        return None
    
    def _select_victim(self, prefer_temp: bool) -> str:
        pool = TEMP_REGS if prefer_temp else SAVED_REGS
        oldest_time = float('inf')
        victim = pool[0]
        for reg in pool:
            last_use = self.reg_last_use.get(reg, 0)
            if last_use < oldest_time:
                oldest_time = last_use
                victim = reg
        return victim
    
    def _spill_register(self, reg: str):
        var = self.descriptor.reg_contents.get(reg)
        if var is None:
            return
        self._store_to_memory(var, reg)
        self.descriptor.free_register(reg)
    
    def _load_from_memory(self, var: str, reg: str):
        offset = self.frame_manager.get_var_offset(var)
        if offset is not None:
            self.emit(f"    lw {reg}, {offset}($fp)")
    
    def _store_to_memory(self, var: str, reg: str):
        offset = self.frame_manager.get_var_offset(var)
        if offset is not None:
            self.emit(f"    sw {reg}, {offset}($fp)")
        else:
            offset = self.frame_manager.allocate_local(var)
            self.emit(f"    sw {reg}, {offset}($fp)")
    
    def _update_lru(self, reg: str):
        self.lru_counter += 1
        self.reg_last_use[reg] = self.lru_counter
    
    def _is_literal(self, operand: str) -> bool:
        if operand is None:
            return False
        s = str(operand)
        return s.isdigit() or (s.startswith('-') and s[1:].isdigit())


# ==================== STACK FRAME MANAGER ====================

class StackFrame:
    def __init__(self, function_name: str):
        self.function_name = function_name
        self.params: List[str] = []
        self.locals: Dict[str, int] = {}
        self.saved_regs_used: Set[str] = set()
        self.next_local_offset = -8
        self.frame_size = 0
    
    def add_param(self, param_name: str):
        self.params.append(param_name)
    
    def add_local(self, var_name: str) -> int:
        if var_name in self.locals:
            return self.locals[var_name]
        offset = self.next_local_offset
        self.locals[var_name] = offset
        self.next_local_offset -= WORD_SIZE
        return offset
    
    def mark_saved_reg_used(self, reg: str):
        if reg in SAVED_REGS:
            self.saved_regs_used.add(reg)
    
    def get_param_location(self, param_name: str) -> Tuple[Optional[str], Optional[int]]:
        try:
            idx = self.params.index(param_name)
        except ValueError:
            return (None, None)
        if idx < 4:
            return (ARG_REGS[idx], None)
        else:
            offset = 8 + (idx - 4) * WORD_SIZE
            return (None, offset)
    
    def finalize(self):
        size = 8
        size += len(self.saved_regs_used) * WORD_SIZE
        size += len(self.locals) * WORD_SIZE
        if size % 8 != 0:
            size += (8 - size % 8)
        self.frame_size = size


class StackFrameManager:
    def __init__(self):
        self.frames: Dict[str, StackFrame] = {}
        self.current_frame: Optional[StackFrame] = None
    
    def enter_function(self, function_name: str):
        if function_name not in self.frames:
            self.frames[function_name] = StackFrame(function_name)
        self.current_frame = self.frames[function_name]
    
    def exit_function(self):
        if self.current_frame:
            self.current_frame.finalize()
        self.current_frame = None
    
    def allocate_local(self, var_name: str) -> int:
        if self.current_frame:
            return self.current_frame.add_local(var_name)
        return 0
    
    def get_var_offset(self, var_name: str) -> Optional[int]:
        if not self.current_frame:
            return None
        if var_name in self.current_frame.locals:
            return self.current_frame.locals[var_name]
        reg, offset = self.current_frame.get_param_location(var_name)
        if reg:
            return self.allocate_local(var_name)
        return offset
    
    def get_frame_size(self) -> int:
        if self.current_frame:
            return self.current_frame.frame_size
        return 0
    
    def get_saved_regs(self) -> List[str]:
        if self.current_frame:
            return sorted(list(self.current_frame.saved_regs_used))
        return []


# ==================== DATA SECTION ====================

class DataSection:
    def __init__(self):
        self.strings: Dict[str, str] = {}
        self.string_counter = 0
        self.globals: Dict[str, any] = {}
    
    def add_string(self, string_literal: str) -> str:
        content = string_literal.strip('"')
        for existing_content, label in self.strings.items():
            if existing_content == content:
                return label
        label = f"str_{self.string_counter}"
        self.string_counter += 1
        self.strings[content] = label
        return label
    
    def generate(self) -> List[str]:
        lines = []
        if not self.strings and not self.globals:
            return lines
        lines.append(".data")
        for content, label in self.strings.items():
            escaped = content.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')
            lines.append(f'{label}: .asciiz "{escaped}"')
        for var_name, value in self.globals.items():
            lines.append(f'{var_name}: .word {value}')
        lines.append("")
        return lines


# ==================== INSTRUCTION EMITTER ====================

class InstructionEmitter:
    def __init__(self, register_allocator, frame_manager, data_section):
        self.reg_alloc = register_allocator
        self.frame_manager = frame_manager
        self.data_section = data_section
        self.output: List[str] = []
        self.pending_params: List[str] = []
    
    def emit(self, line: str):
        self.output.append(line)
    
    def get_output(self) -> List[str]:
        return self.output
    
    def clear_output(self):
        self.output.clear()
    
    def _is_literal(self, operand: str) -> bool:
        if operand is None:
            return False
        s = str(operand)
        return s.isdigit() or (s.startswith('-') and s[1:].isdigit())
    
    def _is_string_literal(self, operand: str) -> bool:
        s = str(operand)
        return s.startswith('"') and s.endswith('"')
    
    def _ensure_in_reg(self, operand: str) -> str:
        if self._is_literal(operand):
            self.emit(f"    li {REG_T9}, {operand}")
            return REG_T9
        if self._is_string_literal(operand):
            label = self.data_section.add_string(operand)
            self.emit(f"    la {REG_T9}, {label}")
            return REG_T9
        return self.reg_alloc.get_reg(operand, for_write=False)
    
    # ========== OPERACIONES ARITMÉTICAS ==========
    
    def emit_add(self, a1: str, a2: str, result: str):
        if self._is_literal(a1) and self._is_literal(a2):
            self.emit(f"    li $t8, {a1}")
            ra = "$t8"
            self.emit(f"    li $t9, {a2}")
            rb = "$t9"
        else:
            ra = self._ensure_in_reg(a1)
            rb = self._ensure_in_reg(a2)
        
        rd = self.reg_alloc.get_reg(result, for_write=True)
        self.emit(f"    addu {rd}, {ra}, {rb}")

    def emit_sub(self, a1: str, a2: str, result: str):
        if self._is_literal(a1) and self._is_literal(a2):
            self.emit(f"    li $t8, {a1}")
            ra = "$t8"
            self.emit(f"    li $t9, {a2}")
            rb = "$t9"
        else:
            ra = self._ensure_in_reg(a1)
            rb = self._ensure_in_reg(a2)
        
        rd = self.reg_alloc.get_reg(result, for_write=True)
        self.emit(f"    subu {rd}, {ra}, {rb}")

    def emit_mul(self, a1: str, a2: str, result: str):
        if self._is_literal(a1) and self._is_literal(a2):
            self.emit(f"    li $t8, {a1}")
            ra = "$t8"
            self.emit(f"    li $t9, {a2}")
            rb = "$t9"
        else:
            ra = self._ensure_in_reg(a1)
            rb = self._ensure_in_reg(a2)
        
        rd = self.reg_alloc.get_reg(result, for_write=True)
        self.emit(f"    mul {rd}, {ra}, {rb}")

    def emit_div(self, a1: str, a2: str, result: str):
        if self._is_literal(a1) and self._is_literal(a2):
            self.emit(f"    li $t8, {a1}")
            ra = "$t8"
            self.emit(f"    li $t9, {a2}")
            rb = "$t9"
        else:
            ra = self._ensure_in_reg(a1)
            rb = self._ensure_in_reg(a2)
        
        rd = self.reg_alloc.get_reg(result, for_write=True)
        self.emit(f"    div {ra}, {rb}")
        self.emit(f"    mflo {rd}")

    def emit_mod(self, a1: str, a2: str, result: str):
        if self._is_literal(a1) and self._is_literal(a2):
            self.emit(f"    li $t8, {a1}")
            ra = "$t8"
            self.emit(f"    li $t9, {a2}")
            rb = "$t9"
        else:
            ra = self._ensure_in_reg(a1)
            rb = self._ensure_in_reg(a2)
        
        rd = self.reg_alloc.get_reg(result, for_write=True)
        self.emit(f"    div {ra}, {rb}")
        self.emit(f"    mfhi {rd}")

    def emit_neg(self, a1: str, result: str):
        ra = self._ensure_in_reg(a1)
        rd = self.reg_alloc.get_reg(result, for_write=True)
        self.emit(f"    subu {rd}, {REG_ZERO}, {ra}")

    def emit_not(self, a1: str, result: str):
        ra = self._ensure_in_reg(a1)
        rd = self.reg_alloc.get_reg(result, for_write=True)
        self.emit(f"    sltiu {rd}, {ra}, 1")
    
    # ========== COMPARACIONES ==========
    
    def emit_cmp_eq(self, a1: str, a2: str, result: str):
        if self._is_literal(a1) and self._is_literal(a2):
            self.emit(f"    li $t8, {a1}")
            ra = "$t8"
            self.emit(f"    li $t9, {a2}")
            rb = "$t9"
        else:
            ra = self._ensure_in_reg(a1)
            rb = self._ensure_in_reg(a2)
        
        rd = self.reg_alloc.get_reg(result, for_write=True)
        self.emit(f"    xor {rd}, {ra}, {rb}")
        self.emit(f"    sltu {rd}, {rd}, 1")

    def emit_cmp_ne(self, a1: str, a2: str, result: str):
        if self._is_literal(a1) and self._is_literal(a2):
            self.emit(f"    li $t8, {a1}")
            ra = "$t8"
            self.emit(f"    li $t9, {a2}")
            rb = "$t9"
        else:
            ra = self._ensure_in_reg(a1)
            rb = self._ensure_in_reg(a2)
        
        rd = self.reg_alloc.get_reg(result, for_write=True)
        self.emit(f"    xor {rd}, {ra}, {rb}")
        self.emit(f"    sltu {rd}, {REG_ZERO}, {rd}")

    def emit_cmp_lt(self, a1: str, a2: str, result: str):
        if self._is_literal(a1) and self._is_literal(a2):
            self.emit(f"    li $t8, {a1}")
            ra = "$t8"
            self.emit(f"    li $t9, {a2}")
            rb = "$t9"
        else:
            ra = self._ensure_in_reg(a1)
            rb = self._ensure_in_reg(a2)
        
        rd = self.reg_alloc.get_reg(result, for_write=True)
        self.emit(f"    slt {rd}, {ra}, {rb}")

    def emit_cmp_le(self, a1: str, a2: str, result: str):
        if self._is_literal(a1) and self._is_literal(a2):
            self.emit(f"    li $t8, {a1}")
            ra = "$t8"
            self.emit(f"    li $t9, {a2}")
            rb = "$t9"
        else:
            ra = self._ensure_in_reg(a1)
            rb = self._ensure_in_reg(a2)
        
        rd = self.reg_alloc.get_reg(result, for_write=True)
        self.emit(f"    slt {rd}, {rb}, {ra}")
        self.emit(f"    xori {rd}, {rd}, 1")

    def emit_cmp_gt(self, a1: str, a2: str, result: str):
        if self._is_literal(a1) and self._is_literal(a2):
            self.emit(f"    li $t8, {a1}")
            ra = "$t8"
            self.emit(f"    li $t9, {a2}")
            rb = "$t9"
        else:
            ra = self._ensure_in_reg(a1)
            rb = self._ensure_in_reg(a2)
        
        rd = self.reg_alloc.get_reg(result, for_write=True)
        self.emit(f"    slt {rd}, {rb}, {ra}")

    def emit_cmp_ge(self, a1: str, a2: str, result: str):
        if self._is_literal(a1) and self._is_literal(a2):
            self.emit(f"    li $t8, {a1}")
            ra = "$t8"
            self.emit(f"    li $t9, {a2}")
            rb = "$t9"
        else:
            ra = self._ensure_in_reg(a1)
            rb = self._ensure_in_reg(a2)
        
        rd = self.reg_alloc.get_reg(result, for_write=True)
        self.emit(f"    slt {rd}, {ra}, {rb}")
        self.emit(f"    xori {rd}, {rd}, 1")
    
    # ========== CONTROL DE FLUJO ==========
    
    def emit_label(self, label: str):
        self.emit(f"{label}:")
    
    def emit_jump(self, label: str):
        self.emit(f"    j {label}")
    
    def emit_ifz(self, cond: str, label: str):
        rc = self._ensure_in_reg(cond)
        self.emit(f"    beq {rc}, {REG_ZERO}, {label}")
    
    def emit_ifnz(self, cond: str, label: str):
        rc = self._ensure_in_reg(cond)
        self.emit(f"    bne {rc}, {REG_ZERO}, {label}")
    
    # ========== MOVIMIENTOS ==========
    
    def emit_mov(self, source: str, dest: str):
        if self._is_literal(source):
            rd = self.reg_alloc.get_reg(dest, for_write=True)
            self.emit(f"    li {rd}, {source}")
        elif self._is_string_literal(source):
            rd = self.reg_alloc.get_reg(dest, for_write=True)
            label = self.data_section.add_string(source)
            self.emit(f"    la {rd}, {label}")
        else:
            rs = self._ensure_in_reg(source)
            rd = self.reg_alloc.get_reg(dest, for_write=True)
            self.emit(f"    move {rd}, {rs}")
    
    # ========== I/O ==========
    
    def emit_print(self, operand: str):
        if self._is_string_literal(operand):
            label = self.data_section.add_string(operand)
            self.emit(f"    la $a0, {label}")
            self.emit(f"    li $v0, 4")  
            self.emit(f"    syscall")
        else:
            ra = self._ensure_in_reg(operand)
            self.emit(f"    move $a0, {ra}")
            self.emit(f"    li $v0, 1")  
            self.emit(f"    syscall")
            self.emit(f"    li $a0, 10")
            self.emit(f"    li $v0, 11")
            self.emit(f"    syscall")
    
    # ========== OBJETOS (OOP) ==========
    
    def emit_new(self, class_name: str, result: str):
        rd = self.reg_alloc.get_reg(result, for_write=True)
        
        self.emit(f"    # NEW {class_name}")
        self.emit(f"    li $a0, 100") 
        self.emit(f"    li $v0, 9")     
        self.emit(f"    syscall")
        self.emit(f"    move {rd}, $v0")  
        
        self.emit(f"    # Initialize fields to 0")
        for i in range(0, 100, 4):
            self.emit(f"    sw $zero, {i}({rd})")
    
    def emit_getp(self, obj: str, field: str, result: str):
        robj = self._ensure_in_reg(obj)
        rd = self.reg_alloc.get_reg(result, for_write=True)
        
        # Obtener offset del campo
        offset = FIELD_OFFSETS.get(field, 0)
        
        self.emit(f"    # GETP {obj}.{field} -> {result}")
        self.emit(f"    lw {rd}, {offset}({robj})")
    
    def emit_setp(self, value: str, obj: str, field: str):
        rval = self._ensure_in_reg(value)
        robj = self._ensure_in_reg(obj)
        
        # Obtener offset del campo
        offset = FIELD_OFFSETS.get(field, 0)
        
        self.emit(f"    # SETP {obj}.{field} = {value}")
        self.emit(f"    sw {rval}, {offset}({robj})")
    
    # ========== FUNCIONES ==========
    
    def emit_enter(self, frame_size: int):
        self.emit(f"    addi $sp, $sp, -4")
        self.emit(f"    sw $ra, 0($sp)")
        self.emit(f"    addi $sp, $sp, -4")
        self.emit(f"    sw $fp, 0($sp)")
        self.emit(f"    move $fp, $sp")
        remaining_space = frame_size - 8
        if remaining_space > 0:
            self.emit(f"    addi $sp, $sp, -{remaining_space}")
        saved_regs = self.frame_manager.get_saved_regs()
        offset = -8
        for reg in saved_regs:
            self.emit(f"    sw {reg}, {offset}($fp)")
            offset -= 4
    
    def emit_leave(self):
        saved_regs = self.frame_manager.get_saved_regs()
        offset = -8
        for reg in saved_regs:
            self.emit(f"    lw {reg}, {offset}($fp)")
            offset -= 4
        self.emit(f"    move $sp, $fp")
        self.emit(f"    lw $fp, 0($sp)")
        self.emit(f"    addi $sp, $sp, 4")
        self.emit(f"    lw $ra, 0($sp)")
        self.emit(f"    addi $sp, $sp, 4")
    
    def emit_ret(self, return_value: Optional[str] = None):
        if return_value:
            rv = self._ensure_in_reg(return_value)
            self.emit(f"    move $v0, {rv}")
        self.emit(f"    jr $ra")
    
    def emit_param(self, operand: str):
        self.pending_params.append(operand)
    
    def emit_call(self, func_label: str, result: Optional[str] = None):
        reg_params = self.pending_params[:4]
        stack_params = self.pending_params[4:]
        
        # Stack params en orden inverso
        for param in reversed(stack_params):
            rp = self._ensure_in_reg(param)
            self.emit(f"    addi $sp, $sp, -4")
            self.emit(f"    sw {rp}, 0($sp)")
        
        # Register params
        for i, param in enumerate(reg_params):
            rp = self._ensure_in_reg(param)
            self.emit(f"    move $a{i}, {rp}")
        
        # Call
        self.emit(f"    jal {func_label}")
        
        # Cleanup stack
        if stack_params:
            cleanup_bytes = len(stack_params) * 4
            self.emit(f"    addi $sp, $sp, {cleanup_bytes}")
        
        # Capturar resultado
        if result:
            rd = self.reg_alloc.get_reg(result, for_write=True)
            self.emit(f"    move {rd}, $v0")
        
        self.pending_params.clear()
        self.reg_alloc.descriptor.clear_all_temps()


# ==================== MIPS CODE GENERATOR ====================

class MIPSCodeGen:
    def __init__(self):
        self.data_section = DataSection()
        self.frame_manager = StackFrameManager()
        self.reg_alloc = None
        self.emitter = None
        self.output: List[str] = []
        self.in_function = False
    
    def generate(self, tac_program: TACProgram) -> str:
        self.output.clear()
        self._preanalyze(tac_program)
        self._generate_code(tac_program)
        return self._assemble_program()
    
    def _preanalyze(self, tac_program: TACProgram):
        current_func = None
        for ins in tac_program.code:
            op = ins.op
            if op == "LABEL" and ins.res and str(ins.res).startswith("func_"):
                func_name = str(ins.res)
                self.frame_manager.enter_function(func_name)
                current_func = func_name
            elif op == "LEAVE":
                if current_func:
                    self.frame_manager.exit_function()
                    current_func = None
            elif op == "MOV" and current_func and ins.res:
                var_name = str(ins.res)
                if not (var_name.startswith('t') and var_name[1:].isdigit()):
                    self.frame_manager.allocate_local(var_name)
    
    def _generate_code(self, tac_program: TACProgram):
        # Encabezado
        self.output.append(".text")
        self.output.append(".globl main")
        self.output.append("main:")
        
        # Saltar a program_start
        has_program_start = any(ins.op == "LABEL" and ins.res == "program_start" for ins in tac_program.code)
        if has_program_start:
            self.output.append("    j program_start")
        
        # Crear emitter global
        self.frame_manager.enter_function("__global__")
        self.reg_alloc = RegisterAllocator(self.frame_manager)
        self.emitter = InstructionEmitter(self.reg_alloc, self.frame_manager, self.data_section)
        
        # Generar instrucciones
        for ins in tac_program.code:
            self._translate_instruction(ins)
        
        # Volcar output final
        if self.emitter:
            self.output.extend(self.emitter.get_output())
    
    def _translate_instruction(self, ins: TACInstr):
        op = ins.op
        a1 = str(ins.a1) if ins.a1 is not None else None
        a2 = str(ins.a2) if ins.a2 is not None else None
        res = str(ins.res) if ins.res is not None else None
        
        if op == "LABEL":
            label = res if res else a1
            if label and label.startswith("func_"):
                if self.emitter and not self.in_function:
                    self.output.extend(self.emitter.get_output())
                    self.emitter.clear_output()
                self._enter_function(label)
            
            self.emitter.emit_label(label)
            
            # Exit en program_end
            if label == "program_end":
                self.emitter.emit("")
                self.emitter.emit("# Exit program")
                self.emitter.emit("    li $v0, 10")
                self.emitter.emit("    syscall")
        
        elif op == "JUMP":
            label = a1 if a1 else res
            self.emitter.emit_jump(label)
        elif op == "IFZ":
            self.emitter.emit_ifz(a1, res)
        elif op == "IFNZ":
            self.emitter.emit_ifnz(a1, res)
        
        elif op == "ADD":
            self.emitter.emit_add(a1, a2, res)
        elif op == "SUB":
            self.emitter.emit_sub(a1, a2, res)
        elif op == "MUL":
            self.emitter.emit_mul(a1, a2, res)
        elif op == "DIV":
            self.emitter.emit_div(a1, a2, res)
        elif op == "MOD":
            self.emitter.emit_mod(a1, a2, res)
        elif op == "NEG":
            self.emitter.emit_neg(a1, res)
        elif op == "NOT":
            self.emitter.emit_not(a1, res)
        
        elif op == "CMP==":
            self.emitter.emit_cmp_eq(a1, a2, res)
        elif op == "CMP!=":
            self.emitter.emit_cmp_ne(a1, a2, res)
        elif op == "CMP<":
            self.emitter.emit_cmp_lt(a1, a2, res)
        elif op == "CMP<=":
            self.emitter.emit_cmp_le(a1, a2, res)
        elif op == "CMP>":
            self.emitter.emit_cmp_gt(a1, a2, res)
        elif op == "CMP>=":
            self.emitter.emit_cmp_ge(a1, a2, res)
        
        elif op == "MOV":
            self.emitter.emit_mov(a1, res)
        elif op == "PRINT":
            self.emitter.emit_print(a1)
        
        elif op == "ENTER":
            frame_size = int(a1) if a1 and a1.isdigit() else 0
            self.emitter.emit_enter(frame_size)
        elif op == "LEAVE":
            self.emitter.emit_leave()
        elif op == "RET":
            self.emitter.emit_ret(a1)
            self._exit_function()
        elif op == "PARAM":
            self.emitter.emit_param(a1)
        elif op == "CALL":
            self.emitter.emit_call(a1, res)
        
        # ========== OOP OPERATIONS ==========
        elif op == "NEW":
            self.emitter.emit_new(a1, res)
        elif op == "GETP":
            self.emitter.emit_getp(a1, a2, res)
        elif op == "MOVP":
            self.emitter.emit_setp(a1, a2, res)
        
        else:
            self.emitter.emit(f"    # Unsupported: {op}")
    
    def _enter_function(self, func_label: str):
        self.in_function = True
        self.frame_manager.enter_function(func_label)
        self.reg_alloc = RegisterAllocator(self.frame_manager)
        self.emitter = InstructionEmitter(self.reg_alloc, self.frame_manager, self.data_section)
    
    def _exit_function(self):
        if self.emitter:
            self.output.extend(self.emitter.get_output())
            self.emitter.clear_output()
        self.frame_manager.exit_function()
        self.in_function = False
    
    def _assemble_program(self) -> str:
        final = []
        data_lines = self.data_section.generate()
        if data_lines:
            final.extend(data_lines)
        final.extend(self.output)
        return "\n".join(final)


# ==================== API PÚBLICA ====================

def generate_mips_from_tac(tac_program: TACProgram) -> str:
    codegen = MIPSCodeGen()
    return codegen.generate(tac_program)