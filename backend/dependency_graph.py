"""
Lazarus Engine — Phase 1: Dependency Graph & Smart Batching
=============================================================
Builds a file dependency graph from AST analysis results.
Uses the graph to create intelligent batches that respect
import/export relationships and minimize cross-batch dependencies.

Features:
  - Import resolution (relative + absolute)
  - Circular dependency detection (Tarjan's SCC)
  - Topological ordering for build sequence
  - Coupling score calculation
  - Smart batching that groups tightly-coupled files
  - Foundation layer detection (files many others depend on)
"""

import os
import re
import logging
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Dict, List, Set, Tuple, Optional

from ast_parser import FileAnalysis, ImportInfo

logger = logging.getLogger('lazarus.dep_graph')


# ══════════════════════════════════════════════════════════════
# DATA STRUCTURES
# ══════════════════════════════════════════════════════════════

@dataclass
class DependencyEdge:
    """A directed edge in the dependency graph."""
    source: str         # File that imports
    target: str         # File being imported
    imported_names: List[str]  # What symbols are imported
    is_relative: bool   # Whether it's a relative import
    strength: float = 1.0     # How strongly coupled (more imports = stronger)


@dataclass
class FileNode:
    """A node in the dependency graph."""
    path: str
    analysis: Optional[FileAnalysis] = None
    in_degree: int = 0          # Files that import this file
    out_degree: int = 0         # Files this file imports
    coupling_score: float = 0.0 # How coupled to other files
    cluster_id: int = -1        # Which batch cluster it belongs to
    is_foundation: bool = False # Is this a core/foundation file?
    topo_order: int = -1        # Topological sort order

    @property
    def importance_score(self) -> float:
        """Higher = more important. Foundation files scored highest."""
        return self.in_degree * 2 + self.out_degree + (10 if self.is_foundation else 0)


@dataclass
class DependencyGraph:
    """Complete dependency graph for a repository."""
    nodes: Dict[str, FileNode] = field(default_factory=dict)
    edges: List[DependencyEdge] = field(default_factory=list)
    adjacency: Dict[str, Set[str]] = field(default_factory=lambda: defaultdict(set))     # Forward deps
    reverse_adj: Dict[str, Set[str]] = field(default_factory=lambda: defaultdict(set))    # Reverse deps
    circular_deps: List[List[str]] = field(default_factory=list)                          # SCCs with >1 node
    topo_order: List[str] = field(default_factory=list)                                   # Topological ordering

    def get_dependencies(self, path: str) -> Set[str]:
        """Get all files that `path` depends on."""
        return self.adjacency.get(path, set())

    def get_dependents(self, path: str) -> Set[str]:
        """Get all files that depend on `path`."""
        return self.reverse_adj.get(path, set())

    def get_transitive_deps(self, path: str, max_depth: int = 10) -> Set[str]:
        """Get all transitive dependencies of a file (BFS)."""
        visited = set()
        queue = deque([(path, 0)])
        while queue:
            current, depth = queue.popleft()
            if current in visited or depth > max_depth:
                continue
            visited.add(current)
            for dep in self.adjacency.get(current, set()):
                if dep not in visited:
                    queue.append((dep, depth + 1))
        visited.discard(path)
        return visited

    def summary(self) -> str:
        """Human-readable summary of the dependency graph."""
        total_files = len(self.nodes)
        total_edges = len(self.edges)
        foundation = [n.path for n in self.nodes.values() if n.is_foundation]
        circular = len(self.circular_deps)
        return (
            f"Dependency Graph: {total_files} files, {total_edges} edges\n"
            f"  Foundation files: {', '.join(foundation) if foundation else 'none'}\n"
            f"  Circular dependency groups: {circular}\n"
            f"  Topological layers: {len(set(n.topo_order for n in self.nodes.values()))}"
        )


# ══════════════════════════════════════════════════════════════
# IMPORT RESOLUTION
# ══════════════════════════════════════════════════════════════

def _resolve_import(
    importing_file: str,
    imp: ImportInfo,
    all_paths: Set[str],
    path_index: Dict[str, str],
) -> Optional[str]:
    """
    Resolve an import statement to an actual file path in the repo.

    Args:
        importing_file: Path of the file that contains the import
        imp: Import info
        all_paths: Set of all file paths in the repo
        path_index: Mapping of normalized names to full paths
    """
    module = imp.module

    if not module:
        return None

    # ── Relative imports ──
    if imp.is_relative or module.startswith('.'):
        dir_of_importer = os.path.dirname(importing_file)
        # Count dots for relative level
        dots = len(module) - len(module.lstrip('.'))
        rel_module = module.lstrip('.')

        base_dir = dir_of_importer
        for _ in range(dots - 1):
            base_dir = os.path.dirname(base_dir)

        # Convert module dots to path separators
        rel_path = rel_module.replace('.', '/')

        candidates = _get_file_candidates(os.path.join(base_dir, rel_path) if rel_path else base_dir)

        for candidate in candidates:
            normalized = candidate.replace('\\', '/')
            if normalized in all_paths:
                return normalized

        return None

    # ── Absolute imports (Python) ──
    # Convert dots to slashes: my.module.file -> my/module/file
    module_path = module.replace('.', '/')

    candidates = _get_file_candidates(module_path)
    for candidate in candidates:
        normalized = candidate.replace('\\', '/')
        if normalized in all_paths:
            return normalized

    # ── JS/TS module resolution ──
    # Try with/without src/ prefix and various patterns
    prefixes = ['', 'src/', 'lib/', 'app/']
    for prefix in prefixes:
        full_path = prefix + module_path
        # Remove leading @/ or ~/ alias
        full_path = re.sub(r'^[@~]/', 'src/', full_path)

        candidates = _get_file_candidates(full_path)
        for candidate in candidates:
            normalized = candidate.replace('\\', '/')
            if normalized in all_paths:
                return normalized

    # ── Fuzzy match: check path_index ──
    base_name = os.path.basename(module_path)
    if base_name in path_index:
        return path_index[base_name]

    return None


def _get_file_candidates(base_path: str) -> List[str]:
    """
    Generate candidate file paths for a module path.
    e.g., 'utils/helper' -> ['utils/helper.js', 'utils/helper.ts', 'utils/helper/index.js', ...]
    """
    candidates = [base_path]  # Exact match (already has extension)

    # Common extensions to try
    extensions = [
        '.py', '.js', '.ts', '.tsx', '.jsx', '.mjs', '.cjs',
        '.vue', '.svelte',
    ]

    for ext in extensions:
        candidates.append(base_path + ext)

    # Index files (JS/TS convention)
    index_names = ['index.js', 'index.ts', 'index.tsx', 'index.jsx', 'index.mjs']
    for idx in index_names:
        candidates.append(os.path.join(base_path, idx))

    # Python __init__.py
    candidates.append(os.path.join(base_path, '__init__.py'))

    return candidates


# ══════════════════════════════════════════════════════════════
# GRAPH CONSTRUCTION
# ══════════════════════════════════════════════════════════════

def build_dependency_graph(analyses: Dict[str, FileAnalysis]) -> DependencyGraph:
    """
    Build a dependency graph from file analyses.

    Args:
        analyses: Dict mapping file path -> FileAnalysis

    Returns:
        Complete DependencyGraph
    """
    graph = DependencyGraph()

    # Build path index for fuzzy matching
    all_paths = set(analyses.keys())
    path_index: Dict[str, str] = {}
    for path in all_paths:
        basename = os.path.basename(path)
        name_no_ext = os.path.splitext(basename)[0]
        # Don't overwrite if ambiguous (multiple files with same name)
        if name_no_ext not in path_index:
            path_index[name_no_ext] = path
        else:
            path_index[name_no_ext] = None  # Ambiguous, remove

    # Remove ambiguous entries
    path_index = {k: v for k, v in path_index.items() if v is not None}

    # Create nodes
    for path, analysis in analyses.items():
        graph.nodes[path] = FileNode(path=path, analysis=analysis)

    # Resolve imports and create edges
    for path, analysis in analyses.items():
        for imp in analysis.imports:
            # Skip external packages (npm, pip, etc.)
            if not imp.is_relative and not imp.module.startswith('.'):
                # Check if this module resolves to a file in our repo
                resolved = _resolve_import(path, imp, all_paths, path_index)
                if resolved is None:
                    continue  # External package, skip
            else:
                resolved = _resolve_import(path, imp, all_paths, path_index)
                if resolved is None:
                    continue  # Can't resolve

            if resolved == path:
                continue  # Self-import

            # Create edge
            strength = max(1.0, len(imp.names) * 0.5)
            edge = DependencyEdge(
                source=path, target=resolved,
                imported_names=imp.names,
                is_relative=imp.is_relative,
                strength=strength,
            )
            graph.edges.append(edge)
            graph.adjacency[path].add(resolved)
            graph.reverse_adj[resolved].add(path)

    # Calculate degrees
    for path, node in graph.nodes.items():
        node.out_degree = len(graph.adjacency.get(path, set()))
        node.in_degree = len(graph.reverse_adj.get(path, set()))

    # Detect foundation files (high in-degree, low out-degree)
    if graph.nodes:
        max_in = max((n.in_degree for n in graph.nodes.values()), default=0)
        threshold = max(2, max_in * 0.3)
        for node in graph.nodes.values():
            if node.in_degree >= threshold and node.out_degree <= node.in_degree:
                node.is_foundation = True

    # Detect circular dependencies (Tarjan's SCC)
    graph.circular_deps = _find_circular_deps(graph)

    # Topological ordering
    graph.topo_order = _topological_sort(graph)
    for i, path in enumerate(graph.topo_order):
        if path in graph.nodes:
            graph.nodes[path].topo_order = i

    # Coupling scores
    _calculate_coupling(graph)

    logger.info(graph.summary())
    return graph


# ══════════════════════════════════════════════════════════════
# GRAPH ALGORITHMS
# ══════════════════════════════════════════════════════════════

def _find_circular_deps(graph: DependencyGraph) -> List[List[str]]:
    """Find strongly connected components using Tarjan's algorithm."""
    index_counter = [0]
    stack = []
    lowlinks = {}
    index = {}
    on_stack = {}
    result = []

    def strongconnect(v):
        index[v] = index_counter[0]
        lowlinks[v] = index_counter[0]
        index_counter[0] += 1
        stack.append(v)
        on_stack[v] = True

        for w in graph.adjacency.get(v, set()):
            if w not in index:
                strongconnect(w)
                lowlinks[v] = min(lowlinks[v], lowlinks[w])
            elif on_stack.get(w, False):
                lowlinks[v] = min(lowlinks[v], index[w])

        if lowlinks[v] == index[v]:
            component = []
            while True:
                w = stack.pop()
                on_stack[w] = False
                component.append(w)
                if w == v:
                    break
            if len(component) > 1:
                result.append(component)

    for v in graph.nodes:
        if v not in index:
            strongconnect(v)

    return result


def _topological_sort(graph: DependencyGraph) -> List[str]:
    """
    Topological sort using Kahn's algorithm.
    Handles cycles by breaking them at the lowest in-degree node.
    """
    in_degree = {path: 0 for path in graph.nodes}
    for path in graph.nodes:
        for dep in graph.adjacency.get(path, set()):
            if dep in in_degree:
                in_degree[dep] += 1

    queue = deque([p for p, d in in_degree.items() if d == 0])
    result = []
    visited = set()

    while queue:
        node = queue.popleft()
        if node in visited:
            continue
        visited.add(node)
        result.append(node)

        for dep in graph.reverse_adj.get(node, set()):
            if dep not in visited and dep in in_degree:
                in_degree[dep] -= 1
                if in_degree[dep] <= 0:
                    queue.append(dep)

    # Handle remaining nodes (in cycles)
    remaining = set(graph.nodes.keys()) - visited
    if remaining:
        # Sort by in-degree to break ties
        for path in sorted(remaining, key=lambda p: in_degree.get(p, 0)):
            if path not in visited:
                visited.add(path)
                result.append(path)

    return result


def _calculate_coupling(graph: DependencyGraph):
    """Calculate coupling scores for all nodes."""
    for path, node in graph.nodes.items():
        deps = graph.adjacency.get(path, set())
        dependents = graph.reverse_adj.get(path, set())

        # Coupling = (shared dependencies + mutual edges) / total connections
        mutual = deps & dependents  # Bidirectional dependencies
        total_connections = len(deps) + len(dependents)
        if total_connections > 0:
            node.coupling_score = (len(mutual) * 2 + total_connections) / max(1, len(graph.nodes))
        else:
            node.coupling_score = 0.0


# ══════════════════════════════════════════════════════════════
# SMART BATCHING
# ══════════════════════════════════════════════════════════════

@dataclass
class Batch:
    """A group of files to be generated together."""
    id: int
    files: List[str]
    context_files: List[str]    # Files from OTHER batches this batch needs context from
    foundation_files: List[str] # Foundation files included for context (not generated)
    total_lines: int = 0
    total_complexity: float = 0.0
    description: str = ""

    def summary_for_prompt(self, analyses: Dict[str, FileAnalysis]) -> str:
        """Generate a context summary for this batch's prompt."""
        parts = [f"Batch {self.id}: {len(self.files)} files"]
        for path in self.files:
            if path in analyses:
                parts.append(f"  - {path}: {analyses[path].summary()}")
        if self.context_files:
            parts.append(f"\n  Context from other batches:")
            for path in self.context_files[:10]:
                if path in analyses:
                    parts.append(f"    - {path}: {analyses[path].summary()}")
        return '\n'.join(parts)


def create_smart_batches(
    graph: DependencyGraph,
    analyses: Dict[str, FileAnalysis],
    max_batch_size: int = 15,
    max_batch_lines: int = 3000,
    context_limit: int = 50000,
) -> List[Batch]:
    """
    Create intelligent batches that respect dependency relationships.

    Strategy:
    1. Foundation files go first (batch 0) — these are generated early
       and provided as context to all subsequent batches.
    2. Group tightly-coupled files (mutual deps, same directory, same cluster)
    3. Respect topological order — dependencies generated before dependents
    4. Keep batches within size/line limits
    5. Each batch gets context summaries from its dependency batches

    Args:
        graph: Dependency graph
        analyses: Dict of file analyses
        max_batch_size: Max files per batch
        max_batch_lines: Max total lines per batch
        context_limit: Max chars for cross-batch context

    Returns:
        Ordered list of Batches
    """
    if not graph.nodes:
        return []

    batches: List[Batch] = []
    assigned: Set[str] = set()

    # ── Step 1: Foundation batch ──
    foundation_files = [p for p, n in graph.nodes.items() if n.is_foundation]
    if foundation_files:
        batch = Batch(
            id=0,
            files=foundation_files[:max_batch_size],
            context_files=[],
            foundation_files=[],
            description="Foundation/core files (imported by many)"
        )
        for path in batch.files:
            assigned.add(path)
            if path in analyses:
                batch.total_lines += analyses[path].line_count
                batch.total_complexity += analyses[path].complexity_score
        batches.append(batch)

    # ── Step 2: Cluster tightly-coupled files ──
    clusters = _cluster_files(graph, analyses, assigned)

    # ── Step 3: Convert clusters to batches (respecting topo order) ──
    # Sort clusters by earliest topological order
    for cluster in clusters:
        if not cluster:
            continue

        # Sort files within cluster by topo order
        cluster_sorted = sorted(
            cluster,
            key=lambda p: graph.nodes[p].topo_order if p in graph.nodes else 999
        )

        # Split large clusters into multiple batches
        current_files = []
        current_lines = 0

        for path in cluster_sorted:
            if path in assigned:
                continue

            file_lines = analyses[path].line_count if path in analyses else 50
            if (len(current_files) >= max_batch_size or
                current_lines + file_lines > max_batch_lines) and current_files:
                # Flush current batch
                _create_batch_from_files(
                    batches, current_files, graph, analyses, assigned, foundation_files
                )
                current_files = []
                current_lines = 0

            current_files.append(path)
            current_lines += file_lines

        if current_files:
            _create_batch_from_files(
                batches, current_files, graph, analyses, assigned, foundation_files
            )

    # ── Step 4: Remaining unassigned files ──
    remaining = [p for p in graph.topo_order if p not in assigned]
    for i in range(0, len(remaining), max_batch_size):
        chunk = remaining[i:i + max_batch_size]
        if chunk:
            _create_batch_from_files(
                batches, chunk, graph, analyses, assigned, foundation_files
            )

    # ── Step 5: Assign cross-batch context ──
    _assign_cross_batch_context(batches, graph, analyses)

    logger.info(f"Created {len(batches)} smart batches from {len(graph.nodes)} files")
    for b in batches:
        logger.info(f"  Batch {b.id}: {len(b.files)} files, {b.total_lines} lines - {b.description}")

    return batches


def _create_batch_from_files(
    batches: List[Batch],
    files: List[str],
    graph: DependencyGraph,
    analyses: Dict[str, FileAnalysis],
    assigned: Set[str],
    foundation_files: List[str],
):
    """Create a batch from a list of files and add it to batches list."""
    batch_id = len(batches)
    batch = Batch(
        id=batch_id,
        files=files,
        context_files=[],
        foundation_files=foundation_files,
    )
    for path in files:
        assigned.add(path)
        if path in analyses:
            batch.total_lines += analyses[path].line_count
            batch.total_complexity += analyses[path].complexity_score

    # Generate description
    dirs = set(os.path.dirname(p) for p in files)
    langs = set(analyses[p].language for p in files if p in analyses)
    batch.description = f"{', '.join(dirs)} ({', '.join(langs)})"

    batches.append(batch)


def _cluster_files(
    graph: DependencyGraph,
    analyses: Dict[str, FileAnalysis],
    already_assigned: Set[str],
) -> List[List[str]]:
    """
    Cluster files by dependency proximity.
    Uses Union-Find to group files that are tightly coupled.
    """
    unassigned = [p for p in graph.nodes if p not in already_assigned]

    if not unassigned:
        return []

    # Union-Find
    parent = {p: p for p in unassigned}
    rank = {p: 0 for p in unassigned}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x, y):
        rx, ry = find(x), find(y)
        if rx == ry:
            return
        if rank[rx] < rank[ry]:
            rx, ry = ry, rx
        parent[ry] = rx
        if rank[rx] == rank[ry]:
            rank[rx] += 1

    unassigned_set = set(unassigned)

    # Union files that have mutual dependencies
    for path in unassigned:
        deps = graph.adjacency.get(path, set())
        for dep in deps:
            if dep in unassigned_set:
                # Check if mutual
                if path in graph.adjacency.get(dep, set()):
                    union(path, dep)

    # Union files that are in the same directory and share dependencies
    dir_groups = defaultdict(list)
    for path in unassigned:
        dir_groups[os.path.dirname(path)].append(path)

    for dir_path, files in dir_groups.items():
        if len(files) <= 1:
            continue
        # Union files in same directory that share at least one dependency
        for i in range(len(files)):
            deps_i = graph.adjacency.get(files[i], set()) | graph.reverse_adj.get(files[i], set())
            for j in range(i + 1, len(files)):
                deps_j = graph.adjacency.get(files[j], set()) | graph.reverse_adj.get(files[j], set())
                if deps_i & deps_j:  # Shared dependency
                    union(files[i], files[j])

    # Extract clusters
    cluster_map = defaultdict(list)
    for path in unassigned:
        root = find(path)
        cluster_map[root].append(path)

    # Sort clusters by average topo order (process earlier dependencies first)
    clusters = list(cluster_map.values())
    clusters.sort(key=lambda c: min(
        graph.nodes[p].topo_order for p in c if p in graph.nodes
    ) if c else 999)

    return clusters


def _assign_cross_batch_context(
    batches: List[Batch],
    graph: DependencyGraph,
    analyses: Dict[str, FileAnalysis],
):
    """Determine which files from other batches each batch needs context from."""
    # Build file -> batch mapping
    file_to_batch: Dict[str, int] = {}
    for batch in batches:
        for path in batch.files:
            file_to_batch[path] = batch.id

    for batch in batches:
        needed_context = set()
        for path in batch.files:
            # Find dependencies that are in OTHER batches
            deps = graph.adjacency.get(path, set())
            for dep in deps:
                dep_batch = file_to_batch.get(dep, -1)
                if dep_batch != batch.id and dep_batch >= 0:
                    needed_context.add(dep)

        # Sort by importance (most depended-on first)
        batch.context_files = sorted(
            needed_context,
            key=lambda p: graph.nodes[p].importance_score if p in graph.nodes else 0,
            reverse=True
        )[:20]  # Cap at 20 context files


# ══════════════════════════════════════════════════════════════
# CONTEXT GENERATION FOR PROMPTS
# ══════════════════════════════════════════════════════════════

def generate_batch_context(
    batch: Batch,
    analyses: Dict[str, FileAnalysis],
    generated_code: Dict[str, str] = None,
    max_chars: int = 30000,
) -> str:
    """
    Generate rich context string for a batch's code generation prompt.

    Includes:
    - Structural summaries of files in this batch
    - Cross-batch dependency summaries
    - Already-generated code from foundation/dependency batches (truncated)
    """
    sections = []
    chars_used = 0

    # ── Section 1: Files in this batch ──
    sections.append("=== FILES TO GENERATE IN THIS BATCH ===")
    for path in batch.files:
        if path in analyses:
            summary = analyses[path].summary()
            sections.append(f"  {path}: {summary}")

    # ── Section 2: Cross-batch dependencies ──
    if batch.context_files:
        sections.append("\n=== DEPENDENCIES FROM OTHER BATCHES (already generated) ===")
        for path in batch.context_files:
            if path in analyses:
                summary = analyses[path].summary()
                sections.append(f"  {path}: {summary}")

                # If we have the generated code, include key exports
                if generated_code and path in generated_code:
                    code = generated_code[path]
                    # Extract just the function/class signatures (first 20 lines per function)
                    key_lines = _extract_key_signatures(code, analyses.get(path))
                    if key_lines:
                        sections.append(f"    Key signatures:\n{key_lines}")

    # ── Section 3: Foundation file summaries ──
    if batch.foundation_files and batch.id > 0:
        sections.append("\n=== FOUNDATION FILES (core utilities/types) ===")
        for path in batch.foundation_files:
            if path in analyses:
                sections.append(f"  {path}: {analyses[path].summary()}")
                if generated_code and path in generated_code:
                    code = generated_code[path]
                    key_lines = _extract_key_signatures(code, analyses.get(path))
                    if key_lines:
                        remaining = max_chars - chars_used
                        if len(key_lines) > remaining:
                            key_lines = key_lines[:remaining] + "... (truncated)"
                        sections.append(f"    Signatures:\n{key_lines}")
                        chars_used += len(key_lines)

    result = '\n'.join(sections)

    # Truncate if over limit
    if len(result) > max_chars:
        result = result[:max_chars] + "\n... (context truncated)"

    return result


def _extract_key_signatures(code: str, analysis: Optional[FileAnalysis] = None) -> str:
    """Extract function/class signatures from generated code for context."""
    lines = code.split('\n')
    key_lines = []

    for i, line in enumerate(lines):
        stripped = line.strip()
        # Python/JS function/class definitions
        if any(stripped.startswith(kw) for kw in [
            'def ', 'async def ', 'class ', 'function ', 'async function ',
            'export function', 'export async function', 'export class',
            'export default function', 'export default class',
            'export const ', 'export interface ', 'export type ',
            'const ', 'interface ', 'type ',
        ]):
            # Include the signature line + up to 2 more lines for type annotations
            sig_lines = [line]
            for j in range(i + 1, min(i + 3, len(lines))):
                next_line = lines[j].strip()
                if next_line.startswith(('"""', "'''", '/*', '*', '//')):
                    continue
                if next_line and not next_line.startswith(('return', 'this.', 'self.')):
                    sig_lines.append(lines[j])
                else:
                    break
            key_lines.append('\n'.join(sig_lines))

    return '\n'.join(key_lines[:30])  # Cap at 30 signatures
