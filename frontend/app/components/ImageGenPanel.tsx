'use client';

import { useState, useRef, useEffect, useCallback } from 'react';
import {
  ImagePlus, Sparkles, Send, X, Loader2, Upload,
  Paintbrush, Type, Wand2, RefreshCw, Download,
  Maximize2, Square, RectangleHorizontal, Smartphone,
  MousePointerClick, Replace, Scan, Palette, Eraser,
  ChevronDown, ChevronRight, Check, AlertCircle,
} from 'lucide-react';

type Artifact = { filename: string; content: string };

type ImageRef = {
  type: string;
  src: string;
  alt: string;
  filename: string;
  line: number;
  context: string;
  full_match: string;
  is_placeholder: boolean;
};

type SelectedElement = {
  tag: string;
  text?: string;
  src?: string;
  className?: string;
  id?: string;
  type?: string;
  placeholder?: string;
  href?: string;
  parentTag?: string;
  innerHTML?: string;
} | null;

type GeneratedImage = {
  image_base64: string;
  mime_type: string;
  prompt_used: string;
  model_used?: string;
};

type ImageGenPanelProps = {
  artifacts: Artifact[];
  onUpdateArtifacts: (artifacts: Artifact[]) => void;
  selectedElement: SelectedElement;
  onClearElement: () => void;
  onClose: () => void;
};

const ASPECT_RATIOS = [
  { value: '1:1', label: '1:1', icon: Square, desc: 'Square' },
  { value: '16:9', label: '16:9', icon: RectangleHorizontal, desc: 'Landscape' },
  { value: '9:16', label: '9:16', icon: Smartphone, desc: 'Portrait' },
  { value: '4:3', label: '4:3', icon: Maximize2, desc: 'Standard' },
];

const STYLES = [
  { value: 'auto', label: 'Auto' },
  { value: 'photorealistic', label: 'Photo' },
  { value: 'illustration', label: 'Illustration' },
  { value: 'flat', label: 'Flat Design' },
  { value: '3d', label: '3D Render' },
];

const SUGGESTED_PROMPTS = [
  'Modern tech company logo with gradient colors',
  'Hero banner with abstract geometric shapes',
  'Clean product screenshot placeholder',
  'Team photo placeholder, diverse group in office',
  'Dashboard analytics illustration',
  'Success/celebration illustration',
  'Error/warning illustration',
  'Empty state illustration, searching',
];

// ── Drawing Canvas sub-component ────────────────────────────────
function DrawingCanvas({
  onExport,
  width = 400,
  height = 400,
}: {
  onExport: (dataUrl: string) => void;
  width?: number;
  height?: number;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [isDrawing, setIsDrawing] = useState(false);
  const [brushSize, setBrushSize] = useState(4);
  const [brushColor, setBrushColor] = useState('#ffffff');
  const [tool, setTool] = useState<'brush' | 'eraser'>('brush');
  const lastPos = useRef<{ x: number; y: number } | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.fillStyle = '#1a1a1a';
    ctx.fillRect(0, 0, width, height);
  }, [width, height]);

  const getCanvasPos = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current;
    if (!canvas) return { x: 0, y: 0 };
    const rect = canvas.getBoundingClientRect();
    const scaleX = canvas.width / rect.width;
    const scaleY = canvas.height / rect.height;
    return {
      x: (e.clientX - rect.left) * scaleX,
      y: (e.clientY - rect.top) * scaleY,
    };
  };

  const startDraw = (e: React.MouseEvent<HTMLCanvasElement>) => {
    setIsDrawing(true);
    lastPos.current = getCanvasPos(e);
  };

  const draw = (e: React.MouseEvent<HTMLCanvasElement>) => {
    if (!isDrawing || !canvasRef.current) return;
    const ctx = canvasRef.current.getContext('2d');
    if (!ctx || !lastPos.current) return;

    const pos = getCanvasPos(e);

    ctx.beginPath();
    ctx.moveTo(lastPos.current.x, lastPos.current.y);
    ctx.lineTo(pos.x, pos.y);
    ctx.strokeStyle = tool === 'eraser' ? '#1a1a1a' : brushColor;
    ctx.lineWidth = tool === 'eraser' ? brushSize * 3 : brushSize;
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    ctx.stroke();

    lastPos.current = pos;
  };

  const endDraw = () => {
    setIsDrawing(false);
    lastPos.current = null;
  };

  const clearCanvas = () => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.fillStyle = '#1a1a1a';
    ctx.fillRect(0, 0, width, height);
  };

  const exportCanvas = () => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    onExport(canvas.toDataURL('image/png'));
  };

  const COLORS = ['#ffffff', '#ff4444', '#44ff44', '#4444ff', '#ffff44', '#ff44ff', '#44ffff', '#ff8844', '#c678dd', '#39ff14'];

  return (
    <div className="space-y-2">
      {/* Canvas toolbar */}
      <div className="flex items-center gap-2 flex-wrap">
        <button
          onClick={() => setTool('brush')}
          className={`p-1.5 rounded ${tool === 'brush' ? 'bg-[#c678dd]/30 text-[#c678dd]' : 'text-[#888] hover:text-white'}`}
          title="Brush"
        >
          <Paintbrush className="w-3.5 h-3.5" />
        </button>
        <button
          onClick={() => setTool('eraser')}
          className={`p-1.5 rounded ${tool === 'eraser' ? 'bg-[#c678dd]/30 text-[#c678dd]' : 'text-[#888] hover:text-white'}`}
          title="Eraser"
        >
          <Eraser className="w-3.5 h-3.5" />
        </button>
        <div className="h-4 w-px bg-[#3c3c3c] mx-1" />
        {COLORS.map(c => (
          <button
            key={c}
            onClick={() => { setBrushColor(c); setTool('brush'); }}
            className={`w-4 h-4 rounded-full border-2 transition-transform ${
              brushColor === c && tool === 'brush' ? 'border-white scale-125' : 'border-[#3c3c3c]'
            }`}
            style={{ backgroundColor: c }}
          />
        ))}
        <div className="h-4 w-px bg-[#3c3c3c] mx-1" />
        <input
          type="range" min="1" max="20" value={brushSize}
          onChange={e => setBrushSize(Number(e.target.value))}
          className="w-16 h-1 appearance-none bg-[#3c3c3c] rounded cursor-pointer"
          title={`Size: ${brushSize}`}
        />
        <span className="text-[9px] text-[#888]">{brushSize}px</span>
        <div className="flex-1" />
        <button onClick={clearCanvas} className="text-[10px] text-[#888] hover:text-red-400 px-2 py-1 rounded hover:bg-[#3c3c3c]">
          Clear
        </button>
        <button onClick={exportCanvas} className="text-[10px] text-[#39ff14] hover:text-white px-2 py-1 rounded bg-[#39ff14]/10 hover:bg-[#39ff14]/20">
          Use Drawing
        </button>
      </div>

      {/* Canvas */}
      <canvas
        ref={canvasRef}
        width={width}
        height={height}
        className="border border-[#3c3c3c] rounded-lg cursor-crosshair w-full"
        style={{ aspectRatio: `${width}/${height}`, maxHeight: '250px' }}
        onMouseDown={startDraw}
        onMouseMove={draw}
        onMouseUp={endDraw}
        onMouseLeave={endDraw}
      />
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════
// MAIN COMPONENT
// ══════════════════════════════════════════════════════════════════

export default function ImageGenPanel({
  artifacts,
  onUpdateArtifacts,
  selectedElement,
  onClearElement,
  onClose,
}: ImageGenPanelProps) {
  // ── Core state ────────────────────────────────────────────
  const [activeTab, setActiveTab] = useState<'generate' | 'scan' | 'draw' | 'upload'>('generate');
  const [prompt, setPrompt] = useState('');
  const [aspectRatio, setAspectRatio] = useState('1:1');
  const [style, setStyle] = useState('auto');
  const [usePro, setUsePro] = useState(false);
  const [isGenerating, setIsGenerating] = useState(false);
  const [generatedImage, setGeneratedImage] = useState<GeneratedImage | null>(null);
  const [error, setError] = useState<string | null>(null);

  // ── Scan state ────────────────────────────────────────────
  const [imageRefs, setImageRefs] = useState<ImageRef[]>([]);
  const [isScanning, setIsScanning] = useState(false);
  const [selectedImageRef, setSelectedImageRef] = useState<ImageRef | null>(null);
  const [isSuggesting, setIsSuggesting] = useState(false);

  // ── Upload state ──────────────────────────────────────────
  const [uploadedImage, setUploadedImage] = useState<string | null>(null);
  const [uploadedMime, setUploadedMime] = useState<string>('image/png');
  const fileInputRef = useRef<HTMLInputElement>(null);
  const dropZoneRef = useRef<HTMLDivElement>(null);

  // ── Replace state ─────────────────────────────────────────
  const [replaceTarget, setReplaceTarget] = useState<{filename: string; oldSrc: string} | null>(null);
  const [isReplacing, setIsReplacing] = useState(false);

  // Auto-fill from selected element
  useEffect(() => {
    if (selectedElement?.src) {
      setReplaceTarget(null);
      // Find which artifact contains this src
      for (const art of artifacts) {
        if (art.content.includes(selectedElement.src) ||
            (selectedElement.tag === 'IMG' && art.content.includes(selectedElement.src))) {
          setReplaceTarget({ filename: art.filename, oldSrc: selectedElement.src });
          break;
        }
      }
    }
  }, [selectedElement, artifacts]);

  // ── Auto-suggest prompt from element ──────────────────────
  useEffect(() => {
    if (selectedElement && !prompt) {
      if (selectedElement.tag === 'IMG' || selectedElement.src) {
        setPrompt('');
        autoSuggestPrompt();
      }
    }
  }, [selectedElement]);

  const autoSuggestPrompt = async () => {
    if (!selectedElement) return;
    setIsSuggesting(true);
    try {
      const resp = await fetch('http://localhost:8000/api/suggest-image', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          context: selectedElement.innerHTML || selectedElement.text || '',
          alt: '',
          element_info: {
            tag: selectedElement.tag,
            src: selectedElement.src,
            text: selectedElement.text,
            className: selectedElement.className,
            parentTag: selectedElement.parentTag,
          },
        }),
      });
      const data = await resp.json();
      if (data.suggested_prompt) {
        setPrompt(data.suggested_prompt);
      }
    } catch (e) {
      console.error('Suggest failed:', e);
    } finally {
      setIsSuggesting(false);
    }
  };

  // ── Generate image ────────────────────────────────────────
  const handleGenerate = async () => {
    if (!prompt.trim()) return;
    setIsGenerating(true);
    setError(null);
    setGeneratedImage(null);

    try {
      // Build website context for prompt refinement
      const websiteContext = artifacts.slice(0, 3).map(a => 
        `${a.filename}: ${a.content.substring(0, 300)}`
      ).join('\n');

      const resp = await fetch('http://localhost:8000/api/generate-image', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ 
          prompt, 
          aspect_ratio: aspectRatio, 
          style, 
          use_pro: usePro,
          website_context: websiteContext,
        }),
      });
      const data = await resp.json();

      if (data.success) {
        setGeneratedImage({
          image_base64: data.image_base64,
          mime_type: data.mime_type,
          prompt_used: data.prompt_used,
          model_used: data.model_used,
        });
      } else {
        setError(data.error || 'Failed to generate image');
      }
    } catch (e: any) {
      setError(e.message || 'Network error');
    } finally {
      setIsGenerating(false);
    }
  };

  // ── Scan images in code ───────────────────────────────────
  const handleScan = async () => {
    setIsScanning(true);
    try {
      const resp = await fetch('http://localhost:8000/api/scan-images', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ artifacts }),
      });
      const data = await resp.json();
      setImageRefs(data.images || []);
    } catch (e) {
      console.error('Scan failed:', e);
    } finally {
      setIsScanning(false);
    }
  };

  // ── Replace image in code ─────────────────────────────────
  const handleReplace = async (imageB64: string, imageMime: string) => {
    if (!replaceTarget) return;
    setIsReplacing(true);
    try {
      const resp = await fetch('http://localhost:8000/api/replace-image', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          artifacts,
          target_filename: replaceTarget.filename,
          old_src: replaceTarget.oldSrc,
          image_base64: imageB64,
          image_mime: imageMime,
        }),
      });
      const data = await resp.json();
      if (data.status === 'success' && data.artifacts) {
        onUpdateArtifacts(data.artifacts);
        setReplaceTarget(null);
        onClearElement();
      }
    } catch (e) {
      console.error('Replace failed:', e);
    } finally {
      setIsReplacing(false);
    }
  };

  // ── File upload / drag-n-drop ─────────────────────────────
  const handleFileUpload = (file: File) => {
    if (!file.type.startsWith('image/')) return;
    setUploadedMime(file.type);
    const reader = new FileReader();
    reader.onload = (e) => {
      const dataUrl = e.target?.result as string;
      setUploadedImage(dataUrl);
      // Extract base64 portion
      const b64 = dataUrl.split(',')[1];
      setGeneratedImage({
        image_base64: b64,
        mime_type: file.type,
        prompt_used: `Uploaded: ${file.name}`,
      });
    };
    reader.readAsDataURL(file);
  };

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    const file = e.dataTransfer.files[0];
    if (file) handleFileUpload(file);
  }, []);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
  }, []);

  // ── Drawing export ────────────────────────────────────────
  const handleDrawingExport = (dataUrl: string) => {
    const b64 = dataUrl.split(',')[1];
    setGeneratedImage({
      image_base64: b64,
      mime_type: 'image/png',
      prompt_used: 'Hand-drawn sketch',
    });
    setActiveTab('generate');
  };

  // ── Download generated image ──────────────────────────────
  const handleDownload = () => {
    if (!generatedImage) return;
    const link = document.createElement('a');
    link.href = `data:${generatedImage.mime_type};base64,${generatedImage.image_base64}`;
    link.download = `lazarus-image-${Date.now()}.png`;
    link.click();
  };

  return (
    <div className="bg-[#1e1e1e] flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2 bg-[#252526] border-b border-[#3c3c3c]">
        <div className="flex items-center gap-2">
          <span className="text-lg">🍌</span>
          <span className="text-xs font-bold text-[#e8ab53] tracking-wider">
            NANO BANANA STUDIO
          </span>
          <span className="text-[9px] text-[#555] ml-1">AI Image Generation</span>
        </div>
        <div className="flex items-center gap-1">
          {/* Tab buttons */}
          {([
            { key: 'generate' as const, label: 'Generate', icon: Sparkles },
            { key: 'scan' as const, label: 'Scan Code', icon: Scan },
            { key: 'draw' as const, label: 'Draw', icon: Paintbrush },
            { key: 'upload' as const, label: 'Upload', icon: Upload },
          ] as const).map(({ key, label, icon: Icon }) => (
            <button
              key={key}
              onClick={() => setActiveTab(key)}
              className={`flex items-center gap-1 px-2.5 py-1 rounded text-[10px] transition-colors ${
                activeTab === key
                  ? 'bg-[#e8ab53]/20 text-[#e8ab53] font-semibold'
                  : 'text-[#888] hover:text-white hover:bg-[#3c3c3c]'
              }`}
            >
              <Icon className="w-3 h-3" />
              {label}
            </button>
          ))}
          <div className="h-4 w-px bg-[#3c3c3c] mx-1" />
          <button onClick={onClose} className="p-1 rounded hover:bg-[#3c3c3c] text-[#888] hover:text-white">
            <X className="w-4 h-4" />
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-auto">
        <div className="flex gap-4 p-4">
          {/* ── LEFT COLUMN: Input ───────────────────────────── */}
          <div className="flex-1 space-y-3 min-w-0">
            {/* Selected Element Info */}
            {selectedElement && (selectedElement.tag === 'IMG' || selectedElement.src) && (
              <div className="bg-[#e8ab53]/5 border border-[#e8ab53]/30 rounded-lg p-3">
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <MousePointerClick className="w-3.5 h-3.5 text-[#e8ab53]" />
                    <span className="text-[10px] text-[#e8ab53] uppercase tracking-wider font-semibold">
                      Target Element
                    </span>
                  </div>
                  <button onClick={onClearElement} className="text-[10px] text-[#888] hover:text-[#e8ab53]">
                    Clear
                  </button>
                </div>
                <div className="text-[11px] text-[#ccc] font-mono truncate">
                  &lt;{selectedElement.tag?.toLowerCase()}{selectedElement.src ? ` src="${selectedElement.src.substring(0, 40)}..."` : ''}&gt;
                </div>
                {replaceTarget && (
                  <div className="text-[9px] text-[#39ff14] mt-1">
                    In: {replaceTarget.filename} — Will replace on apply
                  </div>
                )}
              </div>
            )}

            {/* ── GENERATE TAB ─────────────────────────────── */}
            {activeTab === 'generate' && (
              <>
                {/* Prompt input */}
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <label className="text-[10px] text-[#888] uppercase tracking-wider font-semibold">Prompt</label>
                    {selectedElement && (
                      <button
                        onClick={autoSuggestPrompt}
                        disabled={isSuggesting}
                        className="flex items-center gap-1 text-[9px] text-[#e8ab53] hover:text-white"
                      >
                        {isSuggesting ? <Loader2 className="w-3 h-3 animate-spin" /> : <Wand2 className="w-3 h-3" />}
                        Auto-suggest
                      </button>
                    )}
                  </div>
                  <textarea
                    value={prompt}
                    onChange={e => setPrompt(e.target.value)}
                    onKeyDown={e => {
                      if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) handleGenerate();
                    }}
                    placeholder="Describe the image you want to generate..."
                    rows={3}
                    disabled={isGenerating}
                    className="w-full bg-[#1a1a1a] border border-[#333] rounded-lg px-3 py-2 text-sm text-white placeholder-[#555] focus:outline-none focus:border-[#e8ab53]/50 resize-none disabled:opacity-50"
                  />
                </div>

                {/* Style & Aspect Ratio */}
                <div className="flex gap-3">
                  <div className="flex-1">
                    <label className="text-[10px] text-[#888] uppercase tracking-wider font-semibold block mb-1">Style</label>
                    <div className="flex flex-wrap gap-1">
                      {STYLES.map(s => (
                        <button
                          key={s.value}
                          onClick={() => setStyle(s.value)}
                          className={`px-2 py-1 rounded text-[9px] transition-colors ${
                            style === s.value
                              ? 'bg-[#e8ab53]/20 text-[#e8ab53] border border-[#e8ab53]/40'
                              : 'bg-[#1a1a1a] border border-[#333] text-[#888] hover:border-[#e8ab53]/30'
                          }`}
                        >
                          {s.label}
                        </button>
                      ))}
                    </div>
                  </div>
                  <div>
                    <label className="text-[10px] text-[#888] uppercase tracking-wider font-semibold block mb-1">Ratio</label>
                    <div className="flex gap-1">
                      {ASPECT_RATIOS.map(({ value, label, icon: Icon, desc }) => (
                        <button
                          key={value}
                          onClick={() => setAspectRatio(value)}
                          className={`flex flex-col items-center gap-0.5 px-2 py-1 rounded text-[8px] transition-colors ${
                            aspectRatio === value
                              ? 'bg-[#e8ab53]/20 text-[#e8ab53] border border-[#e8ab53]/40'
                              : 'bg-[#1a1a1a] border border-[#333] text-[#888] hover:border-[#e8ab53]/30'
                          }`}
                          title={desc}
                        >
                          <Icon className="w-3 h-3" />
                          {label}
                        </button>
                      ))}
                    </div>
                  </div>
                </div>

                {/* Quick prompts */}
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-[10px] text-[#888] uppercase tracking-wider font-semibold">Quick Ideas</span>
                    {/* Nano Banana Pro toggle */}
                    <button
                      onClick={() => setUsePro(!usePro)}
                      className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[9px] font-semibold transition-all ${
                        usePro
                          ? 'bg-gradient-to-r from-purple-500/20 to-blue-500/20 text-purple-300 border border-purple-500/40'
                          : 'bg-[#1a1a1a] border border-[#333] text-[#888] hover:border-purple-500/30'
                      }`}
                      title={usePro ? "Nano Banana Pro: gemini-3-pro-image-preview (higher quality, thinking)" : "Nano Banana: gemini-2.5-flash-image (fast, efficient)"}
                    >
                      <span className={`w-1.5 h-1.5 rounded-full ${usePro ? 'bg-purple-400' : 'bg-[#555]'}`}></span>
                      {usePro ? '🍌 Pro Model' : '🍌 Fast Model'}
                    </button>
                  </div>
                  <div className="flex flex-wrap gap-1 mt-1">
                    {SUGGESTED_PROMPTS.map((s, i) => (
                      <button
                        key={i}
                        onClick={() => setPrompt(s)}
                        className="px-2 py-0.5 rounded-full text-[9px] bg-[#1a1a1a] border border-[#333] text-[#888] hover:border-[#e8ab53] hover:text-[#e8ab53] transition-colors"
                      >
                        {s.length > 35 ? s.substring(0, 35) + '...' : s}
                      </button>
                    ))}
                  </div>
                </div>

                {/* Generate button */}
                <button
                  onClick={handleGenerate}
                  disabled={!prompt.trim() || isGenerating}
                  className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg text-sm font-bold transition-all
                    bg-gradient-to-r from-[#e8ab53] to-[#f0883e] text-black
                    hover:shadow-[0_0_20px_rgba(232,171,83,0.3)]
                    disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  {isGenerating ? (
                    <><Loader2 className="w-4 h-4 animate-spin" /> Generating with Nano Banana{usePro ? ' Pro' : ''}...</>
                  ) : (
                    <><Sparkles className="w-4 h-4" /> Generate{usePro ? ' (Pro)' : ''}</>
                  )}
                </button>

                {error && (
                  <div className="flex items-center gap-2 p-2 rounded bg-red-500/10 border border-red-500/30 text-red-400 text-[11px]">
                    <AlertCircle className="w-3.5 h-3.5 flex-shrink-0" />
                    {error}
                  </div>
                )}
              </>
            )}

            {/* ── SCAN TAB ─────────────────────────────────── */}
            {activeTab === 'scan' && (
              <div className="space-y-3">
                <button
                  onClick={handleScan}
                  disabled={isScanning || artifacts.length === 0}
                  className="w-full flex items-center justify-center gap-2 px-4 py-2 rounded-lg text-xs font-bold bg-[#007acc] text-white hover:bg-[#0098ff] disabled:opacity-40 transition-all"
                >
                  {isScanning ? (
                    <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Scanning...</>
                  ) : (
                    <><Scan className="w-3.5 h-3.5" /> Scan Code for Images</>
                  )}
                </button>

                {imageRefs.length > 0 && (
                  <div className="space-y-1">
                    <span className="text-[10px] text-[#888]">
                      Found {imageRefs.length} image ref{imageRefs.length !== 1 ? 's' : ''} ({imageRefs.filter(r => r.is_placeholder).length} placeholders)
                    </span>
                    <div className="max-h-44 overflow-auto space-y-1">
                      {imageRefs.map((ref, i) => (
                        <button
                          key={i}
                          onClick={() => {
                            setSelectedImageRef(ref);
                            setReplaceTarget({ filename: ref.filename, oldSrc: ref.src });
                            setActiveTab('generate');
                            // Auto-suggest prompt for this context
                            setPrompt('');
                            fetch('http://localhost:8000/api/suggest-image', {
                              method: 'POST',
                              headers: { 'Content-Type': 'application/json' },
                              body: JSON.stringify({
                                context: ref.context,
                                alt: ref.alt,
                              }),
                            }).then(r => r.json()).then(d => {
                              if (d.suggested_prompt) setPrompt(d.suggested_prompt);
                            }).catch(() => {});
                          }}
                          className={`w-full text-left p-2 rounded-lg border transition-colors ${
                            ref.is_placeholder
                              ? 'border-[#e8ab53]/30 bg-[#e8ab53]/5 hover:border-[#e8ab53]'
                              : 'border-[#333] bg-[#1a1a1a] hover:border-[#007acc]'
                          }`}
                        >
                          <div className="flex items-center gap-2">
                            <ImagePlus className={`w-3.5 h-3.5 flex-shrink-0 ${ref.is_placeholder ? 'text-[#e8ab53]' : 'text-[#888]'}`} />
                            <div className="min-w-0 flex-1">
                              <div className="text-[11px] text-white font-mono truncate">{ref.src || '(empty src)'}</div>
                              <div className="text-[9px] text-[#888] truncate">{ref.filename}:{ref.line} — {ref.type}</div>
                              {ref.alt && <div className="text-[9px] text-[#39ff14]">alt: {ref.alt}</div>}
                            </div>
                            {ref.is_placeholder && (
                              <span className="px-1.5 py-0.5 rounded text-[8px] bg-[#e8ab53]/20 text-[#e8ab53] flex-shrink-0">
                                Placeholder
                              </span>
                            )}
                          </div>
                        </button>
                      ))}
                    </div>
                  </div>
                )}

                {imageRefs.length === 0 && !isScanning && (
                  <div className="text-center py-6 text-[#555]">
                    <Scan className="w-8 h-8 mx-auto mb-2 opacity-30" />
                    <p className="text-[11px]">Click scan to find all &lt;img&gt; tags and image references in your code</p>
                  </div>
                )}
              </div>
            )}

            {/* ── DRAW TAB ─────────────────────────────────── */}
            {activeTab === 'draw' && (
              <div className="space-y-2">
                <p className="text-[10px] text-[#888]">
                  Draw a sketch and use it as reference or directly as an image asset.
                </p>
                <DrawingCanvas onExport={handleDrawingExport} />
              </div>
            )}

            {/* ── UPLOAD TAB ───────────────────────────────── */}
            {activeTab === 'upload' && (
              <div className="space-y-3">
                <div
                  ref={dropZoneRef}
                  onDrop={handleDrop}
                  onDragOver={handleDragOver}
                  onClick={() => fileInputRef.current?.click()}
                  className="border-2 border-dashed border-[#333] rounded-lg p-8 text-center cursor-pointer
                    hover:border-[#e8ab53]/50 hover:bg-[#e8ab53]/5 transition-all"
                >
                  <Upload className="w-8 h-8 text-[#555] mx-auto mb-2" />
                  <p className="text-[11px] text-[#888]">
                    Drag & drop an image here, or click to browse
                  </p>
                  <p className="text-[9px] text-[#555] mt-1">
                    PNG, JPG, SVG, WebP supported
                  </p>
                </div>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept="image/*"
                  onChange={e => {
                    const file = e.target.files?.[0];
                    if (file) handleFileUpload(file);
                  }}
                  className="hidden"
                />
                {uploadedImage && (
                  <div className="bg-[#1a1a1a] border border-[#333] rounded-lg p-3 text-center">
                    <img
                      src={uploadedImage}
                      alt="Uploaded"
                      className="max-h-32 mx-auto rounded"
                    />
                    <p className="text-[9px] text-[#39ff14] mt-2">Image ready to apply</p>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* ── RIGHT COLUMN: Preview & Actions ──────────── */}
          <div className="w-64 flex-shrink-0 space-y-3">
            {/* Generated Image Preview */}
            {generatedImage ? (
              <div className="space-y-2">
                <div className="bg-[#1a1a1a] border border-[#333] rounded-lg overflow-hidden">
                  <div className="flex items-center justify-between px-3 py-1.5 bg-[#252526] border-b border-[#333]">
                    <span className="text-[10px] text-[#888]">Preview</span>
                    <div className="flex gap-1">
                      <button onClick={handleDownload} className="p-1 rounded hover:bg-[#3c3c3c] text-[#888]" title="Download">
                        <Download className="w-3 h-3" />
                      </button>
                      <button onClick={() => setGeneratedImage(null)} className="p-1 rounded hover:bg-[#3c3c3c] text-[#888]" title="Dismiss">
                        <X className="w-3 h-3" />
                      </button>
                    </div>
                  </div>
                  <div className="p-2 flex items-center justify-center bg-checkerboard" style={{
                    backgroundImage: 'linear-gradient(45deg, #1a1a1a 25%, transparent 25%), linear-gradient(-45deg, #1a1a1a 25%, transparent 25%), linear-gradient(45deg, transparent 75%, #1a1a1a 75%), linear-gradient(-45deg, transparent 75%, #1a1a1a 75%)',
                    backgroundSize: '16px 16px',
                    backgroundPosition: '0 0, 0 8px, 8px -8px, -8px 0px',
                  }}>
                    <img
                      src={`data:${generatedImage.mime_type};base64,${generatedImage.image_base64}`}
                      alt="Generated"
                      className="max-w-full max-h-48 rounded"
                    />
                  </div>
                </div>

                <div className="text-[9px] text-[#888]" title={generatedImage.prompt_used}>
                  <span className="text-[#e8ab53]">AI Prompt:</span> {generatedImage.prompt_used.length > 120 ? generatedImage.prompt_used.substring(0, 120) + '...' : generatedImage.prompt_used}
                </div>
                {generatedImage.model_used && (
                  <div className="text-[8px] text-purple-400/70 mt-0.5">
                    🍌 Model: {generatedImage.model_used}
                  </div>
                )}

                {/* Actions */}
                <div className="space-y-1.5">
                  {replaceTarget && (
                    <button
                      onClick={() => handleReplace(generatedImage.image_base64, generatedImage.mime_type)}
                      disabled={isReplacing}
                      className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded-lg text-[11px] font-bold
                        bg-[#39ff14]/10 border border-[#39ff14]/40 text-[#39ff14]
                        hover:bg-[#39ff14]/20 disabled:opacity-40 transition-all"
                    >
                      {isReplacing ? (
                        <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Replacing...</>
                      ) : (
                        <><Replace className="w-3.5 h-3.5" /> Replace in Code</>
                      )}
                    </button>
                  )}

                  <button
                    onClick={handleDownload}
                    className="w-full flex items-center justify-center gap-2 px-3 py-1.5 rounded-lg text-[10px]
                      bg-[#1a1a1a] border border-[#333] text-[#888]
                      hover:border-[#e8ab53] hover:text-[#e8ab53] transition-colors"
                  >
                    <Download className="w-3 h-3" /> Download Image
                  </button>

                  <button
                    onClick={handleGenerate}
                    disabled={isGenerating || !prompt.trim()}
                    className="w-full flex items-center justify-center gap-2 px-3 py-1.5 rounded-lg text-[10px]
                      bg-[#1a1a1a] border border-[#333] text-[#888]
                      hover:border-[#e8ab53] hover:text-[#e8ab53] disabled:opacity-40 transition-colors"
                  >
                    <RefreshCw className="w-3 h-3" /> Regenerate
                  </button>
                </div>
              </div>
            ) : (
              <div className="bg-[#1a1a1a] border border-[#333] rounded-lg p-6 text-center">
                <Palette className="w-10 h-10 text-[#333] mx-auto mb-2" />
                <p className="text-[10px] text-[#555]">
                  Generated image will appear here
                </p>
                <p className="text-[9px] text-[#444] mt-1">
                  {selectedElement?.src
                    ? 'Generate to replace selected element'
                    : 'Enter a prompt and click Generate'}
                </p>
              </div>
            )}

            {/* Quick info */}
            <div className="bg-[#252526] border border-[#333] rounded-lg p-3 space-y-1">
              <h4 className="text-[10px] text-[#e8ab53] font-semibold tracking-wider">HOW TO USE</h4>
              <ul className="text-[9px] text-[#888] space-y-1">
                <li className="flex items-start gap-1.5">
                  <span className="text-[#e8ab53] mt-0.5">1.</span>
                  Click an image element in the preview
                </li>
                <li className="flex items-start gap-1.5">
                  <span className="text-[#e8ab53] mt-0.5">2.</span>
                  Enter a prompt or let AI suggest one
                </li>
                <li className="flex items-start gap-1.5">
                  <span className="text-[#e8ab53] mt-0.5">3.</span>
                  Generate, draw, or upload an image
                </li>
                <li className="flex items-start gap-1.5">
                  <span className="text-[#e8ab53] mt-0.5">4.</span>
                  Click &quot;Replace in Code&quot; to apply
                </li>
              </ul>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
