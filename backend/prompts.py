"""
Lazarus Engine - ABSOLUTE PRESERVATION Code Generation Prompts
Version 7.0 - MULTI-BATCH EFFICIENT ARCHITECTURE

This module contains all prompts used by the Lazarus Engine.
The core philosophy: COPY ALL ORIGINAL CODE, ONLY CHANGE STYLING.

Version 7.0 adds multi-batch processing to handle large repositories
without exceeding API token limits.
"""


# ═══════════════════════════════════════════════════════════════════════════════
# BATCH ARCHITECTURE PROMPTS (NEW - v7.0)
# ═══════════════════════════════════════════════════════════════════════════════

def get_lightweight_plan_prompt(
    repo_url: str,
    instructions: str,
    file_paths: list,
    tech_stack: dict,
    api_endpoints: list,
    must_preserve: list,
    can_modernize: list,
) -> str:
    """
    Lightweight architecture prompt that sends ONLY file paths and metadata.
    NO full file contents - just structure, tech stack, and endpoints.
    This keeps the prompt small so planning never hits token limits.
    
    Returns a structured plan with file groupings for batch processing.
    """
    file_count = len(file_paths)
    
    # Build concise file tree
    file_tree = "\n".join([f"  {i+1}. {p}" for i, p in enumerate(file_paths)])
    
    # Build endpoint summary
    endpoint_summary = "\n".join([f"  - {ep}" for ep in api_endpoints[:30]]) if api_endpoints else "  [None detected]"
    
    # Build preservation summary
    preserve_summary = "\n".join([f"  - {item}" for item in must_preserve[:20]]) if must_preserve else "  [None]"
    modernize_summary = "\n".join([f"  - {item}" for item in can_modernize[:20]]) if can_modernize else "  [None]"
    
    return f"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  LAZARUS ENGINE - PRESERVATION-FIRST ARCHITECTURE ANALYSIS                  ║
║  VERSION: 7.0 - LIGHTWEIGHT PLANNING (NO FILE CONTENTS)                     ║
╚══════════════════════════════════════════════════════════════════════════════╝

ROLE: You are an elite architect analyzing an existing codebase for enhancement.
You will ONLY receive file paths and metadata - NOT file contents.
Your job is to create a detailed enhancement plan with FILE GROUPINGS for batch processing.

═══════════════════════════════════════════════════════════════════════════════
📦 REPOSITORY OVERVIEW
═══════════════════════════════════════════════════════════════════════════════

Repository URL: {repo_url}
User Instructions: "{instructions if instructions else 'Modernize UI while preserving all functionality'}"
Total Files: {file_count}

DETECTED TECH STACK:
- Backend Framework: {tech_stack.get('backend', {}).get('framework', 'Unknown')}
- Database: {tech_stack.get('backend', {}).get('database', 'Unknown')}
- Frontend Framework: {tech_stack.get('frontend', {}).get('framework', 'Unknown')}
- Languages: {tech_stack.get('languages', [])}

🔒 MUST PRESERVE:
{preserve_summary}

✅ CAN MODERNIZE:
{modernize_summary}

API ENDPOINTS:
{endpoint_summary}

═══════════════════════════════════════════════════════════════════════════════
📂 FILE TREE (ALL {file_count} FILES):
═══════════════════════════════════════════════════════════════════════════════
{file_tree}

═══════════════════════════════════════════════════════════════════════════════
📋 YOUR TASK - CREATE AN ENHANCEMENT PLAN
═══════════════════════════════════════════════════════════════════════════════

Create a PRESERVATION-FIRST enhancement plan with these sections:

1. **PRESERVATION AUDIT**: List all functionality, endpoints, database connections that MUST stay identical.

2. **ENHANCEMENT STRATEGY**: What visual/performance improvements to apply (CSS, modern syntax, error handling).

3. **FILE GROUPINGS FOR BATCH PROCESSING**: 
   Group ALL {file_count} files into logical batches of 5-10 files each.
   Files that depend heavily on each other should be in the SAME batch.
   
   Format your groupings EXACTLY like this:
   
   BATCH 1 - [descriptive name, e.g. "Backend Core"]:
   - path/to/file1.js
   - path/to/file2.js
   
   BATCH 2 - [descriptive name, e.g. "Frontend Pages"]:
   - path/to/page1.html
   - path/to/page2.html
   
   (continue for all files)

4. **SHARED INTERFACES**: List key exports, types, or interfaces that are shared across files.
   These will be provided to each batch for cross-file coherence.

5. **ENTRYPOINT & RUNTIME**: Which file is the main entrypoint and what runtime (node/python).

⚠️ CRITICAL RULES:
- EVERY file from the file tree MUST appear in exactly ONE batch
- Do NOT suggest changing the framework (Express stays Express, etc.)
- Do NOT suggest changing the database
- KEEP the same file paths
- Group tightly-coupled files together (e.g., server + its route handlers)
- Config files (package.json, .env, etc.) should be in a "Config" batch

Output format: Plain text with clear section headers.
"""


def get_batch_code_generation_prompt(
    plan: str,
    batch_files: list,
    batch_index: int,
    total_batches: int,
    batch_name: str,
    all_file_paths: list,
    previously_generated_summaries: str,
    memory_context: str = "",
) -> str:
    """
    Per-batch code generation prompt. Only includes the FULL contents
    of files in THIS batch, plus summaries from previous batches.
    
    Args:
        plan: The overall modernization plan
        batch_files: List of file dicts with 'path', 'content', 'language' for THIS batch
        batch_index: 0-based index of current batch
        total_batches: Total number of batches
        batch_name: Descriptive name for this batch
        all_file_paths: ALL file paths across the entire repo (for cross-reference)
        previously_generated_summaries: Summaries of exports/interfaces from earlier batches
        memory_context: Past resurrection memory
    """
    batch_count = len(batch_files)
    
    # Build the file contents for THIS batch only
    batch_code_context = ""
    for f in batch_files:
        batch_code_context += f"""
████████████████████████████████████████████████████████████████████████████████
█ ORIGINAL FILE: {f['path']}
█ COPY THIS FILE COMPLETELY, ONLY ENHANCE STYLING
████████████████████████████████████████████████████████████████████████████████

```{f.get('language', 'text')}
{f['content']}
```

"""
    
    # Build full file manifest (paths only, for cross-reference)
    all_paths_list = "\n".join([f"  - {p}" for p in all_file_paths])
    
    return f"""
████████████████████████████████████████████████████████████████████████████████
█  LAZARUS ENGINE - BATCH CODE GENERATION                                      █
█  BATCH {batch_index + 1} OF {total_batches}: {batch_name}                    █
█  FILES IN THIS BATCH: {batch_count}                                          █
████████████████████████████████████████████████████████████████████████████████

{memory_context if memory_context else ""}

🚨 CRITICAL INSTRUCTION:
You are generating ENHANCED versions of {batch_count} files.
This is batch {batch_index + 1} of {total_batches} total batches.
Other batches handle the remaining files - DO NOT generate files outside this batch.

THE GOLDEN RULE:
"COPY EVERYTHING. CHANGE ONLY HOW IT LOOKS, NOT WHAT IT DOES."

═══════════════════════════════════════════════════════════════════════════════
OVERALL ENHANCEMENT PLAN:
═══════════════════════════════════════════════════════════════════════════════

{plan}

═══════════════════════════════════════════════════════════════════════════════
ALL FILES IN THE REPOSITORY (for cross-reference):
═══════════════════════════════════════════════════════════════════════════════
{all_paths_list}

═══════════════════════════════════════════════════════════════════════════════
CONTEXT FROM PREVIOUSLY GENERATED BATCHES:
═══════════════════════════════════════════════════════════════════════════════
{previously_generated_summaries if previously_generated_summaries else "[This is the first batch - no previous context]"}

═══════════════════════════════════════════════════════════════════════════════
FILES TO GENERATE IN THIS BATCH ({batch_count} files):
═══════════════════════════════════════════════════════════════════════════════

{batch_code_context}

═══════════════════════════════════════════════════════════════════════════════
OUTPUT FORMAT:
═══════════════════════════════════════════════════════════════════════════════

Output EXACTLY {batch_count} files in this XML format:

<file path="[EXACT ORIGINAL PATH]">
[COMPLETE ENHANCED FILE CONTENT]
</file>

RULES FOR THIS BATCH:
1. Generate ONLY the {batch_count} files listed above - no extras
2. Use EXACT ORIGINAL file paths
3. Include COMPLETE file content - NO placeholders, NO "// ... rest of code ..."
4. COPY all functions, endpoints, handlers from originals
5. KEEP the same imports/requires (adjust paths if needed)
6. When importing from files in OTHER batches, use the same import paths as the original
7. ENHANCE: CSS styling, modern syntax (var→const), error handling, comments
8. DO NOT change database type, API endpoints, or core logic

═══════════════════════════════════════════════════════════════════════════════
SERVER FILE RULES (if this batch contains server files):
═══════════════════════════════════════════════════════════════════════════════
- COPY EVERY app.get(), app.post(), app.put(), app.delete()
- COPY EVERY route handler and database query
- **CRITICAL**: Server MUST run on port 8000 (not 5000, 3000, or any other port)
  * FastAPI: uvicorn.run(app, host="0.0.0.0", port=8000)
  * Flask: app.run(host="0.0.0.0", port=8000)
- **CRITICAL**: Backend must be API-ONLY (return JSON, NOT HTML)
  * DO NOT serve static files (no app.static(), StaticFiles, send_file, etc.)
  * DO NOT return HTML responses (only JSON)
  * Frontend files (index.html, .css, .js) should be separate
  * All API endpoints should return JSON: {{"status": "ok", "data": [...]}}
- **CORS CONFIGURATION**: Enable CORS for all origins
  * FastAPI: app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
  * Flask: CORS(app, resources={{r"/*": {{"origins": "*"}}}})
- **MOCK DATA SEEDING**: Auto-populate database with sample data on startup
  * Add initialization function that runs before server starts
  * Insert 5-10 sample records (posts, users, products, etc.)
  * Example: if database is empty, insert sample blog posts
  * This ensures frontend shows data immediately without manual setup
  * See code examples in server rules below
- KEEP the same middleware
- ADD: better error handling, logging, comments

MOCK DATA EXAMPLE (Flask/SQLite):
```python
def init_db():
    if Post.query.count() == 0:
        samples = [Post(title="Welcome", content="Sample", author="Admin") for i in range(5)]
        db.session.add_all(samples)
        db.session.commit()

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        init_db()
    app.run(host="0.0.0.0", port=8000)
```

MOCK DATA EXAMPLE (FastAPI/JSON):
```python
def init_data():
    if not os.path.exists("data.json"):
        json.dump([{{"id": i, "title": f"Post {{i}}"}} for i in range(1,6)], open("data.json","w"))
init_data()
```

═══════════════════════════════════════════════════════════════════════════════
FRONTEND-BACKEND CONNECTION (CRITICAL - READ EVERY LINE!)
═══════════════════════════════════════════════════════════════════════════════
The frontend and backend run on COMPLETELY SEPARATE domains (not localhost!).
The backend URL is injected at deploy time. You MUST use a variable, NEVER a hardcoded URL.

⚠️  ABSOLUTE RULES (violating ANY of these will break the app):
  1. NEVER write `http://localhost:8000` or `http://127.0.0.1:8000` ANYWHERE in frontend code
  2. NEVER write `http://localhost:5000` or ANY `http://localhost:XXXX` in frontend code
  3. NEVER write `http://0.0.0.0:8000` in frontend code
  4. ALWAYS define API_BASE_URL as a variable at the TOP of EVERY file that makes API calls
  5. ALWAYS use that variable for ALL fetch/axios/XMLHttpRequest calls

- **For plain HTML/JS (MOST COMMON)**: 
  ```const API_BASE_URL = window.__API_BASE_URL__ || '';```
  Then use: `fetch(API_BASE_URL + '/api/posts')`
  The empty string fallback means relative URLs (works when same-origin).

- **For Next.js/React**: 
  ```const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || '';```

- **For Vite**: 
  ```const API_BASE_URL = import.meta.env.VITE_API_URL || '';```

- **ENDPOINT CONSISTENCY**: Frontend calls must match backend routes exactly
  * If backend has `/api/posts`, frontend must call `API_BASE_URL + '/api/posts'`
  * If backend has `/login`, frontend must call `API_BASE_URL + '/login'`

- **ERROR HANDLING**: Add try-catch and user-friendly errors
  * Check response.ok before parsing JSON
  * Display errors in UI (not just console.log)

- **CORS**: The backend MUST include CORS headers since frontend and backend are on different domains:
  * Python Flask: `from flask_cors import CORS; CORS(app)`
  * Python FastAPI: `app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])`
  * Node/Express: `app.use(cors())` or manually set `Access-Control-Allow-Origin: *`
  * Python http.server: Add `self.send_header('Access-Control-Allow-Origin', '*')` to ALL responses

FRONTEND API CALL EXAMPLE (Next.js / React):
```javascript
// CRITICAL: Use env variable, NEVER hardcode localhost
const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || '';

async function loadPosts() {{
    try {{
        const response = await fetch(`${{API_BASE_URL}}/api/posts`);
        if (!response.ok) throw new Error(`HTTP ${{response.status}}`);
        const data = await response.json();
        displayPosts(data.posts || data);
    }} catch (error) {{
        document.getElementById('error').textContent = 'Failed to load posts: ' + error.message;
    }}
}}
```

FRONTEND API CALL EXAMPLE (Plain HTML/JS — PREFERRED PATTERN):
```javascript
// CRITICAL: Use window.__API_BASE_URL__ which is injected at deploy time
// The empty string fallback means relative URL (works when same-origin)
const API_BASE_URL = window.__API_BASE_URL__ || '';

async function loadPosts() {{
    try {{
        const response = await fetch(`${{API_BASE_URL}}/api/posts`);
        if (!response.ok) throw new Error(`HTTP ${{response.status}}`);
        const data = await response.json();
        displayPosts(data.posts || data);
    }} catch (error) {{
        document.getElementById('error').textContent = 'Failed to load: ' + error.message;
    }}
}}
```

⚠️ WRONG (will break in production):
```javascript
// ❌ WRONG: const API_BASE_URL = 'http://localhost:8000';
// ❌ WRONG: fetch('http://127.0.0.1:8000/api/posts')
// ✅ RIGHT: const API_BASE_URL = window.__API_BASE_URL__ || '';
// ✅ RIGHT: fetch(API_BASE_URL + '/api/posts')
```

═══════════════════════════════════════════════════════════════════════════════
HTML FILE RULES (if this batch contains HTML files):
═══════════════════════════════════════════════════════════════════════════════
- COPY every element, form field, button, input
- KEEP all JavaScript in <script> tags and event handlers
- ENHANCE: modern CSS, responsive design, better styling

═══════════════════════════════════════════════════════════════════════════════
CSS ENHANCEMENT:
═══════════════════════════════════════════════════════════════════════════════
- CSS variables for theming
- Dark mode support
- Modern color palette
- Smooth transitions and animations
- Responsive breakpoints

═══════════════════════════════════════════════════════════════════════════════
PERFORMANCE OPTIMIZATION:
═══════════════════════════════════════════════════════════════════════════════
- You MAY optimize slow code, but OUTPUT MUST REMAIN IDENTICAL
- Replace nested loops with efficient algorithms
- Add caching for repeated operations
- Use Map/Set for lookups
- But NEVER change what data is returned or API response structure

═══════════════════════════════════════════════════════════════════════════════
NOW GENERATE ALL {batch_count} ENHANCED FILES FOR THIS BATCH
═══════════════════════════════════════════════════════════════════════════════
"""


def extract_batch_summary(generated_files: list) -> str:
    """
    V2 Phase 2: Intelligent Batch Summary Extraction
    
    Produces STRUCTURED summaries instead of raw code snippets:
      - Routes (method, path, handler)
      - Schemas/Models (name, fields)
      - Exports (name, kind)
      - Imports (what this batch needs from others)
      - Version tag per batch output
    
    Also detects potential breaking changes (missing routes, changed schemas).
    """
    summaries = []
    batch_routes = []
    batch_schemas = []
    batch_exports = []
    batch_imports = []

    for f in generated_files:
        path = f.get('filename', f.get('path', 'unknown'))
        content = f.get('content', '')

        file_routes = []
        file_schemas = []
        file_exports = []
        file_imports = []

        for line in content.split('\n'):
            stripped = line.strip()

            # ── Routes ──
            import re as _re
            route_match = _re.match(
                r"""(?:app|router|server)\.(get|post|put|delete|patch|options|all)\s*\(\s*['"]([^'"]+)['"]""",
                stripped, _re.IGNORECASE
            )
            if route_match:
                method = route_match.group(1).upper()
                route_path = route_match.group(2)
                file_routes.append(f"{method} {route_path}")
                batch_routes.append(f"{method} {route_path} (in {path})")

            # Python decorators for routes
            py_route = _re.match(
                r"""@(?:app|router|bp)\.(get|post|put|delete|patch|route)\s*\(\s*['"]([^'"]+)['"]""",
                stripped
            )
            if py_route:
                method = py_route.group(1).upper()
                if method == 'ROUTE':
                    method = 'GET'
                route_path = py_route.group(2)
                file_routes.append(f"{method} {route_path}")
                batch_routes.append(f"{method} {route_path} (in {path})")

            # ── Schemas / Models ──
            schema_match = _re.match(
                r'class\s+(\w+)\s*\(.*(?:BaseModel|Schema|Model|Document|Base|Form)\w*',
                stripped
            )
            if schema_match:
                file_schemas.append(schema_match.group(1))
                batch_schemas.append(f"{schema_match.group(1)} (in {path})")

            # TypeScript interfaces
            ts_interface = _re.match(r'(?:export\s+)?interface\s+(\w+)', stripped)
            if ts_interface:
                file_schemas.append(ts_interface.group(1))
                batch_schemas.append(f"{ts_interface.group(1)} (in {path})")

            # ── Exports ──
            if any(stripped.startswith(kw) for kw in [
                'export ', 'module.exports', 'exports.',
            ]):
                # Extract the exported name
                exp_match = _re.match(
                    r'export\s+(?:default\s+)?(?:const|let|var|function|class|async\s+function|interface|type|enum)\s+(\w+)',
                    stripped
                )
                if exp_match:
                    file_exports.append(exp_match.group(1))
                    batch_exports.append(f"{exp_match.group(1)} (from {path})")

            # Python top-level definitions (implicit exports)
            py_def = _re.match(r'(?:async\s+)?def\s+(\w+)\s*\(', stripped)
            if py_def and not stripped.startswith(' ') and not stripped.startswith('\t'):
                name = py_def.group(1)
                if not name.startswith('_'):
                    file_exports.append(name)
                    batch_exports.append(f"{name}() (from {path})")

            py_class = _re.match(r'class\s+(\w+)', stripped)
            if py_class and not stripped.startswith(' ') and not stripped.startswith('\t'):
                file_exports.append(py_class.group(1))
                batch_exports.append(f"{py_class.group(1)} (from {path})")

            # ── Imports ──
            if stripped.startswith(('import ', 'from ', 'require(')):
                file_imports.append(stripped[:120])
                batch_imports.append(stripped[:120])

        # Build per-file structured summary
        parts = [f"\n── {path} ──"]
        if file_routes:
            parts.append(f"  ROUTES: {', '.join(file_routes[:10])}")
        if file_schemas:
            parts.append(f"  SCHEMAS: {', '.join(file_schemas[:10])}")
        if file_exports:
            parts.append(f"  EXPORTS: {', '.join(file_exports[:15])}")
        if not (file_routes or file_schemas or file_exports):
            parts.append("  [config/static/utility file]")
        summaries.append("\n".join(parts))

    # Build batch-level structured overview
    overview_parts = ["═══ BATCH STRUCTURED SUMMARY ═══"]
    if batch_routes:
        overview_parts.append(f"TOTAL ROUTES ({len(batch_routes)}):")
        for r in batch_routes[:20]:
            overview_parts.append(f"  → {r}")
        if len(batch_routes) > 20:
            overview_parts.append(f"  ... +{len(batch_routes) - 20} more")
    if batch_schemas:
        overview_parts.append(f"TOTAL SCHEMAS ({len(batch_schemas)}):")
        for s in batch_schemas[:15]:
            overview_parts.append(f"  □ {s}")
    if batch_exports:
        overview_parts.append(f"TOTAL EXPORTS ({len(batch_exports)}):")
        for e in batch_exports[:20]:
            overview_parts.append(f"  ▸ {e}")
        if len(batch_exports) > 20:
            overview_parts.append(f"  ... +{len(batch_exports) - 20} more")
    overview_parts.append("═══ END BATCH SUMMARY ═══")

    return "\n".join(overview_parts) + "\n\n" + "\n".join(summaries)


def _detect_batch_breaking_changes(
    previous_summaries: str,
    new_summary: str,
) -> list:
    """
    Compare new batch summary against previous summaries to detect
    potential breaking changes (for logging/warning).
    
    Returns list of warning strings.
    """
    import re as _re
    warnings = []

    # Extract previously declared routes
    prev_routes = set(_re.findall(r'→\s*(GET|POST|PUT|DELETE|PATCH)\s+(\S+)', previous_summaries))
    new_routes = set(_re.findall(r'→\s*(GET|POST|PUT|DELETE|PATCH)\s+(\S+)', new_summary))

    # Check if new batch overwrites a route from a previous batch
    for method, path in new_routes:
        if (method, path) in prev_routes:
            warnings.append(f"Route {method} {path} was already generated in a previous batch — possible duplicate")

    return warnings


# ═══════════════════════════════════════════════════════════════════════════════
# ORIGINAL SINGLE-SHOT PROMPT (FALLBACK for small repos < 10 files)
# ═══════════════════════════════════════════════════════════════════════════════

def get_code_generation_prompt(plan: str, deep_scan_result: dict = None, memory_context: str = "") -> str:
    """
    Returns the ABSOLUTE PRESERVATION code generation prompt.
    Key principle: COPY every line of code, only enhance CSS/styling.
    
    Args:
        plan: The modernization plan
        deep_scan_result: Results from deep scanning the repository
        memory_context: Past resurrection memory for this repository
    """
    
    # Build list of ALL files that MUST be output
    file_list = ""
    existing_code_context = ""
    total_files = 0
    total_endpoints = 0
    
    if deep_scan_result:
        files = deep_scan_result.get("files", [])
        tech_stack = deep_scan_result.get("tech_stack", {})
        must_preserve = deep_scan_result.get("must_preserve", [])
        api_endpoints = deep_scan_result.get("api_endpoints", [])
        total_files = len(files)
        total_endpoints = len(api_endpoints)
        
        # Build MANDATORY file list - ALL files must be output!
        file_list = ""
        for i, f in enumerate(files, 1):
            file_list += f"  {i}. {f['path']}\n"
        
        # Build file contents - COMPLETE, NO TRUNCATION
        for f in files:
            existing_code_context += f"""
████████████████████████████████████████████████████████████████████████████████
█ ORIGINAL FILE #{files.index(f) + 1}: {f['path']}
█ COPY THIS FILE COMPLETELY, ONLY ENHANCE STYLING
████████████████████████████████████████████████████████████████████████████████

```{f['language']}
{f['content']}
```

⚠️ YOU MUST OUTPUT THIS ENTIRE FILE WITH SAME FUNCTIONALITY!
"""
        
        # Build endpoint list
        endpoint_list = ""
        for i, ep in enumerate(api_endpoints, 1):
            endpoint_list += f"  {i}. {ep}\n"
        
        preservation_rules = f"""

████████████████████████████████████████████████████████████████████████████████
█ CRITICAL: ABSOLUTE PRESERVATION REQUIREMENTS
████████████████████████████████████████████████████████████████████████████████

📊 REPOSITORY STATISTICS:
   - Total Files: {total_files}
   - Total API Endpoints: {total_endpoints}

⚠️ YOU MUST OUTPUT ALL {total_files} FILES!
⚠️ YOU MUST PRESERVE ALL {total_endpoints} API ENDPOINTS!

FILES YOU MUST OUTPUT (EVERY SINGLE ONE):
{file_list}

API ENDPOINTS YOU MUST PRESERVE (EVERY SINGLE ONE):
{endpoint_list if endpoint_list else "  [Detect from server files and preserve all]"}

DATABASE: {tech_stack.get('backend', {}).get('database', 'Unknown')}
>> KEEP THE SAME DATABASE! COPY THE EXACT CONNECTION CODE! <<

████████████████████████████████████████████████████████████████████████████████
█ ALL ORIGINAL FILES (COPY EACH ONE COMPLETELY):
████████████████████████████████████████████████████████████████████████████████
{existing_code_context}
"""
    else:
        preservation_rules = """
[WARNING: No deep scan available. Generate from plan only.]
"""
        total_files = 0
    
    return f"""
████████████████████████████████████████████████████████████████████████████████
█  LAZARUS ENGINE - ABSOLUTE PRESERVATION MODE                                █
█  VERSION: 6.0 - COPY EVERYTHING, ENHANCE APPEARANCE ONLY                   █
████████████████████████████████████████████████████████████████████████████████

{memory_context if memory_context else ""}

🚨 CRITICAL INSTRUCTION - READ CAREFULLY:
═══════════════════════════════════════════════════════════════════════════════

YOU ARE NOT CREATING A NEW APPLICATION.
YOU ARE ENHANCING AN EXISTING APPLICATION.

THIS MEANS:
1. COPY every single file from the original repository
2. COPY every single function, endpoint, and feature
3. COPY every single line of business logic
4. ONLY CHANGE: CSS styling, colors, fonts, visual appearance

THE GOLDEN RULE:
"COPY EVERYTHING. CHANGE ONLY HOW IT LOOKS, NOT WHAT IT DOES."

═══════════════════════════════════════════════════════════════════════════════
WHAT "ENHANCEMENT" MEANS (AND DOES NOT MEAN):
═══════════════════════════════════════════════════════════════════════════════

✅ ENHANCEMENT (DO THIS):
- Copy the entire original file
- Keep ALL functions exactly as they are
- Keep ALL API endpoints exactly as they are
- Keep ALL database queries exactly as they are
- ADD modern CSS (better colors, fonts, animations)
- ADD responsive design
- IMPROVE code formatting (var → const, callbacks → async/await)

❌ NOT ENHANCEMENT (DO NOT DO THIS):
- Creating a new file with only some features
- Summarizing the original code
- Removing endpoints because "they're not needed"
- Changing database type
- Changing the framework
- Creating fewer files than the original

═══════════════════════════════════════════════════════════════════════════════
MANDATORY FILE COUNT CHECK:
═══════════════════════════════════════════════════════════════════════════════

ORIGINAL REPOSITORY HAS: {total_files} FILES
YOUR OUTPUT MUST HAVE: {total_files} FILES (OR MORE)

IF YOUR OUTPUT HAS FEWER FILES, YOU HAVE FAILED.

═══════════════════════════════════════════════════════════════════════════════
SECTION 1: MODERNIZATION PLAN
═══════════════════════════════════════════════════════════════════════════════

{plan}

{preservation_rules}

═══════════════════════════════════════════════════════════════════════════════
SECTION 2: OUTPUT FORMAT
═══════════════════════════════════════════════════════════════════════════════

Output EVERY file in this exact XML format:

<file path="[EXACT ORIGINAL PATH]">
[COMPLETE ENHANCED FILE CONTENT]
</file>

EXAMPLE - For a file originally at "Home/Home/adminserver.js":

<file path="Home/Home/adminserver.js">
// ENHANCED VERSION - All original functionality preserved
const express = require('express');
const mongoose = require('mongoose');
// ... EVERY SINGLE LINE OF THE ORIGINAL, WITH IMPROVEMENTS ...
</file>

RULES:
- Use EXACT ORIGINAL file paths
- Include COMPLETE file content
- NO placeholders, NO "// ... rest of code ..."
- NO markdown code blocks inside the XML
- EVERY function from original must be present
- EVERY endpoint from original must be present

═══════════════════════════════════════════════════════════════════════════════
SECTION 3: SERVER FILE RULES (CRITICAL!)
═══════════════════════════════════════════════════════════════════════════════

When enhancing server files (server.js, adminserver.js, etc.):

1. COPY EVERY app.get(), app.post(), app.put(), app.delete() from original
2. COPY EVERY route handler function from original
3. COPY EVERY database connection/query from original
4. **SERVER PORT**: MUST be 8000 (not 5000, 3000, or any other port)
   - FastAPI: uvicorn.run(app, host="0.0.0.0", port=8000)
   - Flask: app.run(host="0.0.0.0", port=8000)
5. **API-ONLY BACKEND**: Backend must ONLY return JSON (NO HTML serving)
   - DO NOT serve static files (no app.static(), StaticFiles, send_file for HTML/CSS/JS)
   - DO NOT return render_template() or HTML responses
   - ALL API endpoints must return JSON: {{"status": "ok", "data": [...]}}
   - Frontend files (index.html, style.css, app.js) are separate from backend
6. **CORS CONFIGURATION**: Enable CORS for all origins
   - FastAPI: app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
   - Flask: CORS(app, resources={{r"/*": {{"origins": "*"}}}})
7. **MOCK DATA SEEDING**: Auto-populate database with sample data on startup
   - Add initialization function that runs BEFORE server starts
   - Insert 5-10 sample records (posts, users, products, etc.)
   - Example: if database is empty, insert sample data
   - This ensures frontend shows data immediately without manual setup
   
   **Example for Flask/SQLite**:
   ```python
   def init_db():
       if Post.query.count() == 0:  # Only if empty
           sample_posts = [
               Post(title="Welcome Post", content="This is sample content", author="Admin"),
               Post(title="Getting Started", content="Sample blog post", author="User"),
               # ... 5-10 sample posts
           ]
           db.session.add_all(sample_posts)
           db.session.commit()
   
   if __name__ == "__main__":
       with app.app_context():
           db.create_all()
           init_db()  # Seed before starting
       app.run(host="0.0.0.0", port=8000)
   ```
   
   **Example for FastAPI/JSON file**:
   ```python
   def init_data():
       if not os.path.exists("posts.json") or os.path.getsize("posts.json") == 0:
           sample_data = [
               {{"id": 1, "title": "Welcome", "content": "Sample post"}},
               {{"id": 2, "title": "Tutorial", "content": "How to use"}},
               # ... 5-10 samples
           ]
           with open("posts.json", "w") as f:
               json.dump(sample_data, f)
   
   init_data()  # Run before starting server
   ```

8. KEEP the same middleware
9. You may ADD: better error handling, logging, comments

═══════════════════════════════════════════════════════════════════════════════
SECTION 3.5: FRONTEND-BACKEND CONNECTION (CRITICAL - READ EVERY LINE!)
═══════════════════════════════════════════════════════════════════════════════

The frontend and backend run on COMPLETELY SEPARATE domains (not localhost!).
The backend URL is injected at deploy time. You MUST use a variable, NEVER a hardcoded URL.

⚠️  ABSOLUTE RULES (violating ANY will break the app):
  1. NEVER write `http://localhost:8000` or `http://127.0.0.1:8000` ANYWHERE in frontend code
  2. NEVER write `http://localhost:5000` or ANY `http://localhost:XXXX` in frontend code
  3. ALWAYS define API_BASE_URL as a variable at the TOP of EVERY file that makes API calls
  4. ALWAYS use that variable for ALL fetch/axios/XMLHttpRequest calls

- **For plain HTML/JS**: `const API_BASE_URL = window.__API_BASE_URL__ || '';`
- **For Next.js/React**: `const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || '';`
- **For Vite**: `const API_BASE_URL = import.meta.env.VITE_API_URL || '';`

- **ENDPOINT CONSISTENCY**: Frontend calls must match backend routes EXACTLY
  * `fetch(API_BASE_URL + '/api/posts')` NOT `fetch('http://localhost:8000/api/posts')`

- **CORS**: Backend MUST include CORS headers:
  * Flask: `from flask_cors import CORS; CORS(app)`
  * FastAPI: `app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])`
  * Express: `app.use(cors())`

- **ERROR HANDLING**: Add try-catch and user-friendly errors

FRONTEND API CALL EXAMPLE (Next.js / React):
```javascript
// CRITICAL: Use env variable, NEVER hardcode localhost
const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || '';

async function loadPosts() {{
    try {{
        const response = await fetch(`${{API_BASE_URL}}/api/posts`);
        if (!response.ok) throw new Error(`HTTP ${{response.status}}`);
        const data = await response.json();
        displayPosts(data.posts || data);
    }} catch (error) {{
        document.getElementById('error').textContent = 'Failed to load: ' + error.message;
    }}
}}
```

FRONTEND API CALL EXAMPLE (Plain HTML/JS — PREFERRED PATTERN):
```javascript
// CRITICAL: window.__API_BASE_URL__ is injected at deploy time
const API_BASE_URL = window.__API_BASE_URL__ || '';

async function loadPosts() {{
    try {{
        const response = await fetch(`${{API_BASE_URL}}/api/posts`);
        if (!response.ok) throw new Error(`HTTP ${{response.status}}`);
        const data = await response.json();
        displayPosts(data.posts || data);
    }} catch (error) {{
        document.getElementById('error').textContent = 'Failed to load: ' + error.message;
    }}
}}
```

⚠️ WRONG (will break):
```javascript
// ❌ WRONG: fetch('http://localhost:8000/api/posts')
// ❌ WRONG: const API_BASE_URL = 'http://127.0.0.1:8000';
// ✅ RIGHT: const API_BASE_URL = window.__API_BASE_URL__ || '';
// ✅ RIGHT: fetch(API_BASE_URL + '/api/posts')
```

═══════════════════════════════════════════════════════════════════════════════
SERVER ENDPOINT PRESERVATION EXAMPLES:
═══════════════════════════════════════════════════════════════════════════════

WRONG (Missing endpoints):
```javascript
app.get('/', (req, res) => res.send('Hello'));
// Only 1 endpoint when original had 20!
```

CORRECT (All endpoints preserved):
```javascript
app.get('/', (req, res) => res.send('Hello'));
app.get('/users', async (req, res) => {{ /* COPY FROM ORIGINAL */ }});
app.post('/login', async (req, res) => {{ /* COPY FROM ORIGINAL */ }});
app.get('/admin', (req, res) => {{ /* COPY FROM ORIGINAL */ }});
// ... ALL 20 endpoints from original!
```

═══════════════════════════════════════════════════════════════════════════════
SECTION 4: HTML FILE RULES
═══════════════════════════════════════════════════════════════════════════════

When enhancing HTML files:

1. COPY every single element from the original
2. KEEP all form fields, buttons, inputs
3. KEEP all JavaScript in <script> tags
4. KEEP all event handlers
5. ENHANCE: Add modern CSS classes, better styling
6. ENHANCE: Add responsive meta tags
7. ENHANCE: Link to modern CSS file

═══════════════════════════════════════════════════════════════════════════════
SECTION 5: CSS ENHANCEMENT
═══════════════════════════════════════════════════════════════════════════════

CREATE OR ENHANCE a modern CSS file with:
- CSS variables for theming
- Dark mode support
- Modern color palette (not basic red/blue/green)
- Smooth transitions and animations
- Glassmorphism effects
- Modern fonts (Inter, Roboto, etc.)
- Responsive breakpoints

═══════════════════════════════════════════════════════════════════════════════
SECTION 6: PERFORMANCE OPTIMIZATION (STRICT OUTPUT PRESERVATION)
═══════════════════════════════════════════════════════════════════════════════

You MAY optimize slow code for better performance, BUT:

🔴 THE GOLDEN RULE: OUTPUT MUST REMAIN IDENTICAL!
If a function returns [1, 2, 3] before optimization, it MUST return [1, 2, 3] after.

ALLOWED OPTIMIZATIONS:
✅ Replace nested loops with single-pass algorithms
✅ Add caching for repeated expensive operations
✅ Use Map/Set instead of arrays for lookups
✅ Replace synchronous I/O with async where safe
✅ Batch database queries instead of N+1 queries
✅ Use pagination for large data fetches
✅ Add indexes hint in comments for databases
✅ Replace string concatenation with template literals
✅ Use array methods (map, filter, reduce) instead of for loops

NOT ALLOWED:
❌ Changing what data is returned
❌ Changing the order of returned data (unless explicitly unordered)
❌ Removing any functionality
❌ Changing API response structure
❌ Changing database schema

EXAMPLE - Before (Slow):
```javascript
// O(n²) - Slow for large arrays
function findDuplicates(arr) {{
  const duplicates = [];
  for (let i = 0; i < arr.length; i++) {{
    for (let j = i + 1; j < arr.length; j++) {{
      if (arr[i] === arr[j] && !duplicates.includes(arr[i])) {{
        duplicates.push(arr[i]);
      }}
    }}
  }}
  return duplicates;
}}
```

EXAMPLE - After (Optimized, SAME OUTPUT):
```javascript
// O(n) - Optimized with Set
function findDuplicates(arr) {{
  const seen = new Set();
  const duplicates = new Set();
  for (const item of arr) {{
    if (seen.has(item)) {{
      duplicates.add(item);
    }} else {{
      seen.add(item);
    }}
  }}
  return [...duplicates]; // SAME OUTPUT as before!
}}
```

═══════════════════════════════════════════════════════════════════════════════
FINAL VERIFICATION BEFORE OUTPUT:
═══════════════════════════════════════════════════════════════════════════════

Before generating output, verify:
□ You are outputting ALL {total_files} files
□ Every server file has ALL original endpoints
□ Every HTML file has ALL original elements
□ Every file uses its ORIGINAL path
□ No functionality has been removed
□ Only styling/appearance has been changed
□ Optimizations preserve exact output behavior

═══════════════════════════════════════════════════════════════════════════════
NOW GENERATE ALL {total_files} ENHANCED FILES
═══════════════════════════════════════════════════════════════════════════════

Output every single file now.
Copy all functionality.
Enhance only appearance.
"""
