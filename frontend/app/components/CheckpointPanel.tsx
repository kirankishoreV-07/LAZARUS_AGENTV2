'use client';

import { useState } from 'react';
import {
  Play, Pause, MessageSquare, Eye, FileCode, CheckCircle,
  ArrowRight, Loader2, AlertCircle, Zap, ExternalLink,
} from 'lucide-react';

type CheckpointData = {
  id: string;
  title: string;
  description: string;
  session_id: string;
  data: Record<string, any>;
};

type CheckpointPanelProps = {
  checkpoint: CheckpointData;
  onContinue: (feedback: string) => void;
  onModify: (feedback: string) => void;
  isResuming: boolean;
};

// ── Quick suggestion chips for each checkpoint type
const SUGGESTIONS: Record<string, string[]> = {
  post_plan: [
    "Looks good, proceed with code generation",
    "Focus more on security improvements",
    "Keep the UI minimal and clean",
    "Add more API endpoints for CRUD operations",
    "Use a modern dark theme design",
    "Ensure mobile responsive layout",
  ],
  post_codegen: [
    "Code looks good, deploy it",
    "Add more error handling",
    "Improve the UI/UX design",
    "Add loading states and animations",
    "Add input validation",
    "Include a navbar and footer",
  ],
  post_sandbox: [
    "Looks great, finalize it!",
    "Fix the layout — needs better spacing",
    "The API isn't connecting properly",
    "Add more sample/mock data",
    "Improve the color scheme",
    "The forms need better validation",
  ],
};

export default function CheckpointPanel({ checkpoint, onContinue, onModify, isResuming }: CheckpointPanelProps) {
  const [feedback, setFeedback] = useState('');
  const [showFeedback, setShowFeedback] = useState(false);

  const suggestions = SUGGESTIONS[checkpoint.id] || SUGGESTIONS.post_plan;

  const handleContinue = () => {
    onContinue(feedback);
  };

  const handleModify = () => {
    if (!feedback.trim()) {
      setShowFeedback(true);
      return;
    }
    onModify(feedback);
  };

  // ── Render checkpoint-specific content
  const renderCheckpointContent = () => {
    switch (checkpoint.id) {
      case 'post_plan':
        return <PlanCheckpoint data={checkpoint.data} />;
      case 'post_codegen':
        return <CodegenCheckpoint data={checkpoint.data} />;
      case 'post_sandbox':
        return <SandboxCheckpoint data={checkpoint.data} />;
      default:
        return null;
    }
  };

  if (isResuming) {
    return (
      <div className="h-full flex items-center justify-center bg-[#0a0a0a]">
        <div className="flex flex-col items-center gap-4">
          <Loader2 className="w-10 h-10 animate-spin text-[#39ff14]" />
          <p className="text-sm text-[#888]">Applying your feedback and resuming...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col bg-[#0a0a0a] overflow-auto">
      {/* Header */}
      <div className="flex items-center gap-3 px-6 py-4 bg-[#1a1a1a] border-b border-[#333] flex-shrink-0">
        <div className="w-10 h-10 rounded-full bg-[#e8ab53]/10 border border-[#e8ab53]/30 flex items-center justify-center">
          <Pause className="w-5 h-5 text-[#e8ab53]" />
        </div>
        <div>
          <h2 className="text-lg font-bold text-white">{checkpoint.title}</h2>
          <p className="text-xs text-[#888]">{checkpoint.description}</p>
        </div>
        <div className="ml-auto">
          <span className="text-[10px] tracking-wider text-[#e8ab53] border border-[#e8ab53]/30 px-2 py-1 rounded bg-[#e8ab53]/5">
            CHECKPOINT
          </span>
        </div>
      </div>

      {/* Checkpoint-specific content */}
      <div className="flex-1 overflow-auto px-6 py-4">
        {renderCheckpointContent()}

        {/* Feedback section */}
        <div className="mt-6 space-y-3">
          {!showFeedback ? (
            <button
              onClick={() => setShowFeedback(true)}
              className="flex items-center gap-2 text-sm text-[#007acc] hover:text-[#3399dd] transition-colors"
            >
              <MessageSquare className="w-4 h-4" />
              Have feedback or specific instructions?
            </button>
          ) : (
            <div className="space-y-3">
              <label className="text-sm text-[#ccc] font-medium">Your feedback / instructions:</label>
              
              {/* Quick suggestion chips */}
              <div className="flex flex-wrap gap-2">
                {suggestions.map((s, i) => (
                  <button
                    key={i}
                    onClick={() => setFeedback(prev => prev ? `${prev}. ${s}` : s)}
                    className="text-[11px] px-3 py-1.5 rounded-full border border-[#333] text-[#888] hover:text-white hover:border-[#007acc] hover:bg-[#007acc]/10 transition-all"
                  >
                    {s}
                  </button>
                ))}
              </div>

              <textarea
                value={feedback}
                onChange={e => setFeedback(e.target.value)}
                placeholder="Describe what you'd like changed or improved..."
                className="w-full h-28 bg-[#1a1a1a] border border-[#333] rounded-lg px-4 py-3 text-sm text-white placeholder-[#555] focus:outline-none focus:border-[#007acc] resize-none"
                autoFocus
              />
            </div>
          )}
        </div>
      </div>

      {/* Action buttons */}
      <div className="flex items-center gap-3 px-6 py-4 bg-[#1a1a1a] border-t border-[#333] flex-shrink-0">
        {feedback.trim() && (
          <button
            onClick={handleModify}
            className="flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-medium bg-[#007acc] text-white hover:bg-[#0088e0] transition-colors"
          >
            <Zap className="w-4 h-4" />
            Apply Changes & Continue
          </button>
        )}
        <button
          onClick={handleContinue}
          className={`flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-medium transition-colors ${
            feedback.trim()
              ? 'border border-[#39ff14]/30 text-[#39ff14] hover:bg-[#39ff14]/10'
              : 'bg-gradient-to-r from-[#39ff14] to-[#22c55e] text-black hover:shadow-[0_0_20px_rgba(57,255,20,0.2)]'
          }`}
        >
          <Play className="w-4 h-4" />
          {feedback.trim() ? 'Skip & Continue' : 'Looks Good — Continue'}
          <ArrowRight className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
}

// ════════════════════════════════════════════════════════════════
// CHECKPOINT-SPECIFIC SUB-COMPONENTS
// ════════════════════════════════════════════════════════════════

function PlanCheckpoint({ data }: { data: Record<string, any> }) {
  const plan = data.plan || '';
  const techStack = data.tech_stack || {};
  const filesAnalyzed = data.files_analyzed || 0;
  const mustPreserve = data.must_preserve || [];

  return (
    <div className="space-y-4">
      {/* Stats row */}
      <div className="grid grid-cols-3 gap-3">
        <StatCard label="Files Analyzed" value={filesAnalyzed} color="#007acc" />
        <StatCard label="Must Preserve" value={mustPreserve.length} color="#ff6b35" />
        <StatCard
          label="Backend"
          value={techStack?.backend?.framework || 'Unknown'}
          color="#39ff14"
          isText
        />
      </div>

      {/* Plan content */}
      <div className="bg-[#1a1a1a] border border-[#333] rounded-lg">
        <div className="flex items-center gap-2 px-4 py-2 border-b border-[#333]">
          <FileCode className="w-4 h-4 text-[#e8ab53]" />
          <span className="text-xs text-[#888] font-medium tracking-wider">MODERNIZATION PLAN</span>
        </div>
        <pre className="p-4 text-xs text-[#ccc] font-mono whitespace-pre-wrap max-h-[400px] overflow-auto leading-relaxed">
          {plan || 'No plan available'}
        </pre>
      </div>

      {/* Preserved items */}
      {mustPreserve.length > 0 && (
        <div className="bg-[#1a1a1a] border border-[#333] rounded-lg p-4">
          <h3 className="text-xs text-[#ff6b35] font-medium tracking-wider mb-2">🔒 ITEMS TO PRESERVE</h3>
          <div className="flex flex-wrap gap-2">
            {mustPreserve.map((item: string, i: number) => (
              <span key={i} className="text-[10px] px-2 py-1 bg-[#ff6b35]/10 border border-[#ff6b35]/20 rounded text-[#ff6b35]">
                {item}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function CodegenCheckpoint({ data }: { data: Record<string, any> }) {
  const files = data.files || [];
  const fileCount = data.file_count || 0;
  const runtime = data.runtime || 'unknown';
  const entrypoint = data.entrypoint || '';
  const [expandedFile, setExpandedFile] = useState<number | null>(null);

  return (
    <div className="space-y-4">
      {/* Stats */}
      <div className="grid grid-cols-3 gap-3">
        <StatCard label="Files Generated" value={fileCount} color="#39ff14" />
        <StatCard label="Runtime" value={runtime.toUpperCase()} color="#007acc" isText />
        <StatCard label="Entrypoint" value={entrypoint.split('/').pop() || ''} color="#c678dd" isText />
      </div>

      {/* File list with previews */}
      <div className="bg-[#1a1a1a] border border-[#333] rounded-lg">
        <div className="flex items-center gap-2 px-4 py-2 border-b border-[#333]">
          <FileCode className="w-4 h-4 text-[#39ff14]" />
          <span className="text-xs text-[#888] font-medium tracking-wider">GENERATED FILES</span>
          <span className="text-[10px] text-[#39ff14] ml-auto">{fileCount} files</span>
        </div>
        <div className="max-h-[500px] overflow-auto">
          {files.map((file: any, i: number) => (
            <div key={i} className="border-b border-[#333] last:border-b-0">
              <button
                onClick={() => setExpandedFile(expandedFile === i ? null : i)}
                className="w-full flex items-center gap-2 px-4 py-2 text-xs text-[#ccc] hover:bg-[#252526] transition-colors text-left"
              >
                <FileCode className="w-3 h-3 text-[#007acc] flex-shrink-0" />
                <span className="flex-1 font-mono">{file.filename}</span>
                <span className="text-[10px] text-[#555]">{file.preview?.length || 0} chars</span>
              </button>
              {expandedFile === i && file.preview && (
                <pre className="px-4 py-2 text-[10px] text-[#888] font-mono bg-[#0d0d0d] border-t border-[#333] max-h-48 overflow-auto whitespace-pre-wrap">
                  {file.preview}
                  {file.preview.length >= 500 && (
                    <span className="text-[#555]">... (truncated)</span>
                  )}
                </pre>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function SandboxCheckpoint({ data }: { data: Record<string, any> }) {
  const previewUrl = data.preview_url || '';
  const backendUrl = data.backend_url || '';
  const fileCount = data.file_count || 0;
  const runtime = data.runtime || 'unknown';

  return (
    <div className="space-y-4">
      {/* Stats */}
      <div className="grid grid-cols-3 gap-3">
        <StatCard label="Status" value="DEPLOYED" color="#39ff14" isText />
        <StatCard label="Files" value={fileCount} color="#007acc" />
        <StatCard label="Runtime" value={runtime.toUpperCase()} color="#c678dd" isText />
      </div>

      {/* Live preview */}
      {previewUrl && (
        <div className="bg-[#1a1a1a] border border-[#333] rounded-lg overflow-hidden">
          <div className="flex items-center gap-2 px-4 py-2 border-b border-[#333]">
            <Eye className="w-4 h-4 text-[#39ff14]" />
            <span className="text-xs text-[#888] font-medium tracking-wider">LIVE PREVIEW</span>
            <a
              href={previewUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="ml-auto flex items-center gap-1 text-[10px] text-[#007acc] hover:text-[#3399dd]"
            >
              Open in new tab <ExternalLink className="w-3 h-3" />
            </a>
          </div>
          <div className="relative w-full h-[400px] bg-white">
            <iframe
              src={previewUrl}
              className="w-full h-full border-none"
              title="Live Preview"
              sandbox="allow-scripts allow-same-origin allow-forms allow-popups"
            />
          </div>
        </div>
      )}

      {/* URLs */}
      <div className="space-y-2">
        {previewUrl && (
          <div className="flex items-center gap-2 bg-[#1a1a1a] border border-[#333] rounded-lg px-4 py-2">
            <Eye className="w-4 h-4 text-[#39ff14]" />
            <span className="text-xs text-[#888]">Frontend:</span>
            <a href={previewUrl} target="_blank" rel="noopener noreferrer" className="text-xs text-[#007acc] font-mono hover:underline truncate">
              {previewUrl}
            </a>
          </div>
        )}
        {backendUrl && (
          <div className="flex items-center gap-2 bg-[#1a1a1a] border border-[#333] rounded-lg px-4 py-2">
            <Zap className="w-4 h-4 text-[#e8ab53]" />
            <span className="text-xs text-[#888]">Backend API:</span>
            <a href={backendUrl} target="_blank" rel="noopener noreferrer" className="text-xs text-[#e8ab53] font-mono hover:underline truncate">
              {backendUrl}
            </a>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Stat card helper
function StatCard({ label, value, color, isText }: { label: string; value: string | number; color: string; isText?: boolean }) {
  return (
    <div className="bg-[#1a1a1a] border border-[#333] rounded-lg p-3 text-center">
      <div className={`text-lg font-bold ${isText ? 'text-sm' : ''}`} style={{ color }}>
        {value}
      </div>
      <div className="text-[10px] text-[#666] tracking-wider mt-1">{label}</div>
    </div>
  );
}
