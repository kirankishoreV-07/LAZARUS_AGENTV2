"""
Lazarus Engine — Phase 1: AST Parser & Code Intelligence
=========================================================
Extracts structural information from source files using AST parsing.
Supports Python, JavaScript, TypeScript, JSX, TSX.

Produces a FileAnalysis for each file containing:
  - Functions (name, args, return type, line range, decorators)
  - Classes (name, bases, methods, properties)
  - Imports (module, imported names, is_relative)
  - Exports (name, kind)
  - API routes and endpoints
  - Schema/model definitions
  - Global variables and constants
  - Complexity score
"""

import ast
import re
import os
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Set, Dict, Tuple

logger = logging.getLogger('lazarus.ast_parser')


# ══════════════════════════════════════════════════════════════
# DATA STRUCTURES
# ══════════════════════════════════════════════════════════════

@dataclass
class ImportInfo:
    """Represents a single import statement."""
    module: str             # e.g., 'os.path' or 'react'
    names: List[str]        # e.g., ['join', 'dirname'] or ['useState']
    is_relative: bool       # True for relative imports (from . import x)
    alias: Optional[str] = None  # import x as alias
    raw_line: str = ""      # Original import line

@dataclass
class FunctionInfo:
    """Represents a function or method definition."""
    name: str
    args: List[str]         # Parameter names
    return_type: Optional[str] = None
    decorators: List[str] = field(default_factory=list)
    is_async: bool = False
    is_method: bool = False
    line_start: int = 0
    line_end: int = 0
    complexity: int = 1     # Cyclomatic complexity estimate
    calls: List[str] = field(default_factory=list)  # Functions called inside

@dataclass
class ClassInfo:
    """Represents a class definition."""
    name: str
    bases: List[str]        # Base classes
    methods: List[FunctionInfo] = field(default_factory=list)
    properties: List[str] = field(default_factory=list)
    decorators: List[str] = field(default_factory=list)
    line_start: int = 0
    line_end: int = 0

@dataclass
class ExportInfo:
    """Represents an exported symbol (JS/TS)."""
    name: str
    kind: str               # 'function', 'class', 'const', 'default', 'type', 'interface'
    is_default: bool = False

@dataclass
class RouteInfo:
    """Represents an API route/endpoint."""
    method: str             # GET, POST, PUT, DELETE, etc.
    path: str               # e.g., '/api/users'
    handler: str            # Function name
    line: int = 0

@dataclass
class FileAnalysis:
    """Complete structural analysis of a source file."""
    path: str
    language: str           # 'python', 'javascript', 'typescript', etc.
    imports: List[ImportInfo] = field(default_factory=list)
    functions: List[FunctionInfo] = field(default_factory=list)
    classes: List[ClassInfo] = field(default_factory=list)
    exports: List[ExportInfo] = field(default_factory=list)
    routes: List[RouteInfo] = field(default_factory=list)
    global_vars: List[str] = field(default_factory=list)
    schemas: List[str] = field(default_factory=list)      # Model/Schema names
    frameworks: Set[str] = field(default_factory=set)       # Detected frameworks
    complexity_score: float = 0.0
    line_count: int = 0
    has_entrypoint: bool = False
    error: Optional[str] = None  # If parsing failed

    @property
    def all_imported_modules(self) -> Set[str]:
        """Get all imported module names (top-level)."""
        modules = set()
        for imp in self.imports:
            top = imp.module.split('.')[0] if imp.module else ''
            if top and not imp.is_relative:
                modules.add(top)
        return modules

    @property
    def all_exported_names(self) -> Set[str]:
        """Get all exported symbol names."""
        return {e.name for e in self.exports}

    @property
    def all_defined_names(self) -> Set[str]:
        """Get all locally defined symbol names."""
        names = set()
        names.update(f.name for f in self.functions)
        names.update(c.name for c in self.classes)
        names.update(self.global_vars)
        return names

    def summary(self) -> str:
        """One-line summary for cross-batch context."""
        parts = []
        if self.classes:
            parts.append(f"classes: {', '.join(c.name for c in self.classes)}")
        if self.functions:
            fns = [f.name for f in self.functions if not f.is_method]
            if fns:
                parts.append(f"functions: {', '.join(fns[:10])}")
        if self.exports:
            parts.append(f"exports: {', '.join(e.name for e in self.exports[:10])}")
        if self.routes:
            parts.append(f"routes: {', '.join(r.method + ' ' + r.path for r in self.routes[:5])}")
        if self.frameworks:
            parts.append(f"frameworks: {', '.join(self.frameworks)}")
        return f"[{self.language}] {' | '.join(parts)}" if parts else f"[{self.language}] (no significant symbols)"


# ══════════════════════════════════════════════════════════════
# LANGUAGE DETECTION
# ══════════════════════════════════════════════════════════════

def detect_language(path: str) -> str:
    """Detect programming language from file extension."""
    ext = os.path.splitext(path)[1].lower()
    lang_map = {
        '.py': 'python',
        '.js': 'javascript', '.mjs': 'javascript', '.cjs': 'javascript',
        '.ts': 'typescript',
        '.tsx': 'typescriptx',
        '.jsx': 'javascriptx',
        '.vue': 'vue',
        '.svelte': 'svelte',
        '.rb': 'ruby',
        '.go': 'go',
        '.java': 'java',
        '.php': 'php',
        '.rs': 'rust',
        '.c': 'c', '.h': 'c',
        '.cpp': 'cpp', '.cc': 'cpp', '.hpp': 'cpp',
        '.cs': 'csharp',
        '.swift': 'swift',
        '.kt': 'kotlin',
        '.dart': 'dart',
        '.html': 'html', '.htm': 'html',
        '.css': 'css', '.scss': 'scss', '.sass': 'sass', '.less': 'less',
        '.json': 'json',
        '.yaml': 'yaml', '.yml': 'yaml',
        '.toml': 'toml',
        '.xml': 'xml',
        '.sql': 'sql',
        '.prisma': 'prisma',
        '.graphql': 'graphql', '.gql': 'graphql',
        '.md': 'markdown', '.mdx': 'mdx',
        '.sh': 'shell', '.bash': 'shell',
        '.dockerfile': 'dockerfile',
    }
    filename = os.path.basename(path).lower()
    if filename == 'dockerfile':
        return 'dockerfile'
    return lang_map.get(ext, 'unknown')


# ══════════════════════════════════════════════════════════════
# PYTHON AST PARSER
# ══════════════════════════════════════════════════════════════

def _get_decorator_names(decorator_list) -> List[str]:
    """Extract decorator names from AST decorator list."""
    names = []
    for d in decorator_list:
        if isinstance(d, ast.Name):
            names.append(d.id)
        elif isinstance(d, ast.Attribute):
            names.append(ast.dump(d))
        elif isinstance(d, ast.Call):
            if isinstance(d.func, ast.Name):
                names.append(d.func.id)
            elif isinstance(d.func, ast.Attribute):
                # e.g., @app.route('/path')
                parts = []
                node = d.func
                while isinstance(node, ast.Attribute):
                    parts.append(node.attr)
                    node = node.value
                if isinstance(node, ast.Name):
                    parts.append(node.id)
                names.append('.'.join(reversed(parts)))
    return names


def _count_complexity(node) -> int:
    """Estimate cyclomatic complexity of an AST node."""
    count = 1
    for child in ast.walk(node):
        if isinstance(child, (ast.If, ast.While, ast.For, ast.ExceptHandler)):
            count += 1
        elif isinstance(child, ast.BoolOp):
            count += len(child.values) - 1
        elif isinstance(child, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            count += 1
    return count


def _extract_calls(node) -> List[str]:
    """Extract function call names from an AST node."""
    calls = []
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            if isinstance(child.func, ast.Name):
                calls.append(child.func.id)
            elif isinstance(child.func, ast.Attribute):
                calls.append(child.func.attr)
    return calls


def _detect_python_routes(tree: ast.Module, content: str) -> List[RouteInfo]:
    """Detect Flask/FastAPI/Django route definitions."""
    routes = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for dec in node.decorator_list:
                route_str = None
                method = 'GET'

                if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute):
                    attr = dec.func.attr
                    if attr in ('route', 'get', 'post', 'put', 'delete', 'patch'):
                        method = attr.upper() if attr != 'route' else 'GET'
                        if dec.args and isinstance(dec.args[0], ast.Constant):
                            route_str = str(dec.args[0].value)
                    # Flask: @app.route('/path', methods=['POST'])
                    if attr == 'route':
                        for kw in dec.keywords:
                            if kw.arg == 'methods' and isinstance(kw.value, ast.List):
                                for elt in kw.value.elts:
                                    if isinstance(elt, ast.Constant):
                                        method = str(elt.value)
                                        break

                if route_str:
                    routes.append(RouteInfo(
                        method=method,
                        path=route_str,
                        handler=node.name,
                        line=node.lineno
                    ))
    return routes


def _detect_python_frameworks(imports: List[ImportInfo]) -> Set[str]:
    """Detect Python frameworks from imports."""
    frameworks = set()
    fw_map = {
        'flask': 'Flask', 'django': 'Django', 'fastapi': 'FastAPI',
        'tornado': 'Tornado', 'aiohttp': 'aiohttp', 'starlette': 'Starlette',
        'pyramid': 'Pyramid', 'bottle': 'Bottle', 'sanic': 'Sanic',
        'streamlit': 'Streamlit', 'gradio': 'Gradio', 'dash': 'Dash',
        'celery': 'Celery', 'sqlalchemy': 'SQLAlchemy', 'pymongo': 'PyMongo',
        'redis': 'Redis', 'pytest': 'pytest', 'unittest': 'unittest',
        'pandas': 'Pandas', 'numpy': 'NumPy', 'tensorflow': 'TensorFlow',
        'torch': 'PyTorch', 'sklearn': 'scikit-learn', 'scipy': 'SciPy',
        'pydantic': 'Pydantic', 'marshmallow': 'Marshmallow',
        'requests': 'requests', 'httpx': 'httpx',
    }
    for imp in imports:
        top = imp.module.split('.')[0]
        if top in fw_map:
            frameworks.add(fw_map[top])
    return frameworks


def parse_python(path: str, content: str) -> FileAnalysis:
    """Parse a Python file using the ast module."""
    analysis = FileAnalysis(path=path, language='python', line_count=content.count('\n') + 1)

    try:
        tree = ast.parse(content, filename=path)
    except SyntaxError as e:
        analysis.error = f"SyntaxError: {e}"
        # Fall back to regex-based parsing
        return _parse_python_regex_fallback(path, content, analysis)

    # ── Imports ──
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                analysis.imports.append(ImportInfo(
                    module=alias.name,
                    names=[alias.name.split('.')[-1]],
                    is_relative=False,
                    alias=alias.asname,
                    raw_line=f"import {alias.name}" + (f" as {alias.asname}" if alias.asname else "")
                ))
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ''
            is_relative = (node.level or 0) > 0
            names = [a.name for a in (node.names or [])]
            prefix = '.' * (node.level or 0)
            analysis.imports.append(ImportInfo(
                module=f"{prefix}{module}" if is_relative else module,
                names=names,
                is_relative=is_relative,
                raw_line=f"from {prefix}{module} import {', '.join(names)}"
            ))

    # ── Top-level nodes ──
    for node in ast.iter_child_nodes(tree):
        # Functions
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = [a.arg for a in node.args.args]
            ret = None
            if node.returns:
                try:
                    ret = ast.unparse(node.returns)
                except:
                    ret = str(node.returns)

            fn = FunctionInfo(
                name=node.name,
                args=args,
                return_type=ret,
                decorators=_get_decorator_names(node.decorator_list),
                is_async=isinstance(node, ast.AsyncFunctionDef),
                line_start=node.lineno,
                line_end=node.end_lineno or node.lineno,
                complexity=_count_complexity(node),
                calls=_extract_calls(node),
            )
            analysis.functions.append(fn)

        # Classes
        elif isinstance(node, ast.ClassDef):
            bases = []
            for b in node.bases:
                try:
                    bases.append(ast.unparse(b))
                except:
                    bases.append(str(b))

            cls = ClassInfo(
                name=node.name,
                bases=bases,
                decorators=_get_decorator_names(node.decorator_list),
                line_start=node.lineno,
                line_end=node.end_lineno or node.lineno,
            )

            for item in ast.iter_child_nodes(node):
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    method_args = [a.arg for a in item.args.args if a.arg != 'self']
                    ret = None
                    if item.returns:
                        try:
                            ret = ast.unparse(item.returns)
                        except:
                            pass
                    cls.methods.append(FunctionInfo(
                        name=item.name,
                        args=method_args,
                        return_type=ret,
                        decorators=_get_decorator_names(item.decorator_list),
                        is_async=isinstance(item, ast.AsyncFunctionDef),
                        is_method=True,
                        line_start=item.lineno,
                        line_end=item.end_lineno or item.lineno,
                        complexity=_count_complexity(item),
                        calls=_extract_calls(item),
                    ))
                elif isinstance(item, ast.Assign):
                    for target in item.targets:
                        if isinstance(target, ast.Name):
                            cls.properties.append(target.id)

            analysis.classes.append(cls)

            # Detect schemas/models
            for base in bases:
                if any(kw in base for kw in ['Model', 'Schema', 'Base', 'Form', 'Serializer']):
                    analysis.schemas.append(node.name)
                    break

        # Global assignments (constants, configs)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.isupper():
                    analysis.global_vars.append(target.id)

    # ── Routes ──
    analysis.routes = _detect_python_routes(tree, content)

    # ── Frameworks ──
    analysis.frameworks = _detect_python_frameworks(analysis.imports)

    # ── Entrypoint detection ──
    if 'if __name__' in content:
        analysis.has_entrypoint = True

    # ── Complexity score ──
    total = sum(f.complexity for f in analysis.functions)
    total += sum(m.complexity for c in analysis.classes for m in c.methods)
    analysis.complexity_score = total / max(1, len(analysis.functions) + sum(len(c.methods) for c in analysis.classes))

    return analysis


def _parse_python_regex_fallback(path: str, content: str, analysis: FileAnalysis) -> FileAnalysis:
    """Regex-based fallback for files with syntax errors."""
    # Imports
    for m in re.finditer(r'^(?:from\s+(\S+)\s+)?import\s+(.+)$', content, re.MULTILINE):
        module = m.group(1) or m.group(2).split('.')[0]
        names = [n.strip().split(' as ')[0] for n in m.group(2).split(',')]
        analysis.imports.append(ImportInfo(
            module=module, names=names,
            is_relative=module.startswith('.'),
            raw_line=m.group(0)
        ))

    # Functions
    for m in re.finditer(r'^(async\s+)?def\s+(\w+)\s*\(([^)]*)\)', content, re.MULTILINE):
        analysis.functions.append(FunctionInfo(
            name=m.group(2),
            args=[a.strip().split(':')[0].split('=')[0].strip() for a in m.group(3).split(',') if a.strip()],
            is_async=bool(m.group(1)),
        ))

    # Classes
    for m in re.finditer(r'^class\s+(\w+)\s*(?:\(([^)]*)\))?:', content, re.MULTILINE):
        bases = [b.strip() for b in (m.group(2) or '').split(',') if b.strip()]
        analysis.classes.append(ClassInfo(name=m.group(1), bases=bases))

    return analysis


# ══════════════════════════════════════════════════════════════
# JAVASCRIPT / TYPESCRIPT REGEX PARSER
# ══════════════════════════════════════════════════════════════

def parse_javascript(path: str, content: str) -> FileAnalysis:
    """
    Parse JavaScript/TypeScript files using regex patterns.
    (No JS AST available in Python — regex is robust enough for structural analysis.)
    """
    lang = detect_language(path)
    analysis = FileAnalysis(path=path, language=lang, line_count=content.count('\n') + 1)

    try:
        _parse_js_imports(content, analysis)
        _parse_js_functions(content, analysis)
        _parse_js_classes(content, analysis)
        _parse_js_exports(content, analysis)
        _parse_js_routes(content, analysis)
        _parse_js_frameworks(analysis)
        _detect_js_schemas(content, analysis)

        # Entrypoint detection
        if any(pattern in content for pattern in [
            'createServer', 'app.listen', 'server.listen',
            'ReactDOM.render', 'createRoot', 'hydrateRoot',
            'export default function', 'module.exports',
        ]):
            analysis.has_entrypoint = True

    except Exception as e:
        analysis.error = f"Parse error: {e}"

    return analysis


def _parse_js_imports(content: str, analysis: FileAnalysis):
    """Parse ES6 imports and require() calls."""
    # ES6: import X from 'module'
    for m in re.finditer(
        r"""import\s+(?:(?:(\w+)(?:\s*,\s*)?)?(?:\{([^}]+)\})?\s+from\s+)?['"]([^'"]+)['"]""",
        content
    ):
        default_name = m.group(1)
        named = m.group(2)
        module = m.group(3)
        names = []
        if default_name:
            names.append(default_name)
        if named:
            names.extend(n.strip().split(' as ')[0].strip() for n in named.split(',') if n.strip())
        if not names:
            names = ['*']  # Side-effect import

        is_relative = module.startswith('.')
        analysis.imports.append(ImportInfo(
            module=module, names=names,
            is_relative=is_relative, raw_line=m.group(0)
        ))

    # import * as X from 'module'
    for m in re.finditer(r"""import\s+\*\s+as\s+(\w+)\s+from\s+['"]([^'"]+)['"]""", content):
        analysis.imports.append(ImportInfo(
            module=m.group(2), names=['*'],
            is_relative=m.group(2).startswith('.'),
            alias=m.group(1), raw_line=m.group(0)
        ))

    # CommonJS: require('module')
    for m in re.finditer(r"""(?:const|let|var)\s+(?:(\w+)|\{([^}]+)\})\s*=\s*require\s*\(\s*['"]([^'"]+)['"]\s*\)""", content):
        default_name = m.group(1)
        destructured = m.group(2)
        module = m.group(3)
        names = []
        if default_name:
            names.append(default_name)
        if destructured:
            names.extend(n.strip().split(':')[0].strip() for n in destructured.split(',') if n.strip())

        analysis.imports.append(ImportInfo(
            module=module, names=names,
            is_relative=module.startswith('.'),
            raw_line=m.group(0)
        ))


def _parse_js_functions(content: str, analysis: FileAnalysis):
    """Parse function declarations and arrow functions."""
    # Regular functions: function name(args)
    for m in re.finditer(
        r'^[\t ]*(export\s+(?:default\s+)?)?(async\s+)?function\s*\*?\s+(\w+)\s*\(([^)]*)\)',
        content, re.MULTILINE
    ):
        args = [a.strip().split(':')[0].split('=')[0].strip()
                for a in m.group(4).split(',') if a.strip()]
        analysis.functions.append(FunctionInfo(
            name=m.group(3), args=args,
            is_async=bool(m.group(2)),
        ))

    # Arrow functions: const name = (args) => / const name = async (args) =>
    for m in re.finditer(
        r'^[\t ]*(export\s+(?:default\s+)?)?(?:const|let|var)\s+(\w+)\s*(?::\s*\w+)?\s*=\s*(async\s+)?(?:\([^)]*\)|(\w+))\s*(?::\s*\w+)?\s*=>',
        content, re.MULTILINE
    ):
        analysis.functions.append(FunctionInfo(
            name=m.group(2), args=[],
            is_async=bool(m.group(3)),
        ))

    # React components: const Name = () => { / function Name() {
    # (already captured above, but flag them)
    for fn in analysis.functions:
        if fn.name and fn.name[0].isupper():
            fn.decorators.append('component')


def _parse_js_classes(content: str, analysis: FileAnalysis):
    """Parse class declarations."""
    for m in re.finditer(
        r'^[\t ]*(export\s+(?:default\s+)?)?class\s+(\w+)(?:\s+extends\s+(\w+(?:\.\w+)*))?',
        content, re.MULTILINE
    ):
        bases = [m.group(3)] if m.group(3) else []
        analysis.classes.append(ClassInfo(name=m.group(2), bases=bases))

    # TypeScript interfaces (treat as classes for dependency tracking)
    if analysis.language in ('typescript', 'typescriptx'):
        for m in re.finditer(
            r'^[\t ]*(export\s+)?interface\s+(\w+)(?:\s+extends\s+([^{]+))?',
            content, re.MULTILINE
        ):
            bases = [b.strip() for b in (m.group(3) or '').split(',') if b.strip()]
            analysis.classes.append(ClassInfo(name=m.group(2), bases=bases))

        # TypeScript type aliases
        for m in re.finditer(r'^[\t ]*(export\s+)?type\s+(\w+)', content, re.MULTILINE):
            analysis.global_vars.append(m.group(2))


def _parse_js_exports(content: str, analysis: FileAnalysis):
    """Parse export statements."""
    # export default
    for m in re.finditer(
        r'export\s+default\s+(?:(?:async\s+)?function\s+)?(\w+)',
        content
    ):
        analysis.exports.append(ExportInfo(
            name=m.group(1), kind='default', is_default=True
        ))

    # export { name1, name2 }
    for m in re.finditer(r'export\s*\{([^}]+)\}', content):
        for name in m.group(1).split(','):
            name = name.strip().split(' as ')[0].strip()
            if name:
                analysis.exports.append(ExportInfo(name=name, kind='named'))

    # export const/let/var/function/class
    for m in re.finditer(
        r'export\s+(const|let|var|function|class|async\s+function|interface|type|enum)\s+(\w+)',
        content
    ):
        kind = m.group(1).replace('async ', '').strip()
        analysis.exports.append(ExportInfo(name=m.group(2), kind=kind))

    # module.exports
    for m in re.finditer(r'module\.exports\s*=\s*(?:(\w+)|\{([^}]+)\})', content):
        if m.group(1):
            analysis.exports.append(ExportInfo(name=m.group(1), kind='default', is_default=True))
        elif m.group(2):
            for name in m.group(2).split(','):
                name = name.strip().split(':')[0].strip()
                if name:
                    analysis.exports.append(ExportInfo(name=name, kind='named'))


def _parse_js_routes(content: str, analysis: FileAnalysis):
    """Parse Express/Next.js/Fastify route definitions."""
    # Express: app.get('/path', handler) or router.post('/path', ...)
    for m in re.finditer(
        r'(?:app|router|server)\.(get|post|put|delete|patch|options|all)\s*\(\s*[\'"]([^\'"]+)[\'"]',
        content, re.IGNORECASE
    ):
        analysis.routes.append(RouteInfo(
            method=m.group(1).upper(),
            path=m.group(2),
            handler='anonymous',
        ))

    # Next.js App Router: export async function GET/POST/PUT/DELETE
    for m in re.finditer(
        r'export\s+(?:async\s+)?function\s+(GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS)\s*\(',
        content
    ):
        # Path inferred from file path
        route_path = _infer_nextjs_route(analysis.path) if hasattr(analysis, 'path') else '/'
        analysis.routes.append(RouteInfo(
            method=m.group(1), path=route_path, handler=m.group(1)
        ))


def _infer_nextjs_route(file_path: str) -> str:
    """Infer Next.js route from file path."""
    # app/api/users/route.ts -> /api/users
    path = file_path.replace('\\', '/')
    if '/app/' in path:
        route_part = path.split('/app/')[-1]
        route_part = re.sub(r'/route\.\w+$', '', route_part)
        route_part = re.sub(r'/page\.\w+$', '', route_part)
        route_part = re.sub(r'\[(\w+)\]', r':\1', route_part)  # [id] -> :id
        return '/' + route_part
    return '/'


def _parse_js_frameworks(analysis: FileAnalysis):
    """Detect JS/TS frameworks from imports."""
    fw_map = {
        'react': 'React', 'next': 'Next.js', 'vue': 'Vue',
        'svelte': 'Svelte', 'angular': 'Angular', 'express': 'Express',
        'fastify': 'Fastify', 'koa': 'Koa', 'hapi': 'Hapi',
        'nestjs': 'NestJS', '@nestjs': 'NestJS',
        'prisma': 'Prisma', '@prisma': 'Prisma',
        'mongoose': 'Mongoose', 'sequelize': 'Sequelize',
        'typeorm': 'TypeORM', 'drizzle-orm': 'Drizzle',
        'tailwindcss': 'Tailwind', 'styled-components': 'styled-components',
        '@mui': 'MUI', '@chakra-ui': 'Chakra UI',
        'redux': 'Redux', '@reduxjs': 'Redux Toolkit',
        'zustand': 'Zustand', 'jotai': 'Jotai', 'recoil': 'Recoil',
        'axios': 'Axios', 'socket.io': 'Socket.IO',
        'jest': 'Jest', 'mocha': 'Mocha', 'vitest': 'Vitest',
        'three': 'Three.js', 'd3': 'D3.js',
        'gatsby': 'Gatsby', 'remix': 'Remix', 'astro': 'Astro',
    }
    for imp in analysis.imports:
        top = imp.module.split('/')[0]
        if top in fw_map:
            analysis.frameworks.add(fw_map[top])


def _detect_js_schemas(content: str, analysis: FileAnalysis):
    """Detect schema/model definitions in JS/TS."""
    # Prisma models
    for m in re.finditer(r'model\s+(\w+)\s*\{', content):
        analysis.schemas.append(m.group(1))

    # Mongoose schemas
    for m in re.finditer(r'(?:const|let)\s+(\w+)Schema\s*=\s*new\s+(?:mongoose\.)?Schema', content):
        analysis.schemas.append(m.group(1))

    # Zod schemas
    for m in re.finditer(r'(?:const|let)\s+(\w+)\s*=\s*z\.\w+', content):
        analysis.schemas.append(m.group(1))

    # TypeScript interfaces named *Model or *Schema
    for m in re.finditer(r'(?:interface|type)\s+(\w+(?:Model|Schema|Entity|DTO))\b', content):
        analysis.schemas.append(m.group(1))


# ══════════════════════════════════════════════════════════════
# CONFIG / DATA FILE PARSERS (Lightweight)
# ══════════════════════════════════════════════════════════════

def parse_config_file(path: str, content: str) -> FileAnalysis:
    """Lightweight parser for JSON, YAML, TOML, etc."""
    lang = detect_language(path)
    analysis = FileAnalysis(path=path, language=lang, line_count=content.count('\n') + 1)
    filename = os.path.basename(path).lower()

    # package.json: extract dependencies
    if filename == 'package.json':
        try:
            import json
            pkg = json.loads(content)
            deps = list(pkg.get('dependencies', {}).keys())
            dev_deps = list(pkg.get('devDependencies', {}).keys())
            for dep in deps + dev_deps:
                analysis.imports.append(ImportInfo(
                    module=dep, names=[dep], is_relative=False,
                    raw_line=f"(package.json dependency)"
                ))
            if 'scripts' in pkg:
                for name in pkg['scripts']:
                    analysis.global_vars.append(f"script:{name}")
        except Exception:
            pass

    # requirements.txt
    elif filename in ('requirements.txt', 'requirements.in'):
        for line in content.split('\n'):
            line = line.strip()
            if line and not line.startswith('#') and not line.startswith('-'):
                pkg = re.split(r'[>=<!\[]', line)[0].strip()
                if pkg:
                    analysis.imports.append(ImportInfo(
                        module=pkg, names=[pkg], is_relative=False,
                        raw_line=line
                    ))

    # .env files: detect env var names
    elif filename.startswith('.env'):
        for line in content.split('\n'):
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                var_name = line.split('=')[0].strip()
                analysis.global_vars.append(var_name)

    return analysis


# ══════════════════════════════════════════════════════════════
# HTML/CSS PARSERS (Lightweight)
# ══════════════════════════════════════════════════════════════

def parse_html(path: str, content: str) -> FileAnalysis:
    """Lightweight HTML parser — extract scripts, stylesheets, links."""
    analysis = FileAnalysis(path=path, language='html', line_count=content.count('\n') + 1)

    # Script sources
    for m in re.finditer(r'<script[^>]*\bsrc=["\']([^"\']+)["\']', content):
        analysis.imports.append(ImportInfo(
            module=m.group(1), names=['script'], is_relative=not m.group(1).startswith('http'),
            raw_line=m.group(0)
        ))

    # Stylesheet links
    for m in re.finditer(r'<link[^>]*\bhref=["\']([^"\']+\.css[^"\']*)["\']', content):
        analysis.imports.append(ImportInfo(
            module=m.group(1), names=['stylesheet'], is_relative=not m.group(1).startswith('http'),
            raw_line=m.group(0)
        ))

    return analysis


def parse_css(path: str, content: str) -> FileAnalysis:
    """Lightweight CSS parser — extract @import statements."""
    analysis = FileAnalysis(path=path, language='css', line_count=content.count('\n') + 1)

    for m in re.finditer(r'@import\s+(?:url\s*\()?["\']([^"\']+)["\']', content):
        analysis.imports.append(ImportInfo(
            module=m.group(1), names=['stylesheet'], is_relative=not m.group(1).startswith('http'),
            raw_line=m.group(0)
        ))

    return analysis


# ══════════════════════════════════════════════════════════════
# MAIN DISPATCHER
# ══════════════════════════════════════════════════════════════

def analyze_file(path: str, content: str) -> FileAnalysis:
    """
    Analyze a single file and return its structural analysis.
    Dispatches to the appropriate language-specific parser.
    """
    lang = detect_language(path)

    if lang == 'python':
        return parse_python(path, content)
    elif lang in ('javascript', 'typescript', 'typescriptx', 'javascriptx'):
        return parse_javascript(path, content)
    elif lang in ('json', 'yaml', 'toml'):
        return parse_config_file(path, content)
    elif lang == 'html':
        return parse_html(path, content)
    elif lang in ('css', 'scss', 'sass', 'less'):
        return parse_css(path, content)
    else:
        # For unsupported languages, return basic analysis
        analysis = FileAnalysis(path=path, language=lang, line_count=content.count('\n') + 1)
        # Try basic import detection
        for m in re.finditer(r'(?:import|require|include|use)\s+["\']?(\S+)', content):
            analysis.imports.append(ImportInfo(
                module=m.group(1).strip("'\";"), names=['*'],
                is_relative=m.group(1).startswith('.'),
                raw_line=m.group(0)
            ))
        return analysis


def analyze_all_files(files: List[Tuple[str, str]]) -> Dict[str, FileAnalysis]:
    """
    Analyze all files and return a dict mapping path -> FileAnalysis.

    Args:
        files: List of (path, content) tuples

    Returns:
        Dict mapping file path to FileAnalysis
    """
    results = {}
    for path, content in files:
        try:
            results[path] = analyze_file(path, content)
        except Exception as e:
            logger.error(f"Failed to analyze {path}: {e}")
            results[path] = FileAnalysis(path=path, language=detect_language(path), error=str(e))
    return results
