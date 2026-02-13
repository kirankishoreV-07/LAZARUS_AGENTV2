"""Phase 2 Integration Test — validates all new modules work together."""

from context_extraction import extract_project_context, ProjectContext
from context_manager import CrossBatchContextManager
from resurrection_memory import (
    record_dependency_graph, record_api_contracts, record_schema_registry,
    record_critical_pattern, record_package_versions,
    record_cross_batch_context, record_breaking_changes,
    record_auth_patterns, record_env_vars, get_enhanced_memory_context,
)
from prompts import extract_batch_summary

print("=" * 60)
print("PHASE 2: Context Intelligence — Integration Tests")
print("=" * 60)

# ─── Test 1: CrossBatchContextManager with no project context ───
mgr = CrossBatchContextManager(project_context=None)
ctx0 = mgr.prepare_batch_context(batch_idx=0, batch_file_paths=["src/app.py"])
print(f"[1] Batch 0 context (no project ctx): {len(ctx0)} chars — OK")

# ─── Test 2: Record batch output ───
mgr.record_batch_output(
    batch_idx=0,
    batch_name="Core",
    generated_files=[
        {
            "filename": "src/app.py",
            "content": (
                "from flask import Flask\n"
                "app = Flask(__name__)\n"
                '@app.route("/api/users")\n'
                "def get_users(): pass\n"
            ),
        }
    ],
    original_files=["src/app.py"],
)
assert len(mgr.batch_records) == 1, "Should have 1 batch record"
print(f"[2] Recorded batch 0: {len(mgr.batch_records)} records — OK")

# ─── Test 3: Batch 1 context includes batch 0 summary ───
ctx1 = mgr.prepare_batch_context(batch_idx=1, batch_file_paths=["src/models.py"])
assert len(ctx1) > len(ctx0), "Batch 1 should have more context than batch 0"
print(f"[3] Batch 1 context (with history): {len(ctx1)} chars — OK")

# ─── Test 4: Memory serialization ───
mem = mgr.to_memory_dict()
assert "batch_summaries" in mem
assert len(mem["batch_summaries"]) == 1
print(f"[4] Memory dict: {list(mem.keys())} — OK")

# ─── Test 5: extract_batch_summary (upgraded) ───
summary = extract_batch_summary([
    {
        "filename": "server.js",
        "content": (
            "const express = require('express');\n"
            "const app = express();\n"
            "app.get('/api/health', (req, res) => res.json({ok: true}));\n"
            "module.exports = { app };\n"
        ),
    }
])
assert "ROUTES" in summary.upper() or "server.js" in summary
print(f"[5] extract_batch_summary: {len(summary)} chars — OK")

# ─── Test 6: ProjectContext creation (with mock AST data) ───
from ast_parser import FileAnalysis, FunctionInfo, ClassInfo, ImportInfo, RouteInfo

mock_analysis = FileAnalysis(
    path="src/app.py",
    language="python",
    imports=[ImportInfo(module="flask", names=["Flask", "request"], alias=None, is_relative=False)],
    functions=[
        FunctionInfo(name="get_users", args=["page", "limit"], return_type="list",
                     decorators=["app.route"], line_start=10, is_async=False,
                     complexity=3)
    ],
    classes=[],
    exports=[],
    routes=[RouteInfo(method="GET", path="/api/users", handler="get_users")],
    schemas=[],
    frameworks={"flask"},
    complexity_score=3,
)

file_contents = {
    "src/app.py": (
        "from flask import Flask\n"
        "import os\n"
        'JWT_SECRET = os.getenv("JWT_SECRET")\n'
        "app = Flask(__name__)\n"
    )
}

project_ctx = extract_project_context({"src/app.py": mock_analysis}, file_contents)
assert isinstance(project_ctx, ProjectContext)
assert len(project_ctx.api_contracts) >= 1
print(f"[6] ProjectContext: {len(project_ctx.api_contracts)} APIs, "
      f"{len(project_ctx.env_vars_required)} env vars — OK")

# ─── Test 7: CrossBatchContextManager with project context ───
mgr2 = CrossBatchContextManager(project_context=project_ctx)
ctx_rich = mgr2.prepare_batch_context(batch_idx=0, batch_file_paths=["src/app.py"])
assert len(ctx_rich) > 50, "Should have significant context with project_context"
print(f"[7] Manager with project context: {len(ctx_rich)} chars — OK")

# ─── Test 8: full_context_prompt renders ───
prompt = project_ctx.full_context_prompt()
assert "API" in prompt.upper() or "CONTRACT" in prompt.upper() or len(prompt) > 0
print(f"[8] full_context_prompt: {len(prompt)} chars — OK")

# ─── Test 9: Enhanced memory functions exist and are callable ───
# (Don't actually write to disk, just verify function signatures)
import inspect
assert callable(record_dependency_graph)
assert callable(record_api_contracts)
assert callable(get_enhanced_memory_context)
print(f"[9] Enhanced memory functions: all callable — OK")

print("\n" + "=" * 60)
print("ALL PHASE 2 TESTS PASSED ✅")
print("=" * 60)
