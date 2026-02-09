'use client';

import { useState, useEffect } from 'react';
import {
  Sparkles, Send, X, FileText, Loader2,
  ChevronDown, ChevronRight, Wand2, RotateCcw,
  MousePointerClick, Type, Image, Code2,
} from 'lucide-react';

type EditFile = {
  filename: string;
  content: string;
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

type EditPanelProps = {
  selectedFiles: EditFile[];
  onRemoveFile: (filename: string) => void;
  onSubmitEdit: (files: EditFile[], instructions: string) => Promise<void>;
  onClose: () => void;
  isEditing: boolean;
  selectedElement?: SelectedElement;
  onClearElement?: () => void;
};

const SUGGESTED_EDITS = [
  'Improve the UI styling and make it more modern',
  'Add proper error handling and loading states',
  'Make it responsive for mobile devices',
  'Add form validation',
  'Change the color scheme',
  'Add animations and transitions',
  'Restructure and clean up the code',
  'Add authentication/login flow',
];

function getElementDescription(el: NonNullable<SelectedElement>): string {
  const tag = el.tag?.toLowerCase() || 'element';
  if (el.src) return `<${tag}> image: ${el.src.split('/').pop()}`;
  if (el.text && el.text.length > 0) {
    const preview = el.text.length > 60 ? el.text.slice(0, 60) + '...' : el.text;
    return `<${tag}>: "${preview}"`;
  }
  if (el.placeholder) return `<${tag}> input: "${el.placeholder}"`;
  if (el.id) return `<${tag}#${el.id}>`;
  if (el.className) return `<${tag}.${el.className.split(' ')[0]}>`;
  return `<${tag}> element`;
}

function getElementIcon(el: NonNullable<SelectedElement>) {
  const tag = el.tag?.toLowerCase();
  if (el.src || tag === 'img' || tag === 'svg') return Image;
  if (['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'span', 'label', 'a'].includes(tag || '')) return Type;
  return Code2;
}

export default function EditPanel({
  selectedFiles,
  onRemoveFile,
  onSubmitEdit,
  onClose,
  isEditing,
  selectedElement,
  onClearElement,
}: EditPanelProps) {
  const [instructions, setInstructions] = useState('');
  const [expandedFile, setExpandedFile] = useState<string | null>(null);

  // Auto-prefill instructions when an element is selected
  useEffect(() => {
    if (selectedElement && !instructions.trim()) {
      const desc = getElementDescription(selectedElement);
      setInstructions(`Modify this ${desc}\n\nChanges: `);
    }
  }, [selectedElement]);

  const handleSubmit = () => {
    if (!instructions.trim() || selectedFiles.length === 0) return;
    onSubmitEdit(selectedFiles, instructions);
  };

  return (
    <div className="border-t border-[#3c3c3c] bg-[#1e1e1e] flex flex-col" style={{ maxHeight: '50vh' }}>
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2 bg-[#252526] border-b border-[#3c3c3c]">
        <div className="flex items-center gap-2">
          <Wand2 className="w-4 h-4 text-[#c678dd]" />
          <span className="text-xs font-bold text-[#c678dd] tracking-wider">
            AI EDIT MODE
          </span>
          <span className="text-[10px] text-[#666] ml-2">
            {selectedFiles.length} file{selectedFiles.length !== 1 ? 's' : ''} selected
          </span>
        </div>
        <button
          onClick={onClose}
          className="p-1 rounded hover:bg-[#3c3c3c] text-[#888] hover:text-white transition-colors"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      <div className="flex-1 overflow-auto p-4 space-y-3">
        {/* Selected Element Card */}
        {selectedElement && (
          <div className="bg-[#c678dd]/5 border border-[#c678dd]/30 rounded-lg p-3 space-y-2">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <MousePointerClick className="w-3.5 h-3.5 text-[#c678dd]" />
                <span className="text-[10px] text-[#c678dd] uppercase tracking-wider font-semibold">
                  Selected Element
                </span>
              </div>
              {onClearElement && (
                <button
                  onClick={onClearElement}
                  className="text-[10px] text-[#888] hover:text-[#c678dd] transition-colors"
                >
                  Clear
                </button>
              )}
            </div>
            <div className="flex items-start gap-2">
              {(() => {
                const IconComp = getElementIcon(selectedElement);
                return <IconComp className="w-4 h-4 text-[#c678dd] mt-0.5 flex-shrink-0" />;
              })()}
              <div className="min-w-0 flex-1">
                <div className="text-[12px] text-white font-mono">
                  {getElementDescription(selectedElement)}
                </div>
                {selectedElement.src && (
                  <div className="text-[10px] text-[#888] mt-1 truncate">
                    Source: {selectedElement.src}
                  </div>
                )}
                {selectedElement.id && (
                  <span className="inline-block mt-1 px-1.5 py-0.5 rounded text-[9px] bg-[#264f78] text-[#9cdcfe] font-mono">
                    #{selectedElement.id}
                  </span>
                )}
                {selectedElement.className && (
                  <span className="inline-block mt-1 ml-1 px-1.5 py-0.5 rounded text-[9px] bg-[#3c3c3c] text-[#ce9178] font-mono truncate max-w-[200px]">
                    .{selectedElement.className.split(' ')[0]}
                  </span>
                )}
              </div>
            </div>
          </div>
        )}

        {/* Hint when no element and no files selected */}
        {!selectedElement && selectedFiles.length === 0 && (
          <div className="bg-[#1a1a1a] border border-[#333] border-dashed rounded-lg p-4 text-center">
            <MousePointerClick className="w-6 h-6 text-[#555] mx-auto mb-2" />
            <p className="text-[11px] text-[#888]">
              Click any element in the preview to select it, or choose files from the file tree
            </p>
          </div>
        )}

        {/* Selected files list */}
        {selectedFiles.length > 0 && (
          <div className="space-y-1">
            <span className="text-[10px] text-[#888] uppercase tracking-wider font-semibold">
              Files to edit
            </span>
            <div className="flex flex-wrap gap-1.5 mt-1">
              {selectedFiles.map((file) => (
                <div key={file.filename} className="group relative">
                  <button
                    onClick={() => setExpandedFile(
                      expandedFile === file.filename ? null : file.filename
                    )}
                    className="flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[11px] bg-[#c678dd]/10 border border-[#c678dd]/30 text-[#c678dd] hover:bg-[#c678dd]/20 transition-colors"
                  >
                    <FileText className="w-3 h-3" />
                    <span className="max-w-[180px] truncate">
                      {file.filename.split('/').pop()}
                    </span>
                    {expandedFile === file.filename ? (
                      <ChevronDown className="w-3 h-3" />
                    ) : (
                      <ChevronRight className="w-3 h-3" />
                    )}
                  </button>
                  <button
                    onClick={() => onRemoveFile(file.filename)}
                    className="absolute -top-1 -right-1 w-4 h-4 rounded-full bg-[#3c3c3c] border border-[#555] text-[#888] hover:text-red-400 hover:border-red-400 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"
                  >
                    <X className="w-2.5 h-2.5" />
                  </button>
                </div>
              ))}
            </div>

            {/* Expanded file preview */}
            {expandedFile && (
              <div className="mt-2 bg-[#1a1a1a] border border-[#333] rounded-lg overflow-hidden">
                <div className="flex items-center justify-between px-3 py-1.5 bg-[#252526] border-b border-[#333]">
                  <span className="text-[10px] text-[#888] font-mono truncate">{expandedFile}</span>
                  <span className="text-[9px] text-[#555]">
                    {selectedFiles.find(f => f.filename === expandedFile)?.content.split('\n').length || 0} lines
                  </span>
                </div>
                <pre className="p-3 text-[11px] text-[#d4d4d4] font-mono overflow-auto max-h-32 leading-relaxed">
                  {selectedFiles.find(f => f.filename === expandedFile)?.content.slice(0, 2000) || ''}
                  {(selectedFiles.find(f => f.filename === expandedFile)?.content.length || 0) > 2000 && (
                    <span className="text-[#555]">{'\n'}... truncated ...</span>
                  )}
                </pre>
              </div>
            )}
          </div>
        )}

        {/* Suggested edits */}
        <div>
          <span className="text-[10px] text-[#888] uppercase tracking-wider font-semibold">
            Quick suggestions
          </span>
          <div className="flex flex-wrap gap-1.5 mt-1">
            {SUGGESTED_EDITS.map((s, i) => (
              <button
                key={i}
                onClick={() => setInstructions(prev =>
                  prev ? `${prev}\n${s}` : s
                )}
                className="px-2 py-1 rounded-full text-[9px] bg-[#1a1a1a] border border-[#333] text-[#888] hover:border-[#c678dd] hover:text-[#c678dd] transition-colors"
              >
                {s}
              </button>
            ))}
          </div>
        </div>

        {/* Instructions input + submit */}
        <div className="flex gap-2">
          <textarea
            value={instructions}
            onChange={e => setInstructions(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                handleSubmit();
              }
            }}
            placeholder={
              selectedElement
                ? `Describe how to change this ${selectedElement.tag?.toLowerCase() || 'element'}... (⌘+Enter to submit)`
                : 'Describe the changes you want... (⌘+Enter to submit)'
            }
            rows={3}
            disabled={isEditing}
            className="flex-1 bg-[#1a1a1a] border border-[#333] rounded-lg px-3 py-2 text-sm text-white placeholder-[#555] focus:outline-none focus:border-[#c678dd]/50 resize-none transition-all disabled:opacity-50"
          />
          <div className="flex flex-col gap-1.5 self-end">
            <button
              onClick={handleSubmit}
              disabled={!instructions.trim() || selectedFiles.length === 0 || isEditing}
              className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-xs font-bold bg-[#c678dd] text-white hover:bg-[#d19ae8] disabled:opacity-30 disabled:cursor-not-allowed transition-all"
            >
              {isEditing ? (
                <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Editing...</>
              ) : (
                <><Sparkles className="w-3.5 h-3.5" /> Apply Edit</>
              )}
            </button>
            <button
              onClick={() => setInstructions('')}
              disabled={isEditing}
              className="flex items-center justify-center gap-1 px-4 py-1.5 rounded-lg text-[10px] text-[#888] hover:text-white hover:bg-[#3c3c3c] transition-colors disabled:opacity-30"
            >
              <RotateCcw className="w-3 h-3" />
              Clear
            </button>
          </div>
        </div>
      </div>

      {/* Loading overlay */}
      {isEditing && (
        <div className="px-4 py-2 bg-[#c678dd]/10 border-t border-[#c678dd]/20 flex items-center gap-2">
          <Loader2 className="w-3.5 h-3.5 animate-spin text-[#c678dd]" />
          <span className="text-[11px] text-[#c678dd]">
            Gemini Pro is editing your files...
          </span>
        </div>
      )}
    </div>
  );
}
