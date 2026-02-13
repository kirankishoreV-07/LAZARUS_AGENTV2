"""
Lazarus Engine — Phase 1: Async Parallel I/O
=============================================
Replaces sequential file fetching with concurrent async operations.
Uses asyncio + aiohttp for 10x faster repository scanning.

Features:
  - Parallel file fetching (up to 20 concurrent requests)
  - Multi-strategy fallback (Contents API → Raw URL → Blob API)
  - Exponential backoff with jitter for rate limits
  - Multi-encoding detection (UTF-8, Latin-1, UTF-16, CP1252)
  - Magic number binary detection
  - Connection pooling and timeout management
"""

import asyncio
import aiohttp
import base64
import time
import os
import logging
import random
from typing import Optional, Dict, List, Tuple

logger = logging.getLogger('lazarus.async_fetcher')

# ══════════════════════════════════════════════════════════════
# CONSTANTS
# ══════════════════════════════════════════════════════════════

MAX_CONCURRENT_REQUESTS = 20  # Semaphore limit
REQUEST_TIMEOUT = 30          # Per-request timeout (seconds)
MAX_RETRIES = 3               # Retries per file
MAX_FILE_SIZE = 500_000       # Skip files > 500KB

# Binary file magic numbers (first few bytes)
BINARY_MAGIC_BYTES = [
    b'\x89PNG',       # PNG
    b'\xff\xd8\xff',  # JPEG
    b'GIF87a', b'GIF89a',  # GIF
    b'PK',            # ZIP/DOCX/XLSX
    b'\x7fELF',       # ELF binary
    b'\xfe\xed\xfa',  # Mach-O
    b'MZ',            # PE/EXE
    b'\x1f\x8b',      # GZIP
    b'BM',            # BMP
    b'RIFF',          # WAV/AVI
    b'\x00\x00\x01\x00',  # ICO
    b'wOFF',          # WOFF
    b'wOF2',          # WOFF2
    b'\x00\x01\x00\x00',  # TTF
    b'OTTO',          # OTF
]

# Extensions that are definitely binary (skip entirely)
BINARY_EXTENSIONS = {
    '.png', '.jpg', '.jpeg', '.gif', '.ico', '.bmp', '.webp', '.tiff',
    '.mp3', '.mp4', '.wav', '.avi', '.mkv', '.mov', '.flac', '.ogg',
    '.zip', '.tar', '.gz', '.rar', '.7z', '.bz2', '.xz',
    '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
    '.woff', '.woff2', '.ttf', '.eot', '.otf',
    '.pyc', '.pyo', '.so', '.dll', '.exe', '.o', '.a', '.dylib',
    '.DS_Store', '.map', '.min.js.map', '.min.css.map',
}

# Directories to skip (exact component match)
SKIP_DIRS = {
    'node_modules', 'venv', '.venv', '__pycache__', '.git',
    'dist', 'build', '.next', '.nuxt', 'coverage', '.cache',
    'vendor', 'bower_components', '.tox', 'egg-info', '.eggs',
    '.svn', '.hg', '.idea', '.vscode',
}

# File extensions worth fetching
CODE_EXTENSIONS = {
    '.py', '.js', '.ts', '.tsx', '.jsx', '.mjs', '.cjs',
    '.rb', '.go', '.rs', '.java', '.php', '.c', '.cpp', '.h', '.cs',
    '.swift', '.kt', '.dart', '.lua', '.r', '.pl', '.sh', '.bat', '.ps1',
    '.html', '.htm', '.css', '.scss', '.sass', '.less', '.styl',
    '.vue', '.svelte', '.ejs', '.pug', '.hbs', '.handlebars', '.mustache',
    '.astro', '.mdx',
    '.json', '.yaml', '.yml', '.toml', '.cfg', '.ini', '.xml',
    '.env', '.conf', '.properties', '.editorconfig',
    '.sql', '.prisma', '.graphql', '.gql', '.proto',
    '.md', '.txt', '.rst', '.csv',
    '.lock', '.npmrc', '.nvmrc', '.babelrc',
    '.dockerfile', '.svg',
}

IMPORTANT_FILES = {
    'package.json', 'package-lock.json', 'yarn.lock', 'pnpm-lock.yaml',
    'requirements.txt', 'Pipfile', 'pyproject.toml', 'setup.py', 'setup.cfg',
    'docker-compose.yml', 'docker-compose.yaml', 'Dockerfile',
    '.env', '.env.example', '.env.local',
    'Makefile', 'Procfile', 'Gemfile',
    '.gitignore', '.dockerignore', 'vercel.json', 'netlify.toml',
    'tsconfig.json', 'next.config.js', 'next.config.mjs', 'next.config.ts',
    'vite.config.js', 'vite.config.ts', 'tailwind.config.js', 'tailwind.config.ts',
    'postcss.config.js', 'postcss.config.mjs',
    'eslint.config.js', 'eslint.config.mjs',
}


# ══════════════════════════════════════════════════════════════
# ENCODING DETECTION
# ══════════════════════════════════════════════════════════════

ENCODINGS_TO_TRY = ['utf-8', 'latin-1', 'utf-16', 'cp1252', 'ascii']

def decode_content(raw_bytes: bytes) -> Optional[str]:
    """
    Try multiple encodings to decode bytes to string.
    Returns None if content appears to be binary.
    """
    # Check magic bytes first
    for magic in BINARY_MAGIC_BYTES:
        if raw_bytes[:len(magic)] == magic:
            return None

    # Heuristic: if > 10% null bytes, it's binary
    if raw_bytes.count(b'\x00') > len(raw_bytes) * 0.1:
        return None

    for encoding in ENCODINGS_TO_TRY:
        try:
            text = raw_bytes.decode(encoding)
            # Additional binary check: control characters (except common ones)
            control_count = sum(1 for c in text[:1000] if ord(c) < 32
                                and c not in '\n\r\t')
            if control_count > len(text[:1000]) * 0.05:
                continue  # Too many control chars, probably binary
            return text
        except (UnicodeDecodeError, UnicodeError):
            continue

    return None  # All encodings failed


def should_fetch_file(path: str, size: int = 0) -> bool:
    """Determine if a file should be fetched based on path and size."""
    _, ext = os.path.splitext(path)
    filename = os.path.basename(path)

    # Skip binary extensions
    if ext.lower() in BINARY_EXTENSIONS:
        return False

    # Skip large files
    if size > MAX_FILE_SIZE:
        return False

    # Skip directories in SKIP_DIRS
    path_parts = set(path.replace('\\', '/').split('/'))
    if path_parts & SKIP_DIRS:
        return False

    # Fetch if code extension or important file
    return (
        ext.lower() in CODE_EXTENSIONS
        or filename in IMPORTANT_FILES
        or 'model' in path.lower()
        or 'schema' in path.lower()
        or 'route' in path.lower()
        or 'api' in path.lower()
        or 'controller' in path.lower()
    )


# ══════════════════════════════════════════════════════════════
# ASYNC FILE FETCHER
# ══════════════════════════════════════════════════════════════

async def _fetch_single_file(
    session: aiohttp.ClientSession,
    semaphore: asyncio.Semaphore,
    owner: str,
    repo: str,
    path: str,
    branch: str,
    headers: dict,
    blob_sha: Optional[str] = None,
) -> Optional[Tuple[str, str]]:
    """
    Fetch a single file with multi-strategy fallback.
    Returns (path, content) or None if all strategies fail.

    Strategy 1: GitHub Contents API (< 1MB)
    Strategy 2: raw.githubusercontent.com (no limit)
    Strategy 3: Git Blob API (if SHA available)
    """
    async with semaphore:
        for attempt in range(MAX_RETRIES):
            # Strategy 1: Contents API
            try:
                url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}?ref={branch}"
                async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if isinstance(data, list):
                            return None  # Directory listing
                        if data.get('encoding') == 'base64' and data.get('content'):
                            raw = base64.b64decode(data['content'])
                            text = decode_content(raw)
                            if text is not None:
                                return (path, text)
                        download_url = data.get('download_url')
                        if download_url:
                            async with session.get(download_url, timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)) as dl_resp:
                                if dl_resp.status == 200:
                                    raw = await dl_resp.read()
                                    text = decode_content(raw)
                                    if text is not None:
                                        return (path, text)
                    elif resp.status == 403:
                        body = await resp.text()
                        if 'too large' in body.lower():
                            break  # Skip to Strategy 2
                        # Rate limited — backoff
                        wait = (2 ** attempt) + random.uniform(0, 1)
                        await asyncio.sleep(wait)
                        continue
                    elif resp.status == 404:
                        return None
                    elif resp.status == 429:
                        wait = (3 ** attempt) + random.uniform(0, 2)
                        logger.warning(f"Rate limited fetching {path}, waiting {wait:.1f}s")
                        await asyncio.sleep(wait)
                        continue
            except asyncio.TimeoutError:
                logger.debug(f"Timeout fetching {path} (attempt {attempt + 1})")
                continue
            except Exception as e:
                logger.debug(f"Contents API error for {path}: {e}")
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(1)
                    continue

        # Strategy 2: Raw URL (no rate limit, no size limit)
        try:
            raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path}"
            async with session.get(raw_url, timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)) as resp:
                if resp.status == 200:
                    raw = await resp.read()
                    text = decode_content(raw)
                    if text is not None:
                        return (path, text)
        except Exception as e:
            logger.debug(f"Raw URL fallback failed for {path}: {e}")

        # Strategy 3: Blob API (if SHA available)
        if blob_sha:
            try:
                blob_url = f"https://api.github.com/repos/{owner}/{repo}/git/blobs/{blob_sha}"
                async with session.get(blob_url, headers=headers, timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get('encoding') == 'base64':
                            raw = base64.b64decode(data['content'])
                            text = decode_content(raw)
                            if text is not None:
                                return (path, text)
            except Exception as e:
                logger.debug(f"Blob API fallback failed for {path}: {e}")

        logger.warning(f"All fetch strategies failed for: {path}")
        return None


async def fetch_all_files_async(
    owner: str,
    repo: str,
    tree: List[dict],
    branch: str,
    github_token: Optional[str] = None,
) -> List[Tuple[str, str]]:
    """
    Fetch all eligible files from a GitHub repository concurrently.

    Args:
        owner: GitHub repo owner
        repo: GitHub repo name
        tree: List of tree items from GitHub API
        branch: Branch name
        github_token: Optional GitHub auth token

    Returns:
        List of (path, content) tuples
    """
    headers = {"Accept": "application/vnd.github.v3+json"}
    if github_token:
        headers["Authorization"] = f"token {github_token}"

    # Filter to fetchable files
    fetchable = []
    for item in tree:
        if item['type'] != 'blob':
            continue
        path = item['path']
        size = item.get('size', 0)
        if should_fetch_file(path, size):
            fetchable.append(item)

    total = len(fetchable)
    logger.info(f"Async fetching {total} files (from {len(tree)} total items)")

    semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

    connector = aiohttp.TCPConnector(limit=MAX_CONCURRENT_REQUESTS, limit_per_host=10)
    timeout = aiohttp.ClientTimeout(total=60)

    results = []
    start_time = time.time()

    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        tasks = [
            _fetch_single_file(
                session, semaphore, owner, repo,
                item['path'], branch, headers, item.get('sha')
            )
            for item in fetchable
        ]

        # Gather with progress logging
        completed = 0
        for coro in asyncio.as_completed(tasks):
            result = await coro
            completed += 1
            if result is not None:
                results.append(result)
            if completed % 20 == 0 or completed == total:
                elapsed = time.time() - start_time
                logger.info(f"  Progress: {completed}/{total} files fetched ({len(results)} successful, {elapsed:.1f}s)")

    elapsed = time.time() - start_time
    logger.info(f"Async fetch complete: {len(results)}/{total} files in {elapsed:.1f}s")

    return results


def fetch_files_parallel(
    owner: str,
    repo: str,
    tree: List[dict],
    branch: str,
    github_token: Optional[str] = None,
) -> List[Tuple[str, str]]:
    """
    Synchronous wrapper for async file fetching.
    Can be called from non-async code (like the existing LazarusEngine).

    Returns list of (path, content) tuples.
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # If already in an event loop (e.g., Jupyter), create a new one in a thread
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(
                    asyncio.run,
                    fetch_all_files_async(owner, repo, tree, branch, github_token)
                )
                return future.result(timeout=300)
        else:
            return loop.run_until_complete(
                fetch_all_files_async(owner, repo, tree, branch, github_token)
            )
    except RuntimeError:
        # No event loop exists
        return asyncio.run(
            fetch_all_files_async(owner, repo, tree, branch, github_token)
        )
