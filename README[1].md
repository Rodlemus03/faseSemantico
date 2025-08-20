# Fase analizador lexico

El sistema implementa un compilador para el lenguaje Compiscript, capaz de realizar análisis sintáctico y semántico con verificación de tipos, manejo de ámbitos, control de flujo y funciones, generando errores detallados y una visualización del árbol sintáctico. 

---

## 1) Requisitos previos
- **Python 3.10+**
- **Java JDK 17+** 
- **Graphviz** instalado en el sistema 
  - Windows: https://graphviz.org/download/ 
  - macOS: `brew install graphviz`
  - Linux: `sudo apt-get install graphviz`

---

## 2) Crear entorno y dependencias
```bash
cd /mnt/data/compiscript_lab
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
# source .venv/bin/activate

pip install -r requirements.txt
```

---

## 3) Instalar ANTLR 4.13.1
Descarga el jar: https://www.antlr.org/download/antlr-4.13.1-complete.jar  
Colócalo por ejemplo en:
- Windows: `C:\antlr\antlr-4.13.1-complete.jar`
- Unix: `~/lib/antlr-4.13.1-complete.jar`

### Aliases útiles
- **PowerShell (Windows):**
  ```powershell
  setx ANTLR_JAR "C:\antlr\antlr-4.13.1-complete.jar"
  setx CLASSPATH ".;%%ANTLR_JAR%%;"
  function antlr4 { java -Xmx500M -cp "$env:ANTLR_JAR" org.antlr.v4.Tool @Args }
  function grun   { java -Xmx500M -cp "$env:ANTLR_JAR" org.antlr.v4.gui.TestRig @Args }
  ```
- **Bash (macOS/Linux)**, agrega a `~/.bashrc` o `~/.zshrc`:
  ```bash
  export ANTLR_JAR=~/lib/antlr-4.13.1-complete.jar
  export CLASSPATH=".:$ANTLR_JAR:$CLASSPATH"
  alias antlr4='java -Xmx500M -cp "$ANTLR_JAR" org.antlr.v4.Tool'
  alias grun='java -Xmx500M -cp "$ANTLR_JAR" org.antlr.v4.gui.TestRig'
  ```

---

## 4) Generar Lexer/Parser 
```bash
cd program
antlr4 -Dlanguage=Python3 Compiscript.g4
```

---

## 5) Ejecutar el parser
```bash
# desde la carpeta program
python Driver.py program.cps
```

- Si hay errores sintácticos o semánticos se listarán con línea/columna.  
- Si todo está Nitido verás: `ANÁLISIS SEMÁNTICO NÍTICO`.

---

## 6) Ejecutar el IDE Streamlit
```bash
streamlit run ide/app.py
```
Abre el navegador en la URL mostrada. Podrás escribir Compiscript, compilar y ver el árbol/símbolos/errores.

---

## 7) Correr pruebas
```bash
pytest -q
```

---

# Arquitectura del Compilador

## 1) Componentes principales

### 🔹 Sistema de Tipos (`types.py`)
Define los tipos soportados:
- **Primitivos**: `IntegerType`, `FloatType`, `StringType`, `BooleanType`, `NullType`.
- **Compuestos**: 
  - `ArrayType` (verifica compatibilidad entre elementos).  
  - `ClassType` (modela clases con nombre).  
- Constantes globales (`INT`, `FLOAT`, `STR`, `BOOL`, `NULL`) facilitan la verificación.

---

### 🔹 Símbolos (`symbols.py`)
Representan entidades del lenguaje:
- `VarSymbol` → variables (con flags `const` e inicialización).  
- `ParamSymbol` → parámetros de funciones.  
- `FunctionSymbol` → funciones con retorno y parámetros.  
- `ClassSymbol` → clases con campos, métodos y herencia opcional.

---

### 🔹 Ámbitos (`scope.py`)
Maneja la visibilidad de símbolos:
- Cada `Scope` tiene su propia tabla de símbolos.  
- Métodos principales:  
  - `define()` → registra un símbolo nuevo.  
  - `resolve()` → busca un símbolo en el scope actual y padres.

---

### 🔹 Manejo de Errores (`errors.py`)
- `SyntaxErrorListener`: intercepta errores sintácticos de ANTLR.  
- `SemanticError`: excepción para abortar en caso de errores graves.

---

### 🔹 Visualización de Árbol (`treeviz.py`)
- Usa **Graphviz** para renderizar el árbol sintáctico.  
- Función `render_parse_tree_svg()` devuelve un **SVG navegable**.

---

### 🔹 Chequeo Semántico (`checker.py`)
Clase **`SemanticChecker`** (visitor):
- **Declaraciones**: variables, constantes, funciones y clases.  
- **Asignaciones**: compatibilidad de tipos, prohíbe reasignar `const`.  
- **Control de flujo**: condiciones booleanas en `if`, `while`, `for`, etc.  
- **Funciones**: verifica número y tipos de parámetros, así como retornos.  
- **Clases**: permite definición con scope propio para sus miembros.  
- **Expresiones**: validación en operaciones aritméticas, lógicas, ternarias, indexación y llamadas a funciones.  
- Incluye:
  - `loop_depth` para validar `break`/`continue`.  
  - Inferencia de tipos en inicializaciones.  
  - Registro de errores acumulados para reportes finales.  

---

## 2) Flujo General del Compilador

1. **Parsing (ANTLR)** → se genera el árbol sintáctico con la gramática `Compiscript.g4`.  
2. **Análisis semántico (`SemanticChecker`)** → recorre el árbol, construye símbolos y valida semántica.  
3. **Visualización (`treeviz.py`)** → genera un árbol SVG para el IDE.  
4. **Ejecución/Reporte** → `Driver.py` integra todo y muestra resultados (Nitido o lista de errores).  
5. **Modo interactivo** → `streamlit run ide/app.py` abre un entorno gráfico para pruebas.

---

**Autores:** Hugo Eduardo Rivas Fajardo - 22500, Alexis Mesias Flores - 22562,  Mauricio Julio Rodrigo Lemus Guzman - 22461
