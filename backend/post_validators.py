"""
Lazarus Engine — Phase 2: Post-Generation Validators
======================================================
Validates that generated code across all batches is coherent:

  1. Frontend-Backend Route Validation
     - Scans frontend code for fetch/axios calls
     - Compares against backend-defined routes
     - Flags mismatches BEFORE sandbox execution

  2. Dependency Completeness Check
     - Cross-references generated imports against package.json/requirements.txt
     - Detects missing Node.js AND Python packages
     - Flags missing packages that would cause runtime crashes

  3. Type Coherence Validation
     - Compares TypeScript interfaces against Pydantic/backend models
     - Detects field name/type mismatches between frontend and backend schemas
     - Warns about missing fields that will cause runtime errors

These validators run AFTER all batches complete but BEFORE sandbox execution,
giving us a chance to inject fixes or warn the user.
"""

import re
import os
import json
import logging
from typing import Dict, List, Set, Tuple, Optional
from dataclasses import dataclass, field

logger = logging.getLogger('lazarus.validators')


# ══════════════════════════════════════════════════════════════
# VALIDATION RESULT STRUCTURES
# ══════════════════════════════════════════════════════════════

@dataclass
class ValidationIssue:
    """A single validation issue found in generated code."""
    severity: str           # 'critical', 'warning', 'info'
    category: str           # 'route_mismatch', 'missing_dep', 'type_mismatch'
    message: str
    file: str = ""
    fix_suggestion: str = ""


@dataclass
class ValidationReport:
    """Aggregated report from all validators."""
    issues: List[ValidationIssue] = field(default_factory=list)
    route_mismatches: int = 0
    missing_deps: int = 0
    type_mismatches: int = 0

    @property
    def has_critical(self) -> bool:
        return any(i.severity == 'critical' for i in self.issues)

    @property
    def total_issues(self) -> int:
        return len(self.issues)

    def summary(self) -> str:
        """Human-readable summary for logging."""
        if not self.issues:
            return "✅ All post-generation validations passed"
        lines = [f"⚠ Post-Generation Validation: {self.total_issues} issue(s) found"]
        if self.route_mismatches:
            lines.append(f"  🔗 Route mismatches: {self.route_mismatches}")
        if self.missing_deps:
            lines.append(f"  📦 Missing dependencies: {self.missing_deps}")
        if self.type_mismatches:
            lines.append(f"  🔤 Type mismatches: {self.type_mismatches}")
        for issue in self.issues[:10]:
            icon = "❌" if issue.severity == 'critical' else "⚠️" if issue.severity == 'warning' else "ℹ️"
            lines.append(f"  {icon} [{issue.category}] {issue.message}")
            if issue.fix_suggestion:
                lines.append(f"     💡 Fix: {issue.fix_suggestion}")
        if len(self.issues) > 10:
            lines.append(f"  ... +{len(self.issues) - 10} more issues")
        return "\n".join(lines)

    def prompt_injection(self) -> str:
        """
        Generate a prompt section to inject into a recovery/fix batch
        so Gemini can auto-fix the issues.
        """
        if not self.issues:
            return ""
        lines = [
            "╔══ ⚠ POST-GENERATION VALIDATION ISSUES ══╗",
            "The following issues were detected in your generated code.",
            "FIX ALL OF THEM in the files you regenerate:\n",
        ]
        for issue in self.issues:
            lines.append(f"  [{issue.severity.upper()}] {issue.message}")
            if issue.fix_suggestion:
                lines.append(f"  → FIX: {issue.fix_suggestion}")
            if issue.file:
                lines.append(f"  → File: {issue.file}")
            lines.append("")
        lines.append("╚════════════════════════════════════════════╝")
        return "\n".join(lines)


# ══════════════════════════════════════════════════════════════
# 1. FRONTEND-BACKEND ROUTE VALIDATION
# ══════════════════════════════════════════════════════════════

def validate_routes(
    generated_files: List[Dict],
    project_context=None,
) -> List[ValidationIssue]:
    """
    Scan frontend files for API calls (fetch, axios, etc.) and validate
    they match routes defined in backend files.

    Args:
        generated_files: All generated files [{filename, content}]
        project_context: ProjectContext from context_extraction (if available)

    Returns:
        List of ValidationIssue for mismatched routes
    """
    issues = []

    # Step 1: Collect all backend-defined routes
    backend_routes: Set[Tuple[str, str]] = set()  # (METHOD, /path)
    backend_route_patterns: List[Tuple[str, str]] = []  # For parameterized matching

    # From project context (most reliable source)
    if project_context and hasattr(project_context, 'api_contracts'):
        for contract in project_context.api_contracts:
            backend_routes.add((contract.method.upper(), _normalize_route(contract.path)))
            backend_route_patterns.append((contract.method.upper(), contract.path))

    # Also scan generated backend files for routes
    backend_extensions = {'.py', '.js', '.ts', '.mjs'}
    frontend_extensions = {'.jsx', '.tsx', '.vue', '.svelte'}
    frontend_indicators = {'react', 'vue', 'svelte', 'next', 'components', 'pages', 'app', 'views', 'screens'}

    for f in generated_files:
        fname = f.get('filename', '')
        content = f.get('content', '')
        ext = os.path.splitext(fname)[1].lower()

        # Detect backend route definitions
        if ext in backend_extensions:
            # Express/Koa/Hono routes
            for m in re.finditer(
                r"""(?:app|router|server)\.(get|post|put|delete|patch)\s*\(\s*['"`]([^'"`]+)['"`]""",
                content, re.IGNORECASE
            ):
                method = m.group(1).upper()
                path = _normalize_route(m.group(2))
                backend_routes.add((method, path))

            # Python decorator routes
            for m in re.finditer(
                r"""@(?:app|router|bp|api)\.(get|post|put|delete|patch|route)\s*\(\s*['"]([^'"]+)['"]""",
                content
            ):
                method = m.group(1).upper()
                if method == 'ROUTE':
                    method = 'GET'
                path = _normalize_route(m.group(2))
                backend_routes.add((method, path))

            # FastAPI with methods= kwarg
            for m in re.finditer(
                r"""@(?:app|router)\.api_route\s*\(\s*['"]([^'"]+)['"].*?methods\s*=\s*\[([^\]]+)\]""",
                content, re.DOTALL
            ):
                path = _normalize_route(m.group(1))
                for method_str in re.findall(r"'(\w+)'|\"(\w+)\"", m.group(2)):
                    method = (method_str[0] or method_str[1]).upper()
                    backend_routes.add((method, path))

    if not backend_routes:
        return issues  # No backend routes found — nothing to validate

    # Step 2: Scan frontend files for API calls
    frontend_calls: List[Tuple[str, str, str, int]] = []  # (method, path, file, line)

    for f in generated_files:
        fname = f.get('filename', '')
        content = f.get('content', '')
        ext = os.path.splitext(fname)[1].lower()

        # Determine if this is a frontend file
        is_frontend = (
            ext in frontend_extensions or
            any(indicator in fname.lower() for indicator in frontend_indicators) or
            'import React' in content or
            'from react' in content.lower() or
            'createApp' in content or
            'use client' in content or
            'use server' in content
        )

        if not is_frontend:
            continue

        lines = content.split('\n')
        for line_num, line in enumerate(lines, 1):
            # fetch() calls
            for m in re.finditer(
                r"""fetch\s*\(\s*[`'"]((?:https?://[^/]*)?/[^'"`\s$]+)['"`]""",
                line
            ):
                url = m.group(1)
                # Strip protocol/host if present
                url = re.sub(r'^https?://[^/]+', '', url)
                method = _infer_method_from_context(line, lines, line_num)
                frontend_calls.append((method, _normalize_route(url), fname, line_num))

            # Template literal fetch: fetch(`/api/...${id}`)
            for m in re.finditer(
                r"""fetch\s*\(\s*`([^`]+)`""",
                line
            ):
                url = m.group(1)
                url = re.sub(r'^https?://[^/]+', '', url)
                # Replace ${...} with :param placeholder
                url = re.sub(r'\$\{[^}]+\}', ':param', url)
                if url.startswith('/'):
                    method = _infer_method_from_context(line, lines, line_num)
                    frontend_calls.append((method, _normalize_route(url), fname, line_num))

            # axios calls: axios.get('/api/...'), axios.post('/api/...')
            for m in re.finditer(
                r"""axios\.(get|post|put|delete|patch)\s*\(\s*[`'"]([^'"`\s]+)['"`]""",
                line, re.IGNORECASE
            ):
                method = m.group(1).upper()
                url = m.group(2)
                url = re.sub(r'^https?://[^/]+', '', url)
                url = re.sub(r'\$\{[^}]+\}', ':param', url)
                if url.startswith('/'):
                    frontend_calls.append((method, _normalize_route(url), fname, line_num))

            # Generic API helper: api.get('/users'), apiClient.post('/auth/login')
            for m in re.finditer(
                r"""(?:api|apiClient|client|http)\.(get|post|put|delete|patch)\s*\(\s*[`'"]([^'"`\s]+)['"`]""",
                line, re.IGNORECASE
            ):
                method = m.group(1).upper()
                url = m.group(2)
                url = re.sub(r'\$\{[^}]+\}', ':param', url)
                if url.startswith('/'):
                    frontend_calls.append((method, _normalize_route(url), fname, line_num))

            # String concatenation fetch: fetch('/api/users/' + id, ...)
            for m in re.finditer(
                r"""fetch\s*\(\s*['"]([^'"]+)['"]\s*\+""",
                line
            ):
                url = m.group(1).rstrip('/')
                # The concatenated part is a param
                if url.startswith('/'):
                    url = url + '/:param'
                    method = _infer_method_from_context(line, lines, line_num)
                    frontend_calls.append((method, _normalize_route(url), fname, line_num))

    if not frontend_calls:
        return issues  # No frontend API calls found

    # Step 3: Cross-reference frontend calls against backend routes
    for method, path, file, line_num in frontend_calls:
        exact_match = (method, path) in backend_routes
        path_only_match = any(_paths_match(path, rp) for _, rp in backend_routes) if not exact_match else False
        
        if exact_match:
            continue  # Perfect match — no issue
        
        if path_only_match:
            # Path exists but with different method — softer warning
            available_methods = sorted({rm for rm, rp in backend_routes if _paths_match(path, rp)})
            issues.append(ValidationIssue(
                severity='warning',
                category='route_mismatch',
                message=(
                    f"Frontend calls {method} {path} (line {line_num}) but backend only has "
                    f"{', '.join(available_methods)} for that path"
                ),
                file=file,
                fix_suggestion=f"Add {method} handler for {path} in the backend, or change frontend to use {available_methods[0]}",
            ))
        else:
            # No match at all — critical
            closest = _find_closest_route(method, path, backend_routes)
            suggestion = f"Did you mean '{closest}'?" if closest else "Add this route to the backend"
            issues.append(ValidationIssue(
                severity='warning',
                category='route_mismatch',
                message=f"Frontend calls {method} {path} (line {line_num}) but no matching backend route exists",
                file=file,
                fix_suggestion=suggestion,
            ))

    return issues


def _normalize_route(path: str) -> str:
    """Normalize a route path for comparison."""
    # Strip trailing slash
    path = path.rstrip('/')
    if not path:
        path = '/'
    # Normalize param formats: :id, <id>, {id} → :param
    path = re.sub(r':[a-zA-Z_]\w*', ':param', path)
    path = re.sub(r'<[^>]+>', ':param', path)
    path = re.sub(r'\{[^}]+\}', ':param', path)
    return path.lower()


def _infer_method_from_context(line: str, lines: List[str], line_num: int) -> str:
    """Infer HTTP method from fetch() call context."""
    # Check current line and surrounding lines for method
    context = line
    if line_num > 1:
        context = lines[line_num - 2] + '\n' + context
    if line_num < len(lines):
        context = context + '\n' + lines[line_num - 1] if line_num < len(lines) else context

    method_match = re.search(r"""method\s*:\s*['"]?(GET|POST|PUT|DELETE|PATCH)['"]?""", context, re.IGNORECASE)
    if method_match:
        return method_match.group(1).upper()

    # Default: GET for fetch without method
    return 'GET'


def _route_matches_any(method: str, path: str, routes: Set[Tuple[str, str]]) -> bool:
    """Check if a frontend call matches any backend route (with param flexibility)."""
    # Exact match
    if (method, path) in routes:
        return True

    # Try matching with ANY method (some frontends use different methods)
    for route_method, route_path in routes:
        if _paths_match(path, route_path):
            return True

    return False


def _paths_match(frontend_path: str, backend_path: str) -> bool:
    """Check if two normalized paths match (handling param segments)."""
    f_parts = frontend_path.strip('/').split('/')
    b_parts = backend_path.strip('/').split('/')

    if len(f_parts) != len(b_parts):
        return False

    for fp, bp in zip(f_parts, b_parts):
        if fp == bp:
            continue
        if fp == ':param' or bp == ':param':
            continue  # Param segments always match
        return False
    return True


def _find_closest_route(method: str, path: str, routes: Set[Tuple[str, str]]) -> Optional[str]:
    """Find the closest matching route for a suggestion."""
    path_parts = set(path.strip('/').split('/'))
    best_match = None
    best_score = 0

    for route_method, route_path in routes:
        route_parts = set(route_path.strip('/').split('/'))
        overlap = len(path_parts & route_parts)
        if overlap > best_score:
            best_score = overlap
            best_match = f"{route_method} {route_path}"

    return best_match if best_score > 0 else None


# ══════════════════════════════════════════════════════════════
# 2. DEPENDENCY COMPLETENESS VALIDATION
# ══════════════════════════════════════════════════════════════

# Exhaustive Node.js import→package mapping
NODE_PACKAGE_MAP = {
    # Core frameworks
    'express': 'express',
    'koa': 'koa',
    'hapi': '@hapi/hapi',
    'fastify': 'fastify',
    'hono': 'hono',
    'next': 'next',
    'nuxt': 'nuxt',

    # React ecosystem
    'react': 'react',
    'react-dom': 'react-dom',
    'react-router-dom': 'react-router-dom',
    'react-query': '@tanstack/react-query',
    '@tanstack/react-query': '@tanstack/react-query',
    'zustand': 'zustand',
    'jotai': 'jotai',
    'recoil': 'recoil',

    # Database
    'mongoose': 'mongoose',
    'sequelize': 'sequelize',
    'prisma': '@prisma/client',
    '@prisma/client': '@prisma/client',
    'typeorm': 'typeorm',
    'knex': 'knex',
    'pg': 'pg',
    'mysql2': 'mysql2',
    'better-sqlite3': 'better-sqlite3',
    'redis': 'redis',
    'ioredis': 'ioredis',
    'mongodb': 'mongodb',

    # Auth
    'jsonwebtoken': 'jsonwebtoken',
    'bcrypt': 'bcrypt',
    'bcryptjs': 'bcryptjs',
    'passport': 'passport',
    'passport-jwt': 'passport-jwt',
    'passport-local': 'passport-local',
    'cookie-parser': 'cookie-parser',
    'express-session': 'express-session',
    'cors': 'cors',

    # Utilities
    'axios': 'axios',
    'lodash': 'lodash',
    'dayjs': 'dayjs',
    'moment': 'moment',
    'uuid': 'uuid',
    'dotenv': 'dotenv',
    'chalk': 'chalk',
    'winston': 'winston',
    'morgan': 'morgan',
    'multer': 'multer',
    'sharp': 'sharp',
    'nodemailer': 'nodemailer',
    'socket.io': 'socket.io',
    'ws': 'ws',
    'zod': 'zod',
    'joi': 'joi',
    'yup': 'yup',
    'class-validator': 'class-validator',
    'class-transformer': 'class-transformer',

    # Tailwind / CSS
    'tailwindcss': 'tailwindcss',
    'autoprefixer': 'autoprefixer',
    'postcss': 'postcss',
    'sass': 'sass',
    'styled-components': 'styled-components',
    '@emotion/react': '@emotion/react',
    '@emotion/styled': '@emotion/styled',

    # Build tools
    'vite': 'vite',
    'esbuild': 'esbuild',
    'webpack': 'webpack',
    'typescript': 'typescript',

    # Testing
    'jest': 'jest',
    'vitest': 'vitest',
    'supertest': 'supertest',
    '@testing-library/react': '@testing-library/react',
}

# Python import→package mapping (extends the one in lazarus_agent.py)
PYTHON_PACKAGE_MAP = {
    # Web frameworks
    'fastapi': 'fastapi',
    'flask': 'flask',
    'flask_cors': 'flask-cors',
    'django': 'django',
    'starlette': 'starlette',
    'uvicorn': 'uvicorn',
    'gunicorn': 'gunicorn',

    # Database
    'sqlalchemy': 'sqlalchemy',
    'alembic': 'alembic',
    'pymongo': 'pymongo',
    'motor': 'motor',
    'redis': 'redis',
    'psycopg2': 'psycopg2-binary',
    'asyncpg': 'asyncpg',
    'tortoise': 'tortoise-orm',
    'peewee': 'peewee',

    # Auth
    'jose': 'python-jose[cryptography]',
    'jwt': 'PyJWT',
    'passlib': 'passlib[bcrypt]',
    'bcrypt': 'bcrypt',
    'authlib': 'authlib',

    # Data
    'pydantic': 'pydantic',
    'pandas': 'pandas',
    'numpy': 'numpy',
    'scipy': 'scipy',
    'sklearn': 'scikit-learn',
    'cv2': 'opencv-python-headless',
    'PIL': 'pillow',
    'matplotlib': 'matplotlib',

    # HTTP/API
    'requests': 'requests',
    'httpx': 'httpx',
    'aiohttp': 'aiohttp',

    # Utilities
    'dotenv': 'python-dotenv',
    'pydantic_settings': 'pydantic-settings',
    'celery': 'celery',
    'boto3': 'boto3',
    'stripe': 'stripe',
    'openai': 'openai',
    'google.generativeai': 'google-generativeai',
    'bs4': 'beautifulsoup4',
    'email_validator': 'email-validator',
    'multipart': 'python-multipart',
    'jinja2': 'jinja2',
    'marshmallow': 'marshmallow',
    'loguru': 'loguru',
}

# Node built-in modules (don't need packages)
NODE_BUILTINS = {
    'fs', 'path', 'os', 'http', 'https', 'url', 'util', 'crypto',
    'stream', 'events', 'child_process', 'cluster', 'net', 'dns',
    'readline', 'assert', 'buffer', 'querystring', 'zlib', 'tls',
    'worker_threads', 'perf_hooks', 'module', 'process', 'timers',
    'node:fs', 'node:path', 'node:os', 'node:http', 'node:https',
    'node:url', 'node:util', 'node:crypto', 'node:stream', 'node:events',
    'node:child_process', 'node:net', 'node:dns', 'node:readline',
    'node:assert', 'node:buffer', 'node:querystring', 'node:zlib',
    'node:tls', 'node:worker_threads', 'node:perf_hooks',
}

# Python standard library modules (don't need packages)
PYTHON_BUILTINS = {
    'os', 'sys', 'json', 're', 'time', 'datetime', 'math', 'random',
    'hashlib', 'base64', 'io', 'pathlib', 'typing', 'collections',
    'functools', 'itertools', 'enum', 'dataclasses', 'abc', 'logging',
    'unittest', 'argparse', 'configparser', 'csv', 'sqlite3', 'uuid',
    'copy', 'shutil', 'tempfile', 'glob', 'subprocess', 'threading',
    'multiprocessing', 'asyncio', 'socket', 'http', 'email', 'html',
    'xml', 'struct', 'ctypes', 'traceback', 'inspect', 'ast',
    'contextvars', 'secrets', 'hmac', 'textwrap', 'string', 'operator',
}


def validate_dependencies(
    generated_files: List[Dict],
    original_files: List[Dict] = None,
) -> List[ValidationIssue]:
    """
    Cross-reference all imports in generated code against declared dependencies
    in package.json / requirements.txt.

    Args:
        generated_files: All generated files [{filename, content}]
        original_files: Original repo files (for reading existing package.json/requirements.txt)

    Returns:
        List of ValidationIssue for missing dependencies
    """
    issues = []

    # Step 1: Parse existing dependency declarations
    declared_node_deps = set()
    declared_python_deps = set()

    all_files = (generated_files or []) + (original_files or [])
    for f in all_files:
        fname = f.get('filename', f.get('path', ''))
        content = f.get('content', '')

        if fname.endswith('package.json'):
            try:
                pkg = json.loads(content)
                for dep_section in ('dependencies', 'devDependencies', 'peerDependencies'):
                    if dep_section in pkg:
                        declared_node_deps.update(pkg[dep_section].keys())
            except (json.JSONDecodeError, TypeError):
                pass

        elif fname.endswith('requirements.txt'):
            for line in content.split('\n'):
                line = line.strip()
                if line and not line.startswith('#'):
                    # Extract package name (before ==, >=, etc.)
                    pkg_name = re.split(r'[>=<!\[;]', line)[0].strip()
                    if pkg_name:
                        declared_python_deps.add(pkg_name.lower())

    # Step 2: Scan all generated files for imports
    node_imports: Dict[str, List[str]] = {}     # package → [files using it]
    python_imports: Dict[str, List[str]] = {}   # package → [files using it]

    for f in generated_files:
        fname = f.get('filename', '')
        content = f.get('content', '')
        ext = os.path.splitext(fname)[1].lower()

        if ext in ('.js', '.jsx', '.ts', '.tsx', '.mjs', '.cjs'):
            _scan_node_imports(fname, content, node_imports)
        elif ext == '.py':
            _scan_python_imports(fname, content, python_imports)

    # Step 3: Check Node.js imports against declared deps
    for import_name, files in node_imports.items():
        if import_name in NODE_BUILTINS:
            continue
        if import_name.startswith('.') or import_name.startswith('/'):
            continue  # Local import

        # Get the package name (handle scoped packages)
        package = _get_node_package_name(import_name)

        if package not in declared_node_deps:
            mapped_package = NODE_PACKAGE_MAP.get(package, package)
            issues.append(ValidationIssue(
                severity='warning',
                category='missing_dep',
                message=f"Node.js: '{import_name}' imported in {', '.join(files[:3])} but not in package.json",
                file=files[0],
                fix_suggestion=f"Add '{mapped_package}' to package.json dependencies",
            ))

    # Step 4: Check Python imports against declared deps
    for import_name, files in python_imports.items():
        if import_name in PYTHON_BUILTINS:
            continue

        # Map to PyPI package name
        mapped = PYTHON_PACKAGE_MAP.get(import_name, import_name)
        mapped_lower = mapped.lower().split('[')[0]  # Remove extras like [cryptography]

        if mapped_lower not in declared_python_deps and import_name not in declared_python_deps:
            issues.append(ValidationIssue(
                severity='warning',
                category='missing_dep',
                message=f"Python: '{import_name}' imported in {', '.join(files[:3])} but not in requirements.txt",
                file=files[0],
                fix_suggestion=f"Add '{mapped}' to requirements.txt",
            ))

    return issues


def _scan_node_imports(fname: str, content: str, imports: Dict[str, List[str]]):
    """Extract all Node.js imports from a file."""
    # ES6: import X from 'package'
    for m in re.finditer(r"""(?:import|export)\s+.*?\s+from\s+['"]([^'"]+)['"]""", content):
        pkg = m.group(1)
        if not pkg.startswith('.'):
            imports.setdefault(pkg, []).append(fname)

    # import 'package' (side-effect)
    for m in re.finditer(r"""^import\s+['"]([^'"]+)['"]""", content, re.MULTILINE):
        pkg = m.group(1)
        if not pkg.startswith('.'):
            imports.setdefault(pkg, []).append(fname)

    # CommonJS: require('package')
    for m in re.finditer(r"""require\s*\(\s*['"]([^'"]+)['"]""", content):
        pkg = m.group(1)
        if not pkg.startswith('.'):
            imports.setdefault(pkg, []).append(fname)

    # Dynamic import: import('package')
    for m in re.finditer(r"""import\s*\(\s*['"]([^'"]+)['"]""", content):
        pkg = m.group(1)
        if not pkg.startswith('.'):
            imports.setdefault(pkg, []).append(fname)


def _scan_python_imports(fname: str, content: str, imports: Dict[str, List[str]]):
    """Extract all Python imports from a file."""
    for line in content.split('\n'):
        stripped = line.strip()

        # import module
        m = re.match(r'^import\s+(\S+)', stripped)
        if m:
            module = m.group(1).split('.')[0].split(',')[0].strip()
            if module:
                imports.setdefault(module, []).append(fname)

        # from module import ...
        m = re.match(r'^from\s+(\S+)\s+import', stripped)
        if m:
            module = m.group(1).split('.')[0]
            if module and not module.startswith('.'):
                imports.setdefault(module, []).append(fname)


def _get_node_package_name(import_path: str) -> str:
    """Extract the package name from a Node.js import path."""
    # Scoped packages: @scope/package/subpath → @scope/package
    if import_path.startswith('@'):
        parts = import_path.split('/')
        return '/'.join(parts[:2]) if len(parts) >= 2 else import_path
    # Regular packages: package/subpath → package
    return import_path.split('/')[0]


# ══════════════════════════════════════════════════════════════
# 3. TYPE COHERENCE VALIDATION
# ══════════════════════════════════════════════════════════════

def validate_type_coherence(
    generated_files: List[Dict],
    project_context=None,
) -> List[ValidationIssue]:
    """
    Compare TypeScript interfaces/types against Python Pydantic/SQLAlchemy models
    to detect field name and type mismatches.

    Args:
        generated_files: All generated files [{filename, content}]
        project_context: ProjectContext from context_extraction

    Returns:
        List of ValidationIssue for type mismatches
    """
    issues = []

    # Step 1: Extract all TypeScript interfaces and types
    ts_types: Dict[str, Dict] = {}   # name → {fields: [(name, type)], file: str}
    py_models: Dict[str, Dict] = {}  # name → {fields: [(name, type)], file: str}

    for f in generated_files:
        fname = f.get('filename', '')
        content = f.get('content', '')
        ext = os.path.splitext(fname)[1].lower()

        if ext in ('.ts', '.tsx'):
            _extract_ts_types(fname, content, ts_types)
        elif ext == '.py':
            _extract_py_models(fname, content, py_models)

    # Also use project context for more reliable schema data
    if project_context and hasattr(project_context, 'schemas'):
        for schema in project_context.schemas:
            if schema.kind in ('pydantic', 'sqlalchemy', 'django_model', 'dataclass', 'marshmallow'):
                name = schema.name
                if name not in py_models or len(schema.fields) > len(py_models.get(name, {}).get('fields', [])):
                    py_models[name] = {
                        'fields': schema.fields,
                        'file': schema.file,
                        'kind': schema.kind,
                    }
            elif schema.kind in ('typescript_interface', 'typescript_type', 'zod'):
                name = schema.name
                if name not in ts_types or len(schema.fields) > len(ts_types.get(name, {}).get('fields', [])):
                    ts_types[name] = {
                        'fields': schema.fields,
                        'file': schema.file,
                        'kind': schema.kind,
                    }

    if not ts_types or not py_models:
        return issues  # Need both sides to compare

    # Step 2: Match types by name (fuzzy)
    matched_pairs = _match_type_names(ts_types, py_models)

    # Step 3: Compare fields
    for ts_name, py_name in matched_pairs:
        ts_info = ts_types[ts_name]
        py_info = py_models[py_name]

        ts_fields = {_normalize_field_name(f[0]): f[1] for f in ts_info.get('fields', [])}
        py_fields = {_normalize_field_name(f[0]): f[1] for f in py_info.get('fields', [])}

        # Fields in Python but not in TypeScript
        missing_in_ts = set(py_fields.keys()) - set(ts_fields.keys())
        # Fields in TypeScript but not in Python
        missing_in_py = set(ts_fields.keys()) - set(py_fields.keys())

        # Filter out common false positives
        ignore_fields = {'id', 'created_at', 'updated_at', 'createdat', 'updatedat', '_id', 'v', '__v'}
        missing_in_ts -= ignore_fields
        missing_in_py -= ignore_fields

        if missing_in_ts and len(missing_in_ts) <= len(py_fields) * 0.5:
            # Only warn if it's a partial mismatch (not completely different types)
            issues.append(ValidationIssue(
                severity='warning',
                category='type_mismatch',
                message=(
                    f"TypeScript '{ts_name}' ({ts_info.get('file', '?')}) is missing fields "
                    f"from Python '{py_name}' ({py_info.get('file', '?')}): "
                    f"{', '.join(sorted(missing_in_ts)[:5])}"
                ),
                file=ts_info.get('file', ''),
                fix_suggestion=f"Add missing fields to the TypeScript interface: {', '.join(sorted(missing_in_ts)[:5])}",
            ))

        if missing_in_py and len(missing_in_py) <= len(ts_fields) * 0.5:
            issues.append(ValidationIssue(
                severity='info',
                category='type_mismatch',
                message=(
                    f"Python '{py_name}' ({py_info.get('file', '?')}) is missing fields "
                    f"from TypeScript '{ts_name}' ({ts_info.get('file', '?')}): "
                    f"{', '.join(sorted(missing_in_py)[:5])}"
                ),
                file=py_info.get('file', ''),
                fix_suggestion=f"These may be frontend-only fields, verify they're not needed in the API",
            ))

        # Check type compatibility for shared fields
        shared_fields = set(ts_fields.keys()) & set(py_fields.keys()) - ignore_fields
        for field_name in shared_fields:
            ts_type = ts_fields[field_name]
            py_type = py_fields[field_name]
            if not _types_compatible(ts_type, py_type):
                issues.append(ValidationIssue(
                    severity='warning',
                    category='type_mismatch',
                    message=(
                        f"Field '{field_name}' type mismatch: "
                        f"TS '{ts_name}.{field_name}: {ts_type}' vs "
                        f"Python '{py_name}.{field_name}: {py_type}'"
                    ),
                    file=ts_info.get('file', ''),
                    fix_suggestion=f"Align types: TS={ts_type}, Python={py_type}",
                ))

    return issues


def _extract_ts_types(fname: str, content: str, types: Dict[str, Dict]):
    """Extract TypeScript interfaces and type aliases."""
    # Interfaces: interface User { name: string; age: number; }
    for m in re.finditer(r'(?:export\s+)?interface\s+(\w+)(?:\s+extends\s+\w+)?\s*\{([^}]+)\}', content, re.DOTALL):
        name = m.group(1)
        fields = []
        for fm in re.finditer(r'(\w+)\??\s*:\s*([^;\n]+)', m.group(2)):
            fields.append((fm.group(1).strip(), fm.group(2).strip().rstrip(';')))
        types[name] = {'fields': fields, 'file': fname, 'kind': 'interface'}

    # Type aliases: type User = { name: string; age: number; }
    for m in re.finditer(r'(?:export\s+)?type\s+(\w+)\s*=\s*\{([^}]+)\}', content, re.DOTALL):
        name = m.group(1)
        if name not in types:
            fields = []
            for fm in re.finditer(r'(\w+)\??\s*:\s*([^;\n]+)', m.group(2)):
                fields.append((fm.group(1).strip(), fm.group(2).strip().rstrip(';')))
            types[name] = {'fields': fields, 'file': fname, 'kind': 'type'}


def _extract_py_models(fname: str, content: str, models: Dict[str, Dict]):
    """Extract Python Pydantic models and class-based schemas."""
    # Class definitions with schema-like bases
    for m in re.finditer(
        r'class\s+(\w+)\s*\(([^)]+)\)\s*:(.+?)(?=\nclass\s|\Z)',
        content, re.DOTALL
    ):
        name = m.group(1)
        bases = m.group(2)
        body = m.group(3)

        # Check if it's a model/schema
        if not any(kw in bases for kw in ('BaseModel', 'Schema', 'Model', 'Base', 'Document', 'Form', 'Serializer')):
            continue

        fields = []
        for fm in re.finditer(r'^\s+(\w+)\s*:\s*([^\n=]+?)(?:\s*=.*)?$', body, re.MULTILINE):
            field_name = fm.group(1).strip()
            field_type = fm.group(2).strip()
            if field_name not in ('class', 'model', 'Meta') and not field_name.startswith('_'):
                fields.append((field_name, field_type))

        if fields:
            models[name] = {'fields': fields, 'file': fname, 'kind': 'pydantic'}


def _match_type_names(
    ts_types: Dict[str, Dict],
    py_models: Dict[str, Dict],
) -> List[Tuple[str, str]]:
    """Match TypeScript type names to Python model names."""
    pairs = []
    matched_py = set()

    for ts_name in ts_types:
        ts_lower = ts_name.lower().replace('type', '').replace('dto', '').replace('props', '').replace('interface', '')

        for py_name in py_models:
            if py_name in matched_py:
                continue
            py_lower = py_name.lower().replace('schema', '').replace('model', '').replace('create', '').replace('update', '').replace('base', '').replace('response', '')

            # Exact match
            if ts_lower == py_lower:
                pairs.append((ts_name, py_name))
                matched_py.add(py_name)
                break

            # One contains the other
            if len(ts_lower) > 2 and len(py_lower) > 2:
                if ts_lower in py_lower or py_lower in ts_lower:
                    pairs.append((ts_name, py_name))
                    matched_py.add(py_name)
                    break

    return pairs


def _normalize_field_name(name: str) -> str:
    """Normalize field name for comparison (camelCase ↔ snake_case)."""
    # Convert camelCase to snake_case
    snake = re.sub(r'([a-z])([A-Z])', r'\1_\2', name).lower()
    return snake


def _types_compatible(ts_type: str, py_type: str) -> bool:
    """Check if a TypeScript type is compatible with a Python type."""
    ts_lower = ts_type.lower().strip()
    py_lower = py_type.lower().strip()

    # Type mapping: TS → Python
    compat_map = {
        'string': {'str', 'string', 'emailstr', 'text', 'varchar', 'optional[str]'},
        'number': {'int', 'float', 'decimal', 'integer', 'optional[int]', 'optional[float]'},
        'boolean': {'bool', 'boolean', 'optional[bool]'},
        'date': {'datetime', 'date', 'optional[datetime]', 'optional[date]'},
        'any': {'any', 'dict', 'object'},
        'string[]': {'list[str]', 'list', 'optional[list[str]]'},
        'number[]': {'list[int]', 'list[float]', 'list', 'optional[list[int]]'},
        'object': {'dict', 'dict[str, any]', 'jsonfield'},
        'null': {'none', 'optional'},
    }

    # Check direct compatibility
    for ts_group, py_set in compat_map.items():
        if ts_lower == ts_group or ts_lower.startswith(ts_group):
            if any(py_lower.startswith(p) or py_lower == p for p in py_set):
                return True

    # If types look similar, consider compatible
    if ts_lower == py_lower:
        return True

    # Array/List compatibility
    if ('[]' in ts_lower or 'array' in ts_lower) and ('list' in py_lower or 'array' in py_lower):
        return True

    # Optional compatibility
    if ts_lower.endswith('| null') or ts_lower.endswith('| undefined'):
        base_ts = ts_lower.replace('| null', '').replace('| undefined', '').strip()
        return _types_compatible(base_ts, py_lower)

    if py_lower.startswith('optional['):
        base_py = py_lower[9:-1] if py_lower.endswith(']') else py_lower
        return _types_compatible(ts_lower, base_py)

    # Custom types (User, Product, etc.) — consider compatible if names match
    if ts_lower == py_lower or ts_lower.replace('type', '') == py_lower.replace('schema', ''):
        return True

    # Be lenient for complex types — only flag obvious mismatches
    simple_ts = {'string', 'number', 'boolean'}
    simple_py = {'str', 'int', 'float', 'bool'}
    if ts_lower in simple_ts and py_lower in simple_py:
        # Check cross-type mismatches
        if ts_lower == 'string' and py_lower in ('int', 'float', 'bool'):
            return False
        if ts_lower == 'number' and py_lower in ('str', 'bool'):
            return False
        if ts_lower == 'boolean' and py_lower in ('str', 'int', 'float'):
            return False

    return True  # Default: consider compatible (avoid false positives)


# ══════════════════════════════════════════════════════════════
# MASTER VALIDATION RUNNER
# ══════════════════════════════════════════════════════════════

def run_all_validations(
    generated_files: List[Dict],
    project_context=None,
    original_files: List[Dict] = None,
) -> ValidationReport:
    """
    Run all post-generation validators and return a combined report.

    Args:
        generated_files: All generated files [{filename, content}]
        project_context: ProjectContext from context_extraction
        original_files: Original repo files for dependency checking

    Returns:
        ValidationReport with all issues
    """
    report = ValidationReport()

    # 1. Route validation
    try:
        route_issues = validate_routes(generated_files, project_context)
        report.issues.extend(route_issues)
        report.route_mismatches = len(route_issues)
    except Exception as e:
        logger.warning(f"Route validation failed: {e}")

    # 2. Dependency validation
    try:
        dep_issues = validate_dependencies(generated_files, original_files)
        report.issues.extend(dep_issues)
        report.missing_deps = len(dep_issues)
    except Exception as e:
        logger.warning(f"Dependency validation failed: {e}")

    # 3. Type coherence validation
    try:
        type_issues = validate_type_coherence(generated_files, project_context)
        report.issues.extend(type_issues)
        report.type_mismatches = len(type_issues)
    except Exception as e:
        logger.warning(f"Type validation failed: {e}")

    logger.info(
        f"Validation complete: {report.total_issues} issues "
        f"({report.route_mismatches} routes, {report.missing_deps} deps, {report.type_mismatches} types)"
    )

    return report
