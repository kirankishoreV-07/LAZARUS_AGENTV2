"""
Lazarus Engine — Phase 2: Cross-Batch Context Manager
=======================================================
Maintains a shared state across all batch generations so that:

  1. Every batch sees the full API route map
  2. Every batch knows the exact data schemas
  3. Frontend batches know backend contracts (and vice versa)
  4. Auth requirements propagate to all consuming code
  5. Previously-generated exports are tracked as structured contracts

The manager is instantiated once per resurrection run and updated
after each batch completes.

Usage:
    mgr = CrossBatchContextManager(project_context)
    mgr.prepare_batch_context(batch_idx, batch_files, ...)
    ... call Gemini ...
    mgr.record_batch_output(batch_idx, generated_files)
"""

import re
import os
import json
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Set, Optional, Tuple

from ast_parser import FileAnalysis, analyze_file
from context_extraction import ProjectContext, APIContract, SchemaContract

logger = logging.getLogger('lazarus.context_manager')


# ══════════════════════════════════════════════════════════════
# BATCH OUTPUT RECORD
# ══════════════════════════════════════════════════════════════

@dataclass
class BatchRecord:
    """What a single batch produced — tracked for cross-batch coherence."""
    batch_id: int
    batch_name: str
    files_generated: List[str] = field(default_factory=list)
    routes_generated: List[Dict] = field(default_factory=list)    # [{method, path, handler}]
    schemas_generated: List[Dict] = field(default_factory=list)   # [{name, kind, fields}]
    exports_generated: List[Dict] = field(default_factory=list)   # [{name, kind, file}]
    imports_expected: List[Dict] = field(default_factory=list)     # [{module, names, file}]
    version: int = 1                                               # Incremented on re-gen

    def structured_summary(self) -> str:
        """Structured summary for injection into subsequent batch prompts."""
        lines = [f"── Batch {self.batch_id}: {self.batch_name} ({len(self.files_generated)} files) ──"]

        if self.routes_generated:
            lines.append("  ROUTES:")
            for r in self.routes_generated:
                lines.append(f"    {r['method']} {r['path']} → {r.get('handler', '?')}()")

        if self.schemas_generated:
            lines.append("  SCHEMAS:")
            for s in self.schemas_generated:
                fields_str = ", ".join(f"{f[0]}: {f[1]}" for f in s.get('fields', [])[:6])
                lines.append(f"    {s['name']} ({s.get('kind', '?')}) {{ {fields_str} }}")

        if self.exports_generated:
            lines.append("  EXPORTS:")
            for e in self.exports_generated[:15]:
                lines.append(f"    {e.get('kind', 'const')} {e['name']} (from {e.get('file', '?')})")
            if len(self.exports_generated) > 15:
                lines.append(f"    ... +{len(self.exports_generated) - 15} more")

        if not (self.routes_generated or self.schemas_generated or self.exports_generated):
            lines.append("  (config/static files)")

        return "\n".join(lines)


# ══════════════════════════════════════════════════════════════
# BREAKING CHANGE DETECTION
# ══════════════════════════════════════════════════════════════

@dataclass
class BreakingChange:
    """Detected breaking change between batch outputs."""
    kind: str           # 'route_removed', 'schema_changed', 'export_missing', 'type_mismatch'
    description: str
    batch_id: int
    severity: str       # 'critical', 'warning'


# ══════════════════════════════════════════════════════════════
# CROSS-BATCH CONTEXT MANAGER
# ══════════════════════════════════════════════════════════════

class CrossBatchContextManager:
    """
    Maintains shared state across all batches in a resurrection run.
    
    Lifecycle:
        1. __init__: Receive ProjectContext (from context_extraction)
        2. prepare_batch_context(): Build the context string for a batch's prompt
        3. record_batch_output(): After Gemini returns, parse & record what was generated
        4. detect_breaking_changes(): Compare outputs to expectations
    """

    def __init__(self, project_context: ProjectContext = None):
        self.project_context = project_context
        self.batch_records: Dict[int, BatchRecord] = {}
        self.breaking_changes: List[BreakingChange] = []

        # Derived lookup tables
        self._all_routes: Dict[str, APIContract] = {}   # "METHOD /path" → contract
        self._all_schemas: Dict[str, SchemaContract] = {}  # name → schema
        self._generated_code: Dict[str, str] = {}        # path → generated source

        # Populate lookup from project context (if available)
        if project_context:
            for c in project_context.api_contracts:
                key = f"{c.method} {c.path}"
                self._all_routes[key] = c
            for s in project_context.schemas:
                self._all_schemas[s.name] = s

        logger.info(
            f"CrossBatchContextManager initialized: "
            f"{len(self._all_routes)} routes, {len(self._all_schemas)} schemas"
        )

    # ──────────────────────────────────────────────────────────
    # CONTEXT PREPARATION (called BEFORE each Gemini call)
    # ──────────────────────────────────────────────────────────

    def prepare_batch_context(
        self,
        batch_idx: int,
        batch_file_paths: List[str],
        analyses: Dict[str, FileAnalysis] = None,
        max_chars: int = 50000,
    ) -> str:
        """
        Build the rich context string to inject into a batch's code generation prompt.

        Includes:
          1. Project-wide API contracts (always)
          2. All schema definitions (always)
          3. Auth patterns (always)
          4. Structured summaries from previously-completed batches
          5. Cross-batch dependency alerts

        Args:
            batch_idx: 0-based index of the batch being generated
            batch_file_paths: Paths of files in THIS batch
            analyses: All file analyses (optional — needed for dependency alerts)
            max_chars: Max chars for the context section

        Returns:
            Formatted context string for prompt injection
        """
        sections = []
        chars_used = 0

        # ── Section A: PROJECT-WIDE CONTRACTS (every batch gets this) ──
        if self.project_context:
            contracts_section = self.project_context.full_context_prompt(max_chars=max_chars // 3)
            if contracts_section.strip():
                sections.append("╔══ PHASE 2: PROJECT-WIDE CONTEXT (shared across ALL batches) ══╗")
                sections.append(contracts_section)
                sections.append("╚════════════════════════════════════════════════════════════════╝")
                chars_used += len(contracts_section) + 200

        # ── Section B: STRUCTURED SUMMARIES FROM PREVIOUS BATCHES ──
        if self.batch_records:
            sections.append("\n╔══ PREVIOUSLY GENERATED BATCHES (structured exports) ══╗")
            for bid in sorted(self.batch_records.keys()):
                if bid >= batch_idx:
                    continue  # Only show earlier batches
                record = self.batch_records[bid]
                summary = record.structured_summary()
                if chars_used + len(summary) > max_chars * 0.8:
                    sections.append(f"  ... (earlier batch summaries truncated)")
                    break
                sections.append(summary)
                chars_used += len(summary)
            sections.append("╚════════════════════════════════════════════════════════╝")

        # ── Section C: CROSS-BATCH DEPENDENCY ALERTS ──
        if analyses:
            alerts = self._get_dependency_alerts(batch_file_paths, analyses)
        else:
            alerts = []
        if alerts:
            sections.append("\n╔══ CROSS-BATCH DEPENDENCY ALERTS ══╗")
            sections.append("These files/symbols are referenced by this batch but defined elsewhere:")
            for alert in alerts[:20]:
                sections.append(f"  ⚠ {alert}")
            sections.append("Ensure your generated code uses the EXACT same names/types as above.")
            sections.append("╚════════════════════════════════════╝")

        # ── Section D: BREAKING CHANGES WARNING ──
        if self.breaking_changes:
            sections.append("\n╔══ ⚠ BREAKING CHANGES DETECTED ══╗")
            for bc in self.breaking_changes:
                sections.append(f"  [{bc.severity.upper()}] {bc.description}")
            sections.append("Fix these inconsistencies in this batch's output!")
            sections.append("╚════════════════════════════════════╝")

        result = "\n".join(sections)
        if len(result) > max_chars:
            result = result[:max_chars] + "\n... (context truncated)"

        return result

    def _get_dependency_alerts(
        self,
        batch_file_paths: List[str],
        analyses: Dict[str, FileAnalysis],
    ) -> List[str]:
        """Generate alerts about cross-batch dependencies this batch needs."""
        alerts = []
        batch_set = set(batch_file_paths)

        for path in batch_file_paths:
            analysis = analyses.get(path)
            if not analysis:
                continue

            # Check imports that resolve to files outside this batch
            for imp in analysis.imports:
                if imp.is_relative or imp.module.startswith('.'):
                    # Could be a local file import
                    for name in imp.names:
                        # Check if any generated batch already produced this
                        for record in self.batch_records.values():
                            for exp in record.exports_generated:
                                if exp['name'] == name:
                                    alerts.append(
                                        f"{path} imports '{name}' from {imp.module} → "
                                        f"already generated in Batch {record.batch_id} "
                                        f"(file: {exp.get('file', '?')})"
                                    )

            # Check if this file's routes should match schemas
            for route in analysis.routes:
                route_key = f"{route.method} {route.path}"
                if route_key in self._all_routes:
                    contract = self._all_routes[route_key]
                    if contract.body_schema and contract.body_schema in self._all_schemas:
                        schema = self._all_schemas[contract.body_schema]
                        if schema.file not in batch_set:
                            alerts.append(
                                f"Route {route_key} expects body schema '{contract.body_schema}' "
                                f"defined in {schema.file} (not in this batch)"
                            )

        return alerts

    # ──────────────────────────────────────────────────────────
    # BATCH OUTPUT RECORDING (called AFTER each Gemini call)
    # ──────────────────────────────────────────────────────────

    def record_batch_output(
        self,
        batch_idx: int,
        batch_name: str,
        generated_files: List[Dict],
        original_files: List[str] = None,
    ) -> BatchRecord:
        """
        Parse the generated files and record structured exports for future batches.

        Args:
            batch_idx: 0-based index of the completed batch
            batch_name: Human-readable name
            generated_files: List of {"filename": str, "content": str}

        Returns:
            BatchRecord with parsed exports
        """
        record = BatchRecord(
            batch_id=batch_idx,
            batch_name=batch_name,
            files_generated=[f["filename"] for f in generated_files],
        )

        for f in generated_files:
            path = f["filename"]
            content = f.get("content", "")

            # Store generated code for cross-reference
            self._generated_code[path] = content

            # Quick-parse the generated code for exports
            try:
                analysis = analyze_file(path, content)
            except Exception:
                analysis = None

            if analysis:
                # Routes
                for route in analysis.routes:
                    record.routes_generated.append({
                        "method": route.method,
                        "path": route.path,
                        "handler": route.handler,
                        "file": path,
                    })

                # Schemas
                for cls in analysis.classes:
                    for base in cls.bases:
                        if any(kw in base.lower() for kw in ('model', 'schema', 'base', 'document')):
                            fields = []
                            for prop in cls.properties:
                                fields.append((prop, "Any"))
                            record.schemas_generated.append({
                                "name": cls.name,
                                "kind": "model",
                                "fields": fields,
                                "file": path,
                            })
                            break

                # Exports
                for exp in analysis.exports:
                    record.exports_generated.append({
                        "name": exp.name,
                        "kind": exp.kind,
                        "file": path,
                    })

                # Also track top-level functions as exports (Python modules)
                if analysis.language == 'python':
                    for fn in analysis.functions:
                        if not fn.is_method:
                            record.exports_generated.append({
                                "name": fn.name,
                                "kind": "function",
                                "file": path,
                            })

                # Track imports this batch expects
                for imp in analysis.imports:
                    if imp.is_relative or imp.module.startswith('.'):
                        record.imports_expected.append({
                            "module": imp.module,
                            "names": imp.names,
                            "file": path,
                        })

        self.batch_records[batch_idx] = record

        logger.info(
            f"Batch {batch_idx} recorded: {len(record.files_generated)} files, "
            f"{len(record.routes_generated)} routes, {len(record.schemas_generated)} schemas, "
            f"{len(record.exports_generated)} exports"
        )

        # Run breaking change detection after recording
        self._detect_breaking_changes(record)

        return record

    # ──────────────────────────────────────────────────────────
    # BREAKING CHANGE DETECTION
    # ──────────────────────────────────────────────────────────

    def _detect_breaking_changes(self, new_record: BatchRecord):
        """Check if the new batch output breaks contracts with previous batches."""
        if not self.project_context:
            return  # No project context → no contract validation possible
        
        # Check: routes expected by the project context but not generated
        for contract in self.project_context.api_contracts:
            if contract.file in new_record.files_generated:
                route_key = f"{contract.method} {contract.path}"
                generated_keys = {
                    f"{r['method']} {r['path']}" for r in new_record.routes_generated
                }
                if route_key not in generated_keys:
                    self.breaking_changes.append(BreakingChange(
                        kind='route_removed',
                        description=f"Expected route {route_key} in {contract.file} was NOT generated by Batch {new_record.batch_id}",
                        batch_id=new_record.batch_id,
                        severity='critical',
                    ))

        # Check: schemas expected but fields differ
        for schema in self.project_context.schemas:
            if schema.file in new_record.files_generated:
                generated_schemas = {
                    s['name']: s for s in new_record.schemas_generated
                }
                if schema.name in generated_schemas:
                    # Check field count as a rough diff
                    expected_fields = len(schema.fields)
                    actual_fields = len(generated_schemas[schema.name].get('fields', []))
                    if expected_fields > 0 and actual_fields < expected_fields * 0.5:
                        self.breaking_changes.append(BreakingChange(
                            kind='schema_changed',
                            description=(
                                f"Schema '{schema.name}' in {schema.file}: "
                                f"expected ~{expected_fields} fields, got {actual_fields}"
                            ),
                            batch_id=new_record.batch_id,
                            severity='warning',
                        ))

        # Check: imports expected by previous batches but not exported here
        for prev_id, prev_record in self.batch_records.items():
            if prev_id == new_record.batch_id:
                continue
            for imp in prev_record.imports_expected:
                for name in imp.get('names', []):
                    if name == '*':
                        continue
                    # Check if this batch should provide that export
                    for gen_file in new_record.files_generated:
                        # Fuzzy module match
                        module = imp.get('module', '')
                        if os.path.splitext(os.path.basename(gen_file))[0] in module.replace('.', '/'):
                            found = any(
                                e['name'] == name for e in new_record.exports_generated
                            )
                            if not found:
                                self.breaking_changes.append(BreakingChange(
                                    kind='export_missing',
                                    description=(
                                        f"Batch {prev_id} expects '{name}' from {module}, "
                                        f"but Batch {new_record.batch_id} ({gen_file}) doesn't export it"
                                    ),
                                    batch_id=new_record.batch_id,
                                    severity='warning',
                                ))

    # ──────────────────────────────────────────────────────────
    # UTILITY
    # ──────────────────────────────────────────────────────────

    def get_all_generated_routes(self) -> List[Dict]:
        """Get all routes generated across all batches."""
        routes = []
        for record in self.batch_records.values():
            routes.extend(record.routes_generated)
        return routes

    def get_all_generated_schemas(self) -> List[Dict]:
        """Get all schemas generated across all batches."""
        schemas = []
        for record in self.batch_records.values():
            schemas.extend(record.schemas_generated)
        return schemas

    def get_all_generated_exports(self) -> List[Dict]:
        """Get all exports generated across all batches."""
        exports = []
        for record in self.batch_records.values():
            exports.extend(record.exports_generated)
        return exports

    def get_generated_code(self, path: str) -> Optional[str]:
        """Get the generated code for a specific file path (if available)."""
        return self._generated_code.get(path)

    def get_full_summaries(self) -> str:
        """Get all batch structured summaries concatenated."""
        parts = []
        for bid in sorted(self.batch_records.keys()):
            parts.append(self.batch_records[bid].structured_summary())
        return "\n\n".join(parts)

    def get_breaking_changes_summary(self) -> str:
        """Get a summary of all detected breaking changes."""
        if not self.breaking_changes:
            return ""
        lines = [f"⚠ {len(self.breaking_changes)} BREAKING CHANGES DETECTED:"]
        for bc in self.breaking_changes:
            lines.append(f"  [{bc.severity.upper()}] {bc.description}")
        return "\n".join(lines)

    def to_memory_dict(self) -> dict:
        """Serializable dict for saving to resurrection memory."""
        return {
            "batch_count": len(self.batch_records),
            "total_routes_generated": len(self.get_all_generated_routes()),
            "total_schemas_generated": len(self.get_all_generated_schemas()),
            "total_exports_generated": len(self.get_all_generated_exports()),
            "breaking_changes": [
                {"kind": bc.kind, "description": bc.description,
                 "batch_id": bc.batch_id, "severity": bc.severity}
                for bc in self.breaking_changes
            ],
            "batch_summaries": {
                str(bid): record.structured_summary()
                for bid, record in self.batch_records.items()
            },
        }
