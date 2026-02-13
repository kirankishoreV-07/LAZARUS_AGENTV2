"""
Lazarus Engine — Phase 2: Rich Context Extraction
=====================================================
Extracts deep structural contracts from AST analysis results.
Goes beyond raw file listings to produce:

  - Full API contracts (method, path, params, return type, auth required)
  - Data schemas (Pydantic, TypeScript interfaces, Mongoose models, SQLAlchemy)
  - Authentication patterns (JWT, session, OAuth, API key)
  - Data flow maps (input → validation → DB → output)
  - Shared type definitions for cross-batch coherence

This feeds the Cross-Batch Context Manager so every batch
knows exactly what the rest of the codebase exposes.
"""

import re
import os
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Set, Optional, Tuple

from ast_parser import FileAnalysis, RouteInfo, FunctionInfo, ClassInfo, ImportInfo

logger = logging.getLogger('lazarus.context_extraction')


# ══════════════════════════════════════════════════════════════
# DATA STRUCTURES — Rich Contracts
# ══════════════════════════════════════════════════════════════

@dataclass
class APIContract:
    """A fully-described API endpoint contract."""
    method: str             # GET, POST, PUT, DELETE, PATCH
    path: str               # e.g. /api/users/:id
    handler: str            # Function name handling the route
    file: str               # File where the route is defined
    params: List[str] = field(default_factory=list)       # Path/query params
    body_schema: Optional[str] = None                     # Request body type/schema
    return_type: Optional[str] = None                     # Response type
    auth_required: bool = False                           # Whether auth middleware is present
    middleware: List[str] = field(default_factory=list)    # Middleware chain
    line: int = 0

    def signature(self) -> str:
        """Human-readable one-liner."""
        auth = " [AUTH]" if self.auth_required else ""
        body = f" body={self.body_schema}" if self.body_schema else ""
        ret = f" → {self.return_type}" if self.return_type else ""
        return f"{self.method} {self.path}{auth}{body}{ret}  ({self.handler} in {self.file})"


@dataclass
class SchemaContract:
    """A data model / schema definition."""
    name: str
    file: str
    kind: str               # 'pydantic', 'sqlalchemy', 'mongoose', 'typescript_interface',
                            # 'typescript_type', 'zod', 'prisma', 'dataclass', 'django_model'
    fields: List[Tuple[str, str]] = field(default_factory=list)  # (field_name, field_type)
    base_classes: List[str] = field(default_factory=list)
    relationships: List[str] = field(default_factory=list)       # FK / relations
    validators: List[str] = field(default_factory=list)          # Validation rules
    line: int = 0

    def signature(self) -> str:
        """Compact type description."""
        fields_str = ", ".join(f"{n}: {t}" for n, t in self.fields[:8])
        if len(self.fields) > 8:
            fields_str += f", ... +{len(self.fields) - 8} more"
        return f"{self.name} ({self.kind}) {{ {fields_str} }}"


@dataclass
class AuthPattern:
    """Detected authentication / authorization pattern."""
    kind: str               # 'jwt', 'session', 'oauth', 'api_key', 'basic', 'custom'
    file: str
    details: str            # Brief description
    middleware_name: Optional[str] = None  # e.g. 'authMiddleware', 'login_required'
    protected_routes: List[str] = field(default_factory=list)


@dataclass
class DataFlow:
    """A traced data flow through the system."""
    name: str               # e.g. "User Registration Flow"
    steps: List[str] = field(default_factory=list)  # Ordered description of steps
    files_involved: List[str] = field(default_factory=list)
    schemas_used: List[str] = field(default_factory=list)
    endpoints_used: List[str] = field(default_factory=list)


@dataclass
class ProjectContext:
    """
    Complete rich context for the entire project.
    This is the master object passed to the Cross-Batch Context Manager.
    """
    api_contracts: List[APIContract] = field(default_factory=list)
    schemas: List[SchemaContract] = field(default_factory=list)
    auth_patterns: List[AuthPattern] = field(default_factory=list)
    data_flows: List[DataFlow] = field(default_factory=list)
    shared_constants: Dict[str, str] = field(default_factory=dict)  # name → value/description
    env_vars_required: List[Tuple[str, str]] = field(default_factory=list)  # (name, category)
    frameworks_detected: Set[str] = field(default_factory=set)
    entry_points: List[str] = field(default_factory=list)

    # ── Compact serialisation for prompts ──

    def api_summary(self, max_routes: int = 50) -> str:
        """Render API contracts as a concise prompt section."""
        if not self.api_contracts:
            return "[No API routes detected]"
        lines = []
        for c in self.api_contracts[:max_routes]:
            lines.append(f"  {c.signature()}")
        if len(self.api_contracts) > max_routes:
            lines.append(f"  ... +{len(self.api_contracts) - max_routes} more routes")
        return "\n".join(lines)

    def schema_summary(self, max_schemas: int = 30) -> str:
        """Render schema contracts as a concise prompt section."""
        if not self.schemas:
            return "[No data schemas detected]"
        lines = []
        for s in self.schemas[:max_schemas]:
            lines.append(f"  {s.signature()}")
        if len(self.schemas) > max_schemas:
            lines.append(f"  ... +{len(self.schemas) - max_schemas} more schemas")
        return "\n".join(lines)

    def auth_summary(self) -> str:
        """Render auth patterns."""
        if not self.auth_patterns:
            return "[No auth patterns detected]"
        lines = []
        for a in self.auth_patterns:
            routes = f" protecting {len(a.protected_routes)} routes" if a.protected_routes else ""
            lines.append(f"  {a.kind.upper()}: {a.details}{routes} (in {a.file})")
        return "\n".join(lines)

    def env_summary(self) -> str:
        """Render required env vars."""
        if not self.env_vars_required:
            return "[No env vars detected]"
        lines = []
        for name, cat in self.env_vars_required:
            lines.append(f"  {name} ({cat})")
        return "\n".join(lines)

    def full_context_prompt(self, max_chars: int = 40000) -> str:
        """
        Render the entire project context as a structured prompt section.
        This is injected into every batch's code generation prompt.
        """
        sections = []

        sections.append("═══ PROJECT-WIDE API CONTRACTS ═══")
        sections.append(self.api_summary())

        sections.append("\n═══ DATA SCHEMAS & MODELS ═══")
        sections.append(self.schema_summary())

        sections.append("\n═══ AUTHENTICATION PATTERNS ═══")
        sections.append(self.auth_summary())

        if self.env_vars_required:
            sections.append("\n═══ REQUIRED ENVIRONMENT VARIABLES ═══")
            sections.append(self.env_summary())

        if self.shared_constants:
            sections.append("\n═══ SHARED CONSTANTS ═══")
            for name, desc in list(self.shared_constants.items())[:20]:
                sections.append(f"  {name} = {desc}")

        if self.data_flows:
            sections.append("\n═══ DATA FLOWS ═══")
            for flow in self.data_flows[:5]:
                sections.append(f"  {flow.name}:")
                for step in flow.steps[:6]:
                    sections.append(f"    → {step}")

        result = "\n".join(sections)
        if len(result) > max_chars:
            result = result[:max_chars] + "\n... (context truncated)"
        return result

    def to_dict(self) -> dict:
        """Serialisable dict for memory storage."""
        return {
            "api_contracts": [
                {"method": c.method, "path": c.path, "handler": c.handler,
                 "file": c.file, "auth_required": c.auth_required,
                 "body_schema": c.body_schema, "return_type": c.return_type}
                for c in self.api_contracts
            ],
            "schemas": [
                {"name": s.name, "file": s.file, "kind": s.kind,
                 "fields": s.fields, "base_classes": s.base_classes}
                for s in self.schemas
            ],
            "auth_patterns": [
                {"kind": a.kind, "file": a.file, "details": a.details,
                 "middleware_name": a.middleware_name}
                for a in self.auth_patterns
            ],
            "env_vars": self.env_vars_required,
            "frameworks": list(self.frameworks_detected),
            "constant_count": len(self.shared_constants),
            "flow_count": len(self.data_flows),
        }


# ══════════════════════════════════════════════════════════════
# EXTRACTION ENGINE
# ══════════════════════════════════════════════════════════════

def extract_project_context(
    analyses: Dict[str, FileAnalysis],
    file_contents: Dict[str, str] = None,
) -> ProjectContext:
    """
    Master extraction function.  Takes AST analyses (and optionally raw
    file contents for deeper regex passes) and returns a complete
    ProjectContext.

    Args:
        analyses: Dict mapping file path → FileAnalysis (from ast_parser)
        file_contents: Optional dict mapping file path → raw source text

    Returns:
        ProjectContext with all extracted contracts
    """
    ctx = ProjectContext()
    file_contents = file_contents or {}

    for path, analysis in analyses.items():
        content = file_contents.get(path, "")

        # ── 1. API contracts ──
        _extract_api_contracts(path, analysis, content, ctx)

        # ── 2. Schemas ──
        _extract_schemas(path, analysis, content, ctx)

        # ── 3. Auth patterns ──
        _extract_auth_patterns(path, analysis, content, ctx)

        # ── 4. Env vars ──
        _extract_env_vars(path, analysis, content, ctx)

        # ── 5. Shared constants ──
        _extract_shared_constants(path, analysis, content, ctx)

        # ── 6. Frameworks ──
        ctx.frameworks_detected.update(analysis.frameworks)

        # ── 7. Entry points ──
        if analysis.has_entrypoint:
            ctx.entry_points.append(path)

    # ── 8. Data flows (cross-file) ──
    _build_data_flows(analyses, ctx)

    # De-duplicate
    _deduplicate_context(ctx)

    logger.info(
        f"Rich context extracted: {len(ctx.api_contracts)} APIs, "
        f"{len(ctx.schemas)} schemas, {len(ctx.auth_patterns)} auth patterns, "
        f"{len(ctx.env_vars_required)} env vars, {len(ctx.data_flows)} data flows"
    )
    return ctx


# ──────────────────────────────────────────────────────────────
# 1. API CONTRACT EXTRACTION
# ──────────────────────────────────────────────────────────────

def _extract_api_contracts(
    path: str, analysis: FileAnalysis, content: str, ctx: ProjectContext
):
    """Extract detailed API contracts from routes and handler functions."""
    # Start with AST-detected routes
    for route in analysis.routes:
        contract = APIContract(
            method=route.method,
            path=route.path,
            handler=route.handler,
            file=path,
            line=route.line,
        )

        # Find the handler function to get params/return type
        handler_fn = _find_function(analysis, route.handler)
        if handler_fn:
            contract.params = [a for a in handler_fn.args if a not in ('self', 'request', 'req', 'res', 'next', 'db')]
            contract.return_type = handler_fn.return_type

        # Check for auth decorators / middleware
        if handler_fn:
            auth_decs = [d for d in handler_fn.decorators
                         if any(kw in d.lower() for kw in ('auth', 'login', 'protect', 'permission', 'token', 'jwt'))]
            if auth_decs:
                contract.auth_required = True
                contract.middleware = auth_decs

        # Regex: detect body schema from handler content
        if content:
            _enrich_contract_from_content(content, route, contract)

        ctx.api_contracts.append(contract)

    # Additional regex pass for routes the AST might have missed
    if content:
        _extract_routes_regex(path, content, ctx, analysis)


def _find_function(analysis: FileAnalysis, name: str) -> Optional[FunctionInfo]:
    """Find a function or method by name in the analysis."""
    for fn in analysis.functions:
        if fn.name == name:
            return fn
    for cls in analysis.classes:
        for method in cls.methods:
            if method.name == name:
                return method
    return None


def _enrich_contract_from_content(content: str, route: RouteInfo, contract: APIContract):
    """Use regex on raw content to enrich a contract with body/response details."""
    # Pydantic body: def handler(item: ItemCreate)
    pattern = rf'def\s+{re.escape(route.handler)}\s*\([^)]*?(\w+)\s*:\s*(\w+(?:Schema|Model|Create|Update|Input|Request|Body|DTO)\w*)'
    m = re.search(pattern, content)
    if m:
        contract.body_schema = m.group(2)

    # FastAPI Depends for auth
    if re.search(rf'def\s+{re.escape(route.handler)}\s*\([^)]*Depends\s*\(\s*(\w*(?:auth|token|current_user)\w*)', content, re.IGNORECASE):
        contract.auth_required = True

    # Express middleware chain: app.post('/path', authMiddleware, handler)
    mw_pattern = rf"""(?:app|router)\.{re.escape(route.method.lower())}\s*\(\s*['"](?:{re.escape(route.path)})['"],\s*(.+?),"""
    mw_match = re.search(mw_pattern, content)
    if mw_match:
        middleware_str = mw_match.group(1)
        middlewares = [m.strip() for m in middleware_str.split(',')]
        for mw in middlewares:
            mw_clean = mw.strip()
            if mw_clean and not mw_clean.startswith(('(', 'async', 'function')):
                contract.middleware.append(mw_clean)
                if any(kw in mw_clean.lower() for kw in ('auth', 'protect', 'verify', 'jwt', 'token')):
                    contract.auth_required = True


def _extract_routes_regex(path: str, content: str, ctx: ProjectContext, analysis: FileAnalysis):
    """Catch routes the AST parser may have missed (e.g. dynamic registration)."""
    existing_sigs = {(c.method, c.path) for c in ctx.api_contracts if c.file == path}

    # Django URL patterns: path('api/users/', views.user_list)
    for m in re.finditer(r"""path\s*\(\s*['"]([^'"]+)['"].*?(?:views\.)?(\w+)""", content):
        route_path = '/' + m.group(1).strip('/')
        handler = m.group(2)
        if ('GET', route_path) not in existing_sigs:
            ctx.api_contracts.append(APIContract(
                method='GET', path=route_path, handler=handler, file=path
            ))

    # Blueprint routes: @bp.route(...)
    for m in re.finditer(r"""@(\w+)\.(route|get|post|put|delete|patch)\s*\(\s*['"]([^'"]+)['"]""", content):
        method = m.group(2).upper() if m.group(2) != 'route' else 'GET'
        route_path = m.group(3)
        if (method, route_path) not in existing_sigs:
            ctx.api_contracts.append(APIContract(
                method=method, path=route_path, handler='blueprint_handler', file=path
            ))


# ──────────────────────────────────────────────────────────────
# 2. SCHEMA EXTRACTION
# ──────────────────────────────────────────────────────────────

def _extract_schemas(
    path: str, analysis: FileAnalysis, content: str, ctx: ProjectContext
):
    """Extract data schemas from classes and type definitions."""
    for cls in analysis.classes:
        schema = _classify_schema(cls, analysis, content)
        if schema:
            schema.file = path
            ctx.schemas.append(schema)

    # TypeScript interfaces / types already captured as classes by ast_parser
    # Additional regex pass for inline Zod schemas and Prisma
    if content:
        _extract_schema_regex(path, content, ctx)


def _classify_schema(
    cls: ClassInfo, analysis: FileAnalysis, content: str
) -> Optional[SchemaContract]:
    """Determine if a class is a data schema and extract its fields."""
    kind = None
    for base in cls.bases:
        base_lower = base.lower()
        if 'basemodel' in base_lower or 'pydantic' in base_lower:
            kind = 'pydantic'
        elif 'base' == base_lower or 'declarativebase' in base_lower or 'db.model' in base_lower:
            kind = 'sqlalchemy'
        elif 'model' in base_lower and ('django' in ' '.join(i.module for i in analysis.imports).lower()):
            kind = 'django_model'
        elif 'document' in base_lower:
            kind = 'mongoose'
        elif 'schema' in base_lower:
            kind = 'marshmallow'

    # Check decorators
    for dec in cls.decorators:
        if 'dataclass' in dec.lower():
            kind = 'dataclass'

    # Check if name looks like a schema/model
    if not kind and any(kw in cls.name for kw in ('Model', 'Schema', 'Entity', 'DTO', 'Base')):
        kind = 'generic_model'

    if not kind:
        return None

    # Extract fields
    fields = _extract_class_fields(cls, content)

    return SchemaContract(
        name=cls.name,
        file="",  # set by caller
        kind=kind,
        fields=fields,
        base_classes=cls.bases,
        line=cls.line_start,
    )


def _extract_class_fields(cls: ClassInfo, content: str) -> List[Tuple[str, str]]:
    """Extract field names and types from a class definition using regex on content."""
    fields = []

    # Properties from AST
    for prop in cls.properties:
        fields.append((prop, "Any"))

    # Python type-annotated fields: name: str = "default"
    # Look in the class body region
    class_pattern = rf'class\s+{re.escape(cls.name)}\b.*?(?=\nclass\s|\Z)'
    class_match = re.search(class_pattern, content, re.DOTALL)
    if class_match:
        class_body = class_match.group(0)
        for m in re.finditer(r'^\s+(\w+)\s*:\s*([^\n=]+?)(?:\s*=.*)?$', class_body, re.MULTILINE):
            field_name = m.group(1).strip()
            field_type = m.group(2).strip()
            if field_name not in ('self', 'cls') and not field_name.startswith('_'):
                # Avoid duplicates
                if not any(f[0] == field_name for f in fields):
                    fields.append((field_name, field_type))

    # TypeScript interface fields: name: string;
    for m in re.finditer(r'^\s+(\w+)\??\s*:\s*([^;{}\n]+)', content, re.MULTILINE):
        field_name = m.group(1).strip()
        field_type = m.group(2).strip().rstrip(';')
        if not any(f[0] == field_name for f in fields):
            fields.append((field_name, field_type))

    return fields


def _extract_schema_regex(path: str, content: str, ctx: ProjectContext):
    """Extract schemas the AST parser might miss (Zod, Prisma, Mongoose)."""
    existing = {s.name for s in ctx.schemas if s.file == path}

    # Zod schemas: const userSchema = z.object({ ... })
    for m in re.finditer(r'(?:const|let|export\s+const)\s+(\w+)\s*=\s*z\.\w+\(\s*\{([^}]*)\}', content, re.DOTALL):
        name = m.group(1)
        if name not in existing:
            fields = []
            for fm in re.finditer(r'(\w+)\s*:\s*z\.(\w+)', m.group(2)):
                fields.append((fm.group(1), f"z.{fm.group(2)}"))
            ctx.schemas.append(SchemaContract(
                name=name, file=path, kind='zod', fields=fields
            ))

    # Mongoose: new Schema({ field: Type, ... })
    for m in re.finditer(r'(?:const|let)\s+(\w+)Schema\s*=\s*new\s+(?:mongoose\.)?Schema\(\s*\{([^}]*)\}', content, re.DOTALL):
        name = m.group(1)
        if name not in existing:
            fields = []
            for fm in re.finditer(r'(\w+)\s*:\s*(?:\{[^}]*type\s*:\s*(\w+)|(\w+))', m.group(2)):
                ftype = fm.group(2) or fm.group(3) or 'Mixed'
                fields.append((fm.group(1), ftype))
            ctx.schemas.append(SchemaContract(
                name=name, file=path, kind='mongoose', fields=fields
            ))

    # Prisma models (from .prisma files)
    if path.endswith('.prisma'):
        for m in re.finditer(r'model\s+(\w+)\s*\{([^}]+)\}', content):
            name = m.group(1)
            if name not in existing:
                fields = []
                for fm in re.finditer(r'^\s+(\w+)\s+(\w+)', m.group(2), re.MULTILINE):
                    fields.append((fm.group(1), fm.group(2)))
                ctx.schemas.append(SchemaContract(
                    name=name, file=path, kind='prisma', fields=fields
                ))


# ──────────────────────────────────────────────────────────────
# 3. AUTH PATTERN EXTRACTION
# ──────────────────────────────────────────────────────────────

def _extract_auth_patterns(
    path: str, analysis: FileAnalysis, content: str, ctx: ProjectContext
):
    """Detect authentication and authorization patterns."""
    if not content:
        return

    content_lower = content.lower()

    # JWT detection
    if any(kw in content_lower for kw in ('jsonwebtoken', 'pyjwt', 'python-jose', 'jwt.encode', 'jwt.decode', 'jwt.sign', 'jwt.verify')):
        middleware_name = None
        for fn in analysis.functions:
            if any(kw in fn.name.lower() for kw in ('auth', 'verify_token', 'get_current_user', 'protect')):
                middleware_name = fn.name
                break
        ctx.auth_patterns.append(AuthPattern(
            kind='jwt', file=path,
            details='JWT token-based authentication',
            middleware_name=middleware_name,
        ))

    # Session-based auth
    if any(kw in content_lower for kw in ('express-session', 'flask-login', 'session_auth', 'req.session', 'login_user')):
        ctx.auth_patterns.append(AuthPattern(
            kind='session', file=path,
            details='Session-based authentication',
        ))

    # OAuth
    if any(kw in content_lower for kw in ('oauth', 'passport', 'social_django', 'authlib', 'google-auth')):
        ctx.auth_patterns.append(AuthPattern(
            kind='oauth', file=path,
            details='OAuth / third-party authentication',
        ))

    # API Key auth
    if re.search(r'(?:api[_-]?key|x-api-key|authorization.*bearer)', content_lower):
        # Only if it's actually enforcing, not just a config
        if any(kw in content_lower for kw in ('verify', 'validate', 'check', 'require', 'protect')):
            ctx.auth_patterns.append(AuthPattern(
                kind='api_key', file=path,
                details='API key authentication',
            ))

    # Map protected routes to auth patterns
    for auth in ctx.auth_patterns:
        if auth.file == path and auth.middleware_name:
            for contract in ctx.api_contracts:
                if contract.file == path and contract.auth_required:
                    auth.protected_routes.append(f"{contract.method} {contract.path}")


# ──────────────────────────────────────────────────────────────
# 4. ENVIRONMENT VARIABLE EXTRACTION
# ──────────────────────────────────────────────────────────────

_SECRET_KEYWORDS = {'key', 'secret', 'token', 'password', 'passwd', 'credential', 'auth'}
_URL_KEYWORDS = {'url', 'uri', 'host', 'endpoint', 'dsn', 'connection'}
_CONFIG_KEYWORDS = {'port', 'debug', 'env', 'mode', 'level', 'timeout', 'limit'}

def _categorize_env_var(name: str) -> str:
    """Categorize an environment variable as secret, url, or config."""
    lower = name.lower()
    if any(kw in lower for kw in _SECRET_KEYWORDS):
        return 'secret'
    if any(kw in lower for kw in _URL_KEYWORDS):
        return 'url'
    if any(kw in lower for kw in _CONFIG_KEYWORDS):
        return 'config'
    return 'config'


def _extract_env_vars(
    path: str, analysis: FileAnalysis, content: str, ctx: ProjectContext
):
    """Extract environment variable references from code."""
    if not content:
        return

    existing = {name for name, _ in ctx.env_vars_required}

    # Python: os.getenv('X'), os.environ['X'], os.environ.get('X')
    for m in re.finditer(r"""os\.(?:getenv|environ(?:\.get)?)\s*\(\s*['"]([^'"]+)['"]""", content):
        name = m.group(1)
        if name not in existing:
            ctx.env_vars_required.append((name, _categorize_env_var(name)))
            existing.add(name)

    # Python-dotenv: config('X')
    for m in re.finditer(r"""config\s*\(\s*['"]([A-Z_][A-Z0-9_]+)['"]""", content):
        name = m.group(1)
        if name not in existing:
            ctx.env_vars_required.append((name, _categorize_env_var(name)))
            existing.add(name)

    # JavaScript: process.env.X
    for m in re.finditer(r'process\.env\.([A-Z_][A-Z0-9_]+)', content):
        name = m.group(1)
        if name not in existing:
            ctx.env_vars_required.append((name, _categorize_env_var(name)))
            existing.add(name)

    # Vite: import.meta.env.VITE_X
    for m in re.finditer(r'import\.meta\.env\.([A-Z_][A-Z0-9_]+)', content):
        name = m.group(1)
        if name not in existing:
            ctx.env_vars_required.append((name, _categorize_env_var(name)))
            existing.add(name)

    # .env file entries
    if os.path.basename(path).startswith('.env'):
        for var_name in analysis.global_vars:
            if var_name not in existing:
                ctx.env_vars_required.append((var_name, _categorize_env_var(var_name)))
                existing.add(var_name)


# ──────────────────────────────────────────────────────────────
# 5. SHARED CONSTANTS
# ──────────────────────────────────────────────────────────────

def _extract_shared_constants(
    path: str, analysis: FileAnalysis, content: str, ctx: ProjectContext
):
    """Extract shared constants and config values."""
    for var_name in analysis.global_vars:
        if var_name.isupper() and len(var_name) > 2:
            # Try to get the value from content
            m = re.search(rf'{re.escape(var_name)}\s*=\s*(.+?)(?:\n|$)', content)
            value = m.group(1).strip()[:80] if m else "(defined)"
            ctx.shared_constants[f"{var_name} ({path})"] = value


# ──────────────────────────────────────────────────────────────
# 6. DATA FLOW TRACING
# ──────────────────────────────────────────────────────────────

def _build_data_flows(analyses: Dict[str, FileAnalysis], ctx: ProjectContext):
    """
    Build high-level data flow maps by connecting:
    API route → handler → validation → DB operation → response
    """
    # Group contracts by resource path (e.g. /api/users)
    resource_groups: Dict[str, List[APIContract]] = {}
    for contract in ctx.api_contracts:
        # Extract the resource from the path: /api/users/:id -> /api/users
        parts = contract.path.strip('/').split('/')
        resource = '/'.join(parts[:3]) if len(parts) >= 2 else contract.path
        resource_groups.setdefault(resource, []).append(contract)

    for resource, contracts in resource_groups.items():
        if len(contracts) < 2:
            continue  # Single route — not interesting as a flow

        methods = sorted(set(c.method for c in contracts))
        files = sorted(set(c.file for c in contracts))
        schemas = []
        for c in contracts:
            if c.body_schema:
                schemas.append(c.body_schema)

        steps = []
        for c in sorted(contracts, key=lambda x: ['GET', 'POST', 'PUT', 'PATCH', 'DELETE'].index(x.method) if x.method in ['GET', 'POST', 'PUT', 'PATCH', 'DELETE'] else 99):
            auth_tag = " (requires auth)" if c.auth_required else ""
            body_tag = f" accepts {c.body_schema}" if c.body_schema else ""
            ret_tag = f" returns {c.return_type}" if c.return_type else ""
            steps.append(f"{c.method} {c.path}{auth_tag}{body_tag}{ret_tag} → {c.handler}()")

        flow = DataFlow(
            name=f"Resource: /{resource}",
            steps=steps,
            files_involved=files,
            schemas_used=schemas,
            endpoints_used=[f"{c.method} {c.path}" for c in contracts],
        )
        ctx.data_flows.append(flow)


# ──────────────────────────────────────────────────────────────
# DE-DUPLICATION
# ──────────────────────────────────────────────────────────────

def _deduplicate_context(ctx: ProjectContext):
    """Remove duplicate entries across all context collections."""
    # API contracts: de-dup by (method, path, file)
    seen = set()
    deduped = []
    for c in ctx.api_contracts:
        key = (c.method, c.path, c.file)
        if key not in seen:
            seen.add(key)
            deduped.append(c)
    ctx.api_contracts = deduped

    # Schemas: de-dup by (name, file)
    seen = set()
    deduped = []
    for s in ctx.schemas:
        key = (s.name, s.file)
        if key not in seen:
            seen.add(key)
            deduped.append(s)
    ctx.schemas = deduped

    # Auth patterns: de-dup by (kind, file)
    seen = set()
    deduped = []
    for a in ctx.auth_patterns:
        key = (a.kind, a.file)
        if key not in seen:
            seen.add(key)
            deduped.append(a)
    ctx.auth_patterns = deduped

    # Env vars: de-dup by name
    seen = set()
    deduped = []
    for name, cat in ctx.env_vars_required:
        if name not in seen:
            seen.add(name)
            deduped.append((name, cat))
    ctx.env_vars_required = deduped
