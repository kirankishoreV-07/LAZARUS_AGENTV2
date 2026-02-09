import os
import json
import re
import requests
import time
import ast
import logging
import traceback as tb_module
from simple_env import load_env
from prompts import (
    get_code_generation_prompt,
    get_lightweight_plan_prompt,
    get_batch_code_generation_prompt,
    extract_batch_summary,
)
from resurrection_memory import (
    load_memory, record_attempt_start, record_failure, 
    record_success, record_dependency_issue, record_decision,
    get_memory_context_for_prompt, get_memory_summary
)


class GeminiAPIError(Exception):
    """Raised when all Gemini API models fail after retries."""
    def __init__(self, message, models_tried=None, last_status=None):
        super().__init__(message)
        self.models_tried = models_tried or []
        self.last_status = last_status

# Setup logger for lazarus_agent module
logger = logging.getLogger('lazarus.agent')

# Debug log bridge - imports from main.py at runtime to avoid circular imports
def _add_debug_log(level, category, message, details=None):
    """Add debug log entry - bridges to main.py's buffer."""
    try:
        from main import add_debug_log
        add_debug_log(level, category, message, details)
    except ImportError:
        pass  # Running standalone, skip

# Try to import E2B, handle failure
try:
    from e2b_code_interpreter import Sandbox
    E2B_AVAILABLE = True
except ImportError:
    E2B_AVAILABLE = False
    print("[!] E2B Code Interpreter not found. Sandbox execution will be skipped.")

# Load Environment
load_env()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
E2B_API_KEY = os.getenv("E2B_API_KEY")

def sanitize_path(path: str) -> str:
    """
    Sanitizes file paths to be safe for bash shell commands.
    Removes characters that break mkdir and other shell commands.
    """
    if not path:
        return path
    
    # Replace problematic characters
    replacements = {
        '(': '',  # Remove parentheses - causes subshell
        ')': '',
        '[': '',  # Remove brackets - causes glob
        ']': '',
        '{': '',  # Remove braces - causes expansion
        '}': '',
        '@': '',  # Remove @ - causes issues
        '#': '',  # Remove # - causes comments
        '$': '',  # Remove $ - causes variable expansion
        '&': '',  # Remove & - causes background
        '*': '',  # Remove * - causes glob
        '?': '',  # Remove ? - causes glob
        '!': '',  # Remove ! - causes history expansion
        '|': '',  # Remove | - causes pipe
        ';': '',  # Remove ; - causes command separator
        '<': '',  # Remove < - causes redirect
        '>': '',  # Remove > - causes redirect
        '`': '',  # Remove ` - causes command substitution
        "'": '',  # Remove ' - causes quoting issues
        '"': '',  # Remove " - causes quoting issues
        ' ': '_',  # Replace spaces with underscores
    }
    
    result = path
    for char, replacement in replacements.items():
        result = result.replace(char, replacement)
    
    # Remove any double underscores
    while '__' in result:
        result = result.replace('__', '_')
    
    # Remove any double slashes
    while '//' in result:
        result = result.replace('//', '/')
    
    return result

class LazarusEngine:
    # ═══════════════════════════════════════════════════════════
    # MODEL CONTEXT WINDOWS (Dynamic Batch Sizing)
    # ═══════════════════════════════════════════════════════════
    MODEL_CONTEXT_LIMITS = {
        # Model Name: (tokens, safe_chars_for_code, description)
        "gemini-3-flash-preview": (1_048_576, 700_000, "1M tokens - Gemini 3 Flash (PRIMARY)"),
        "gemini-3-pro-preview": (2_097_152, 1_400_000, "1M tokens - Gemini 3 Pro (flagship)"),
        "gemini-2.0-flash-exp": (1_048_576, 600_000, "1M tokens - Experimental Flash"),
        "gemini-2.0-flash": (1_048_576, 600_000, "1M tokens - Stable Flash (fallback)"),
        "gemini-1.5-flash": (1_048_576, 600_000, "1M tokens - Legacy Flash"),
        "gemini-1.5-pro": (2_097_152, 1_400_000, "2M tokens - Legacy Pro"),
    }
    
    def __init__(self):
        self.api_key = GEMINI_API_KEY
        self.github_token = os.getenv("GITHUB_TOKEN")
        # ── Model Selection (Gemini 3 Series - Confirmed Working) ──
        # gemini-3-flash-preview: Latest Flash - Best cost/performance ✨
        # gemini-2.0-flash:       Stable fallback - 2K RPM
        # gemini-1.5-flash:       Legacy fallback - High availability
        self.planner_model = "gemini-2.0-flash"              # Fast planning (2K RPM)
        self.coder_model = "gemini-3-flash-preview"          # PRIMARY: Gemini 3 Flash ✅
        self.base_url = "https://generativelanguage.googleapis.com/v1beta/models"
        
        # E2B Persistence
        self.sandbox = None
    
    def get_model_max_chars(self, model_name: str = None) -> int:
        """Get safe character limit for a model (defaults to coder model)."""
        model = model_name or self.coder_model
        if model in self.MODEL_CONTEXT_LIMITS:
            return self.MODEL_CONTEXT_LIMITS[model][1]  # safe_chars
        # Fallback for unknown models
        return 400_000  # Conservative default

    def commit_to_github(self, repo_url: str, filename: str, content: str) -> dict:
        """
        Commits a file to a 'lazarus-resurrection' branch, creating it if needed.
        Returns a URL to open a Pull Request.
        """
        if not self.github_token:
            return {"status": "error", "message": "GITHUB_TOKEN is missing."}

        try:
            # Parse owner/repo
            match = re.search(r"github\.com/([^/]+)/([^/.]+)", repo_url)
            if not match:
                return {"status": "error", "message": "Invalid GitHub URL."}
            
            owner, repo_name = match.groups()
            base_api = f"https://api.github.com/repos/{owner}/{repo_name}"
            headers = {
                "Authorization": f"token {self.github_token}",
                "Accept": "application/vnd.github.v3+json"
            }
            target_branch = "lazarus-resurrection"

            # 1. Check if target branch exists
            branch_resp = requests.get(f"{base_api}/git/ref/heads/{target_branch}", headers=headers)
            
            if branch_resp.status_code == 404:
                # Branch doesn't exist, create it from main
                print(f"[*] Branch {target_branch} not found. Creating from main...")
                main_resp = requests.get(f"{base_api}/git/ref/heads/main", headers=headers)
                if main_resp.status_code != 200:
                    return {"status": "error", "message": "Could not find main branch to fork from."}
                
                main_sha = main_resp.json()['object']['sha']
                
                create_resp = requests.post(
                    f"{base_api}/git/refs",
                    headers=headers,
                    json={"ref": f"refs/heads/{target_branch}", "sha": main_sha}
                )
                if create_resp.status_code != 201:
                    return {"status": "error", "message": f"Failed to create branch: {create_resp.text}"}
            
            elif branch_resp.status_code != 200:
                 return {"status": "error", "message": f"Error checking branch: {branch_resp.text}"}

            # 2. Get file SHA in target branch (if exists) for update
            file_api = f"{base_api}/contents/{filename}?ref={target_branch}"
            sha = None
            file_resp = requests.get(file_api, headers=headers)
            if file_resp.status_code == 200:
                sha = file_resp.json().get('sha')

            # 3. Commit File
            import base64
            content_bytes = content.encode('utf-8')
            base64_content = base64.b64encode(content_bytes).decode('utf-8')

            data = {
                "message": f"Lazarus Resurrection: {filename}",
                "content": base64_content,
                "branch": target_branch
            }
            if sha:
                data["sha"] = sha

            put_resp = requests.put(f"{base_api}/contents/{filename}", headers=headers, json=data)
            
            if put_resp.status_code in [200, 201]:
                # 4. Create Pull Request
                print(f"[*] File committed. Creating Pull Request...")
                
                # Check if PR already exists
                pr_check_resp = requests.get(
                    f"{base_api}/pulls",
                    headers=headers,
                    params={"head": f"{owner}:{target_branch}", "base": "main", "state": "open"}
                )
                
                if pr_check_resp.status_code == 200 and len(pr_check_resp.json()) > 0:
                    # PR already exists, return its URL
                    existing_pr = pr_check_resp.json()[0]
                    return {
                        "status": "success", 
                        "commit_url": existing_pr['html_url'],
                        "message": f"Pull Request already exists. Check it on GitHub."
                    }
                
                # Create new PR
                pr_data = {
                    "title": "🧬 Lazarus Resurrection - Modernized Codebase",
                    "body": "## 🦾 Automated Resurrection by Lazarus Engine\n\nThis PR contains the modernized version of your legacy codebase.\n\n### Changes:\n- ✅ Modern FastAPI backend with CORS, validation, and JWT auth\n- ✅ Next.js 15 frontend with Tailwind CSS\n- ✅ Production-ready code with error handling\n- ✅ Docker Compose for easy deployment\n\n---\n*Generated by [Lazarus Engine](https://github.com/ArunN2005/lazarus-hackathon)*",
                    "head": target_branch,
                    "base": "main"
                }
                
                pr_resp = requests.post(f"{base_api}/pulls", headers=headers, json=pr_data)
                
                if pr_resp.status_code == 201:
                    pr_url = pr_resp.json()['html_url']
                    pr_number = pr_resp.json()['number']
                    return {
                        "status": "success", 
                        "commit_url": pr_url,
                        "message": f"Pull Request #{pr_number} created successfully! Check it on GitHub."
                    }
                elif pr_resp.status_code == 422:
                    # PR might already exist or no changes
                    compare_url = f"https://github.com/{owner}/{repo_name}/compare/main...{target_branch}?expand=1"
                    return {
                        "status": "success", 
                        "commit_url": compare_url,
                        "message": f"Files committed to {target_branch}. Create PR manually or check existing PRs."
                    }
                else:
                    compare_url = f"https://github.com/{owner}/{repo_name}/compare/main...{target_branch}?expand=1"
                    return {
                        "status": "success", 
                        "commit_url": compare_url,
                        "message": f"Files committed. PR creation failed: {pr_resp.text[:100]}"
                    }
            else:
                return {"status": "error", "message": f"GitHub API Error: {put_resp.text}"}

        except Exception as e:
            return {"status": "error", "message": str(e)}

    def commit_all_files_to_github(self, repo_url: str, files: list) -> dict:
        """
        Commits ALL files to a 'lazarus-resurrection' branch and creates a PR.
        files: list of {"filename": str, "content": str}
        """
        if not self.github_token:
            return {"status": "error", "message": "GITHUB_TOKEN is missing."}

        try:
            import base64
            
            # Parse owner/repo
            match = re.search(r"github\.com/([^/]+)/([^/.]+)", repo_url)
            if not match:
                return {"status": "error", "message": "Invalid GitHub URL."}
            
            owner, repo_name = match.groups()
            base_api = f"https://api.github.com/repos/{owner}/{repo_name}"
            headers = {
                "Authorization": f"token {self.github_token}",
                "Accept": "application/vnd.github.v3+json"
            }
            target_branch = "lazarus-resurrection"

            print(f"[*] Creating PR for {len(files)} files...")

            # 1. Get the base branch (try main, then master)
            base_branch = "main"
            main_resp = requests.get(f"{base_api}/git/ref/heads/main", headers=headers)
            if main_resp.status_code != 200:
                main_resp = requests.get(f"{base_api}/git/ref/heads/master", headers=headers)
                base_branch = "master"
                if main_resp.status_code != 200:
                    return {"status": "error", "message": "Could not find main or master branch."}
            
            base_sha = main_resp.json()['object']['sha']

            # 2. Create or update the target branch
            branch_resp = requests.get(f"{base_api}/git/ref/heads/{target_branch}", headers=headers)
            
            if branch_resp.status_code == 404:
                print(f"[*] Creating branch '{target_branch}'...")
                create_resp = requests.post(
                    f"{base_api}/git/refs",
                    headers=headers,
                    json={"ref": f"refs/heads/{target_branch}", "sha": base_sha}
                )
                if create_resp.status_code != 201:
                    return {"status": "error", "message": f"Failed to create branch: {create_resp.text}"}
            else:
                # Update existing branch to latest base
                print(f"[*] Updating branch '{target_branch}'...")
                requests.patch(
                    f"{base_api}/git/refs/heads/{target_branch}",
                    headers=headers,
                    json={"sha": base_sha, "force": True}
                )

            # 3. Get the base tree
            base_commit_resp = requests.get(f"{base_api}/git/commits/{base_sha}", headers=headers)
            base_tree_sha = base_commit_resp.json()['tree']['sha']

            # 4. Create blobs for each file
            tree_items = []
            for f in files:
                content_bytes = f['content'].encode('utf-8')
                base64_content = base64.b64encode(content_bytes).decode('utf-8')
                
                blob_resp = requests.post(
                    f"{base_api}/git/blobs",
                    headers=headers,
                    json={"content": base64_content, "encoding": "base64"}
                )
                
                if blob_resp.status_code == 201:
                    blob_sha = blob_resp.json()['sha']
                    tree_items.append({
                        "path": f['filename'],
                        "mode": "100644",
                        "type": "blob",
                        "sha": blob_sha
                    })
                    print(f"  [+] Staged: {f['filename']}")
                else:
                    print(f"  [!] Failed to create blob for {f['filename']}")

            if not tree_items:
                return {"status": "error", "message": "No files were staged."}

            # 5. Create a new tree
            tree_resp = requests.post(
                f"{base_api}/git/trees",
                headers=headers,
                json={"base_tree": base_tree_sha, "tree": tree_items}
            )
            
            if tree_resp.status_code != 201:
                return {"status": "error", "message": f"Failed to create tree: {tree_resp.text}"}
            
            new_tree_sha = tree_resp.json()['sha']

            # 6. Create a commit
            commit_resp = requests.post(
                f"{base_api}/git/commits",
                headers=headers,
                json={
                    "message": f"🧬 Lazarus Resurrection: Modernized {len(files)} files",
                    "tree": new_tree_sha,
                    "parents": [base_sha]
                }
            )
            
            if commit_resp.status_code != 201:
                return {"status": "error", "message": f"Failed to create commit: {commit_resp.text}"}
            
            new_commit_sha = commit_resp.json()['sha']
            print(f"[*] Created commit: {new_commit_sha[:7]}")

            # 7. Update the branch reference
            update_resp = requests.patch(
                f"{base_api}/git/refs/heads/{target_branch}",
                headers=headers,
                json={"sha": new_commit_sha}
            )
            
            if update_resp.status_code != 200:
                return {"status": "error", "message": f"Failed to update branch: {update_resp.text}"}

            # 8. Check if PR already exists
            pr_check_resp = requests.get(
                f"{base_api}/pulls",
                headers=headers,
                params={"head": f"{owner}:{target_branch}", "base": base_branch, "state": "open"}
            )
            
            if pr_check_resp.status_code == 200 and len(pr_check_resp.json()) > 0:
                existing_pr = pr_check_resp.json()[0]
                return {
                    "status": "success", 
                    "pr_url": existing_pr['html_url'],
                    "message": f"Pull Request updated with {len(files)} files. Check it on GitHub!"
                }

            # 9. Create new PR
            pr_data = {
                "title": "🧬 Lazarus Resurrection - Modernized Codebase",
                "body": f"""## 🦾 Automated Resurrection by Lazarus Engine

This PR contains the **completely modernized** version of your legacy codebase.

### 📁 Files Changed ({len(files)} files)
{chr(10).join([f"- `{f['filename']}`" for f in files[:20]])}
{"..." if len(files) > 20 else ""}

### ✨ What's Included
- ✅ Modern FastAPI backend with CORS and validation
- ✅ Next.js 15 frontend with Tailwind CSS
- ✅ Production-ready code with error handling
- ✅ Docker Compose for deployment  
- ✅ TypeScript types and Pydantic models

---
*Generated by [Lazarus Engine](https://github.com/ArunN2005/lazarus-hackathon) 🧬*""",
                "head": target_branch,
                "base": base_branch
            }
            
            pr_resp = requests.post(f"{base_api}/pulls", headers=headers, json=pr_data)
            
            if pr_resp.status_code == 201:
                pr_url = pr_resp.json()['html_url']
                pr_number = pr_resp.json()['number']
                print(f"[*] Pull Request #{pr_number} created!")
                return {
                    "status": "success", 
                    "pr_url": pr_url,
                    "message": f"Pull Request #{pr_number} created with {len(files)} files!"
                }
            else:
                compare_url = f"https://github.com/{owner}/{repo_name}/compare/{base_branch}...{target_branch}?expand=1"
                return {
                    "status": "success", 
                    "pr_url": compare_url,
                    "message": f"Files committed. Create PR manually: {pr_resp.text[:100]}"
                }

        except Exception as e:
            print(f"[!] PR Creation Error: {str(e)}")
            return {"status": "error", "message": str(e)}

    def scan_repository(self, repo_url: str) -> list:
        """ Fetches the file tree of the remote repository using GitHub API. """
        try:
            # Parse owner/repo
            match = re.search(r"github\.com/([^/]+)/([^/.]+)", repo_url)
            if not match:
                return ["(Invalid URL - Simulating Scan)"]
            
            owner, repo_name = match.groups()
            
            # Try both 'main' and 'master' branches
            branches = ['main', 'master']
            
            headers = {"Accept": "application/vnd.github.v3+json"}
            if self.github_token:
                headers["Authorization"] = f"token {self.github_token}"
            
            for branch in branches:
                api_url = f"https://api.github.com/repos/{owner}/{repo_name}/git/trees/{branch}?recursive=1"
                
                resp = requests.get(api_url, headers=headers, timeout=30)
                if resp.status_code == 200:
                    resp_json = resp.json()
                    tree = resp_json.get('tree', [])
                    if resp_json.get('truncated'):
                        print(f"[!] Warning: Repository tree was truncated by GitHub API")
                    # Return list of paths (filter out directories)
                    paths = [item['path'] for item in tree if item['type'] == 'blob']
                    print(f"[*] Scan found {len(paths)} files on branch '{branch}'")
                    return paths
            
            # If both branches failed, try to get default branch from repo info
            repo_api_url = f"https://api.github.com/repos/{owner}/{repo_name}"
            repo_resp = requests.get(repo_api_url, headers=headers)
            if repo_resp.status_code == 200:
                default_branch = repo_resp.json().get('default_branch', 'main')
                api_url = f"https://api.github.com/repos/{owner}/{repo_name}/git/trees/{default_branch}?recursive=1"
                resp = requests.get(api_url, headers=headers)
                if resp.status_code == 200:
                    tree = resp.json().get('tree', [])
                    return [item['path'] for item in tree if item['type'] == 'blob']
            
            return [f"(API Error - Could not find repository or branch)"]
                 
        except Exception as e:
            return [f"(Scan Error: {str(e)})"]

    def scan_repository_deep(self, repo_url: str) -> dict:
        """
        DEEP SCAN: Fetches ALL file CONTENTS, not just paths.
        This is the foundation of preservation-first architecture.
        
        Returns: {
            "files": [{"path": str, "content": str, "language": str}],
            "tech_stack": {...},
            "database": {...},
            "must_preserve": [...],
            "can_modernize": [...]
        }
        """
        import base64
        
        result = {
            "files": [],
            "tech_stack": {
                "backend": {"framework": None, "database": None, "auth": None},
                "frontend": {"framework": None, "styling": None},
            },
            "must_preserve": [],
            "can_modernize": [],
            "env_vars": [],
            "api_endpoints": [],
            "database_schemas": []
        }
        
        try:
            # Parse owner/repo
            match = re.search(r"github\.com/([^/]+)/([^/.]+)", repo_url)
            if not match:
                return result
            
            owner, repo_name = match.groups()
            
            headers = {"Accept": "application/vnd.github.v3+json"}
            if self.github_token:
                headers["Authorization"] = f"token {self.github_token}"
            
            # Get default branch
            repo_resp = requests.get(f"https://api.github.com/repos/{owner}/{repo_name}", headers=headers)
            default_branch = "main"
            if repo_resp.status_code == 200:
                default_branch = repo_resp.json().get('default_branch', 'main')
            
            # Get file tree
            tree_url = f"https://api.github.com/repos/{owner}/{repo_name}/git/trees/{default_branch}?recursive=1"
            tree_resp = requests.get(tree_url, headers=headers, timeout=30)
            
            if tree_resp.status_code != 200:
                print(f"[!] Failed to get repository tree: {tree_resp.status_code}")
                _add_debug_log('ERROR', 'DEEP_SCAN', f'Tree API failed: HTTP {tree_resp.status_code}', {
                    'response': tree_resp.text[:300]
                })
                return result
            
            tree_json = tree_resp.json()
            tree = tree_json.get('tree', [])
            
            if tree_json.get('truncated'):
                print(f"[!] ⚠️ Tree was truncated by GitHub! Some files may be missing.")
                _add_debug_log('WARNING', 'DEEP_SCAN', 'GitHub tree API returned truncated results', {})
            
            total_items = len(tree)
            blob_items = [item for item in tree if item['type'] == 'blob']
            print(f"[*] Repository tree: {total_items} items total, {len(blob_items)} files (blobs)")
            
            # File extensions to fetch content for (COMPREHENSIVE)
            code_extensions = {
                # Languages
                '.py', '.js', '.ts', '.tsx', '.jsx', '.mjs', '.cjs',
                '.rb', '.go', '.rs', '.java', '.php', '.c', '.cpp', '.h', '.cs',
                '.swift', '.kt', '.dart', '.lua', '.r', '.pl', '.sh', '.bat', '.ps1',
                # Web
                '.html', '.htm', '.css', '.scss', '.sass', '.less', '.styl',
                '.vue', '.svelte', '.ejs', '.pug', '.hbs', '.handlebars', '.mustache',
                '.astro', '.mdx',
                # Config & Data
                '.json', '.yaml', '.yml', '.toml', '.cfg', '.ini', '.xml',
                '.env', '.env.example', '.env.local', '.env.development', '.env.production',
                '.conf', '.properties', '.editorconfig',
                # DB & API
                '.sql', '.prisma', '.graphql', '.gql', '.proto',
                # Docs & Text
                '.md', '.txt', '.rst', '.csv',
                # Build & Package
                '.lock', '.npmrc', '.nvmrc', '.babelrc',
                # Docker
                '.dockerfile',
                # SVG (used in components)
                '.svg',
            }
            
            # Files to always fetch (by exact name)
            important_files = {
                'package.json', 'package-lock.json', 'yarn.lock', 'pnpm-lock.yaml',
                'requirements.txt', 'Pipfile', 'Pipfile.lock', 'pyproject.toml', 'setup.py', 'setup.cfg',
                'docker-compose.yml', 'docker-compose.yaml', 'Dockerfile',
                '.env', '.env.example', '.env.local', '.env.development',
                'config.py', 'settings.py', 'config.js', 'config.ts',
                'schema.prisma', 'models.py', 'schemas.py', 'database.py',
                'tsconfig.json', 'jsconfig.json', 'next.config.js', 'next.config.mjs', 'next.config.ts',
                'vite.config.js', 'vite.config.ts', 'webpack.config.js',
                'tailwind.config.js', 'tailwind.config.ts', 'postcss.config.js', 'postcss.config.mjs',
                'eslint.config.js', 'eslint.config.mjs', '.eslintrc.js', '.eslintrc.json',
                '.prettierrc', '.prettierrc.json', '.prettierrc.js',
                'Makefile', 'Procfile', 'Gemfile', 'Gemfile.lock',
                '.gitignore', '.dockerignore', 'vercel.json', 'netlify.toml',
                'babel.config.js', 'jest.config.js', 'jest.config.ts',
                'vitest.config.ts', 'playwright.config.ts',
            }
            
            print(f"[*] Deep scanning {len(tree)} files in repository...")
            files_fetched = 0
            # NO LIMIT - Fetch ALL files! Gemini has a large context window.
            
            for item in tree:
                if item['type'] != 'blob':
                    continue
                    
                path = item['path']
                _, ext = os.path.splitext(path)
                filename = os.path.basename(path)
                
                # Check if we should fetch this file
                should_fetch = (
                    ext.lower() in code_extensions or
                    filename in important_files or
                    'model' in path.lower() or
                    'schema' in path.lower() or
                    'route' in path.lower() or
                    'api' in path.lower() or
                    'controller' in path.lower()
                )
                
                # Skip dependency/build directories using PATH COMPONENT matching
                # (NOT substring - 'dist' must not match 'distribution')
                skip_dirs = {'node_modules', 'venv', '.venv', '__pycache__', '.git', 
                             'dist', 'build', '.next', '.nuxt', 'coverage', '.cache',
                             'vendor', 'bower_components', '.tox', 'egg-info', '.eggs'}
                path_parts = set(path.replace('\\', '/').split('/'))
                if path_parts & skip_dirs:  # Set intersection - only matches exact directory names
                    should_fetch = False
                
                # Skip binary/media files by extension
                binary_extensions = {'.png', '.jpg', '.jpeg', '.gif', '.ico', '.bmp', '.webp',
                                     '.mp3', '.mp4', '.wav', '.avi', '.mkv', '.mov',
                                     '.zip', '.tar', '.gz', '.rar', '.7z',
                                     '.pdf', '.doc', '.docx', '.xls', '.xlsx',
                                     '.woff', '.woff2', '.ttf', '.eot', '.otf',
                                     '.pyc', '.pyo', '.so', '.dll', '.exe', '.o',
                                     '.DS_Store', '.map'}
                if ext.lower() in binary_extensions:
                    should_fetch = False
                
                # Skip files larger than 500KB (from tree metadata)
                file_size = item.get('size', 0)
                if file_size > 500_000:
                    print(f"  [⚠] Skipping large file ({file_size:,} bytes): {path}")
                    should_fetch = False
                
                if should_fetch:
                    content = self._fetch_file_content(
                        owner, repo_name, path, default_branch, headers, item.get('sha')
                    )
                    
                    if content is not None:
                        lang = self._detect_language(path, content)
                        
                        result["files"].append({
                            "path": path,
                            "content": content,
                            "language": lang
                        })
                        
                        # Analyze this file for tech stack
                        self._analyze_file_for_tech_stack(path, content, result)
                        
                        files_fetched += 1
                        print(f"  [+] Fetched ({files_fetched}): {path}")
                    
                    # GitHub API rate limit protection: pause every 30 files
                    if files_fetched > 0 and files_fetched % 30 == 0:
                        print(f"  [⏳] Rate limit pause after {files_fetched} files...")
                        time.sleep(1)
            
            print(f"[*] Deep scan complete: {files_fetched}/{len([i for i in tree if i['type']=='blob'])} files analyzed")
            
            # Warn if we got suspiciously few files
            total_blobs = len([i for i in tree if i['type'] == 'blob'])
            if files_fetched == 0:
                print(f"[!] WARNING: No files were fetched! Total blobs in tree: {total_blobs}")
                _add_debug_log('ERROR', 'DEEP_SCAN', f'Zero files fetched from {total_blobs} blobs', {
                    'repo_url': repo_url, 'tree_count': total_blobs
                })
            elif files_fetched < total_blobs * 0.3:  # Less than 30% of files
                print(f"[!] WARNING: Only fetched {files_fetched}/{total_blobs} files ({100*files_fetched//total_blobs}%)")
                _add_debug_log('WARNING', 'DEEP_SCAN', f'Low file fetch rate: {files_fetched}/{total_blobs}', {})
            
            # Summarize what must be preserved vs modernized
            self._categorize_preservation_targets(result)
            
            return result
            
        except Exception as e:
            print(f"[!] Deep scan error: {str(e)}")
            return result
    
    def _fetch_file_content(self, owner: str, repo_name: str, path: str, 
                            branch: str, headers: dict, blob_sha: str = None) -> str:
        """
        Fetches file content with multiple fallback strategies and retries.
        
        Strategy 1: GitHub Contents API (/contents/)
        Strategy 2: Raw content URL (raw.githubusercontent.com) 
        Strategy 3: Git Blob API (/git/blobs/) using SHA from tree
        
        Returns file content string, or None if all strategies fail.
        """
        import base64
        
        max_retries = 3
        
        for attempt in range(max_retries):
            # Strategy 1: Contents API (works for files < 1MB)
            try:
                content_url = f"https://api.github.com/repos/{owner}/{repo_name}/contents/{path}?ref={branch}"
                content_resp = requests.get(content_url, headers=headers, timeout=30)
                
                if content_resp.status_code == 200:
                    content_data = content_resp.json()
                    
                    # Handle array response (directory listing - skip)
                    if isinstance(content_data, list):
                        return None
                    
                    if content_data.get('encoding') == 'base64' and content_data.get('content'):
                        return base64.b64decode(content_data['content']).decode('utf-8', errors='ignore')
                    
                    # Some files return download_url instead
                    download_url = content_data.get('download_url')
                    if download_url:
                        raw_resp = requests.get(download_url, timeout=30)
                        if raw_resp.status_code == 200:
                            return raw_resp.text
                
                elif content_resp.status_code == 403:
                    # File too large for Contents API (>1MB) or rate limited
                    if 'too large' in content_resp.text.lower():
                        break  # Skip to Strategy 2
                    # Rate limited - wait and retry
                    time.sleep(2 * (attempt + 1))
                    continue
                    
                elif content_resp.status_code == 404:
                    return None  # File doesn't exist
                    
                elif content_resp.status_code == 429:
                    # Rate limited
                    time.sleep(5 * (attempt + 1))
                    continue
                    
            except requests.exceptions.Timeout:
                print(f"  [⏱️] Timeout fetching {path} (attempt {attempt+1})")
                continue
            except Exception as e:
                print(f"  [!] Contents API error for {path}: {e}")
                if attempt < max_retries - 1:
                    time.sleep(1)
                    continue
        
        # Strategy 2: Raw content URL (no size limit, no API rate limit)
        try:
            raw_url = f"https://raw.githubusercontent.com/{owner}/{repo_name}/{branch}/{path}"
            raw_resp = requests.get(raw_url, timeout=30)
            if raw_resp.status_code == 200:
                # Check if content looks like binary
                try:
                    text = raw_resp.content.decode('utf-8')
                    # Heuristic: if > 10% null bytes, it's binary
                    if text.count('\x00') > len(text) * 0.1:
                        return None
                    return text
                except UnicodeDecodeError:
                    return None  # Binary file
        except Exception as e:
            print(f"  [!] Raw URL fallback failed for {path}: {e}")
        
        # Strategy 3: Git Blob API (if we have the SHA)
        if blob_sha:
            try:
                blob_url = f"https://api.github.com/repos/{owner}/{repo_name}/git/blobs/{blob_sha}"
                blob_resp = requests.get(blob_url, headers=headers, timeout=30)
                if blob_resp.status_code == 200:
                    blob_data = blob_resp.json()
                    if blob_data.get('encoding') == 'base64':
                        return base64.b64decode(blob_data['content']).decode('utf-8', errors='ignore')
            except Exception as e:
                print(f"  [!] Blob API fallback failed for {path}: {e}")
        
        print(f"  [✗] All fetch strategies failed for: {path}")
        _add_debug_log('ERROR', 'DEEP_SCAN', f'Failed to fetch: {path}', {
            'owner': owner, 'repo': repo_name, 'branch': branch
        })
        return None

    def _detect_language(self, path: str, content: str) -> str:
        """Detect programming language from file path and content."""
        ext_map = {
            '.py': 'python', '.js': 'javascript', '.ts': 'typescript',
            '.tsx': 'typescript-react', '.jsx': 'javascript-react',
            '.mjs': 'javascript', '.cjs': 'javascript',
            '.json': 'json', '.yaml': 'yaml', '.yml': 'yaml',
            '.html': 'html', '.htm': 'html', '.css': 'css',
            '.scss': 'scss', '.sass': 'sass', '.less': 'less',
            '.sql': 'sql', '.md': 'markdown', '.mdx': 'mdx',
            '.xml': 'xml', '.svg': 'svg',
            '.vue': 'vue', '.svelte': 'svelte',
            '.ejs': 'ejs', '.pug': 'pug', '.hbs': 'handlebars',
            '.rb': 'ruby', '.go': 'go', '.rs': 'rust',
            '.java': 'java', '.php': 'php', '.c': 'c', '.cpp': 'cpp',
            '.cs': 'csharp', '.swift': 'swift', '.kt': 'kotlin',
            '.dart': 'dart', '.lua': 'lua', '.sh': 'bash',
            '.bat': 'batch', '.ps1': 'powershell',
            '.toml': 'toml', '.ini': 'ini', '.cfg': 'ini',
            '.prisma': 'prisma', '.graphql': 'graphql', '.gql': 'graphql',
            '.proto': 'protobuf', '.dockerfile': 'dockerfile',
            '.astro': 'astro', '.r': 'r',
        }
        _, ext = os.path.splitext(path)
        basename = os.path.basename(path)
        
        # Special files without extensions
        if basename == 'Dockerfile':
            return 'dockerfile'
        if basename == 'Makefile':
            return 'makefile'
        if basename == 'Gemfile':
            return 'ruby'
        if basename == 'Procfile':
            return 'yaml'
        
        return ext_map.get(ext.lower(), 'text')
    
    def _analyze_file_for_tech_stack(self, path: str, content: str, result: dict):
        """Analyze file content to detect tech stack and important patterns."""
        path_lower = path.lower()
        content_lower = content.lower()
        
        # Detect Backend Framework
        if 'fastapi' in content_lower or 'from fastapi' in content_lower:
            result["tech_stack"]["backend"]["framework"] = "FastAPI"
        elif 'flask' in content_lower or 'from flask' in content_lower:
            result["tech_stack"]["backend"]["framework"] = "Flask"
        elif 'express' in content_lower or "require('express')" in content_lower:
            result["tech_stack"]["backend"]["framework"] = "Express.js"
        elif 'django' in content_lower:
            result["tech_stack"]["backend"]["framework"] = "Django"
        
        # Detect Database - CRITICAL FOR PRESERVATION
        if 'mongodb' in content_lower or 'mongoose' in content_lower or 'pymongo' in content_lower:
            result["tech_stack"]["backend"]["database"] = "MongoDB"
            result["must_preserve"].append(f"MongoDB database connection in {path}")
        elif 'postgresql' in content_lower or 'psycopg' in content_lower or 'pg.' in content_lower:
            result["tech_stack"]["backend"]["database"] = "PostgreSQL"
            result["must_preserve"].append(f"PostgreSQL database connection in {path}")
        elif 'mysql' in content_lower or 'pymysql' in content_lower:
            result["tech_stack"]["backend"]["database"] = "MySQL"
            result["must_preserve"].append(f"MySQL database connection in {path}")
        elif 'sqlite' in content_lower:
            result["tech_stack"]["backend"]["database"] = "SQLite"
        elif 'prisma' in content_lower or path.endswith('.prisma'):
            result["must_preserve"].append(f"Prisma schema in {path}")
        
        # Detect Frontend Framework
        if 'react' in content_lower or 'from react' in content_lower or "'react'" in content_lower:
            result["tech_stack"]["frontend"]["framework"] = "React"
        elif 'vue' in content_lower:
            result["tech_stack"]["frontend"]["framework"] = "Vue.js"
        elif 'angular' in content_lower:
            result["tech_stack"]["frontend"]["framework"] = "Angular"
        elif 'next' in content_lower or "'next'" in content_lower:
            result["tech_stack"]["frontend"]["framework"] = "Next.js"
        
        # Detect API Endpoints - MUST PRESERVE
        if 'model' in path_lower or 'schema' in path_lower:
            result["database_schemas"].append(path)
            result["must_preserve"].append(f"Database schema/model in {path}")
        
        if '@app.route' in content or '@app.get' in content or '@app.post' in content:
            result["must_preserve"].append(f"API endpoints in {path}")
            # Extract Python/Flask/FastAPI endpoint patterns
            endpoints = re.findall(r'@app\.(get|post|put|delete|patch)\([\'"]([^\'"]+)[\'"]', content)
            for method, endpoint in endpoints:
                result["api_endpoints"].append(f"{method.upper()} {endpoint}")
        
        # Also detect Express.js endpoints: app.get('/path', ...) or router.get('/path', ...)
        if 'app.get(' in content or 'app.post(' in content or 'router.get(' in content:
            express_endpoints = re.findall(
                r'(?:app|router)\.(get|post|put|delete|patch|options)\s*\(\s*[\'"]([^\'"]+)[\'"]',
                content
            )
            if express_endpoints:
                result["must_preserve"].append(f"Express API endpoints in {path}")
                for method, endpoint in express_endpoints:
                    ep_str = f"{method.upper()} {endpoint}"
                    if ep_str not in result["api_endpoints"]:
                        result["api_endpoints"].append(ep_str)
        
        # Detect environment variables
        if '.env' in path or 'config' in path_lower:
            env_vars = re.findall(r'([A-Z_][A-Z0-9_]+)\s*=', content)
            result["env_vars"].extend(env_vars[:10])  # Limit
    
    def _categorize_preservation_targets(self, result: dict):
        """Categorize what must be preserved vs what can be modernized."""
        # Must preserve: database, schemas, core API logic, auth
        # Can modernize: UI, styling, performance optimizations
        
        for file_info in result["files"]:
            path = file_info["path"]
            
            # MUST PRESERVE
            if any(x in path.lower() for x in ['model', 'schema', 'database', 'db.', 'auth', 'middleware']):
                if path not in [p for p in result["must_preserve"]]:
                    result["must_preserve"].append(f"Core logic in {path}")
            
            # CAN MODERNIZE
            elif any(x in path.lower() for x in ['component', 'page', 'view', 'template', 'style', 'css', 'ui']):
                result["can_modernize"].append(path)
        
        # Add summary
        result["preservation_summary"] = {
            "database": result["tech_stack"]["backend"]["database"],
            "total_files": len(result["files"]),
            "must_preserve_count": len(result["must_preserve"]),
            "can_modernize_count": len(result["can_modernize"]),
            "api_endpoints_count": len(result["api_endpoints"])
        }


    def _call_gemini(self, prompt: str, model: str = None) -> str:
        """Raw HTTP call to Gemini API with automatic model fallback."""
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY is missing.")
        
        target_model = model or "gemini-3-flash-preview"  # Use Gemini 3 Flash by default
        
        # Model fallback chain: Gemini 3 → Gemini 2 → Gemini 1.5
        #   gemini-3-flash-preview: PRIMARY (1M context, latest)
        #   gemini-2.0-flash:       FALLBACK (2K RPM, stable)
        #   gemini-1.5-flash:       LAST RESORT (proven, high availability)
        fallback_models = []
        if target_model == "gemini-3-flash-preview":
            fallback_models = ["gemini-2.0-flash", "gemini-1.5-flash"]
        elif target_model == "gemini-3-pro-preview":
            fallback_models = ["gemini-3-flash-preview", "gemini-2.0-flash", "gemini-1.5-pro"]
        elif target_model in ("gemini-2.0-flash-exp", "gemini-2.0-flash"):
            fallback_models = ["gemini-1.5-flash", "gemini-1.5-pro"]
        elif target_model == "gemini-1.5-flash":
            fallback_models = ["gemini-2.0-flash", "gemini-1.5-pro"]
        elif target_model == "gemini-1.5-pro":
            fallback_models = ["gemini-2.0-flash", "gemini-1.5-flash"]
        else:
            # Unknown model - use safe Gemini 3 → 2 → 1.5 chain
            fallback_models = ["gemini-3-flash-preview", "gemini-2.0-flash", "gemini-1.5-flash"]
        
        # Remove the target model from fallbacks (avoid duplicate)
        fallback_models = [m for m in fallback_models if m != target_model]
        all_models = [target_model] + fallback_models
        
        headers = {'Content-Type': 'application/json'}
        data = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "maxOutputTokens": 65536,  # Request maximum output
                "temperature": 0.2,         # Low temp for code generation accuracy
            }
        }

        for model_idx, current_model in enumerate(all_models):
            is_fallback = model_idx > 0
            if is_fallback:
                logger.warning(f"   🔄 Falling back to model: {current_model}")
                _add_debug_log('WARNING', 'GEMINI_API', f'Falling back to {current_model}', {
                    'original_model': target_model,
                    'fallback_index': model_idx,
                })

            logger.info(f"🤖 Gemini API call: model={current_model} | prompt_length={len(prompt)} chars{' (FALLBACK)' if is_fallback else ''}")
            _add_debug_log('INFO', 'GEMINI_API', f'Calling {current_model}', {
                'model': current_model,
                'prompt_length': len(prompt),
                'prompt_preview': prompt[:500],
                'is_fallback': is_fallback,
            })

            actual_url = f"{self.base_url}/{current_model}:generateContent?key={self.api_key}"

            # Retry logic for transient errors
            max_retries = 4
            base_wait = 3

            for attempt in range(max_retries):
                try:
                    call_start = time.time()
                    # 300s timeout for large code generation responses
                    response = requests.post(actual_url, headers=headers, json=data, timeout=300)
                    call_elapsed = time.time() - call_start
                    
                    logger.info(f"   Gemini response: HTTP {response.status_code} in {call_elapsed:.2f}s | body_size={len(response.text)} chars (attempt {attempt+1}/{max_retries})")
                    _add_debug_log('INFO', 'GEMINI_API', f'Response: HTTP {response.status_code}', {
                        'status_code': response.status_code,
                        'elapsed_ms': round(call_elapsed * 1000),
                        'response_size': len(response.text),
                        'attempt': attempt + 1,
                        'model': current_model,
                    })
                    
                    if response.status_code == 200:
                        try:
                            resp_json = response.json()
                            candidates = resp_json.get('candidates', [])
                            if not candidates:
                                # Check for prompt feedback (blocked)
                                feedback = resp_json.get('promptFeedback', {})
                                block_reason = feedback.get('blockReason', '')
                                if block_reason:
                                    logger.warning(f"   ⚠️ Prompt blocked: {block_reason}")
                                    _add_debug_log('WARNING', 'GEMINI_API', f'Prompt blocked: {block_reason}', {'feedback': feedback})
                                    return f"[ERROR] Prompt blocked by safety filter: {block_reason}"
                                logger.error(f"   ❌ Empty candidates in response")
                                _add_debug_log('ERROR', 'GEMINI_API', 'Empty candidates', {'response': resp_json})
                                break  # Try next model
                            
                            result = candidates[0]['content']['parts'][0]['text']
                            logger.info(f"   ✅ Gemini success ({current_model}): {len(result)} chars returned")
                            _add_debug_log('INFO', 'GEMINI_API', f'Success: {len(result)} chars', {
                                'model_used': current_model,
                                'response_preview': result[:500],
                            })
                            return result
                        except (KeyError, IndexError) as parse_err:
                            logger.error(f"   ❌ Bad response structure: {parse_err} | {response.text[:300]}")
                            _add_debug_log('ERROR', 'GEMINI_API', 'Bad response structure', {'error': str(parse_err), 'response_text': response.text[:500]})
                            break  # Try next model
                    
                    elif response.status_code == 429:
                        # Rate limited - wait longer with jitter
                        import random
                        wait = base_wait * (2 ** attempt) + random.uniform(0, 2)
                        logger.warning(f"   ⚠️ Rate limited (429). Retry {attempt+1}/{max_retries} in {wait:.1f}s...")
                        _add_debug_log('WARNING', 'GEMINI_API', f'Rate limited (429)', {
                            'wait_seconds': round(wait, 1),
                            'attempt': attempt + 1,
                            'response_text': response.text[:300],
                        })
                        time.sleep(wait)
                        continue
                    
                    elif response.status_code in [500, 503]:
                        # Server error - check if it's a model availability issue
                        wait = base_wait * (attempt + 1)
                        error_text = response.text[:500]
                        try:
                            error_json = response.json()
                            error_detail = error_json.get('error', {}).get('message', error_text)
                        except:
                            error_detail = error_text
                        
                        logger.warning(f"   ⚠️ Server error ({response.status_code}): {error_detail[:200]}")
                        logger.warning(f"   ⏱️ Retry {attempt+1}/{max_retries} in {wait}s...")
                        _add_debug_log('WARNING', 'GEMINI_API', f'Server error: {response.status_code}', {
                            'wait_seconds': wait,
                            'attempt': attempt + 1,
                            'error_message': error_detail[:500],
                            'model': current_model,
                        })
                        time.sleep(wait)
                        continue
                    
                    elif response.status_code == 400:
                        # Bad request - possibly prompt too large or model issue
                        error_msg = response.text[:500]
                        logger.error(f"   ❌ Bad request (400): {error_msg}")
                        _add_debug_log('ERROR', 'GEMINI_API', f'Bad request (400)', {'response_text': error_msg})
                        
                        if 'too long' in error_msg.lower() or 'token' in error_msg.lower() or 'size' in error_msg.lower():
                            logger.warning(f"   📏 Prompt may be too large ({len(prompt)} chars). Trying next model...")
                        # Always try fallback model for 400 errors
                        break  # Try fallback model
                    
                    else:
                        logger.error(f"   ❌ API error {response.status_code}: {response.text[:300]}")
                        _add_debug_log('ERROR', 'GEMINI_API', f'API error: {response.status_code}', {
                            'response_text': response.text[:500],
                        })
                        break  # Try next model
                        
                except requests.exceptions.Timeout:
                    logger.warning(f"   ⏱️ Request timed out (300s). Retry {attempt+1}/{max_retries}...")
                    _add_debug_log('WARNING', 'GEMINI_API', 'Request timeout (300s)', {'attempt': attempt + 1})
                    continue
                except Exception as e:
                    logger.error(f"   ❌ Request failed: {e}")
                    _add_debug_log('ERROR', 'GEMINI_API', f'Request exception: {e}', {'traceback': tb_module.format_exc()})
                    break  # Try next model
            else:
                # All retries for this model exhausted (only reached if all `continue`d)
                logger.warning(f"   ⚠️ All retries exhausted for {current_model}, trying next model...")
                continue
            
            # `break` from inner loop = try next model in fallback chain
            continue
        
        # All models exhausted — raise so callers can handle properly
        logger.error(f"   ❌ All models exhausted. Tried: {', '.join(all_models)}")
        _add_debug_log('ERROR', 'GEMINI_API', 'All models exhausted', {'models_tried': all_models})
        raise GeminiAPIError(
            f"All Gemini models failed after retries. Models tried: {', '.join(all_models)}. Check your API key quota at https://aistudio.google.com/",
            models_tried=all_models,
        )

    def clean_code(self, text: str) -> str:
        """Extracts code from markdown blocks."""
        pattern = r"```(?:javascript|python|bash)?\n(.*?)```"
        match = re.search(pattern, text, re.DOTALL)
        if match:
            return match.group(1).strip()
        return text.strip()

    def _parse_files_from_response(self, response: str) -> list:
        """
        Robust XML file parser with multiple fallback strategies.
        Handles edge cases like nested code blocks, special chars, malformed tags.
        
        Returns list of {"filename": str, "content": str}
        """
        files = []
        seen_paths = set()

        def _clean_content(raw: str) -> str:
            """Strip markdown code fences the model sometimes wraps content in."""
            c = raw.strip()
            c = re.sub(r'^```\w*\n', '', c)
            c = re.sub(r'\n```\s*$', '', c)
            return c

        # Strategy 1: Standard regex
        pattern = r'<file\s+path="(.*?)">(.*?)</file>'
        matches = re.findall(pattern, response, re.DOTALL)
        for fp, content in matches:
            fp = fp.strip()
            if fp and fp not in seen_paths:
                files.append({"filename": fp, "content": _clean_content(content)})
                seen_paths.add(fp)
        if files:
            return files

        # Strategy 2: Single-quoted paths
        pattern2 = r"<file\s+path=['\"]([^'\"]+)['\"]>(.*?)</file>"
        matches2 = re.findall(pattern2, response, re.DOTALL)
        for fp, content in matches2:
            fp = fp.strip()
            if fp and fp not in seen_paths:
                files.append({"filename": fp, "content": _clean_content(content)})
                seen_paths.add(fp)
        if files:
            return files

        # Strategy 3: Extra whitespace in tags
        pattern3 = r'<file\s+path\s*=\s*"([^"]+)"\s*>(.*?)</file\s*>'
        matches3 = re.findall(pattern3, response, re.DOTALL)
        for fp, content in matches3:
            fp = fp.strip()
            if fp and fp not in seen_paths:
                files.append({"filename": fp, "content": _clean_content(content)})
                seen_paths.add(fp)
        if files:
            return files

        # Strategy 4: Line-by-line state machine for deeply malformed output
        in_file = False
        current_path = None
        current_content = []

        for line in response.split('\n'):
            start_match = re.match(r'<file\s+path\s*=\s*["\']([^"\']+)["\']', line)
            if start_match:
                # Save any previous file
                if in_file and current_path and current_content:
                    fp = current_path.strip()
                    if fp not in seen_paths:
                        files.append({"filename": fp, "content": _clean_content('\n'.join(current_content))})
                        seen_paths.add(fp)
                current_path = start_match.group(1)
                current_content = []
                in_file = True
                after_tag = re.sub(r'<file\s+path\s*=\s*["\'][^"\']+["\']>\s*', '', line)
                if after_tag.strip():
                    current_content.append(after_tag.rstrip())
                continue

            if '</file' in line and in_file:
                before_tag = line.split('</file')[0]
                if before_tag.strip():
                    current_content.append(before_tag.rstrip())
                fp = current_path.strip()
                if fp not in seen_paths:
                    files.append({"filename": fp, "content": _clean_content('\n'.join(current_content))})
                    seen_paths.add(fp)
                in_file = False
                current_path = None
                current_content = []
                continue

            if in_file:
                current_content.append(line)

        # Handle unclosed last file
        if in_file and current_path and current_content:
            fp = current_path.strip()
            if fp not in seen_paths:
                files.append({"filename": fp, "content": _clean_content('\n'.join(current_content))})

        if files:
            print(f"[PARSER] Recovered {len(files)} files using state-machine parser")
            _add_debug_log('WARNING', 'PARSER', f'Used fallback state-machine parser', {'files_recovered': len(files)})

        return files

    def generate_modernization_plan(self, repo_url: str, instructions: str, deep_scan_result: dict = None) -> str:
        """
        PRESERVATION-FIRST PLANNING (v7.0 - LIGHTWEIGHT)
        
        Sends ONLY file paths, tech stack, and endpoint metadata to Gemini.
        NO full file contents in the plan prompt - keeps it fast and small.
        Also requests FILE GROUPINGS for batch processing.
        """
        if deep_scan_result:
            tech_stack = deep_scan_result.get("tech_stack", {})
            must_preserve = deep_scan_result.get("must_preserve", [])
            can_modernize = deep_scan_result.get("can_modernize", [])
            api_endpoints = deep_scan_result.get("api_endpoints", [])
            files = deep_scan_result.get("files", [])
            file_paths = [f["path"] for f in files]
            
            total_chars = sum(len(f.get("content", "")) for f in files)
            print(f"[PLAN] Lightweight planning: {len(files)} files, {total_chars:,} total chars")
            print(f"[PLAN] Sending ONLY file paths + metadata (NOT full file contents)")
            _add_debug_log('INFO', 'PLAN', f'Lightweight plan: {len(files)} files, {total_chars:,} chars of source code', {
                'file_count': len(files),
                'total_chars': total_chars,
                'tech_stack': tech_stack,
            })
            
            prompt = get_lightweight_plan_prompt(
                repo_url=repo_url,
                instructions=instructions,
                file_paths=file_paths,
                tech_stack=tech_stack,
                api_endpoints=api_endpoints,
                must_preserve=must_preserve,
                can_modernize=can_modernize,
            )
        else:
            # Fallback: minimal prompt if no deep scan
            total_chars = 0
            prompt = f"""Create a modernization plan for {repo_url}.
Instructions: {instructions if instructions else 'Modernize UI while preserving all functionality'}
Group the files into batches for processing."""
        
        print(f"[PLAN] Plan prompt size: {len(prompt):,} chars (vs old approach: would have been {total_chars + len(prompt):,}+)")
        _add_debug_log('DEBUG', 'PLAN', f'Plan prompt: {len(prompt):,} chars', {})
        
        # Use planner model (2.0-flash: 2K RPM, planning is simple)
        try:
            return self._call_gemini(prompt, model=self.planner_model)
        except GeminiAPIError as e:
            logger.warning(f"[PLAN] Gemini API failed for planning: {e}")
            _add_debug_log('WARNING', 'PLAN', f'Planning API failed, building synthetic plan', {'error': str(e)})
            # Build a synthetic plan from deep_scan_result so code gen can still work
            return self._build_fallback_plan(repo_url, instructions, deep_scan_result)

    def _build_fallback_plan(self, repo_url: str, instructions: str, deep_scan_result: dict = None) -> str:
        """
        Build a synthetic modernization plan when the Gemini API is unavailable.
        Uses tech stack and file list from deep_scan_result.
        """
        if not deep_scan_result:
            return f"Modernize {repo_url}. Instructions: {instructions or 'Preserve all functionality and modernize the UI.'}"
        
        tech_stack = deep_scan_result.get("tech_stack", {})
        files = deep_scan_result.get("files", [])
        file_paths = [f["path"] for f in files]
        
        backend = tech_stack.get("backend", {})
        frontend_tech = tech_stack.get("frontend", {})
        
        # Group files by directory for batch suggestions
        dir_groups = {}
        for fp in file_paths:
            parts = fp.replace("\\", "/").split("/")
            group = parts[0] if len(parts) > 1 else "root"
            dir_groups.setdefault(group, []).append(fp)
        
        plan = f"""# Fallback Modernization Plan for {repo_url}
## (Auto-generated from repository scan — Gemini API was unavailable)

### Instructions
{instructions or 'Modernize the UI while preserving ALL backend logic, database schemas, and API endpoints.'}

### Detected Tech Stack
- Backend Framework: {backend.get('framework', 'Unknown')}
- Backend Language: {backend.get('language', 'Unknown')}
- Database: {backend.get('database', 'None detected')}
- Frontend Framework: {frontend_tech.get('framework', 'Unknown')}

### Files ({len(file_paths)} total)
{chr(10).join(f'- {p}' for p in file_paths)}

### Batch Groups
"""
        for i, (group, group_files) in enumerate(dir_groups.items(), 1):
            plan += f"\n#### BATCH {i}: {group}\n"
            for f in group_files:
                plan += f"- {f}\n"
        
        plan += """
### Modernization Strategy
1. PRESERVE all backend logic, API endpoints, and database schemas exactly
2. Modernize the frontend with clean HTML/CSS/JS or React
3. Keep the same file structure where possible
4. Ensure all imports and dependencies are correct
"""
        print(f"[PLAN] Built fallback plan from scan data ({len(plan)} chars)")
        _add_debug_log('INFO', 'PLAN', f'Fallback plan built: {len(plan)} chars', {})
        return plan

    def generate_code(self, plan: str, deep_scan_result: dict = None, repo_url: str = None) -> dict:
        """
        Returns info about the code to be generated (Multiple Files, Nested Structure).
        Uses PRESERVATION-FIRST prompt from prompts.py module.
        
        deep_scan_result: Contains existing codebase info for preservation.
        repo_url: Repository URL for loading resurrection memory.
        Raises GeminiAPIError if the API is unreachable.
        """
        # Load resurrection memory for this repository
        memory_context = ""
        if repo_url:
            memory_context = get_memory_context_for_prompt(repo_url)
            memory_summary = get_memory_summary(repo_url)
            if memory_summary["total_attempts"] > 0:
                print(f"[*] 🧠 Resurrection Memory Loaded: {memory_summary['total_attempts']} past attempts, {memory_summary['failed_attempts']} failures")
        
        # Get the comprehensive prompt from the prompts module
        # Pass deep_scan_result for preservation context (existing code, database, etc.)
        # Pass memory_context for cross-session learning
        prompt = get_code_generation_prompt(plan, deep_scan_result, memory_context)
        
        # Phase 2: Write Code -> Use coder model (3-flash: 1K RPM)
        # GeminiAPIError will propagate up to process_resurrection_stream's try/except
        response = self._call_gemini(prompt, model=self.coder_model)
        print(f"[DEBUG] {self.coder_model} Connected Successfully. Code Generated.")
        
        # Robust XML Parsing (multi-strategy)
        files = self._parse_files_from_response(response)
            
        if not files:
            print(f"[!] XML parsing failed. Response preview: {response[:500]}")
            _add_debug_log('ERROR', 'PARSER', 'No files parsed from response', {
                'response_length': len(response),
                'response_preview': response[:1000],
            })
            # Raise instead of returning error.log sentinel — let the retry loop handle it
            raise Exception(f"CODE GENERATION FAILED: Gemini returned {len(response)} chars but no parseable files. Preview: {response[:200]}")
        
        print(f"[*] Parsed {len(files)} files from Gemini response")

        # Categorize files for clarity
        backend_files = [f for f in files if 'backend' in f['filename'].lower() or f['filename'].endswith('.py') or 'api' in f['filename'].lower()]
        frontend_files = [f for f in files if 'frontend' in f['filename'].lower() or f['filename'].endswith(('.html', '.css', '.jsx', '.tsx'))]
        config_files = [f for f in files if f['filename'] in ('requirements.txt', 'package.json', '.env', 'Dockerfile')]
        
        if backend_files:
            print(f"[*] Backend files: {[f['filename'] for f in backend_files[:5]]}{' ...' if len(backend_files) > 5 else ''}")
        if frontend_files:
            print(f"[*] Frontend files: {[f['filename'] for f in frontend_files[:5]]}{' ...' if len(frontend_files) > 5 else ''}")

        # Use centralized entrypoint detection
        entrypoint, runtime = self._detect_entrypoint_and_runtime(files)
        print(f"[*] 🎯 Entrypoint Selected: {entrypoint} (runtime: {runtime})")
        
        if 'frontend' in entrypoint.lower():
            print(f"[!] WARNING: Entrypoint appears to be frontend file - this should not happen!")

        return {
            "files": files,
            "entrypoint": entrypoint,
            "runtime": runtime
        }

    # ═══════════════════════════════════════════════════════════════════════════
    # MULTI-BATCH CODE GENERATION (v7.0)
    # ═══════════════════════════════════════════════════════════════════════════

    def _detect_entrypoint_and_runtime(self, files: list) -> tuple:
        """
        Detects runtime and entrypoint from generated files.
        Returns (entrypoint, runtime) tuple.
        
        Priority:
        1. Python backend if requirements.txt exists
        2. Node.js server files (excluding frontend/)
        3. Fallback to first .py or .js file
        """
        entrypoint = None
        runtime = "python"

        # Check if there's a Python backend first (requirements.txt is a strong signal)
        has_python_backend = any(f["filename"].endswith("requirements.txt") for f in files)
        has_any_py = any(f["filename"].endswith(".py") for f in files)
        
        python_entrypoints = [
            "main.py", "app.py", "server.py", "run.py", "api.py"
        ]
        node_server_entrypoints = [
            "server.js", "index.js", "backend.js", "api.js"
        ]
        
        # PRIORITY 1: If requirements.txt exists, prefer Python backend
        if has_python_backend or has_any_py:
            for f in files:
                filename = f["filename"]
                basename = os.path.basename(filename)
                # Skip frontend files
                if "frontend" in filename.lower() or "client" in filename.lower():
                    continue
                if basename in python_entrypoints:
                    entrypoint = filename
                    runtime = "python"
                    break
            
            # If no named entrypoint, find first .py file in backend/
            if not entrypoint:
                for f in files:
                    fn = f["filename"]
                    if fn.endswith(".py") and ("backend" in fn.lower() or "api" in fn.lower()):
                        entrypoint = fn
                        runtime = "python"
                        break
        
        # PRIORITY 2: Node.js server files (but exclude frontend/)
        if not entrypoint:
            for f in files:
                filename = f["filename"]
                basename = os.path.basename(filename)
                
                # CRITICAL: Skip frontend directories
                if "frontend" in filename.lower() or "client" in filename.lower() or "public" in filename.lower():
                    continue
                
                # Check if it's a Node.js server file
                if basename in node_server_entrypoints or filename.endswith("server.js"):
                    # Verify it's not client-side JS by checking content
                    content = f.get("content", "")
                    is_client_side = ("document." in content or "window." in content or 
                                    "addEventListener" in content or "getElementById" in content)
                    if not is_client_side:
                        entrypoint = filename
                        runtime = "node"
                        break

        # PRIORITY 3: Fallback - check for package.json or any .py file
        if not entrypoint:
            # If there's ANY .py file, default to Python
            py_files = [f for f in files if f["filename"].endswith(".py")]
            if py_files:
                runtime = "python"
                # Try to find one in backend/
                backend_py = next((f["filename"] for f in py_files if "backend" in f["filename"].lower()), None)
                entrypoint = backend_py or py_files[0]["filename"]
            elif any(f["filename"].endswith("package.json") for f in files):
                # Only use Node if there's a package.json and it has server deps
                runtime = "node"
                # Look for server.js or index.js in backend/
                for ff in files:
                    fn = ff["filename"]
                    if fn.endswith(".js") and ("backend" in fn.lower() or "server" in fn.lower()):
                        content = ff.get("content", "")
                        if "document." not in content and "window." not in content:
                            entrypoint = fn
                            break
                if not entrypoint:
                    # Couldn't find valid server - default to Python
                    runtime = "python"
                    entrypoint = "modernized_stack/backend/main.py"
            else:
                # No clear indicator - default to Python
                runtime = "python"
                entrypoint = "modernized_stack/backend/main.py"

        return entrypoint, runtime

    def _group_files_into_batches(self, files: list, plan: str = "", max_chars_per_batch: int = None) -> list:
        """
        Groups files into logical batches for multi-call processing.
        
        Strategy:
        1. Try to parse batch groupings from the AI-generated plan
        2. If plan parsing fails, fall back to directory-based grouping
        3. Enforce max chars per batch to stay within token limits
        
        Args:
            files: List of dicts with 'path', 'content', 'language'
            plan: The modernization plan (may contain BATCH groupings)
            max_chars_per_batch: Max total source chars per batch (auto-calculated from model if None)
            
        Returns:
            List of batch dicts: [{"name": str, "files": [file_dicts]}]
        """
        # Dynamically calculate batch size based on coder model's context window
        if max_chars_per_batch is None:
            max_chars_per_batch = self.get_model_max_chars(self.coder_model)
            print(f"[BATCH] Dynamic batch limit: {max_chars_per_batch:,} chars (model: {self.coder_model})")
        # ── Attempt 1: Parse batch groups from plan ──
        batches_from_plan = self._parse_batches_from_plan(plan, files)
        if batches_from_plan:
            # Validate all files are assigned
            assigned_paths = set()
            for batch in batches_from_plan:
                for f in batch["files"]:
                    assigned_paths.add(f["path"])
            
            all_paths = set(f["path"] for f in files)
            missing = all_paths - assigned_paths
            
            if not missing:
                # All files assigned - enforce size limits
                return self._split_oversized_batches(batches_from_plan, max_chars_per_batch)
            else:
                print(f"[BATCH] Plan missed {len(missing)} files, adding to extra batch")
                _add_debug_log('WARNING', 'BATCH', f'Plan missed {len(missing)} files', {'missing': list(missing)[:10]})
                missing_files = [f for f in files if f["path"] in missing]
                batches_from_plan.append({"name": "Remaining Files", "files": missing_files})
                return self._split_oversized_batches(batches_from_plan, max_chars_per_batch)

        # ── Attempt 2: Directory-based grouping ──
        print("[BATCH] Using directory-based grouping (plan parsing failed)")
        _add_debug_log('INFO', 'BATCH', 'Using directory-based grouping fallback', {})
        return self._group_by_directory(files, max_chars_per_batch)

    def _parse_batches_from_plan(self, plan: str, files: list) -> list:
        """
        Tries to parse BATCH groupings from the AI plan.
        Looks for patterns like:
            BATCH 1 - Backend Core:
            - path/to/file.js
            - path/to/other.js
        """
        if not plan:
            return []
        
        # Map paths to file dicts for quick lookup
        path_to_file = {f["path"]: f for f in files}
        
        batches = []
        current_batch = None
        
        for line in plan.split('\n'):
            stripped = line.strip()
            
            # Detect batch header: "BATCH N - Name:" or "BATCH N: Name" or "**BATCH N - Name**:"
            batch_match = re.match(
                r'(?:\*\*)?BATCH\s+\d+\s*[-:]\s*(.+?)(?:\*\*)?:?\s*$',
                stripped, re.IGNORECASE
            )
            if batch_match:
                if current_batch and current_batch["files"]:
                    batches.append(current_batch)
                current_batch = {"name": batch_match.group(1).strip().rstrip(':'), "files": []}
                continue
            
            # Detect file path lines: "- path/to/file.ext" or "  - path/to/file.ext"
            if current_batch is not None and stripped.startswith('- '):
                file_path = stripped[2:].strip()
                # Clean up any markdown or quotes
                file_path = file_path.strip('`"\'')
                
                # Try direct match
                if file_path in path_to_file:
                    current_batch["files"].append(path_to_file[file_path])
                else:
                    # Try fuzzy match (path might have slight differences)
                    for p, f in path_to_file.items():
                        if p.endswith(file_path) or file_path.endswith(p) or os.path.basename(p) == os.path.basename(file_path):
                            current_batch["files"].append(f)
                            break
        
        # Don't forget the last batch
        if current_batch and current_batch["files"]:
            batches.append(current_batch)
        
        if batches:
            total_assigned = sum(len(b["files"]) for b in batches)
            print(f"[BATCH] Parsed {len(batches)} batches from plan ({total_assigned}/{len(files)} files assigned)")
            _add_debug_log('INFO', 'BATCH', f'Parsed {len(batches)} batches from plan', {
                'batches': [{"name": b["name"], "file_count": len(b["files"])} for b in batches]
            })
        
        return batches if batches else []

    def _group_by_directory(self, files: list, max_chars_per_batch: int) -> list:
        """
        Fallback: groups files by their directory path.
        Config files (package.json, requirements.txt, etc.) go in a separate batch.
        """
        config_extensions = {'.json', '.yml', '.yaml', '.toml', '.cfg', '.ini', '.env', '.lock'}
        config_names = {'package.json', 'requirements.txt', 'tsconfig.json', '.gitignore', 
                       'Dockerfile', 'docker-compose.yml', '.env', '.env.example',
                       'next.config.mjs', 'next.config.ts', 'tailwind.config.ts',
                       'postcss.config.mjs', 'eslint.config.mjs', 'vite.config.ts'}
        
        dir_groups = {}
        config_files = []
        
        for f in files:
            basename = os.path.basename(f["path"])
            ext = os.path.splitext(f["path"])[1]
            
            if basename in config_names or ext in config_extensions:
                config_files.append(f)
            else:
                dir_path = os.path.dirname(f["path"]) or "root"
                if dir_path not in dir_groups:
                    dir_groups[dir_path] = []
                dir_groups[dir_path].append(f)
        
        batches = []
        if config_files:
            batches.append({"name": "Config & Dependencies", "files": config_files})
        
        for dir_path, dir_files in sorted(dir_groups.items()):
            batch_name = dir_path.replace('/', ' > ') if dir_path != "root" else "Root Files"
            batches.append({"name": batch_name, "files": dir_files})
        
        return self._split_oversized_batches(batches, max_chars_per_batch)

    def _split_oversized_batches(self, batches: list, max_chars: int) -> list:
        """
        Splits any batch that exceeds max_chars into smaller sub-batches.
        """
        result = []
        for batch in batches:
            total_chars = sum(len(f.get("content", "")) for f in batch["files"])
            
            if total_chars <= max_chars:
                result.append(batch)
            else:
                # Split into sub-batches
                sub_batch_files = []
                sub_batch_chars = 0
                sub_idx = 1
                
                for f in batch["files"]:
                    file_chars = len(f.get("content", ""))
                    
                    if sub_batch_chars + file_chars > max_chars and sub_batch_files:
                        result.append({
                            "name": f"{batch['name']} (Part {sub_idx})",
                            "files": sub_batch_files
                        })
                        sub_batch_files = []
                        sub_batch_chars = 0
                        sub_idx += 1
                    
                    sub_batch_files.append(f)
                    sub_batch_chars += file_chars
                
                if sub_batch_files:
                    name = f"{batch['name']} (Part {sub_idx})" if sub_idx > 1 else batch['name']
                    result.append({"name": name, "files": sub_batch_files})
        
        return result

    def generate_code_batched(self, plan: str, deep_scan_result: dict, repo_url: str = None, progress_callback=None) -> dict:
        """
        Multi-batch code generation: processes files in logical groups
        to avoid hitting API token limits.
        
        For repos with < 10 files, falls back to single-call generate_code().
        
        Args:
            plan: The modernization plan (with batch groupings)
            deep_scan_result: Deep scan results with file contents
            repo_url: Repository URL for memory context
            progress_callback: Optional callable(msg) for progress updates
            
        Returns:
            dict with 'files', 'entrypoint', 'runtime'
        """
        files = deep_scan_result.get("files", [])
        total_files = len(files)
        
        # Small/Medium repos: use single-call approach (maximize based on model capacity)
        single_call_limit = int(self.get_model_max_chars(self.coder_model) * 0.7)  # 70% of limit for safety
        
        if total_files <= 150:  # Up from 100
            total_chars = sum(len(f.get("content", "")) for f in files)
            if total_chars < single_call_limit:
                print(f"[BATCH] Single-call mode: {total_files} files, {total_chars:,} chars (limit: {single_call_limit:,})")
                _add_debug_log('INFO', 'BATCH', f'Using single-call mode', {
                    'file_count': total_files, 'total_chars': total_chars, 'model': self.coder_model
                })
                return self.generate_code(plan, deep_scan_result, repo_url)
        
        # Load memory context
        memory_context = ""
        if repo_url:
            memory_context = get_memory_context_for_prompt(repo_url)
        
        # Group files into batches
        batches = self._group_files_into_batches(files, plan)
        
        print(f"\n{'='*70}")
        print(f"[BATCH] MULTI-BATCH CODE GENERATION")
        print(f"[BATCH] Total files: {total_files} | Batches: {len(batches)}")
        for i, batch in enumerate(batches):
            batch_chars = sum(len(f.get("content", "")) for f in batch["files"])
            print(f"[BATCH]   Batch {i+1}: {batch['name']} ({len(batch['files'])} files, {batch_chars:,} chars)")
        print(f"{'='*70}\n")
        
        _add_debug_log('INFO', 'BATCH', f'Starting multi-batch generation', {
            'total_files': total_files,
            'batch_count': len(batches),
            'batches': [{"name": b["name"], "files": len(b["files"])} for b in batches]
        })
        
        # All file paths for cross-reference
        all_file_paths = [f["path"] for f in files]
        
        # Process each batch
        all_generated_files = []
        previously_generated_summaries = ""
        
        for batch_idx, batch in enumerate(batches):
            batch_name = batch["name"]
            batch_files = batch["files"]
            batch_file_count = len(batch_files)
            
            print(f"\n[BATCH {batch_idx+1}/{len(batches)}] Processing: {batch_name} ({batch_file_count} files)")
            _add_debug_log('INFO', 'BATCH', f'Processing batch {batch_idx+1}/{len(batches)}: {batch_name}', {
                'files': [f["path"] for f in batch_files]
            })
            
            if progress_callback:
                progress_callback(f"🔨 Generating batch {batch_idx+1}/{len(batches)}: {batch_name} ({batch_file_count} files)...")
            
            # Build batch-specific prompt
            prompt = get_batch_code_generation_prompt(
                plan=plan,
                batch_files=batch_files,
                batch_index=batch_idx,
                total_batches=len(batches),
                batch_name=batch_name,
                all_file_paths=all_file_paths,
                previously_generated_summaries=previously_generated_summaries,
                memory_context=memory_context if batch_idx == 0 else "",  # Memory only for first batch
            )
            
            # Call Gemini for this batch
            print(f"[BATCH {batch_idx+1}] Prompt size: {len(prompt):,} chars")
            _add_debug_log('DEBUG', 'BATCH', f'Batch {batch_idx+1} prompt size: {len(prompt):,} chars', {})
            
            try:
                response = self._call_gemini(prompt, model=self.coder_model)
            except GeminiAPIError as api_err:
                print(f"[BATCH {batch_idx+1}] ❌ Gemini API error: {api_err}")
                _add_debug_log('ERROR', 'BATCH', f'Batch {batch_idx+1} API error: {str(api_err)[:200]}', {})
                if batch_idx == 0 and len(batches) == 1:
                    # Single batch and it failed — re-raise
                    raise
                # Multi-batch: skip this batch, wait extra time, continue
                if progress_callback:
                    progress_callback(f"⚠️ Batch {batch_idx+1} API error — waiting 10s before retry...")
                time.sleep(10)
                continue
            
            if "[ERROR]" in response:
                print(f"[BATCH {batch_idx+1}] ❌ Gemini error: {response[:200]}")
                _add_debug_log('ERROR', 'BATCH', f'Batch {batch_idx+1} failed: {response[:200]}', {})
                # Continue with remaining batches - don't fail everything
                continue
            
            # Parse generated files from response (robust multi-strategy parser)
            batch_generated = self._parse_files_from_response(response)
            
            print(f"[BATCH {batch_idx+1}] ✅ Generated {len(batch_generated)}/{batch_file_count} files")
            _add_debug_log('INFO', 'BATCH', f'Batch {batch_idx+1} generated {len(batch_generated)} files', {
                'expected': batch_file_count,
                'generated_paths': [f["filename"] for f in batch_generated]
            })
            
            all_generated_files.extend(batch_generated)
            
            # Extract summaries for next batch's context
            if batch_generated:
                batch_summary = extract_batch_summary(batch_generated)
                previously_generated_summaries += f"\n\n=== Batch {batch_idx+1}: {batch_name} ===\n{batch_summary}"
            
            # Rate limit protection: wait between batches
            # Gemini 3 Flash = 1K RPM, so 3s is plenty of headroom
            if batch_idx < len(batches) - 1:
                wait_time = 3
                print(f"[BATCH] ⏳ Waiting {wait_time}s before next batch (rate limit protection)...")
                _add_debug_log('INFO', 'BATCH', f'Rate limit cooldown: {wait_time}s', {})
                if progress_callback:
                    progress_callback(f"⏳ Cooldown: {wait_time}s before next batch...")
                time.sleep(wait_time)
        
        # ═══════════════════════════════════════════════════════════════════
        # MISSING FILE RECOVERY - Detect and regenerate any files that
        # were expected but not generated across all batches
        # ═══════════════════════════════════════════════════════════════════
        generated_paths = set(f["filename"] for f in all_generated_files)
        expected_paths = set(f["path"] for f in files)
        missing_paths = expected_paths - generated_paths
        
        # Also check for path variations (with/without leading directories)
        still_missing = set()
        for mp in missing_paths:
            # Check if a generated file matches by basename
            mp_base = os.path.basename(mp)
            found = False
            for gp in generated_paths:
                if os.path.basename(gp) == mp_base:
                    found = True
                    break
            if not found:
                still_missing.add(mp)
        
        if still_missing and len(still_missing) <= 15:
            print(f"\n[RECOVERY] {len(still_missing)} files missing after batch generation. Attempting recovery...")
            _add_debug_log('WARNING', 'RECOVERY', f'{len(still_missing)} missing files detected', {
                'missing': list(still_missing)
            })
            
            if progress_callback:
                progress_callback(f"🔄 Recovering {len(still_missing)} missing files...")
            
            # Build a mini-batch with just the missing files
            missing_file_dicts = [f for f in files if f["path"] in still_missing]
            
            if missing_file_dicts:
                recovery_prompt = get_batch_code_generation_prompt(
                    plan=plan,
                    batch_files=missing_file_dicts,
                    batch_index=len(batches),
                    total_batches=len(batches) + 1,
                    batch_name="Recovery - Missing Files",
                    all_file_paths=all_file_paths,
                    previously_generated_summaries=previously_generated_summaries,
                    memory_context="",
                )
                
                time.sleep(3)  # Rate limit pause
                try:
                    recovery_response = self._call_gemini(recovery_prompt, model=self.coder_model)
                except GeminiAPIError:
                    print(f"[RECOVERY] ❌ Recovery Gemini API call failed (all models exhausted)")
                    recovery_response = None
                
                if recovery_response and "[ERROR]" not in recovery_response:
                    recovered_files = self._parse_files_from_response(recovery_response)
                    if recovered_files:
                        all_generated_files.extend(recovered_files)
                        print(f"[RECOVERY] ✅ Recovered {len(recovered_files)} additional files")
                        _add_debug_log('INFO', 'RECOVERY', f'Recovered {len(recovered_files)} files', {
                            'recovered_paths': [f["filename"] for f in recovered_files]
                        })
                    else:
                        print(f"[RECOVERY] ⚠️ Recovery call returned no parseable files")
                else:
                    print(f"[RECOVERY] ❌ Recovery Gemini call failed")
        elif still_missing:
            print(f"[RECOVERY] ⚠️ {len(still_missing)} files missing but too many for single recovery call")
            _add_debug_log('WARNING', 'RECOVERY', f'Too many missing files for recovery: {len(still_missing)}', {})
        
        print(f"\n{'='*70}")
        print(f"[BATCH] FINAL: Generated {len(all_generated_files)}/{total_files} files across {len(batches)} batches")
        print(f"{'='*70}\n")
        
        _add_debug_log('INFO', 'BATCH', f'Multi-batch complete: {len(all_generated_files)}/{total_files} files', {
            'generated_paths': [f["filename"] for f in all_generated_files]
        })
        
        if not all_generated_files:
            raise Exception("BATCH GENERATION FAILED: No files were generated across all batches. The Gemini API may be overloaded — try again in a minute.")
        
        # Detect entrypoint and runtime
        entrypoint, runtime = self._detect_entrypoint_and_runtime(all_generated_files)
        print(f"[BATCH] Smart Detection: Runtime={runtime}, Entrypoint={entrypoint}")
        
        return {
            "files": all_generated_files,
            "entrypoint": entrypoint,
            "runtime": runtime
        }

    def infer_dependencies(self, files: list) -> list:
        """
        Scans generated python code for imports using AST and returns specific PyPI packages.
        """
        detected = set()
        
        # 1. The "Rosetta Stone" of Imports
        PACKAGE_MAP = {
            # Data & AI
            "numpy": "numpy",
            "pandas": "pandas",
            "cv2": "opencv-python-headless", # Headless for servers!
            "PIL": "pillow",
            "sklearn": "scikit-learn",
            "openai": "openai",
            "google.generativeai": "google-generative-ai",
            
            # Backend Frameworks
            "fastapi": "fastapi",
            "uvicorn": "uvicorn",
            "flask": "flask",
            "flask_cors": "flask-cors",
            "sqlalchemy": "sqlalchemy",
            
            # Auth & Security
            "jose": "python-jose[cryptography]",
            "jwt": "python-jose[cryptography]",
            "passlib": "passlib[bcrypt]",
            "bcrypt": "bcrypt==4.0.1", # CRITICAL: Force 4.0.1
            "multipart": "python-multipart", # Required for Form data
            
            # Utilities
            "dotenv": "python-dotenv",
            "requests": "requests",
            "pydantic": "pydantic",
            "email_validator": "email-validator",
            "bs4": "beautifulsoup4"
        }

        # Scan all .py files
        for f in files:
            if f['filename'].endswith('.py'):
                try:
                    tree = ast.parse(f['content'])
                    for node in ast.walk(tree):
                        # Scan "import x"
                        if isinstance(node, ast.Import):
                            for alias in node.names:
                                root = alias.name.split('.')[0]
                                if root in PACKAGE_MAP:
                                    detected.add(PACKAGE_MAP[root])
                        
                        # Scan "from x import y"
                        elif isinstance(node, ast.ImportFrom):
                            if node.module:
                                root = node.module.split('.')[0]
                                if root in PACKAGE_MAP:
                                    detected.add(PACKAGE_MAP[root])
                                
                                # SPECIAL CASE: Pydantic Email
                                if root == "pydantic":
                                    for name in node.names:
                                        if name.name == "EmailStr":
                                            detected.add("pydantic[email]")
                                            detected.add("email-validator")
                except SyntaxError:
                    print(f"[!] SyntaxError parsing {f['filename']}. Skipping AST scan.")

        # Always ensure basic runner tools are present
        detected.add("uvicorn")
        detected.add("fastapi")
        detected.add("python-multipart")
            
        return list(detected)

    def execute_in_sandbox(self, files: list, entrypoint: str, runtime: str = "python", deep_scan_result: dict = None):
        """
        Execute generated code in E2B sandbox.
        Supports both Python and Node.js runtimes.
        
        runtime: "python" or "node"
        deep_scan_result: Original repository scan result for dependency detection
        """
        if not E2B_AVAILABLE or not E2B_API_KEY:
            logger.warning("E2B Sandbox not available (Dependencies or Key missing)")
            _add_debug_log('WARNING', 'SANDBOX', 'E2B not available', {})
            return "E2B Sandbox not available (Dependencies or Key missing)."
            
        # SAFETY CHECK: Did Code Gen Fail?
        if entrypoint == "error.log":
            return f"GENERATION FAILED: Gemini API returned an error.\n\n=== ERROR LOG ===\n{files[0]['content']}\n================="

        logger.info(f"📦 Sandbox execution starting: {entrypoint} | Runtime: {runtime} | Files: {len(files)}")
        _add_debug_log('INFO', 'SANDBOX', f'Execution starting', {
            'entrypoint': entrypoint,
            'runtime': runtime,
            'file_count': len(files),
            'file_list': [f['filename'] for f in files],
        })
        
        try:
            # AGGRESSIVE CLEANUP: Kill previous sandbox if exists
            if self.sandbox:
                try:
                    print("[*] Terminating previous Sandbox...")
                    self.sandbox.close()
                    print("[*] Previous Sandbox terminated successfully.")
                except Exception as e:
                    print(f"[*] Sandbox cleanup warning: {str(e)[:100]}")
                finally:
                    self.sandbox = None

            # Create NEW Sandbox (Persistent) defined by self.sandbox
            # Timeout set to 1800s (30m) to allow user to explore preview
            print("[*] Creating new E2B Sandbox (30min timeout)...")
            try:
                self.sandbox = Sandbox.create(timeout=1800)
                print(f"[*] Sandbox created successfully. ID: {self.sandbox.id if hasattr(self.sandbox, 'id') else 'N/A'}")
            except Exception as sandbox_create_err:
                error_msg = str(sandbox_create_err)
                print(f"[!] Sandbox creation failed: {error_msg}")
                _add_debug_log('ERROR', 'SANDBOX', f'Creation failed: {error_msg}', {})
                # Retry once after a brief pause
                time.sleep(3)
                try:
                    self.sandbox = Sandbox.create(timeout=1800)
                    print(f"[*] Sandbox created on retry. ID: {self.sandbox.id if hasattr(self.sandbox, 'id') else 'N/A'}")
                except Exception as retry_err:
                    return f"Sandbox Error: Failed to create sandbox after retry: {retry_err}"
            
            # Write ALL files (with path sanitization for bash compatibility)
            files_written = 0
            files_failed = 0
            for file in files:
                # Sanitize the filename to prevent bash shell issues
                safe_filename = sanitize_path(file['filename'])
                
                # Log if path was modified
                if safe_filename != file['filename']:
                    print(f"  [!] Path sanitized: {file['filename']} -> {safe_filename}")
                
                # Create directories if needed
                dir_path = os.path.dirname(safe_filename)
                if dir_path and dir_path not in [".", ""]:
                    try:
                        # We can't easily mkdir -p in sandbox file write, so we run a command
                        mkdir_result = self.sandbox.commands.run(f"mkdir -p '{dir_path}'")
                        if mkdir_result.exit_code != 0:
                            print(f"  [!] mkdir warning for {dir_path}: {mkdir_result.stderr}")
                    except Exception as mkdir_err:
                        print(f"  [!] mkdir failed for {dir_path}: {mkdir_err}")
                        # Try alternative - just continue, file write might still work
                        pass
                
                try:
                    self.sandbox.files.write(safe_filename, file['content'])
                    files_written += 1
                except Exception as write_err:
                    files_failed += 1
                    print(f"  [!] File write error for {safe_filename}: {write_err}")
            
            print(f"[*] Files written: {files_written}/{len(files)} ({files_failed} failed)")
            _add_debug_log('INFO', 'SANDBOX', f'Files written: {files_written}/{len(files)}', {
                'failed': files_failed
            })
            
            # Install Dependencies Based on Runtime
            if runtime == "node" or entrypoint.endswith('.js'):
                # ═══════════════════════════════════════════════════════════
                # NODE.JS EXECUTION PATH
                # ═══════════════════════════════════════════════════════════
                print("[*] 🟢 Node.js Runtime Detected")
                
                # Find the directory containing package.json
                entrypoint_dir = os.path.dirname(entrypoint)
                if not entrypoint_dir:
                    entrypoint_dir = "."
                
                # CRITICAL: Look for package.json in ORIGINAL deep_scan first (uses 'path' key)
                # Then fall back to generated files (uses 'filename' key)
                original_package = None
                if deep_scan_result:
                    original_files = deep_scan_result.get("files", [])
                    original_package = next((f for f in original_files if f.get('path', '').endswith('package.json')), None)
                    if original_package:
                        print(f"[*] Found ORIGINAL package.json from repository scan: {original_package.get('path')}")
                
                # Also check generated files (fallback)
                gen_package_json = next((f for f in files if f['filename'].endswith('package.json')), None)
                
                # Check for package.json in entrypoint directory specifically
                entrypoint_package = next((f for f in files if f['filename'] == f"{entrypoint_dir}/package.json"), None)
                
                # Use ORIGINAL package.json for dependencies, fall back to generated
                package_source = original_package if original_package else gen_package_json
                package_dir = entrypoint_dir  # Default to entrypoint dir
                
                if package_source:
                    # Determine the directory
                    if original_package:
                        package_dir = os.path.dirname(original_package.get('path', '')) or "."
                    elif gen_package_json:
                        package_dir = os.path.dirname(gen_package_json.get('filename', '')) or "."
                    
                    print(f"[*] Found package.json - extracting dependencies...")
                    
                    # DYNAMIC DEPENDENCY DETECTION - Parse the package.json content!
                    try:
                        # Get the content of package.json
                        package_content = package_source.get('content', '')
                        if package_content:
                            import json as json_module
                            pkg_data = json_module.loads(package_content)
                            deps = list(pkg_data.get('dependencies', {}).keys())
                            dev_deps = list(pkg_data.get('devDependencies', {}).keys())
                            all_deps = deps + dev_deps
                            
                            if all_deps:
                                print(f"[*] 📦 Detected {len(all_deps)} dependencies: {', '.join(all_deps[:10])}{'...' if len(all_deps) > 10 else ''}")
                                # Install ALL detected dependencies in entrypoint directory
                                deps_str = ' '.join(all_deps)
                                print(f"[*] Installing dependencies in {entrypoint_dir}...")
                                install_result = self.sandbox.commands.run(f"cd {entrypoint_dir} && npm init -y && npm install {deps_str}", timeout=300)
                            else:
                                print("[*] No dependencies found in package.json, installing common packages...")
                                install_result = self.sandbox.commands.run(f"cd {entrypoint_dir} && npm init -y && npm install express mongoose cors dotenv bcrypt multer node-fetch xlsx cookie-parser", timeout=300)
                        else:
                            print("[*] Package.json has no content, installing common packages...")
                            install_result = self.sandbox.commands.run(f"cd {entrypoint_dir} && npm init -y && npm install express mongoose cors dotenv bcrypt multer node-fetch xlsx cookie-parser", timeout=300)
                    except Exception as pkg_err:
                        print(f"[!] Error parsing package.json: {pkg_err}, installing common packages...")
                        install_result = self.sandbox.commands.run(f"cd {entrypoint_dir} && npm init -y && npm install express mongoose cors dotenv bcrypt multer node-fetch xlsx cookie-parser", timeout=300)
                    
                    if install_result.exit_code != 0:
                        print(f"[!] npm install warning: {install_result.stderr[:200] if install_result.stderr else 'No stderr'}")
                    
                    # CRITICAL: If entrypoint is in a subdirectory, also install there
                    # This handles cases like: package.json in root, server in server/
                    if entrypoint_dir and entrypoint_dir != "." and entrypoint_dir != package_dir:
                        # Check if there's a package.json in the server directory
                        if entrypoint_package:
                            print(f"[*] Found separate package.json in server directory: {entrypoint_dir}")
                            print(f"[*] Installing dependencies in {entrypoint_dir}...")
                            self.sandbox.commands.run(f"cd {entrypoint_dir} && npm install", timeout=300)
                        else:
                            # No package.json in server dir - install common packages there
                            print(f"[*] No package.json in {entrypoint_dir}, installing common packages...")
                            self.sandbox.commands.run(f"cd {entrypoint_dir} && npm init -y && npm install express mongoose cors dotenv bcrypt multer node-fetch xlsx", timeout=180)
                else:
                    # No package.json anywhere, install common packages in entrypoint directory
                    print("[*] No package.json found, installing common packages...")
                    package_dir = entrypoint_dir
                    self.sandbox.commands.run(f"cd {entrypoint_dir} && npm init -y", timeout=30)
                    self.sandbox.commands.run(f"cd {entrypoint_dir} && npm install express mongoose cors dotenv bcrypt multer node-fetch xlsx", timeout=180)
                
                # START NODE SERVER IN BACKGROUND
                print(f"[*] Starting Node.js Server: {entrypoint} (logging to app.log)...")
                
                # Run from entrypoint directory (where we installed dependencies)
                # Just run the entrypoint file directly
                server_basename = os.path.basename(entrypoint)
                
                if entrypoint_dir and entrypoint_dir != ".":
                    print(f"[*] Node.js Command: cd {entrypoint_dir} && node {server_basename}")
                    node_cmd = f"cd {entrypoint_dir} && node {server_basename} > app.log 2>&1"
                else:
                    print(f"[*] Node.js Command: node {entrypoint}")
                    node_cmd = f"node {entrypoint} > app.log 2>&1"
                
                self.sandbox.commands.run(node_cmd, background=True)
                
                # HEALTH CHECK LOOP (for Node.js - check ports 3000 and 8000)
                print("[*] Waiting for Node.js Backend to boot...")
                backend_success = False
                node_port = None
                
                for i in range(20):  # Try for 60 seconds
                    time.sleep(3)
                    try:
                        # Check ALL common Node.js ports (3001 is very common!)
                        for port in [3000, 3001, 8000, 8080, 5000, 4000, 5001]:
                            check_script = f"""
import urllib.request
import urllib.error
try:
    response = urllib.request.urlopen('http://127.0.0.1:{port}', timeout=2)
    print('PORT_{port}_OK')
except urllib.error.HTTPError as e:
    print('PORT_{port}_OK')  # 4xx/5xx still means server is running
except:
    pass
"""
                            result = self.sandbox.commands.run(f"python3 -c \"{check_script}\"")
                            if f"PORT_{port}_OK" in result.stdout:
                                node_port = port
                                backend_success = True
                                break
                        
                        if backend_success:
                            break
                            
                        print(f"[*] Node.js Health Check {i+1}/20: Waiting...")
                        
                        # Early log check for crash detection
                        if i == 4:
                            log_check = self.sandbox.commands.run(f"cd {package_dir} && cat app.log 2>/dev/null | head -10")
                            if log_check.stdout:
                                print(f"[DEBUG] Early Log Check:\n{log_check.stdout[:300]}")
                                
                    except Exception as e:
                        print(f"[*] Node.js Health Check {i+1}/20: {str(e)[:50]}...")
                
                if not backend_success:
                    # Get logs for debugging
                    log_result = self.sandbox.commands.run(f"cd {package_dir} && cat app.log 2>/dev/null")
                    return f"FATAL: Node.js Backend failed to start after 60 seconds.\n\n=== APP.LOG ===\n{log_result.stdout[:1000]}\n==============="
                
                backend_url = f"https://{self.sandbox.get_host(node_port)}"
                print(f"[*] Node.js Backend Live at: {backend_url}")
                
                # ═══════════════════════════════════════════════════════════
                # POST-WRITE URL FIXUP: Replace ALL hardcoded localhost with real backend URL
                # This catches cases where Gemini still hardcodes localhost despite prompts
                # CRITICAL: Also updates file['content'] so downstream code reads fixed content
                # ═══════════════════════════════════════════════════════════
                import re as _re
                print(f"[*] Fixing hardcoded localhost references in frontend files...")
                url_fix_count = 0
                for file in files:
                    fname = file['filename']
                    if any(fname.endswith(ext) for ext in ['.html', '.js', '.jsx', '.ts', '.tsx', '.vue', '.svelte', '.mjs', '.cjs', '.css']):
                        content = file['content']
                        original_content = content
                        # Replace ALL localhost/127.0.0.1 URLs with any port (8000, 5000, 3001, etc.)
                        content = _re.sub(r'https?://(?:localhost|127\.0\.0\.1|0\.0\.0\.0):(?:8000|5000|3001|8080|5001|4000)\b', backend_url, content)
                        # Also replace quoted versions to handle edge cases
                        content = _re.sub(r"'https?://(?:localhost|127\.0\.0\.1|0\.0\.0\.0):(?:8000|5000|3001|8080|5001|4000)(/[^']*)?'", f"'{backend_url}\\1'", content)
                        content = _re.sub(r'"https?://(?:localhost|127\.0\.0\.1|0\.0\.0\.0):(?:8000|5000|3001|8080|5001|4000)(/[^"]*)?\"', f'"{backend_url}\\1"', content)
                        content = _re.sub(r'`https?://(?:localhost|127\.0\.0\.1|0\.0\.0\.0):(?:8000|5000|3001|8080|5001|4000)', f'`{backend_url}', content)
                        if content != original_content:
                            # CRITICAL: Update file['content'] so downstream code sees fixed version
                            file['content'] = content
                            safe_fn = fname.lstrip('/')
                            if safe_fn.startswith('..'):
                                safe_fn = safe_fn.replace('..', '')
                            try:
                                self.sandbox.files.write(safe_fn, content)
                                url_fix_count += 1
                                print(f"  [*] Fixed URL in: {safe_fn}")
                            except Exception as fix_err:
                                print(f"  [!] Failed to fix URL in {safe_fn}: {fix_err}")
                print(f"[*] URL fixup complete: {url_fix_count} files updated")
                
                # ═══════════════════════════════════════════════════════════
                # COMPREHENSIVE FRONTEND/PROJECT DETECTION
                # Detects: React, Vue, Next.js, Vite, Angular, Static HTML,
                #          PHP, Flask templates, Django templates, and more
                # ═══════════════════════════════════════════════════════════
                frontend_dirs = []
                frontend_type = "unknown"
                has_static_html = False
                static_html_dirs = set()
                
                for f in files:
                    path = f['filename']
                    path_lower = path.lower()
                    basename = os.path.basename(path)
                    dirname = os.path.dirname(path)
                    
                    # ───────────────────────────────────────────────────────────
                    # JavaScript Framework Detection (Need npm build)
                    # ───────────────────────────────────────────────────────────
                    
                    # Next.js
                    if 'next.config' in basename.lower():
                        frontend_dirs.append(dirname)
                        frontend_type = "Next.js"
                    
                    # Vite (React, Vue, Svelte)
                    elif 'vite.config' in basename.lower():
                        frontend_dirs.append(dirname)
                        frontend_type = "Vite"
                    
                    # Angular
                    elif basename == 'angular.json':
                        frontend_dirs.append(dirname)
                        frontend_type = "Angular"
                    
                    # Vue CLI
                    elif basename == 'vue.config.js':
                        frontend_dirs.append(dirname)
                        frontend_type = "Vue CLI"
                    
                    # Create React App
                    elif basename == 'package.json' and ('frontend' in path_lower or 'client' in path_lower or 'web' in path_lower):
                        frontend_dirs.append(dirname)
                        frontend_type = "React/NPM"
                    
                    # Nuxt.js
                    elif 'nuxt.config' in basename.lower():
                        frontend_dirs.append(dirname)
                        frontend_type = "Nuxt.js"
                    
                    # Gatsby
                    elif basename == 'gatsby-config.js':
                        frontend_dirs.append(dirname)
                        frontend_type = "Gatsby"
                    
                    # SvelteKit
                    elif basename == 'svelte.config.js':
                        frontend_dirs.append(dirname)
                        frontend_type = "SvelteKit"
                    
                    # ───────────────────────────────────────────────────────────
                    # Static HTML Detection (Served directly by backend)
                    # ───────────────────────────────────────────────────────────
                    if path.endswith('.html'):
                        # Common static directories
                        static_patterns = ['public', 'static', 'views', 'templates', 'www', 'html', 'pages']
                        for pattern in static_patterns:
                            if pattern in path_lower:
                                static_html_dirs.add(dirname)
                                has_static_html = True
                                break
                        
                        # Any HTML at root or in recognized folder
                        if dirname and not has_static_html:
                            static_html_dirs.add(dirname)
                            has_static_html = True
                    
                    # ───────────────────────────────────────────────────────────
                    # Template Engine Detection (Served by backend)
                    # ───────────────────────────────────────────────────────────
                    
                    # EJS (Express)
                    if path.endswith('.ejs'):
                        has_static_html = True
                        static_html_dirs.add(dirname)
                    
                    # Pug/Jade (Express)
                    elif path.endswith('.pug') or path.endswith('.jade'):
                        has_static_html = True
                        static_html_dirs.add(dirname)
                    
                    # Handlebars (Express)
                    elif path.endswith('.hbs') or path.endswith('.handlebars'):
                        has_static_html = True
                        static_html_dirs.add(dirname)
                    
                    # Jinja2 (Flask/Python)
                    elif path.endswith('.jinja2') or path.endswith('.j2'):
                        has_static_html = True
                        static_html_dirs.add(dirname)
                    
                    # Django templates
                    elif '/templates/' in path and path.endswith('.html'):
                        has_static_html = True
                        static_html_dirs.add(dirname)
                    
                    # PHP
                    elif path.endswith('.php'):
                        has_static_html = True
                        static_html_dirs.add(dirname)
                    
                    # Ruby ERB
                    elif path.endswith('.erb'):
                        has_static_html = True
                        static_html_dirs.add(dirname)
                
                # Deduplicate JS framework dirs
                frontend_dirs = list(set(frontend_dirs))
                
                # Log what was detected
                if has_static_html:
                    static_dirs_str = ', '.join(list(static_html_dirs)[:3])
                    print(f"[*] 📄 Static HTML/Templates Detected: {static_dirs_str}")
                    print(f"[*] ℹ️  Static content will be served directly by the Node.js backend")
                
                if frontend_dirs:
                    frontend_dir = frontend_dirs[0]
                    print(f"[*] 🎨 JS Framework Detected: {frontend_type} at {frontend_dir}")
                    
                    # Install frontend dependencies
                    print(f"[*] Installing Frontend dependencies (npm install)...")
                    install_result = self.sandbox.commands.run(f"cd {frontend_dir} && npm install --force", timeout=300)
                    if install_result.exit_code != 0:
                        print(f"[!] npm install warning: {install_result.stderr[:200] if install_result.stderr else 'No stderr'}")
                    
                    # Inject Backend URL into .env.local for Next.js
                    print(f"[*] Injecting Backend URL into frontend environment...")
                    env_content = f"NEXT_PUBLIC_API_URL={backend_url}\nVITE_API_URL={backend_url}\nREACT_APP_API_URL={backend_url}\n"
                    self.sandbox.files.write(f"{frontend_dir}/.env.local", env_content)
                    self.sandbox.files.write(f"{frontend_dir}/.env", env_content)
                    
                    # Build frontend (for Next.js, React)
                    print(f"[*] Building Frontend for production...")
                    build_result = self.sandbox.commands.run(f"cd {frontend_dir} && npm run build", timeout=300)
                    
                    if build_result.exit_code != 0:
                        error_output = (build_result.stderr or '') + (build_result.stdout or '')
                        print(f"[!] Frontend build failed. Error:\n{error_output[:500]}")
                        # Return with just backend URL if frontend fails
                        return f"Node.js Backend started (Frontend build failed).\n[PREVIEW_URL] {backend_url}\n\n=== BUILD ERROR ===\n{error_output[:500]}"
                    
                    # Start frontend in production mode
                    print(f"[*] Starting Frontend in production mode...")
                    # Try different start commands based on framework
                    start_cmd = f"cd {frontend_dir} && npm start -- -p 3000 > frontend.log 2>&1"
                    self.sandbox.commands.run(start_cmd, background=True)
                    
                    # Wait for frontend to boot
                    time.sleep(10)
                    
                    # Get frontend URL
                    frontend_host = self.sandbox.get_host(3000)
                    frontend_url = f"https://{frontend_host}"
                    
                    print(f"[*] 🎨 Frontend Live at: {frontend_url}")
                    print(f"[*] Frontend → Backend Connection: {backend_url}")
                    
                    return f"Dual-Stack Deployed Successfully.\n[PREVIEW_URL] {frontend_url}\n[BACKEND_URL] {backend_url}"
                
                # No frontend detected - just return backend URL
                return f"Node.js Server started successfully.\n[PREVIEW_URL] {backend_url}"
                
            elif runtime == "python" or entrypoint.endswith('.py'):
                # ═══════════════════════════════════════════════════════════
                # PYTHON EXECUTION PATH (Original)
                # ═══════════════════════════════════════════════════════════
                print("[*] 🐍 Python Runtime Detected")
                print("[*] Installing Python dependencies (Timeout: 300s)...")
                
                # 1. Start with Intelligent Inference
                inferred = self.infer_dependencies(files)
                final_reqs = set(inferred)
                
                print(f"[*] Intelligent Scanner detected {len(inferred)} required packages from code analysis.")
                if inferred:
                    print(f"[DEBUG] Inferred: {', '.join(inferred)}")

                # 2. Merge with requirements.txt if it exists
                req_file = next((f for f in files if "requirements.txt" in f['filename']), None)
                if req_file:
                    print(f"[*] Merging with requirements.txt...")
                    self.sandbox.commands.run(f"pip install -r {req_file['filename']}", timeout=300)
                
                # 3. Force Install the Consolidated "Smart" list
                if final_reqs:
                    install_str = " ".join([f"'{p}'" for p in final_reqs])
                    print(f"[*] Pre-loading inferred dependencies to prevent runtime errors...")
                    self.sandbox.commands.run(f"pip install {install_str}", timeout=300)
                
                # 4. CRITICAL: Force bcrypt==4.0.1 to prevent version compatibility errors
                print(f"[*] Enforcing bcrypt==4.0.1 (compatibility fix)...")
                self.sandbox.commands.run("pip install --force-reinstall bcrypt==4.0.1", timeout=60)

                # START SERVER IN BACKGROUND (With Logging)
                print(f"[*] Starting Backend {entrypoint} in background (logging to app.log)...")
                self.sandbox.commands.run(f"python {entrypoint} > app.log 2>&1", background=True)
                
                # HEALTH CHECK LOOP (Backend)
                print("[*] Waiting for Backend to boot...")
                backend_success = False
                for i in range(20): # Try for 60 seconds (increased from 45)
                    time.sleep(3)
                    try:
                        # Use Python instead of curl (curl may not be installed)
                        # Note: urlopen throws HTTPError for 4xx/5xx, so we catch it
                        check_script = """
import urllib.request
import urllib.error
try:
    response = urllib.request.urlopen('http://127.0.0.1:8000', timeout=2)
    print(response.status)
except urllib.error.HTTPError as e:
    print(e.code)
except Exception as e:
    print('error')
"""
                        check = self.sandbox.commands.run(f"python -c \"{check_script}\"")
                        status_code = check.stdout.strip()
                        print(f"[*] Backend Health Check {i+1}/20: HTTP {status_code if status_code and status_code != 'error' else 'No Response'}")
                        
                        # Accept any valid HTTP response (200, 404, etc.) as success
                        if status_code and status_code.isdigit() and int(status_code) < 600: 
                            print(f"[*] Backend Health Check: SUCCESS ✓ (HTTP {status_code})")
                            backend_success = True
                            break
                    except Exception as e:
                        print(f"[*] Backend Health Check {i+1}/20: Exception - {str(e)[:50]}")
                        pass
                    
                    # Early log check after 5 attempts to diagnose issues faster
                    if i == 4:
                        try:
                            early_log = self.sandbox.files.read("app.log")
                            if early_log and len(early_log) > 10:
                                print(f"[DEBUG] Early Log Check (Backend may have crashed):\n{early_log[:300]}")
                                # Check for Python crash indicators
                                crash_indicators = ["SyntaxError", "ImportError", "ModuleNotFoundError", 
                                                   "NameError", "IndentationError", "AttributeError: module"]
                                if any(indicator in early_log for indicator in crash_indicators):
                                    print("[!] PYTHON ERROR DETECTED - Breaking health check loop early")
                                    log_content = early_log
                                    break  # Exit health check loop immediately
                        except:
                            pass

                if not backend_success:
                    print("[!] Backend FAILED to start. Retrieving logs...")
                    
                    # Check if log_content was already read in early check (from break)
                    if 'log_content' not in locals():
                        try:
                            log_content = self.sandbox.files.read("app.log")
                            print(f"[DEBUG] App Log (First 1000 chars):\n{log_content[:1000]}")
                        except:
                            log_content = "Could not read app.log"
                    else:
                        print(f"[DEBUG] Using early log check data ({len(log_content)} bytes)")
                    
                    # Also capture any Python syntax errors
                    if "SyntaxError" in log_content or "ImportError" in log_content or "ModuleNotFoundError" in log_content:
                        print("[!] DETECTED CODE ERROR - Will trigger auto-regeneration")
                    
                    # Return with clear error marker for auto-retry
                    return f"BACKEND_CRASH: {log_content[:800]}"

                # Get Backend URL
                backend_host = self.sandbox.get_host(8000)
                backend_url = f"https://{backend_host}"
                print(f"[*] Backend Live at: {backend_url}")

                # ═══════════════════════════════════════════════════════════
                # POST-WRITE URL FIXUP: Replace ALL hardcoded localhost with real backend URL
                # This catches cases where Gemini still hardcodes localhost despite prompts
                # CRITICAL: Also updates file['content'] so downstream code reads fixed content
                # ═══════════════════════════════════════════════════════════
                import re as _re
                print(f"[*] Fixing hardcoded localhost references in frontend files...")
                url_fix_count = 0
                for file in files:
                    fname = file['filename']
                    if any(fname.endswith(ext) for ext in ['.html', '.js', '.jsx', '.ts', '.tsx', '.vue', '.svelte', '.mjs', '.cjs', '.css']):
                        content = file['content']
                        original_content = content
                        # Replace ALL localhost/127.0.0.1 URLs with any port
                        content = _re.sub(r'https?://(?:localhost|127\.0\.0\.1|0\.0\.0\.0):(?:8000|5000|3001|8080|5001|4000)\b', backend_url, content)
                        content = _re.sub(r"'https?://(?:localhost|127\.0\.0\.1|0\.0\.0\.0):(?:8000|5000|3001|8080|5001|4000)(/[^']*)?'", f"'{backend_url}\\1'", content)
                        content = _re.sub(r'"https?://(?:localhost|127\.0\.0\.1|0\.0\.0\.0):(?:8000|5000|3001|8080|5001|4000)(/[^"]*)?\"', f'"{backend_url}\\1"', content)
                        content = _re.sub(r'`https?://(?:localhost|127\.0\.0\.1|0\.0\.0\.0):(?:8000|5000|3001|8080|5001|4000)', f'`{backend_url}', content)
                        if content != original_content:
                            # CRITICAL: Update file['content'] so downstream code sees fixed version
                            file['content'] = content
                            safe_fn = fname.lstrip('/')
                            if safe_fn.startswith('..'):
                                safe_fn = safe_fn.replace('..', '')
                            try:
                                self.sandbox.files.write(safe_fn, content)
                                url_fix_count += 1
                                print(f"  [*] Fixed URL in: {safe_fn}")
                            except Exception as fix_err:
                                print(f"  [!] Failed to fix URL in {safe_fn}: {fix_err}")
                print(f"[*] URL fixup complete: {url_fix_count} files updated")

                # --- PHASE 2: FRONTEND LAUNCH (Dual Stack) ---
                # Check for frontend: Next.js (package.json) OR static files (index.html)
                # Detect BOTH frontend/ directory structure AND root-level frontend files
                has_next_frontend = any("frontend/package.json" in f['filename'] for f in files)
                has_static_frontend_in_dir = any("frontend/index.html" in f['filename'] for f in files)
                has_static_frontend_root = any(f['filename'] == "index.html" or f['filename'].endswith("/index.html") and "frontend" not in f['filename'] for f in files)
                
                # Combine: frontend detected if EITHER in frontend/ dir OR at root
                has_static_frontend = has_static_frontend_in_dir or has_static_frontend_root
                
                # Determine frontend directory
                if has_static_frontend_in_dir:
                    frontend_dir = "frontend"
                elif has_static_frontend_root:
                    frontend_dir = "."  # Serve from root
                else:
                    frontend_dir = None
                
                if has_next_frontend:
                    print("🚀 Detected Frontend. Initiating Dual-Stack Launch...")
                    frontend_dir = "modernized_stack/frontend"
                    
                    # CRITICAL: Create .env.local with backend URL BEFORE building
                    # Next.js bakes env vars at build time, not runtime
                    print(f"[*] Injecting Backend URL into .env.local...")
                    env_content = f"NEXT_PUBLIC_API_URL={backend_url}\n"
                    self.sandbox.files.write(f"{frontend_dir}/.env.local", env_content)
                    print(f"[DEBUG] Created .env.local with: NEXT_PUBLIC_API_URL={backend_url}")
                    
                    print("[*] Installing Node dependencies (Timeout: 300s)...")
                    self.sandbox.commands.run(f"cd {frontend_dir} && npm install --force", timeout=300)
                    
                    print(f"[*] Building Frontend for production (Backend URL: {backend_url})...")
                    # Now the build will include the backend URL
                    build_result = self.sandbox.commands.run(f"cd {frontend_dir} && npm run build", timeout=300)
                    
                    # Check for build errors
                    if build_result.exit_code != 0:
                        error_output = build_result.stderr + build_result.stdout
                        print(f"[!] Frontend build failed. Error output:\n{error_output[:500]}")
                        
                        # Return error with context for potential retry
                        return f"FRONTEND BUILD FAILED:\\n\\n{error_output}\\n\\nThis error will trigger automatic code regeneration."
                    
                    print(f"[*] Starting Frontend in production mode...")
                    # Start production server (API URL already baked into build)
                    start_cmd = f"cd {frontend_dir} && npm start -- -p 3000"
                    self.sandbox.commands.run(f"{start_cmd} > frontend.log 2>&1", background=True)
                    
                    # Wait for Frontend
                    time.sleep(10) # Give Next.js a moment to spin up
                    frontend_host = self.sandbox.get_host(3000)
                    frontend_url = f"https://{frontend_host}"
                    
                    print(f"[*] Frontend Live at: {frontend_url}")
                    print(f"[*] Frontend → Backend Connection: {backend_url}")
                    
                    return f"Dual-Stack Deployed Successfully.\\n[PREVIEW_URL] {frontend_url}\\n[BACKEND_URL] {backend_url}"
                
                elif has_static_frontend:
                    # Static Frontend (HTML/CSS/JS) - Serve with Python http.server
                    if has_static_frontend_in_dir:
                        print("🎨 Detected Static Frontend (HTML/CSS/JS in frontend/ directory)...")
                    else:
                        print("🎨 Detected Static Frontend (HTML/CSS/JS at root level)...")
                    
                    # Inject window.__API_BASE_URL__ into all HTML files for static frontends
                    # CRITICAL: file['content'] is already URL-fixed by the fixup step above
                    print(f"[*] Injecting backend URL into static HTML files...")
                    api_script_tag = f'<script>window.__API_BASE_URL__ = "{backend_url}";</script>'
                    for file in files:
                        if file['filename'].endswith('.html'):
                            # Use the already-fixed content (file['content'] was updated in URL fixup)
                            content = file['content']
                            # Only inject if not already present
                            if '__API_BASE_URL__' not in content or f'window.__API_BASE_URL__ = "{backend_url}"' not in content:
                                if '<head>' in content:
                                    content = content.replace('<head>', f'<head>\n{api_script_tag}', 1)
                                elif '<body>' in content:
                                    content = content.replace('<body>', f'<body>\n{api_script_tag}', 1)
                                else:
                                    content = api_script_tag + '\n' + content
                            # Update file['content'] with the injected version
                            file['content'] = content
                            safe_fn = file['filename'].lstrip('/')
                            if safe_fn.startswith('..'):
                                safe_fn = safe_fn.replace('..', '')
                            try:
                                self.sandbox.files.write(safe_fn, content)
                                print(f"  [*] Injected API URL into: {safe_fn}")
                            except Exception as inj_err:
                                print(f"  [!] Failed to inject into {safe_fn}: {inj_err}")
                    
                    # Verify files exist before starting server
                    try:
                        ls_result = self.sandbox.commands.run("ls -la /home/user/*.html /home/user/*.css /home/user/*.js 2>/dev/null | head -10")
                        print(f"[DEBUG] Frontend files in /home/user:\n{ls_result.stdout}")
                    except:
                        pass
                    
                    print(f"[*] Serving static files from: {frontend_dir}/")
                    print(f"[*] Backend APIs remain on: {backend_url}")
                    
                    # Start simple HTTP server on port 3000
                    # CRITICAL: E2B writes files to /home/user/, so explicitly cd there
                    if frontend_dir == ".":
                        # Root level - serve from /home/user where files are written
                        self.sandbox.commands.run(f"cd /home/user && python -m http.server 3000 > /home/user/frontend.log 2>&1", background=True)
                    else:
                        # frontend/ directory
                        self.sandbox.commands.run(f"cd /home/user/{frontend_dir} && python -m http.server 3000 > /home/user/frontend.log 2>&1", background=True)
                    
                    time.sleep(3)  # Give server time to start
                    frontend_host = self.sandbox.get_host(3000)
                    frontend_url = f"https://{frontend_host}"
                    
                    # Verify frontend server is actually responding
                    try:
                        check_script = """
import urllib.request
try:
    response = urllib.request.urlopen('http://127.0.0.1:3000', timeout=2)
    print('OK')
except Exception as e:
    print(f'ERROR: {e}')
"""
                        check = self.sandbox.commands.run(f"python -c \"{check_script}\"")
                        if 'OK' in check.stdout:
                            print(f"[*] Frontend Health Check: SUCCESS ✓")
                        else:
                            print(f"[!] Frontend Health Check FAILED: {check.stdout.strip()}")
                            # Try to get error logs
                            try:
                                frontend_log = self.sandbox.files.read("/home/user/frontend.log")
                                print(f"[DEBUG] Frontend Log: {frontend_log[:300]}")
                            except:
                                pass
                    except Exception as e:
                        print(f"[!] Frontend health check exception: {str(e)[:100]}")
                    
                    print(f"[*] 🎨 Frontend Live at: {frontend_url}")
                    print(f"[*] 🔌 Backend APIs at: {backend_url}")
                    
                    return f"Dual-Stack Deployed Successfully.\n[PREVIEW_URL] {frontend_url}\n[BACKEND_URL] {backend_url}"
                
                else:
                    # Single Stack (Backend Only)
                    return f"Backend Server started.\n[PREVIEW_URL] {backend_url}"

            else: 
                    # Node entrypoint (Fallback)
                    cmd = f"node {entrypoint} > app.log 2>&1"
                    self.sandbox.commands.run(cmd, background=True)
                    time.sleep(5)
                    host = self.sandbox.get_host(3000)
                    return f"Node Server started.\n[PREVIEW_URL] https://{host}"
                
        except Exception as e:
            return f"Sandbox Error: {str(e)}"

    def process_resurrection_stream(self, repo_url: str, instructions: str):
        """Generator that yields logs and results in real-time with interactive checkpoints."""
        logs = []
        deep_scan_result = None  # Store deep scan for reuse
        
        def emit_log(msg):
            logs.append(msg)
            logger.info(f"   ➡ {msg}")
            _add_debug_log('INFO', 'RESURRECT', msg, {})
            return {"type": "log", "content": msg}

        def emit_debug(msg):
            logger.debug(f"   🔍 {msg[:200]}")
            _add_debug_log('DEBUG', 'RESURRECT_DEBUG', msg[:500], {})
            return {"type": "debug", "content": msg}

        # Record resurrection attempt start in memory
        record_attempt_start(repo_url, None)
        
        # 1. DEEP SCAN - Fetch ALL file contents for preservation
        yield emit_log("🔍 Initiating DEEP SCAN of Legacy Repository...")
        yield emit_log("📂 Fetching ALL file contents for preservation analysis...")
        
        # DEEP SCAN (fetches full file contents)
        deep_scan_result = self.scan_repository_deep(repo_url)
        
        tech_stack = deep_scan_result.get("tech_stack", {})
        must_preserve = deep_scan_result.get("must_preserve", [])
        files_analyzed = len(deep_scan_result.get("files", []))
        
        # Send repo file list to frontend for VS Code-style tree view
        repo_file_paths = [f["path"] for f in deep_scan_result.get("files", []) if "path" in f]
        if repo_file_paths:
            yield {"type": "repo_files", "files": repo_file_paths}
        
        # Update memory with tech stack
        record_attempt_start(repo_url, tech_stack)
        
        yield emit_debug(f"[DEBUG] Deep Scan Complete:\n  Files Analyzed: {files_analyzed}\n  Tech Stack: {tech_stack}\n  Must Preserve: {len(must_preserve)} items")
        
        if tech_stack.get("backend", {}).get("database"):
            yield emit_log(f"🔒 Detected Database: {tech_stack['backend']['database']} (WILL BE PRESERVED)")
        if tech_stack.get("backend", {}).get("framework"):
            yield emit_log(f"⚙️ Detected Backend: {tech_stack['backend']['framework']}")
        if tech_stack.get("frontend", {}).get("framework"):
            yield emit_log(f"🎨 Detected Frontend: {tech_stack['frontend']['framework']}")

        # 2. PRESERVATION-FIRST PLANNING
        yield emit_log("📋 Creating PRESERVATION-FIRST Modernization Plan...")
        
        plan = self.generate_modernization_plan(repo_url, instructions, deep_scan_result)
        yield emit_debug(f"[DEBUG] Generated Plan:\n{plan}")

        if "[ERROR]" in plan:
             yield emit_log("⚠️ Warning: Connection Unstable. Engaged Fallback Protocols.")
             fallback_mode = True
        else:
             fallback_mode = False
        
        # ═══════════════════════════════════════════════════════════
        # CHECKPOINT 1: POST-PLAN — Let user review the plan
        # ═══════════════════════════════════════════════════════════
        yield {
            "type": "checkpoint",
            "id": "post_plan",
            "title": "Modernization Plan Ready",
            "description": "Review the AI-generated modernization plan before code generation begins.",
            "data": {
                "plan": plan,
                "tech_stack": tech_stack,
                "files_analyzed": files_analyzed,
                "must_preserve": must_preserve[:20],
            }
        }
             
        yield emit_log("🏗️ Architecting Enhanced Blueprint (Preserving Core Logic)...")

        # 2. Code Gen with COMPREHENSIVE Auto-Healing Loop
        MAX_RETRIES = 3
        retry_count = 0
        sandbox_logs = None
        files = []
        entrypoint = 'modernized_stack/backend/main.py'
        all_errors = []  # Track all errors for context accumulation
        
        # Progress callback for batch processing - collects messages to yield
        batch_progress_messages = []
        def batch_progress(msg):
            batch_progress_messages.append(msg)
        
        while retry_count <= MAX_RETRIES:
            try:
                batch_progress_messages.clear()
                
                if retry_count > 0:
                    yield emit_log(f"🔧 Auto-Healing: Regenerating code (Attempt {retry_count + 1}/{MAX_RETRIES + 1})...")
                    
                    # Build comprehensive error context for AI
                    error_context = self._build_error_context(all_errors)
                    plan_with_error = plan + error_context
                    code_data = self.generate_code_batched(plan_with_error, deep_scan_result, repo_url, progress_callback=batch_progress)
                else:
                    yield emit_log("🔨 Synthesizing Enhanced Infrastructure (Multi-Batch Engine v7.0)...")
                    code_data = self.generate_code_batched(plan, deep_scan_result, repo_url, progress_callback=batch_progress)
                
                # Emit any batch progress messages
                for msg in batch_progress_messages:
                    yield emit_log(msg)
                
                files = code_data.get('files', [])
                entrypoint = code_data.get('entrypoint', 'modernized_stack/backend/main.py')
                runtime = code_data.get('runtime', 'python')
                
                # Validate generated files
                if not files:
                    raise Exception("CODE GENERATION FAILED: No files were generated")
                
                # Reject error.log sentinel if it somehow slipped through
                if len(files) == 1 and files[0].get('filename') == 'error.log':
                    raise Exception(f"CODE GENERATION FAILED: Only error.log produced. Content: {files[0].get('content', '')[:200]}")
                
                encoded_files = [f['filename'] for f in files]
                yield emit_debug(f"[DEBUG] Generated Files: {', '.join(encoded_files)}")
                yield emit_log(f"Generated {len(encoded_files)} System Modules...")
                yield emit_log(f"📦 Detected Runtime: {runtime.upper()} | Entrypoint: {entrypoint}")
                
                # ═══════════════════════════════════════════════════════════
                # CHECKPOINT 2: POST-CODEGEN — Let user review generated files
                # ═══════════════════════════════════════════════════════════
                yield {
                    "type": "checkpoint",
                    "id": "post_codegen",
                    "title": "Code Generation Complete",
                    "description": "Review the generated files before deploying to the sandbox. You can request changes or proceed.",
                    "data": {
                        "files": [{"filename": f['filename'], "preview": f['content'][:500]} for f in files],
                        "file_count": len(files),
                        "runtime": runtime,
                        "entrypoint": entrypoint,
                        "full_artifacts": files,
                    }
                }
                
                # 3. Execution
                yield emit_log("Booting Neural Sandbox Environment...")
                sandbox_logs = self.execute_in_sandbox(files, entrypoint, runtime, deep_scan_result)
                yield emit_debug(f"[DEBUG] Sandbox Output:\n{sandbox_logs}")
                
                # Extract preview URL early for checkpoint
                import re as _re
                _url_match = _re.search(r"\[PREVIEW_URL\] (https://[^\s]+)", sandbox_logs or "")
                _backend_match = _re.search(r"\[BACKEND_URL\] (https://[^\s]+)", sandbox_logs or "")
                _preview_url = _url_match.group(1) if _url_match else ""
                _backend_url = _backend_match.group(1) if _backend_match else ""
                
                # 4. Comprehensive Error Detection
                error_detected, error_type, error_message = self._detect_errors(sandbox_logs)
                
                if not error_detected and _preview_url:
                    # ═══════════════════════════════════════════════════════════
                    # CHECKPOINT 3: POST-SANDBOX — Live preview for user review
                    # ═══════════════════════════════════════════════════════════
                    yield {
                        "type": "checkpoint",
                        "id": "post_sandbox",
                        "title": "Live Preview Ready",
                        "description": "Your modernized app is running! Review the live preview and request refinements if needed.",
                        "data": {
                            "preview_url": _preview_url,
                            "backend_url": _backend_url,
                            "file_count": len(files),
                            "runtime": runtime,
                            "status": "deployed",
                        }
                    }
                
                if error_detected:
                    all_errors.append({
                        "attempt": retry_count + 1,
                        "type": error_type,
                        "message": error_message
                    })
                    
                    if retry_count < MAX_RETRIES:
                        yield emit_log(f"⚠️ {error_type} Detected. Initiating Auto-Heal...")
                        retry_count += 1
                        continue  # Retry
                    else:
                        error_context = self._build_error_context(all_errors)
                        record_failure(repo_url, error_type, error_context[:200], f"Attempt {retry_count + 1}")
                        yield emit_log(f"❌ Auto-Heal Failed after {MAX_RETRIES + 1} attempts. Proceeding with partial result.")
                        break
                else:
                    # Success!
                    record_success(repo_url, decisions=["Resurrection completed successfully"], patterns_used=[f"Runtime: {runtime}", f"Entrypoint: {entrypoint}"])
                    yield emit_log("✅ Verifying System Integrity... All checks passed!")
                    break
                    
            except GeminiAPIError as api_error:
                # API is completely down — wait longer before retry
                error_str = str(api_error)
                all_errors.append({
                    "attempt": retry_count + 1,
                    "type": "GEMINI_API_DOWN",
                    "message": error_str
                })
                
                if retry_count < MAX_RETRIES:
                    wait_secs = 15 * (retry_count + 1)  # 15s, 30s, 45s
                    yield emit_log(f"⚠️ Gemini API unavailable. Waiting {wait_secs}s before retry {retry_count + 2}/{MAX_RETRIES + 1}...")
                    time.sleep(wait_secs)
                    retry_count += 1
                    sandbox_logs = f"GEMINI_API_ERROR: {error_str}"
                    continue
                else:
                    record_failure(repo_url, "GEMINI_API_DOWN", error_str[:200], "Max retries exceeded")
                    yield emit_log(f"❌ Gemini API is unreachable after {MAX_RETRIES + 1} attempts. Please check your API key and quota at https://aistudio.google.com/")
                    sandbox_logs = f"FATAL: Gemini API unreachable: {error_str}"
                    break
                    
            except Exception as loop_error:
                error_str = str(loop_error)
                all_errors.append({
                    "attempt": retry_count + 1,
                    "type": "EXCEPTION",
                    "message": error_str
                })
                
                if retry_count < MAX_RETRIES:
                    yield emit_log(f"⚠️ Exception caught: {error_str[:150]}. Retrying...")
                    retry_count += 1
                    sandbox_logs = f"EXCEPTION: {error_str}"
                    time.sleep(3)  # Brief pause before code-level retry
                    continue
                else:
                    record_failure(repo_url, "EXCEPTION", error_str[:200], "Max retries exceeded")
                    yield emit_log(f"❌ Max retries exceeded. Error: {error_str[:150]}")
                    sandbox_logs = f"FATAL ERROR: {error_str}"
                    break
        
        # Extract HTML for preview
        preview = ""
        # Check logs for URL
        url_match = re.search(r"\[PREVIEW_URL\] (https://[^\s]+)", sandbox_logs or "")
        if url_match:
            preview = url_match.group(1) # It's a URL now, not HTML content
        else:
             # Fallback: No URL found
             pass
        
        # Check artifacts for preview content
        # Priority: preview.html > index.html > any .html file
        html_file = None
        for f in files:
            fname = f.get('filename', '').lower()
            if 'preview.html' in fname:
                html_file = f
                break
        if not html_file:
            for f in files:
                fname = f.get('filename', '').lower()
                basename = fname.rsplit('/', 1)[-1] if '/' in fname else fname
                if basename == 'index.html':
                    html_file = f
                    break
        if not html_file:
            for f in files:
                fname = f.get('filename', '').lower()
                if fname.endswith('.html') or fname.endswith('.htm'):
                    html_file = f
                    break
        
        if html_file and not preview.startswith("http"):
            # Build a self-contained preview by inlining CSS and JS
            preview_html = html_file['content']
            
            # Collect CSS and JS files for inlining
            css_files = {}
            js_files = {}
            for f in files:
                fn = f.get('filename', '')
                fn_lower = fn.lower()
                if fn_lower.endswith('.css'):
                    # Map both full path and basename
                    css_files[fn] = f['content']
                    basename = fn.rsplit('/', 1)[-1] if '/' in fn else fn
                    css_files[basename] = f['content']
                elif fn_lower.endswith('.js') and not fn_lower.endswith('.json'):
                    js_files[fn] = f['content']
                    basename = fn.rsplit('/', 1)[-1] if '/' in fn else fn
                    js_files[basename] = f['content']
            
            # Inline CSS: replace <link rel="stylesheet" href="..."> with <style>...</style>
            import re as _re
            def _inline_css(match):
                href = match.group(1) or match.group(2) or ''
                # Try to find the CSS file
                basename = href.rsplit('/', 1)[-1] if '/' in href else href
                css_content = css_files.get(href) or css_files.get(basename) or css_files.get('./' + href)
                if css_content:
                    return f'<style>\n{css_content}\n</style>'
                return match.group(0)  # Keep original if not found
            
            preview_html = _re.sub(
                r'<link[^>]*rel=["\']stylesheet["\'][^>]*href=["\']([^"\'>]+)["\'][^>]*/?>|<link[^>]*href=["\']([^"\'>]+)["\'][^>]*rel=["\']stylesheet["\'][^>]*/?>',
                _inline_css,
                preview_html,
                flags=_re.IGNORECASE
            )
            
            # Inline JS: replace <script src="..."> with <script>...</script>
            def _inline_js(match):
                src = match.group(1)
                basename = src.rsplit('/', 1)[-1] if '/' in src else src
                js_content = js_files.get(src) or js_files.get(basename) or js_files.get('./' + src)
                if js_content:
                    return f'<script>\n{js_content}\n</script>'
                return match.group(0)  # Keep original if not found
            
            preview_html = _re.sub(
                r'<script[^>]*src=["\']([^"\'>]+)["\'][^>]*>\s*</script>',
                _inline_js,
                preview_html,
                flags=_re.IGNORECASE
            )
            
            preview = preview_html
        
        # Determine Status
        status = "Resurrected"
        if fallback_mode or (sandbox_logs and ("Sandbox Error" in sandbox_logs or "BUILD FAILED" in sandbox_logs or "FATAL ERROR" in sandbox_logs)):
            status = "Fallback"
        elif preview.startswith("http"):
            status = "Resurrected"  # Successfully got live URLs
        
        # ═══════════════════════════════════════════════════════════
        # FINAL SAFETY NET: Remove ANY remaining localhost URLs from artifacts
        # This is the last-chance catch for any URLs that slipped through
        # ═══════════════════════════════════════════════════════════
        if preview.startswith("http"):
            # Extract backend URL from preview or BACKEND_URL marker
            _backend_url_final = ""
            _bu_match = re.search(r"\[BACKEND_URL\] (https://[^\s]+)", sandbox_logs or "")
            if _bu_match:
                _backend_url_final = _bu_match.group(1)
            elif preview.startswith("http"):
                # For single-stack, the preview IS the backend
                _backend_url_final = preview.rstrip('/')
            
            if _backend_url_final:
                _localhost_pattern = re.compile(r'https?://(?:localhost|127\.0\.0\.1|0\.0\.0\.0):(?:8000|5000|3001|8080|5001|4000)\b')
                _fix_final_count = 0
                for f in files:
                    fname = f.get('filename', '')
                    if any(fname.endswith(ext) for ext in ['.html', '.js', '.jsx', '.ts', '.tsx', '.vue', '.svelte', '.mjs', '.cjs']):
                        original = f['content']
                        fixed = _localhost_pattern.sub(_backend_url_final, original)
                        if fixed != original:
                            f['content'] = fixed
                            _fix_final_count += 1
                if _fix_final_count > 0:
                    yield {"type": "log", "content": f"🔒 Final safety net: fixed {_fix_final_count} remaining localhost reference(s)"}
        
        # Final Result
        yield {
            "type": "result",
            "data": {
                "logs": "\n".join(logs),
                "artifacts": files,
                "preview": preview,
                "status": status,
                "retry_count": retry_count,
                "errors": all_errors
            }
        }
    
    def _detect_errors(self, sandbox_logs: str) -> tuple:
        """
        Comprehensive error detection for self-healing loop.
        Returns: (error_detected: bool, error_type: str, error_message: str)
        """
        if not sandbox_logs:
            return False, "", ""
        
        # Error patterns to detect with their types
        error_patterns = [
            # ═══════════════════════════════════════════════════════════
            # NODE.JS SPECIFIC ERRORS (CRITICAL FOR AUTO-HEALING)
            # ═══════════════════════════════════════════════════════════
            (r"Cannot find module", "NODE_MODULE_NOT_FOUND"),
            (r"Error: Cannot find module", "NODE_MODULE_NOT_FOUND"),
            (r"MODULE_NOT_FOUND", "NODE_MODULE_NOT_FOUND"),
            (r"node:internal/modules", "NODE_INTERNAL_ERROR"),
            (r"throw err;", "NODE_CRASH"),
            (r"ReferenceError:", "NODE_REFERENCE_ERROR"),
            (r"Error: listen EADDRINUSE", "NODE_PORT_IN_USE"),
            (r"ENOENT: no such file", "NODE_FILE_NOT_FOUND"),
            (r"SyntaxError: Unexpected", "NODE_SYNTAX_ERROR"),
            (r"Error: ENOENT", "NODE_FILE_NOT_FOUND"),
            
            # Server Failures
            (r"BACKEND_CRASH:", "BACKEND_CRASH"),  # Explicit crash marker
            (r"FATAL: Node\.js Backend failed", "NODE_SERVER_CRASH"),
            (r"FATAL: Backend failed", "BACKEND_CRASH"),
            (r"Backend failed to start", "BACKEND_STARTUP_FAILED"),
            (r"No such file or directory", "FILE_NOT_FOUND"),
            (r"can't open file", "FILE_NOT_FOUND"),
            
            # Build Errors
            (r"FRONTEND BUILD FAILED", "FRONTEND_BUILD_ERROR"),
            (r"npm ERR!", "NPM_ERROR"),
            (r"error TS\d+:", "TYPESCRIPT_ERROR"),
            (r"SyntaxError:", "SYNTAX_ERROR"),
            (r"Module not found", "MODULE_NOT_FOUND"),
            
            # Sandbox Errors
            (r"Sandbox Error:", "SANDBOX_ERROR"),
            (r"Command exited with code [^0]", "COMMAND_FAILED"),
            (r"syntax error near unexpected token", "BASH_SYNTAX_ERROR"),
            (r"mkdir.*failed", "MKDIR_ERROR"),
            (r"Permission denied", "PERMISSION_ERROR"),
            
            # Python Errors  
            (r"ModuleNotFoundError:", "PYTHON_IMPORT_ERROR"),
            (r"ImportError:", "PYTHON_IMPORT_ERROR"),
            (r"IndentationError:", "PYTHON_SYNTAX_ERROR"),
            (r"NameError:", "PYTHON_NAME_ERROR"),
            (r"TypeError:", "PYTHON_TYPE_ERROR"),
            (r"FileNotFoundError:", "PYTHON_FILE_NOT_FOUND"),
            
            # Connection Errors
            (r"ECONNREFUSED", "CONNECTION_ERROR"),
            (r"Failed to connect", "CONNECTION_ERROR"),
            (r"Backend connection failed", "BACKEND_ERROR"),
            
            # Generation Errors
            (r"GENERATION FAILED", "GENERATION_ERROR"),
            (r"No files were generated", "EMPTY_GENERATION"),
            
            # MongoDB/Database Errors
            (r"MongoNetworkError", "DATABASE_CONNECTION_ERROR"),
            (r"MongoServerError", "DATABASE_ERROR"),
            (r"ECONNREFUSED.*27017", "MONGODB_CONNECTION_ERROR"),
        ]
        
        for pattern, error_type in error_patterns:
            match = re.search(pattern, sandbox_logs, re.IGNORECASE)
            if match:
                # Extract context around the error
                start = max(0, match.start() - 200)
                end = min(len(sandbox_logs), match.end() + 500)
                error_context = sandbox_logs[start:end]
                return True, error_type, error_context
        
        return False, "", ""
    
    def _build_error_context(self, errors: list) -> str:
        """
        Builds comprehensive error context for AI to understand and fix issues.
        """
        if not errors:
            return ""
        
        context = "\n\n" + "=" * 80 + "\n"
        context += "⚠️ AUTOMATIC ERROR RECOVERY - FIX THE FOLLOWING ISSUES ⚠️\n"
        context += "=" * 80 + "\n\n"
        
        for i, error in enumerate(errors, 1):
            context += f"### Error {i} (Attempt {error['attempt']}) - Type: {error['type']}\n"
            context += f"```\n{error['message'][:1000]}\n```\n\n"
        
        context += """
### COMMON FIXES TO APPLY:

1. **BACKEND_CRASH or "Backend failed to start"**:
   - Check the app.log for the real error (imports, syntax, port conflicts)
   - **CRITICAL**: FastAPI/Uvicorn MUST run on **PORT 8000** (not 5000, 3000, or any other port!)
   - Correct: `uvicorn.run(app, host="0.0.0.0", port=8000)`
   - Correct: `if __name__ == "__main__": uvicorn.run("api:app", host="0.0.0.0", port=8000)`
   - Flask: `app.run(host="0.0.0.0", port=8000)` 
   - The sandbox health check expects port 8000 — any other port will fail!

2. **NODE_INTERNAL_ERROR with 'document is not defined'**: 
   - You generated CLIENT-SIDE JavaScript (browser code) but it's being run as a Node.js server
   - SOLUTION: Create a SEPARATE backend server file (backend/server.js or backend/api.py)
   - Frontend files (HTML/CSS/JS) should be in frontend/ directory
   - The server should serve static files, NOT contain browser code like `document.addEventListener`
   - If migrating Flask → FastAPI, the entrypoint MUST be a Python file, not frontend JavaScript!

3. **TYPESCRIPT ERRORS**: Use `string` not `str`, `number` not `int`, `boolean` not `bool`

4. **MODULE NOT FOUND**: Check import paths, ensure all dependencies in package.json or requirements.txt

5. **SYNTAX ERRORS**: Check for missing brackets, semicolons, proper JSX syntax

6. **BASH/PATH ERRORS**: NO parentheses (), brackets [], spaces in file paths!

7. **BUILD ERRORS**: Ensure next.config.mjs (not .ts), all config files present

8. **PYTHON ERRORS**: Check imports, ensure all packages in requirements.txt

9. **CORS ERRORS**: Backend must have CORS middleware with allow_origins=["*"]

### CRITICAL REMINDERS FOR ARCHITECTURE:
- **Flask → FastAPI migration**: Create backend/main.py or backend/api.py as the server entrypoint
- **PORT REQUIREMENT**: Backend server MUST listen on port 8000 (not 5000, 3000, or any other port!)
- **Node.js full-stack**: Backend server in backend/server.js (port 8000), frontend static files in frontend/
- **Static sites**: Frontend in frontend/, no server needed — use Python SimpleHTTPServer fallback
- Client-side JS goes in frontend/, server-side code in backend/
- Use ONLY alphanumeric, hyphens, underscores in file paths
- Backend must have health check at GET / or GET /health
- layout.tsx MUST import './globals.css'
- globals.css MUST start with @tailwind directives
- next.config.mjs NOT next.config.ts
- All TypeScript files need 'use client' for interactive components

FIX ALL ISSUES AND REGENERATE COMPLETE, WORKING CODE.
"""
        return context


# Singleton
engine = LazarusEngine()

def process_resurrection(repo_url, instructions):
    """Returns generator."""
    return engine.process_resurrection_stream(repo_url, instructions)

def commit_code(repo_url, filename, content):
    return engine.commit_to_github(repo_url, filename, content)

def commit_all_files(repo_url, files):
    """Commits ALL files and creates a PR in one action."""
    return engine.commit_all_files_to_github(repo_url, files)
