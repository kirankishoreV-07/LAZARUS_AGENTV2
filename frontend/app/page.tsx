'use client';

import { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import {
  Play, GitPullRequest, CheckCircle, Cpu, ShieldAlert,
  FolderTree, Terminal as TerminalIcon, Eye,
  Loader2, AlertCircle, Search, ArrowRight, Zap,
  BarChart3, Bug, Wand2, ImagePlus,
} from 'lucide-react';
import FileTree, { FileEntry } from './components/FileTree';
import SyntaxHighlighter from './components/SyntaxHighlighter';
import Logo3D from './components/Logo3D';
import AnalysisPanel from './components/AnalysisPanel';
import PlanningPanel from './components/PlanningPanel';
import ReviewPanel from './components/ReviewPanel';
import DebugPanel from './components/DebugPanel';
import EditPanel from './components/EditPanel';
import CheckpointPanel from './components/CheckpointPanel';
import ImageGenPanel from './components/ImageGenPanel';

type Artifact = { filename: string; content: string };

type Phase = 'logo' | 'input' | 'analyzing' | 'analysis' | 'planning' | 'building' | 'results';

// ── Selector script injected into srcDoc preview when in edit mode ────
function injectSelectorScript(html: string): string {
  const script = `
<style>
  .__lz-hover { outline: 2px dashed #c678dd !important; outline-offset: 2px; cursor: crosshair !important; position: relative; }
  .__lz-selected { outline: 3px solid #c678dd !important; outline-offset: 2px; background: rgba(198,120,221,0.08) !important; }
  .__lz-badge { position: fixed; top: 8px; left: 8px; background: #c678dd; color: white; font: bold 10px/1 system-ui; padding: 4px 10px; border-radius: 6px; z-index: 99999; pointer-events: none; }
</style>
<script>
(function() {
  var sel = null;
  document.addEventListener('mouseover', function(e) {
    if (e.target === document.body || e.target === document.documentElement) return;
    e.target.classList.add('__lz-hover');
  }, true);
  document.addEventListener('mouseout', function(e) {
    e.target.classList.remove('__lz-hover');
  }, true);
  document.addEventListener('click', function(e) {
    e.preventDefault();
    e.stopPropagation();
    if (sel) sel.classList.remove('__lz-selected');
    sel = e.target;
    sel.classList.add('__lz-selected');
    var info = {
      tag: sel.tagName || '',
      text: (sel.textContent || '').trim().substring(0, 200),
      src: sel.src || (sel.querySelector && sel.querySelector('img') ? sel.querySelector('img').src : ''),
      className: (sel.className || '').toString().replace(/__lz-\\w+/g, '').trim(),
      id: sel.id || '',
      type: sel.type || '',
      placeholder: sel.placeholder || '',
      href: sel.href || '',
      parentTag: sel.parentElement ? sel.parentElement.tagName : '',
      innerHTML: (sel.innerHTML || '').substring(0, 500)
    };
    window.parent.postMessage({ type: 'lazarus-element-selected', data: info }, '*');
  }, true);
})();
</script>`;
  // Inject right before </head> or </body> or at the end
  if (html.includes('</head>')) {
    return html.replace('</head>', script + '</head>');
  } else if (html.includes('</body>')) {
    return html.replace('</body>', script + '</body>');
  }
  return html + script;
}

// ── Debug Toggle Button (fixed position) ────────────────────────────
function DebugToggleButton({ showDebug, onToggle }: { showDebug: boolean; onToggle: () => void }) {
  if (showDebug) return null; // Hidden when panel is open
  return (
    <button
      onClick={onToggle}
      className="fixed bottom-4 right-4 z-40 flex items-center gap-2 px-3 py-2 rounded-lg text-[11px] font-mono tracking-wider
        bg-[#1a1a1a]/90 border border-[#f0883e]/30 text-[#f0883e] backdrop-blur-sm
        hover:bg-[#f0883e]/10 hover:border-[#f0883e]/60 hover:shadow-[0_0_20px_rgba(240,136,62,0.15)]
        transition-all duration-200 group"
      title="Toggle Debug Developer Logs"
    >
      <Bug className="w-4 h-4 group-hover:animate-pulse" />
      <span className="hidden sm:inline">DEBUG LOGS</span>
    </button>
  );
}

export default function Home() {
  // ── Phase control ──────────────────────────────────────────────
  const [phase, setPhase] = useState<Phase>('logo');

  // ── Core state ─────────────────────────────────────────────────
  const [repoUrl, setRepoUrl] = useState('');
  const [instructions, setInstructions] = useState('');
  const [logs, setLogs] = useState<string[]>([]);
  const [preview, setPreview] = useState('');

  // ── Helper: build self-contained preview from artifacts ────────
  const buildPreviewFromArtifacts = useCallback((arts: Artifact[]): string => {
    // Find main HTML file: index.html > any .html
    const htmlFile = arts.find(a => {
      const bn = a.filename.split('/').pop()?.toLowerCase() || '';
      return bn === 'index.html';
    }) || arts.find(a => {
      const fn = a.filename.toLowerCase();
      return fn.endsWith('.html') || fn.endsWith('.htm');
    });
    if (!htmlFile) return '';

    let html = htmlFile.content;

    // Collect CSS and JS files
    const cssFiles = arts.filter(a => a.filename.toLowerCase().endsWith('.css'));
    const jsFiles = arts.filter(a => a.filename.toLowerCase().endsWith('.js') && !a.filename.toLowerCase().endsWith('.json'));

    // Inline CSS
    for (const css of cssFiles) {
      const basename = (css.filename.split('/').pop() || css.filename).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      const linkRegex = new RegExp(
        `<link[^>]*href=["'](?:[^"']*\\/)?${basename}["'][^>]*/?>`,
        'gi'
      );
      if (linkRegex.test(html)) {
        html = html.replace(linkRegex, `<style>\n${css.content}\n</style>`);
      } else {
        const styleTag = `<style>\n/* ${css.filename.split('/').pop()} */\n${css.content}\n</style>`;
        if (html.includes('</head>')) {
          html = html.replace('</head>', `${styleTag}\n</head>`);
        } else {
          html = styleTag + '\n' + html;
        }
      }
    }

    // Inline JS
    for (const js of jsFiles) {
      const basename = (js.filename.split('/').pop() || js.filename).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      const scriptRegex = new RegExp(
        `<script[^>]*src=["'](?:[^"']*\\/)?${basename}["'][^>]*>\\s*</script>`,
        'gi'
      );
      if (scriptRegex.test(html)) {
        html = html.replace(scriptRegex, `<script>\n${js.content}\n</script>`);
      } else {
        const scriptTag = `<script>\n/* ${js.filename.split('/').pop()} */\n${js.content}\n</script>`;
        if (html.includes('</body>')) {
          html = html.replace('</body>', `${scriptTag}\n</body>`);
        } else {
          html = html + '\n' + scriptTag;
        }
      }
    }

    return html;
  }, []);

  // ── Inject fetch interceptor into any preview HTML ────────
  // Provides a full in-memory mock backend so resurrected apps work in preview.
  // Supports CRUD operations with sample data for a realistic demo experience.
  const injectFetchInterceptor = useCallback((html: string): string => {
    if (!html || html.startsWith('http')) return html; // skip URL-based previews
    
    const fetchInterceptor = `<script>
(function() {
  // ── In-memory mock database with sample data ──
  var _mockDB = {
    posts: [
      { id: "1", title: "Welcome to Our Modernized Blog", author: "Admin", content: "This blog has been resurrected and modernized by the Lazarus Engine. The legacy code has been updated with modern best practices, responsive design, and clean architecture.", created_at: new Date(Date.now() - 86400000*3).toISOString() },
      { id: "2", title: "Getting Started with Modern Web Dev", author: "Dev Team", content: "Our stack now uses modern JavaScript, CSS Grid, Flexbox, and follows accessibility standards. The backend API is clean and RESTful.", created_at: new Date(Date.now() - 86400000*2).toISOString() },
      { id: "3", title: "New Features Coming Soon", author: "Admin", content: "We are working on adding user authentication, rich text editing, image uploads, and comment sections. Stay tuned for updates!", created_at: new Date(Date.now() - 86400000).toISOString() }
    ],
    users: [{ id: "1", name: "Admin", email: "admin@example.com", role: "admin" }],
    comments: [],
    items: [{ id: "1", name: "Sample Item", description: "A sample item", price: 9.99 }],
    _nextId: 100
  };

  function getCollection(path) {
    var parts = path.replace(/^.*\\/api\\//, '').split('/');
    var name = parts[0];
    if (!_mockDB[name]) _mockDB[name] = [];
    return { name: name, items: _mockDB[name], itemId: parts[1] || null };
  }

  var _origFetch = window.fetch;
  window.fetch = function(url, opts) {
    var u = (typeof url === 'string') ? url : (url && url.url) || '';
    opts = opts || {};
    var method = (opts.method || 'GET').toUpperCase();

    // Only intercept /api/ calls
    var isApi = u.startsWith('/api/') || u.startsWith('api/') || (/^https?:\\/\\/localhost/.test(u) && u.includes('/api/'));
    if (!isApi) return _origFetch.apply(this, arguments);

    console.log('[LAZARUS Preview] Mock ' + method + ' ' + u);
    var col = getCollection(u);

    var responseData;
    if (method === 'GET') {
      if (col.itemId) {
        responseData = col.items.find(function(x) { return x.id === col.itemId; }) || null;
        if (!responseData) return Promise.resolve(new Response('{"error":"Not found"}', { status: 404, headers: {'Content-Type':'application/json'} }));
      } else {
        responseData = col.items;
      }
    } else if (method === 'POST') {
      try {
        var body = typeof opts.body === 'string' ? JSON.parse(opts.body) : (opts.body || {});
        body.id = String(++_mockDB._nextId);
        body.created_at = body.created_at || new Date().toISOString();
        col.items.push(body);
        responseData = body;
      } catch(e) { responseData = { error: 'Invalid JSON' }; }
    } else if (method === 'PUT' || method === 'PATCH') {
      var idx = col.items.findIndex(function(x) { return x.id === col.itemId; });
      if (idx >= 0) {
        try {
          var updates = typeof opts.body === 'string' ? JSON.parse(opts.body) : (opts.body || {});
          Object.assign(col.items[idx], updates);
          responseData = col.items[idx];
        } catch(e) { responseData = col.items[idx]; }
      } else { return Promise.resolve(new Response('{"error":"Not found"}', { status: 404, headers: {'Content-Type':'application/json'} })); }
    } else if (method === 'DELETE') {
      var di = col.items.findIndex(function(x) { return x.id === col.itemId; });
      if (di >= 0) { responseData = col.items.splice(di, 1)[0]; }
      else { responseData = { success: true }; }
    } else {
      responseData = [];
    }

    return Promise.resolve(new Response(JSON.stringify(responseData), {
      status: 200, headers: { 'Content-Type': 'application/json' }
    }));
  };

  // Also intercept XMLHttpRequest for older code
  var _origXHROpen = XMLHttpRequest.prototype.open;
  var _origXHRSend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function(method, url) {
    this._lzMethod = method;
    this._lzUrl = (typeof url === 'string') ? url : '';
    var isApi = this._lzUrl.startsWith('/api/') || this._lzUrl.startsWith('api/') || (/^https?:\\/\\/localhost/.test(this._lzUrl) && this._lzUrl.includes('/api/'));
    this._lzMocked = isApi;
    if (!isApi) return _origXHROpen.apply(this, arguments);
    return _origXHROpen.apply(this, arguments);
  };
  XMLHttpRequest.prototype.send = function(body) {
    if (this._lzMocked) {
      var self = this;
      var col = getCollection(self._lzUrl);
      var method = (self._lzMethod || 'GET').toUpperCase();
      var result;
      if (method === 'GET') { result = col.itemId ? (col.items.find(function(x){return x.id===col.itemId}) || {}) : col.items; }
      else if (method === 'POST') { try { var b = JSON.parse(body||'{}'); b.id=String(++_mockDB._nextId); b.created_at=new Date().toISOString(); col.items.push(b); result=b; } catch(e){result={};} }
      else if (method === 'DELETE') { var i=col.items.findIndex(function(x){return x.id===col.itemId}); if(i>=0)col.items.splice(i,1); result={success:true}; }
      else { result = col.items; }
      var json = JSON.stringify(result);
      Object.defineProperty(self, 'status', { value: 200, writable: true });
      Object.defineProperty(self, 'responseText', { value: json, writable: true });
      Object.defineProperty(self, 'response', { value: json, writable: true });
      Object.defineProperty(self, 'readyState', { value: 4, writable: true });
      setTimeout(function() { if(self.onload)self.onload(); if(self.onreadystatechange)self.onreadystatechange(); }, 10);
      return;
    }
    return _origXHRSend.apply(this, arguments);
  };
})();
</script>`;

    if (html.includes('<head>')) {
      return html.replace('<head>', '<head>' + fetchInterceptor);
    } else if (html.includes('<html>')) {
      return html.replace('<html>', '<html><head>' + fetchInterceptor + '</head>');
    }
    return fetchInterceptor + html;
  }, []);

  const [isLoading, setIsLoading] = useState(false);

  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [selectedFile, setSelectedFile] = useState<string | null>(null);

  const [isDeploying, setIsDeploying] = useState(false);
  const [deployStatus, setDeployStatus] = useState<{ status: string; message: string; url?: string } | null>(null);

  const [repoFiles, setRepoFiles] = useState<string[]>([]);
  const [isScanning, setIsScanning] = useState(false);
  const [scanError, setScanError] = useState<string | null>(null);
  const [hasScanned, setHasScanned] = useState(false);

  const [rightTab, setRightTab] = useState<'code' | 'terminal' | 'preview' | 'image-studio'>('code');

  const [fileContentCache, setFileContentCache] = useState<Record<string, string>>({});
  const [isFetchingFile, setIsFetchingFile] = useState(false);
  const fetchedFilesRef = useRef<Set<string>>(new Set());

  // ── Analysis state ─────────────────────────────────────────────
  const [analysisData, setAnalysisData] = useState<any>(null);
  const [analysisLogs, setAnalysisLogs] = useState<string[]>([]);

  // ── Build result state ─────────────────────────────────────────
  const [buildStatus, setBuildStatus] = useState('');
  const [buildRetryCount, setBuildRetryCount] = useState(0);
  const [buildErrors, setBuildErrors] = useState<{ attempt: number; type: string; message: string }[]>([]);
  const [iterationCount, setIterationCount] = useState(0);

  // ── Debug panel state ──────────────────────────────────────────
  const [showDebug, setShowDebug] = useState(false);
  // ── Checkpoint state ───────────────────────────────────────
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [checkpointData, setCheckpointData] = useState<any>(null);
  const [isResuming, setIsResuming] = useState(false);
  const streamReaderRef = useRef<ReadableStreamDefaultReader<Uint8Array> | null>(null);
  const streamDecoderRef = useRef<TextDecoder | null>(null);
  const streamBufferRef = useRef<string>('');

  // ── Edit mode state ────────────────────────────────────────
  const [editMode, setEditMode] = useState(false);
  const [imageGenMode, setImageGenMode] = useState(false);
  const [checkedFiles, setCheckedFiles] = useState<Set<string>>(new Set());
  const [isEditing, setIsEditing] = useState(false);
  const [selectedElement, setSelectedElement] = useState<{
    tag: string; text: string; src?: string; className?: string;
    id?: string; type?: string; placeholder?: string; href?: string;
    parentTag?: string; innerHTML?: string;
  } | null>(null);

  useEffect(() => { document.documentElement.classList.add('dark'); }, []);

  // ── Listen for element selection from preview iframe ────────
  useEffect(() => {
    const handler = (e: MessageEvent) => {
      if (e.data?.type === 'lazarus-element-selected' && editMode) {
        const info = e.data.data;
        setSelectedElement(info);
        // Auto-detect which files contain this element
        const searchText = info.text?.trim();
        const searchId = info.id;
        const searchSrc = info.src;
        if (searchText || searchId || searchSrc) {
          const matchedFiles = new Set<string>(checkedFiles);
          for (const art of artifacts) {
            let matched = false;
            if (searchText && searchText.length > 2 && searchText.length < 200) {
              // Search for the text in the file content
              if (art.content.includes(searchText) ||
                  art.content.includes(searchText.substring(0, 30))) matched = true;
            }
            if (searchId && art.content.includes(`id="${searchId}"`) ||
                art.content.includes(`id='${searchId}'`) ||
                art.content.includes(`id: '${searchId}'`)) matched = true;
            if (searchSrc && art.content.includes(searchSrc)) matched = true;
            // Also match HTML/JS/CSS files that are likely frontend files
            if (matched && !art.filename.endsWith('.py') && !art.filename.endsWith('.ps1')) {
              matchedFiles.add(art.filename);
            }
          }
          if (matchedFiles.size > 0) setCheckedFiles(matchedFiles);
        }
        // Switch to preview tab to show the selection
        setRightTab('preview');
      }
    };
    window.addEventListener('message', handler);
    return () => window.removeEventListener('message', handler);
  }, [editMode, artifacts, checkedFiles]);

  // ── SCAN + ANALYZE (no instructions asked) ─────────────────────
  const scanAndAnalyze = useCallback(async () => {
    if (!repoUrl) return;
    setPhase('analyzing');
    setIsScanning(true);
    setScanError(null);
    setRepoFiles([]);
    setHasScanned(false);
    setArtifacts([]);
    setSelectedFile(null);
    setFileContentCache({});
    fetchedFilesRef.current.clear();
    setAnalysisData(null);
    setAnalysisLogs([]);

    try {
      const response = await fetch(`http://localhost:8000/api/analyze?repo_url=${encodeURIComponent(repoUrl)}`);
      if (!response.ok) throw new Error(`Analysis failed: ${response.statusText}`);

      const reader = response.body?.getReader();
      const decoder = new TextDecoder();
      if (!reader) throw new Error('No stream');

      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        for (let i = 0; i < lines.length - 1; i++) {
          const line = lines[i].trim();
          if (!line) continue;
          try {
            const chunk = JSON.parse(line);
            if (chunk.type === 'log') {
              setAnalysisLogs(prev => [...prev, chunk.content]);
            } else if (chunk.type === 'files') {
              setRepoFiles(chunk.data || []);
              setHasScanned(true);
            } else if (chunk.type === 'analysis') {
              setAnalysisData(chunk.data);
              setPhase('analysis');
            } else if (chunk.type === 'error') {
              setScanError(chunk.content || 'Analysis failed');
              setPhase('input');
            }
          } catch { /* skip bad lines */ }
        }
        buffer = lines[lines.length - 1];
      }
    } catch (e: any) {
      setScanError(e.message || 'Analysis failed');
      setPhase('input');
    } finally {
      setIsScanning(false);
    }
  }, [repoUrl]);

  // ── Stream reading helper (resumable) ───────────────────────────
  const consumeStream = useCallback(async (
    reader: ReadableStreamDefaultReader<Uint8Array>,
    decoder: TextDecoder,
    initialBuffer: string,
  ) => {
    let buffer = initialBuffer;

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      for (let i = 0; i < lines.length - 1; i++) {
        const line = lines[i].trim();
        if (!line) continue;
        try {
          const chunk = JSON.parse(line);
          if (chunk.type === 'session') {
            // Store session ID for checkpoint communication
            setSessionId(chunk.session_id);
          } else if (chunk.type === 'checkpoint') {
            // Pause the stream — save reader state and show checkpoint UI
            setCheckpointData(chunk);
            streamReaderRef.current = reader;
            streamDecoderRef.current = decoder;
            streamBufferRef.current = lines.slice(i + 1).join('\n');
            setLogs(prev => [...prev, `[⏸] Checkpoint: ${chunk.title}`]);
            return; // exit — resumeFromCheckpoint will continue reading
          } else if (chunk.type === 'log') {
            setLogs(prev => [...prev, chunk.content]);
          } else if (chunk.type === 'repo_files') {
            setRepoFiles(chunk.files || []);
            setHasScanned(true);
          } else if (chunk.type === 'result') {
            const res = chunk.data;
            const arts: Artifact[] = res.artifacts || [];
            setArtifacts(arts);
            
            // Build preview: use backend preview if present, else auto-construct
            let previewContent = res.preview || '';
            if (!previewContent && arts.length > 0) {
              previewContent = buildPreviewFromArtifacts(arts);
            }
            setPreview(injectFetchInterceptor(previewContent));
            
            setBuildStatus(res.status || 'Unknown');
            setBuildRetryCount(res.retry_count || 0);
            setBuildErrors(res.errors || []);
            if (arts.length) {
              setSelectedFile(arts[0].filename);
              setRightTab('code');
            }
            if (previewContent) setRightTab('preview');
            setIsLoading(false);
            setIterationCount(prev => prev + 1);
            setPhase('results');
          }
        } catch { /* skip bad JSON lines */ }
      }
      buffer = lines[lines.length - 1];
    }

    // Stream ended — finalize
    setIsLoading(false);
    setCheckpointData(null);
    setSessionId(null);
    streamReaderRef.current = null;
  }, []);

  // ── Resume from checkpoint ─────────────────────────────────────
  const resumeFromCheckpoint = useCallback(async (action: 'continue' | 'modify', feedback: string) => {
    if (!sessionId) return;
    setIsResuming(true);
    setCheckpointData(null);

    try {
      // Signal the backend to continue
      const resp = await fetch('http://localhost:8000/api/resurrect/continue', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId, action, feedback }),
      });
      if (!resp.ok) {
        setLogs(prev => [...prev, `[ERROR] Failed to resume: ${resp.statusText}`]);
        setIsResuming(false);
        return;
      }

      setLogs(prev => [...prev, `[▶] Resumed — ${action === 'modify' ? 'applying feedback...' : 'continuing...'}`]);
      setIsResuming(false);

      // Resume reading from the same stream
      const reader = streamReaderRef.current;
      const decoder = streamDecoderRef.current;
      const buffer = streamBufferRef.current;
      if (reader && decoder) {
        await consumeStream(reader, decoder, buffer);
      }
    } catch (err) {
      setLogs(prev => [...prev, `[ERROR] Resume failed: ${err}`]);
      setIsResuming(false);
    }
  }, [sessionId, consumeStream]);

  // ── START BUILD (called from PlanningPanel) ────────────────────
  const startBuild = useCallback(async (
    selectedDrawbacks: string[],
    selectedRecs: string[],
    userInstructions: string,
  ) => {
    if (!repoUrl) return;

    // Build combined instructions from the planning phase
    const parts: string[] = [];
    if (selectedDrawbacks.length > 0) {
      parts.push(`FIX THESE ISSUES:\n${selectedDrawbacks.map(d => `- ${d}`).join('\n')}`);
    }
    if (selectedRecs.length > 0) {
      parts.push(`APPLY THESE UPGRADES:\n${selectedRecs.map(r => `- ${r}`).join('\n')}`);
    }
    if (userInstructions) {
      parts.push(`SPECIFIC INSTRUCTIONS:\n${userInstructions}`);
    }
    const combinedInstructions = parts.join('\n\n');
    setInstructions(combinedInstructions);

    // Reset checkpoint state
    setSessionId(null);
    setCheckpointData(null);
    setIsResuming(false);
    streamReaderRef.current = null;

    // Start building
    setPhase('building');
    setIsLoading(true);
    setLogs([`[*] Iteration ${iterationCount + 1} — Connecting to Lazarus Engine...`]);
    setArtifacts([]);
    setSelectedFile(null);
    setPreview('');
    setDeployStatus(null);
    setBuildStatus('');
    setBuildRetryCount(0);
    setBuildErrors([]);
    setRightTab('terminal');

    try {
      const response = await fetch('http://localhost:8000/api/resurrect', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ repo_url: repoUrl, vibe_instructions: combinedInstructions }),
      });
      if (!response.ok) throw new Error(`Failed: ${response.statusText}`);

      const reader = response.body?.getReader();
      const decoder = new TextDecoder();
      if (!reader) throw new Error('No stream');

      setLogs([]);
      await consumeStream(reader, decoder, '');

    } catch (error) {
      setLogs(prev => [...prev, `[ERROR] ${error}`]);
      setIsLoading(false);
    }
  }, [repoUrl, iterationCount, consumeStream]);

  // ── REFINE (called from ReviewPanel) ───────────────────────────
  const handleRefine = useCallback((feedback: string) => {
    // Re-run build with the feedback appended
    startBuild([], [], `${instructions}\n\nUSER FEEDBACK FROM PREVIOUS BUILD:\n${feedback}`);
  }, [instructions, startBuild]);

  // ── Checkpoint handlers ────────────────────────────────────────
  const handleCheckpointContinue = useCallback((feedback: string) => {
    resumeFromCheckpoint('continue', feedback);
  }, [resumeFromCheckpoint]);

  const handleCheckpointModify = useCallback((feedback: string) => {
    resumeFromCheckpoint('modify', feedback);
  }, [resumeFromCheckpoint]);

  // ── Edit mode handlers ─────────────────────────────────────────
  const toggleFileCheck = useCallback((path: string) => {
    setCheckedFiles(prev => {
      const next = new Set(prev);
      next.has(path) ? next.delete(path) : next.add(path);
      return next;
    });
  }, []);

  const handleSubmitEdit = useCallback(async (
    files: { filename: string; content: string }[],
    editInstructions: string,
  ) => {
    setIsEditing(true);
    try {
      const response = await fetch('http://localhost:8000/api/edit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          files,
          instructions: editInstructions,
          all_filenames: artifacts.map(a => a.filename),
        }),
      });
      if (!response.ok) throw new Error(`Edit failed: ${response.statusText}`);
      const result = await response.json();

      if (result.status === 'success' && result.files?.length > 0) {
        // Merge edited files back into artifacts
        setArtifacts(prev => {
          const updated = [...prev];
          for (const editedFile of result.files) {
            const idx = updated.findIndex(a => a.filename === editedFile.filename);
            if (idx >= 0) {
              updated[idx] = { filename: editedFile.filename, content: editedFile.content };
            } else {
              // New file added by the edit
              updated.push({ filename: editedFile.filename, content: editedFile.content });
            }
          }
          return updated;
        });
        // Clear selection, select first edited file
        setCheckedFiles(new Set());
        if (result.files.length > 0) {
          setSelectedFile(result.files[0].filename);
          setRightTab('code');
        }
        // Rebuild preview after edit
        setArtifacts(prev => {
          const rebuilt = buildPreviewFromArtifacts(prev);
          if (rebuilt) setPreview(injectFetchInterceptor(rebuilt));
          return prev;
        });
        setLogs(prev => [...prev, `[✏️] AI edited ${result.files.length} file(s) successfully`]);
      } else {
        setLogs(prev => [...prev, `[⚠️] Edit issue: ${result.message || 'Unknown error'}`]);
      }
    } catch (err: any) {
      setLogs(prev => [...prev, `[ERROR] Edit failed: ${err.message}`]);
    } finally {
      setIsEditing(false);
    }
  }, [artifacts]);

  const closeEditMode = useCallback(() => {
    setEditMode(false);
    setImageGenMode(false);
    setCheckedFiles(new Set());
    setSelectedElement(null);
  }, []);

  const closeImageGenMode = useCallback(() => {
    setImageGenMode(false);
    setSelectedElement(null);
    if (rightTab === 'image-studio') setRightTab('preview');
  }, [rightTab]);

  const handleUpdateArtifacts = useCallback((newArtifacts: Artifact[]) => {
    setArtifacts(newArtifacts);
    // Rebuild preview with inlined CSS/JS
    const newPreview = buildPreviewFromArtifacts(newArtifacts);
    if (newPreview) setPreview(injectFetchInterceptor(newPreview));
  }, [buildPreviewFromArtifacts, injectFetchInterceptor]);

  // Get the files that are checked for editing
  const selectedEditFiles = useMemo(() => {
    return artifacts
      .filter(a => checkedFiles.has(a.filename))
      .map(a => ({ filename: a.filename, content: a.content }));
  }, [artifacts, checkedFiles]);
  // ── DEPLOY ─────────────────────────────────────────────────────
  const deployCode = async () => {
    if (artifacts.length === 0 || !repoUrl) return;
    setIsDeploying(true);
    setDeployStatus(null);
    try {
      let lastUrl = '';
      for (const file of artifacts) {
        const response = await fetch('http://localhost:8000/api/commit', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ repo_url: repoUrl, filename: file.filename, content: file.content }),
        });
        const data = await response.json();
        if (data.status !== 'success') throw new Error(`Failed: ${file.filename}`);
        lastUrl = data.commit_url;
      }
      setDeployStatus({ status: 'success', message: 'MIGRATION COMPLETE', url: lastUrl });
    } catch (error: any) {
      setDeployStatus({ status: 'error', message: error.message || 'Deploy failed' });
    } finally {
      setIsDeploying(false);
    }
  };

  // ── Combined file entries ──────────────────────────────────────
  const allFileEntries: FileEntry[] = useMemo(() => {
    const artifactPaths = new Set(artifacts.map(a => a.filename));
    const entries: FileEntry[] = [];
    for (const path of repoFiles) {
      if (!artifactPaths.has(path)) entries.push({ path, isNew: false });
    }
    for (const a of artifacts) {
      entries.push({ path: a.filename, isNew: true, content: a.content });
    }
    return entries;
  }, [repoFiles, artifacts]);

  // ── Fetch content for existing repo files ──────────────────────
  useEffect(() => {
    if (!selectedFile || !repoUrl) return;
    if (artifacts.find(a => a.filename === selectedFile)) return;
    if (fetchedFilesRef.current.has(selectedFile)) return;

    fetchedFilesRef.current.add(selectedFile);
    setIsFetchingFile(true);

    const controller = new AbortController();

    fetch(
      `http://localhost:8000/api/file-content?repo_url=${encodeURIComponent(repoUrl)}&path=${encodeURIComponent(selectedFile)}`,
      { signal: controller.signal }
    )
      .then(resp => {
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        return resp.json();
      })
      .then(data => {
        setFileContentCache(prev => ({
          ...prev,
          [selectedFile]: data.content || `// Empty file: ${selectedFile}`,
        }));
      })
      .catch(e => {
        if (e.name !== 'AbortError') {
          console.error('Failed to fetch file content:', e);
          setFileContentCache(prev => ({
            ...prev,
            [selectedFile]: `// Error loading file: ${selectedFile}\n// ${e.message}`,
          }));
        }
      })
      .finally(() => {
        setIsFetchingFile(false);
      });

    return () => controller.abort();
  }, [selectedFile, repoUrl, artifacts]);

  const displayContent = selectedFile
    ? artifacts.find(a => a.filename === selectedFile)?.content || fileContentCache[selectedFile] || ''
    : '';

  // ══════════════════════════════════════════════════════════════
  // PHASE 1: LOGO ANIMATION
  // ══════════════════════════════════════════════════════════════
  if (phase === 'logo') {
    return (
      <>
        <Logo3D onComplete={() => setPhase('input')} />
        {/* Debug toggle - always available */}
        <DebugToggleButton showDebug={showDebug} onToggle={() => setShowDebug(v => !v)} />
        <DebugPanel isOpen={showDebug} onToggle={() => setShowDebug(false)} />
      </>
    );
  }

  // ══════════════════════════════════════════════════════════════
  // PHASE 2: INPUT — Just repo URL, no instructions
  // ══════════════════════════════════════════════════════════════
  if (phase === 'input') {
    return (
      <div className="h-screen flex flex-col items-center justify-center bg-[#0a0a0a] text-white relative overflow-hidden">
        <div className="absolute inset-0 opacity-5" style={{
          backgroundImage: 'linear-gradient(rgba(57,255,20,0.5) 1px, transparent 1px), linear-gradient(90deg, rgba(57,255,20,0.5) 1px, transparent 1px)',
          backgroundSize: '80px 80px',
        }} />

        <div className="relative z-10 flex flex-col items-center max-w-2xl w-full px-8">
          <div className="mb-10 flex flex-col items-center">
            <div className="flex items-center gap-3 mb-2">
              <Cpu className="w-10 h-10 text-[#39ff14]" />
              <h1 className="text-4xl font-black tracking-[0.2em] text-transparent bg-clip-text bg-gradient-to-r from-[#39ff14] via-[#007acc] to-[#c678dd]">
                LAZARUS
              </h1>
            </div>
            <div className="flex items-center gap-2">
              <div className="h-px w-16 bg-gradient-to-r from-transparent to-[#39ff14]/50" />
              <span className="text-[10px] tracking-[0.4em] text-[#39ff14]/60 uppercase">Resurrection Engine</span>
              <div className="h-px w-16 bg-gradient-to-l from-transparent to-[#39ff14]/50" />
            </div>
          </div>

          <div className="w-full space-y-4">
            <div className="relative">
              <input
                type="text"
                value={repoUrl}
                onChange={e => setRepoUrl(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && scanAndAnalyze()}
                placeholder="Paste your GitHub repository URL..."
                className="w-full bg-[#1a1a1a] border border-[#333] rounded-xl px-5 py-4 text-lg text-white placeholder-[#555] focus:outline-none focus:border-[#39ff14]/50 focus:shadow-[0_0_20px_rgba(57,255,20,0.1)] transition-all"
                autoFocus
              />
              {scanError && (
                <p className="absolute -bottom-6 left-0 text-xs text-red-400 flex items-center gap-1">
                  <AlertCircle className="w-3 h-3" /> {scanError}
                </p>
              )}
            </div>

            <button
              onClick={scanAndAnalyze}
              disabled={!repoUrl || isScanning}
              className="w-full flex items-center justify-center gap-3 px-6 py-4 rounded-xl text-lg font-bold bg-gradient-to-r from-[#39ff14] to-[#22c55e] text-black hover:shadow-[0_0_40px_rgba(57,255,20,0.3)] disabled:opacity-40 disabled:cursor-not-allowed transition-all"
            >
              {isScanning ? (
                <><Loader2 className="w-5 h-5 animate-spin" /> Analyzing...</>
              ) : (
                <><Search className="w-5 h-5" /> Analyze Repository</>
              )}
            </button>

            <p className="text-center text-[11px] text-[#555] mt-2">
              We&apos;ll deeply analyze your project first &mdash; no changes until you decide.
            </p>
          </div>

          <div className="flex gap-4 mt-10">
            {[
              { icon: BarChart3, label: 'Deep Analysis', color: '#007acc' },
              { icon: Zap, label: 'AI-Powered', color: '#39ff14' },
              { icon: ShieldAlert, label: 'You Decide', color: '#ff6b35' },
            ].map(({ icon: Icon, label, color }) => (
              <div key={label} className="flex items-center gap-2 text-[11px] tracking-wider" style={{ color }}>
                <Icon className="w-4 h-4" />
                {label}
              </div>
            ))}
          </div>
        </div>

        {/* Debug toggle */}
        <DebugToggleButton showDebug={showDebug} onToggle={() => setShowDebug(v => !v)} />
        <DebugPanel isOpen={showDebug} onToggle={() => setShowDebug(false)} />
      </div>
    );
  }

  // ══════════════════════════════════════════════════════════════
  // PHASE 3: ANALYZING — Loading with live logs
  // ══════════════════════════════════════════════════════════════
  if (phase === 'analyzing') {
    return (
      <div className="h-screen flex flex-col items-center justify-center bg-[#0a0a0a] text-white relative overflow-hidden">
        <div className="absolute inset-0 opacity-5" style={{
          backgroundImage: 'linear-gradient(rgba(0,122,204,0.5) 1px, transparent 1px), linear-gradient(90deg, rgba(0,122,204,0.5) 1px, transparent 1px)',
          backgroundSize: '60px 60px',
        }} />

        <div className="relative z-10 flex flex-col items-center max-w-xl w-full px-8">
          <div className="relative w-32 h-32 mb-8">
            <div className="absolute inset-0 border-2 border-[#007acc]/30 rounded-full" />
            <div className="absolute inset-3 border-2 border-[#007acc]/20 rounded-full" />
            <div className="absolute inset-6 border-2 border-[#007acc]/10 rounded-full" />
            <div className="absolute inset-0 rounded-full animate-spin" style={{ animationDuration: '3s' }}>
              <div className="w-1/2 h-full origin-right" style={{
                background: 'conic-gradient(from 0deg, transparent, rgba(0,122,204,0.4))',
                borderRadius: '50% 0 0 50%',
              }} />
            </div>
            <div className="absolute inset-0 flex items-center justify-center">
              <BarChart3 className="w-8 h-8 text-[#007acc]" />
            </div>
          </div>

          <h2 className="text-xl font-bold tracking-wider mb-2">DEEP ANALYSIS IN PROGRESS</h2>
          <p className="text-sm text-[#666] mb-6">Scanning repository and detecting tech stack...</p>

          <div className="w-full bg-[#1a1a1a] rounded-lg border border-[#333] p-4 max-h-60 overflow-auto">
            {analysisLogs.map((log, i) => (
              <div key={i} className="flex items-center gap-2 py-1">
                {i === analysisLogs.length - 1 ? (
                  <Loader2 className="w-3 h-3 animate-spin text-[#007acc] flex-shrink-0" />
                ) : (
                  <CheckCircle className="w-3 h-3 text-[#39ff14] flex-shrink-0" />
                )}
                <span className="text-xs text-[#888] font-mono">{log}</span>
              </div>
            ))}
            {analysisLogs.length === 0 && (
              <div className="flex items-center gap-2 py-1">
                <Loader2 className="w-3 h-3 animate-spin text-[#007acc]" />
                <span className="text-xs text-[#888] font-mono">Connecting to analysis engine...</span>
              </div>
            )}
          </div>
        </div>

        {/* Debug toggle */}
        <DebugToggleButton showDebug={showDebug} onToggle={() => setShowDebug(v => !v)} />
        <DebugPanel isOpen={showDebug} onToggle={() => setShowDebug(false)} />
      </div>
    );
  }

  // ══════════════════════════════════════════════════════════════
  // PHASE 4: ANALYSIS — Show deep analysis (user reviews before acting)
  // ══════════════════════════════════════════════════════════════
  if (phase === 'analysis' && analysisData) {
    return (
      <div className="h-screen flex flex-col bg-[#0a0a0a]">
        <div className="flex items-center gap-3 px-5 py-3 bg-[#1a1a1a] border-b border-[#333] flex-shrink-0">
          <Cpu className="w-5 h-5 text-[#39ff14]" />
          <span className="text-[#39ff14] font-bold text-sm tracking-wider">LAZARUS</span>
          <div className="h-4 w-px bg-[#333] mx-2" />
          <span className="text-xs text-[#888] truncate flex-1">{repoUrl}</span>
          <div className="flex items-center gap-2">
            <span className="text-[10px] text-[#39ff14] tracking-wider">{repoFiles.length} FILES</span>
            <span className="text-[10px] text-[#007acc]">ANALYZED</span>
          </div>
        </div>
        <AnalysisPanel
          analysis={analysisData}
          onProceed={() => setPhase('planning')}
        />
        {/* Debug toggle */}
        <DebugToggleButton showDebug={showDebug} onToggle={() => setShowDebug(v => !v)} />
        <DebugPanel isOpen={showDebug} onToggle={() => setShowDebug(false)} />
      </div>
    );
  }

  // ══════════════════════════════════════════════════════════════
  // PHASE 5: PLANNING — User picks what to fix + writes instructions
  // ══════════════════════════════════════════════════════════════
  if (phase === 'planning' && analysisData) {
    const drawbacks = analysisData.recommendations?.drawbacks || [];
    const recs = analysisData.recommendations?.recommendations || [];

    return (
      <div className="h-screen flex flex-col bg-[#0a0a0a]">
        <div className="flex items-center gap-3 px-5 py-3 bg-[#1a1a1a] border-b border-[#333] flex-shrink-0">
          <Cpu className="w-5 h-5 text-[#39ff14]" />
          <span className="text-[#39ff14] font-bold text-sm tracking-wider">LAZARUS</span>
          <div className="h-4 w-px bg-[#333] mx-2" />
          <span className="text-xs text-[#888] truncate flex-1">{repoUrl}</span>
          <span className="text-[10px] text-[#e8ab53] tracking-wider">PLANNING</span>
        </div>
        <PlanningPanel
          drawbacks={drawbacks}
          recommendations={recs}
          onStartBuild={startBuild}
          onBack={() => setPhase('analysis')}
        />
        {/* Debug toggle */}
        <DebugToggleButton showDebug={showDebug} onToggle={() => setShowDebug(v => !v)} />
        <DebugPanel isOpen={showDebug} onToggle={() => setShowDebug(false)} />
      </div>
    );
  }

  // ══════════════════════════════════════════════════════════════
  // PHASE 6 & 7: BUILDING / RESULTS — VS Code Layout
  // ══════════════════════════════════════════════════════════════
  return (
    <div className="h-screen flex flex-col bg-[#1e1e1e] text-[#cccccc] font-mono overflow-hidden">

      {/* ═══ TOP BAR ═══════════════════════════════════════════════ */}
      <div className="flex items-center gap-3 px-4 py-2 bg-[#323233] border-b border-[#3c3c3c] flex-shrink-0">
        <div className="flex items-center gap-2 mr-4 cursor-pointer" onClick={() => setPhase('input')}>
          <Cpu className="w-5 h-5 text-[#39ff14]" />
          <span className="text-[#39ff14] font-bold text-sm tracking-wider">LAZARUS</span>
        </div>

        <div className="flex-1 flex items-center gap-2 max-w-xl">
          <input
            type="text"
            value={repoUrl}
            onChange={e => setRepoUrl(e.target.value)}
            placeholder="GitHub repo URL..."
            className="flex-1 bg-[#3c3c3c] border border-[#555] rounded px-3 py-1.5 text-sm text-white placeholder-[#888] focus:outline-none focus:border-[#007acc] transition-colors"
          />
          {analysisData && (
            <button
              onClick={() => setPhase('analysis')}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded text-[10px] font-medium border border-[#007acc] text-[#007acc] hover:bg-[#007acc]/10 transition-colors"
            >
              <BarChart3 className="w-3 h-3" />
              Analysis
            </button>
          )}
          {analysisData && (
            <button
              onClick={() => setPhase('planning')}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded text-[10px] font-medium border border-[#e8ab53] text-[#e8ab53] hover:bg-[#e8ab53]/10 transition-colors"
            >
              <Zap className="w-3 h-3" />
              Plan
            </button>
          )}
        </div>

        {iterationCount > 0 && (
          <span className="text-[9px] text-[#c678dd] tracking-wider border border-[#c678dd]/30 px-2 py-1 rounded">
            Iteration {iterationCount}
          </span>
        )}

        <button
          onClick={deployCode}
          disabled={isDeploying || artifacts.length === 0}
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded text-sm font-medium border transition-all
            ${deployStatus?.status === 'success'
              ? 'border-green-500 text-green-400 bg-green-500/10'
              : 'border-[#555] text-[#ccc] hover:bg-[#3c3c3c] disabled:opacity-30 disabled:cursor-not-allowed'}
          `}
        >
          {deployStatus?.status === 'success' ? <CheckCircle className="w-3.5 h-3.5" /> : <GitPullRequest className="w-3.5 h-3.5" />}
          {deployStatus?.status === 'success' ? 'Done' : 'Deploy'}
        </button>

        {deployStatus?.url && (
          <a href={deployStatus.url} target="_blank" className="text-[10px] text-[#007acc] underline">PR</a>
        )}

        <div className="flex items-center gap-2 ml-auto text-[10px]">
          {hasScanned && <span className="text-[#73c991]">{repoFiles.length} files</span>}
          {isLoading && <Loader2 className="w-3 h-3 animate-spin text-[#39ff14]" />}
          <span className="text-[#39ff14]">ONLINE</span>
        </div>
      </div>

      {/* ═══ MAIN AREA ═══════════════════════════════════════════ */}
      <div className="flex flex-1 overflow-hidden">

        {/* ── LEFT: FILE TREE ──────────────────────────────────── */}
        <div className="w-64 flex-shrink-0 border-r border-[#3c3c3c] flex flex-col bg-[#252526]">
          <FileTree
            files={allFileEntries}
            selectedFile={selectedFile}
            onSelectFile={(path) => { setSelectedFile(path); setRightTab('code'); }}
            multiSelect={editMode}
            checkedFiles={checkedFiles}
            onToggleCheck={toggleFileCheck}
          />
          {/* Edit mode toggle — only in results phase */}
          {phase === 'results' && artifacts.length > 0 && (
            <div className="border-t border-[#3c3c3c] p-2 space-y-1.5">
              <button
                onClick={() => {
                  if (editMode) {
                    closeEditMode();
                  } else {
                    setEditMode(true);
                    setImageGenMode(false);
                    setRightTab('preview'); // Show preview for visual element selection
                    setSelectedElement(null);
                  }
                }}
                className={`w-full flex items-center justify-center gap-2 px-3 py-2 rounded-lg text-[11px] font-bold tracking-wider transition-all ${
                  editMode
                    ? 'bg-[#c678dd]/20 text-[#c678dd] border border-[#c678dd]/40'
                    : 'bg-[#252526] text-[#888] border border-[#3c3c3c] hover:border-[#c678dd]/40 hover:text-[#c678dd]'
                }`}
              >
                <Wand2 className="w-3.5 h-3.5" />
                {editMode ? 'EXIT EDIT MODE' : 'EDIT WITH AI'}
              </button>
              {editMode && checkedFiles.size > 0 && (
                <p className="text-[9px] text-[#c678dd]/60 text-center mt-1">
                  Select files &amp; describe changes below
                </p>
              )}
              <button
                onClick={() => {
                  if (imageGenMode) {
                    closeImageGenMode();
                  } else {
                    setImageGenMode(true);
                    setEditMode(true);
                    setRightTab('image-studio');
                  }
                }}
                className={`w-full flex items-center justify-center gap-2 px-3 py-2 rounded-lg text-[11px] font-bold tracking-wider transition-all ${
                  imageGenMode
                    ? 'bg-[#e8ab53]/20 text-[#e8ab53] border border-[#e8ab53]/40'
                    : 'bg-[#252526] text-[#888] border border-[#3c3c3c] hover:border-[#e8ab53]/40 hover:text-[#e8ab53]'
                }`}
              >
                <ImagePlus className="w-3.5 h-3.5" />
                {imageGenMode ? 'EXIT STUDIO' : '🍌 NANO BANANA STUDIO'}
              </button>
            </div>
          )}
        </div>

        {/* ── RIGHT: CODE / TERMINAL / PREVIEW / CHECKPOINT ───── */}
        <div className="flex-1 flex flex-col overflow-hidden">

          {/* Checkpoint panel — takes over the right side when active */}
          {checkpointData && phase === 'building' ? (
            <CheckpointPanel
              checkpoint={checkpointData}
              onContinue={handleCheckpointContinue}
              onModify={handleCheckpointModify}
              isResuming={isResuming}
            />
          ) : (
          <>
          {/* Tab bar */}
          <div className="flex items-center bg-[#252526] border-b border-[#3c3c3c] flex-shrink-0">
            {([
              { key: 'code', label: selectedFile ? selectedFile.split('/').pop()! : 'Code', icon: null as any },
              { key: 'terminal', label: 'Terminal', icon: TerminalIcon },
              { key: 'preview', label: 'Preview', icon: Eye },
              ...(phase === 'results' ? [{ key: 'image-studio', label: '🍌 Nano Banana', icon: ImagePlus }] : []),
            ] as { key: 'code' | 'terminal' | 'preview' | 'image-studio'; label: string; icon: any }[]).map(({ key, label, icon: Icon }) => (
              <button
                key={key}
                onClick={() => {
                  setRightTab(key);
                  if (key === 'image-studio') {
                    setImageGenMode(true);
                    setEditMode(true);
                  }
                }}
                className={`flex items-center gap-1.5 px-4 py-2 text-[12px] border-r border-[#3c3c3c] transition-colors
                  ${rightTab === key
                    ? key === 'image-studio'
                      ? 'bg-[#1e1e1e] text-[#e8ab53] border-b-2 border-b-[#e8ab53]'
                      : 'bg-[#1e1e1e] text-white border-b-2 border-b-[#007acc]'
                    : key === 'image-studio'
                      ? 'bg-[#2d2d2d] text-[#e8ab53]/60 hover:text-[#e8ab53]'
                      : 'bg-[#2d2d2d] text-[#888] hover:text-[#ccc]'}
                `}
              >
                {Icon && <Icon className="w-3.5 h-3.5" />}
                <span className="truncate max-w-[150px]">{label}</span>
                {key === 'code' && selectedFile && artifacts.find(a => a.filename === selectedFile) && (
                  <span className="w-2 h-2 rounded-full bg-[#e8ab53] ml-1" title="Modified" />
                )}
                {key === 'code' && selectedFile && isFetchingFile && (
                  <Loader2 className="w-3 h-3 animate-spin text-[#007acc] ml-1" />
                )}
                {key === 'terminal' && isLoading && (
                  <Loader2 className="w-3 h-3 animate-spin text-[#39ff14] ml-1" />
                )}
                {key === 'image-studio' && (
                  <span className="w-2 h-2 rounded-full bg-[#e8ab53] ml-1 animate-pulse" />
                )}
              </button>
            ))}

            {rightTab === 'code' && selectedFile && (
              <span className="ml-3 text-[11px] text-[#888] truncate">{selectedFile}</span>
            )}
          </div>

          {/* Tab content */}
          <div className="flex-1 overflow-auto bg-[#1e1e1e]">

            {/* CODE VIEW */}
            {rightTab === 'code' && (
              isFetchingFile ? (
                <div className="flex flex-col items-center justify-center h-full text-[#6b6b6b]">
                  <Loader2 className="w-8 h-8 animate-spin text-[#007acc] mb-3" />
                  <p className="text-sm">Loading {selectedFile?.split('/').pop()}...</p>
                </div>
              ) : displayContent ? (
                <SyntaxHighlighter code={displayContent} filename={selectedFile || 'file.txt'} />
              ) : (
                <div className="flex flex-col items-center justify-center h-full text-[#6b6b6b]">
                  {hasScanned ? (
                    <>
                      <FolderTree className="w-12 h-12 mb-3 opacity-30" />
                      <p className="text-sm">Select a file from the explorer</p>
                    </>
                  ) : (
                    <>
                      <Cpu className="w-16 h-16 mb-4 opacity-20" />
                      <p className="text-sm text-[#39ff14]/50">Waiting for build...</p>
                    </>
                  )}
                </div>
              )
            )}

            {/* TERMINAL VIEW */}
            {rightTab === 'terminal' && (
              <div className="p-4 font-mono text-sm space-y-2">
                {logs.length === 0 ? (
                  <div className="flex items-center justify-center h-full text-[#6b6b6b]">
                    <span>{isLoading ? 'Processing...' : 'No output yet.'}</span>
                  </div>
                ) : (
                  logs.map((log, i) => (
                    <div key={i} className="flex items-start gap-3">
                      <span className="flex-shrink-0 mt-0.5">
                        {i === logs.length - 1 && isLoading ? (
                          <Loader2 className="w-4 h-4 animate-spin text-[#39ff14]" />
                        ) : (
                          <CheckCircle className="w-4 h-4 text-[#39ff14]" />
                        )}
                      </span>
                      <span className="text-[#d4d4d4]">{log}</span>
                    </div>
                  ))
                )}
              </div>
            )}

            {/* PREVIEW VIEW */}
            {rightTab === 'preview' && (
              preview ? (
                preview.startsWith('http') ? (
                  <>
                    <iframe src={preview} className="w-full h-full border-none bg-white" title="Preview" key={preview} />
                    {editMode && (
                      <div className="absolute bottom-2 left-1/2 -translate-x-1/2 bg-[#252526]/95 backdrop-blur-sm border border-[#c678dd]/40 rounded-lg px-4 py-2 text-[11px] text-[#c678dd] flex items-center gap-2 z-10">
                        <Wand2 className="w-3.5 h-3.5" />
                        Live preview — select files from the tree and describe changes below
                      </div>
                    )}
                  </>
                ) : (
                  <>
                    <iframe
                      srcDoc={editMode ? injectSelectorScript(preview) : preview}
                      className="w-full h-full border-none bg-white"
                      title="Preview"
                      key={editMode ? 'edit' : 'view'}
                    />
                    {editMode && (
                      <div className="absolute top-2 right-2 bg-[#c678dd]/90 backdrop-blur-sm rounded-lg px-3 py-1.5 text-[10px] text-white font-bold tracking-wider flex items-center gap-1.5 z-10 pointer-events-none">
                        {imageGenMode ? (
                          <><ImagePlus className="w-3 h-3" /> CLICK IMAGE ELEMENTS TO REPLACE</>
                        ) : (
                          <><Wand2 className="w-3 h-3" /> CLICK ANY ELEMENT TO SELECT</>
                        )}
                      </div>
                    )}
                  </>
                )
              ) : (
                <div className="flex items-center justify-center h-full text-[#6b6b6b]">
                  No preview available
                </div>
              )
            )}

            {/* IMAGE STUDIO VIEW */}
            {rightTab === 'image-studio' && phase === 'results' && (
              <div className="h-full overflow-auto">
                <ImageGenPanel
                  artifacts={artifacts}
                  onUpdateArtifacts={handleUpdateArtifacts}
                  selectedElement={selectedElement}
                  onClearElement={() => setSelectedElement(null)}
                  onClose={() => { closeImageGenMode(); setRightTab('preview'); }}
                />
              </div>
            )}
          </div>

          {/* ── Review Panel (only shown when results phase) ────── */}
          {phase === 'results' && !isLoading && !editMode && (
            <ReviewPanel
              artifactCount={artifacts.length}
              status={buildStatus}
              retryCount={buildRetryCount}
              errors={buildErrors}
              onRefine={handleRefine}
              onDeploy={deployCode}
              isDeploying={isDeploying}
              deployStatus={deployStatus}
            />
          )}

          {/* ── Edit Panel (shown in edit mode) ────── */}
          {phase === 'results' && editMode && !imageGenMode && (
            <EditPanel
              selectedFiles={selectedEditFiles}
              onRemoveFile={(fn) => {
                setCheckedFiles(prev => {
                  const next = new Set(prev);
                  next.delete(fn);
                  return next;
                });
              }}
              onSubmitEdit={handleSubmitEdit}
              onClose={closeEditMode}
              isEditing={isEditing}
              selectedElement={selectedElement}
              onClearElement={() => setSelectedElement(null)}
            />
          )}

          {/* Image Gen Panel is now rendered as a right tab (image-studio) */}
          </>
          )}

          {/* Bottom status bar */}
          <div className="flex items-center justify-between px-4 py-1 bg-[#007acc] text-white text-[11px] flex-shrink-0">
            <div className="flex items-center gap-3">
              <span>LAZARUS ENGINE</span>
              {hasScanned && <span>{repoFiles.length} files</span>}
              {artifacts.length > 0 && <span>{artifacts.length} modified</span>}
              {iterationCount > 0 && <span>Iteration {iterationCount}</span>}
            </div>
            <div className="flex items-center gap-3">
              {isLoading && <span className="flex items-center gap-1"><Loader2 className="w-3 h-3 animate-spin" /> Building...</span>}
              {isEditing && <span className="flex items-center gap-1"><Loader2 className="w-3 h-3 animate-spin" /> Editing...</span>}
              <span>
                {checkpointData ? `CHECKPOINT: ${checkpointData.title}` : imageGenMode ? 'IMAGE STUDIO — Click elements to target' : editMode ? `EDIT MODE — ${checkedFiles.size} file(s) selected` : phase === 'building' ? 'BUILDING...' : phase === 'results' ? 'REVIEW & REFINE' : ''}
              </span>
              <span>v11.0</span>
            </div>
          </div>
        </div>
      </div>

      {/* Debug toggle */}
      <DebugToggleButton showDebug={showDebug} onToggle={() => setShowDebug(v => !v)} />
      <DebugPanel isOpen={showDebug} onToggle={() => setShowDebug(false)} />
    </div>
  );
}
