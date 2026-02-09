'use client';

import { useState, useMemo } from 'react';
import { ChevronRight, ChevronDown, FileText, Folder, FolderOpen } from 'lucide-react';

export type FileEntry = {
  path: string;
  isNew: boolean;
  content?: string;
};

type TreeNode = {
  name: string;
  path: string;
  isFolder: boolean;
  isNew: boolean;
  children: TreeNode[];
};

const EXT_COLORS: Record<string, string> = {
  '.py': '#3572A5', '.ts': '#3178C6', '.tsx': '#61DAFB', '.js': '#F7DF1E',
  '.jsx': '#61DAFB', '.json': '#CBB148', '.html': '#E34C26', '.css': '#563D7C',
  '.md': '#083FA1', '.yaml': '#CB171E', '.yml': '#CB171E', '.env': '#ECD53F',
  '.sh': '#89E051', '.lock': '#6B7280', '.toml': '#9C4121', '.txt': '#6B7280',
  '.svg': '#FFB13B', '.png': '#A074C4', '.jpg': '#A074C4', '.gif': '#A074C4',
  '.gitignore': '#F05032', '.sql': '#e38c00', '.rs': '#DEA584', '.go': '#00ADD8',
  '.java': '#B07219', '.rb': '#CC342D', '.php': '#4F5D95', '.c': '#555555',
  '.cpp': '#F34B7D', '.h': '#555555',
};

function getExtColor(name: string): string {
  const lower = name.toLowerCase();
  if (EXT_COLORS[lower]) return EXT_COLORS[lower];
  const ext = '.' + lower.split('.').pop();
  return EXT_COLORS[ext] || '#858585';
}

function buildTree(files: FileEntry[]): TreeNode[] {
  const root: TreeNode[] = [];
  for (const file of files) {
    const parts = file.path.split('/');
    let current = root;
    for (let i = 0; i < parts.length; i++) {
      const part = parts[i];
      const isLast = i === parts.length - 1;
      const existing = current.find(n => n.name === part);
      if (existing) {
        if (isLast) existing.isNew = file.isNew;
        else current = existing.children;
      } else {
        const node: TreeNode = {
          name: part,
          path: parts.slice(0, i + 1).join('/'),
          isFolder: !isLast,
          isNew: isLast ? file.isNew : false,
          children: [],
        };
        current.push(node);
        if (!isLast) current = node.children;
      }
    }
  }
  const sort = (nodes: TreeNode[]) => {
    nodes.sort((a, b) => {
      if (a.isFolder && !b.isFolder) return -1;
      if (!a.isFolder && b.isFolder) return 1;
      return a.name.localeCompare(b.name);
    });
    nodes.forEach(n => sort(n.children));
  };
  sort(root);
  return root;
}

function hasNewChild(node: TreeNode): boolean {
  if (node.isNew) return true;
  return node.children.some(hasNewChild);
}

function TreeRow({
  node, depth, selected, onSelect, expanded, onToggle,
  multiSelect, checkedFiles, onToggleCheck,
}: {
  node: TreeNode; depth: number; selected: string | null;
  onSelect: (p: string) => void; expanded: Set<string>;
  onToggle: (p: string) => void;
  multiSelect?: boolean; checkedFiles?: Set<string>;
  onToggleCheck?: (p: string) => void;
}) {
  const isOpen = expanded.has(node.path);
  const isSel = selected === node.path;
  const hasNew = node.isFolder && hasNewChild(node);
  const isChecked = checkedFiles?.has(node.path) || false;

  return (
    <>
      <div
        className={`w-full text-left flex items-center gap-1 py-[2px] pr-3 text-[13px] leading-[22px] cursor-pointer select-none transition-colors
          ${isSel ? 'bg-[#37373d] text-white' : 'hover:bg-[#2a2d2e] text-[#cccccc]'}
          ${isChecked ? 'bg-[#c678dd]/10' : ''}
        `}
        style={{ paddingLeft: `${8 + depth * 16}px` }}
      >
        {/* Multi-select checkbox */}
        {multiSelect && !node.isFolder && (
          <button
            onClick={(e) => { e.stopPropagation(); onToggleCheck?.(node.path); }}
            className="w-4 flex-shrink-0 flex items-center justify-center mr-0.5"
          >
            <span className={`w-3.5 h-3.5 rounded-sm border flex items-center justify-center transition-all ${
              isChecked
                ? 'bg-[#c678dd] border-[#c678dd]'
                : 'border-[#555] hover:border-[#c678dd]'
            }`}>
              {isChecked && (
                <svg className="w-2.5 h-2.5 text-white" viewBox="0 0 12 12" fill="none">
                  <path d="M2 6L5 9L10 3" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              )}
            </span>
          </button>
        )}

        {/* Chevron */}
        <button
          onClick={() => node.isFolder ? onToggle(node.path) : onSelect(node.path)}
          className="flex-1 flex items-center gap-1"
        >
          <span className="w-4 flex-shrink-0 flex items-center justify-center">
            {node.isFolder ? (
              isOpen ? <ChevronDown size={14} className="text-[#c5c5c5]" /> : <ChevronRight size={14} className="text-[#c5c5c5]" />
            ) : null}
          </span>

          {/* Icon */}
          <span className="w-4 flex-shrink-0 flex items-center justify-center">
            {node.isFolder ? (
              isOpen ? <FolderOpen size={14} className="text-[#dcb67a]" /> : <Folder size={14} className="text-[#dcb67a]" />
            ) : (
              <FileText size={14} style={{ color: getExtColor(node.name) }} />
            )}
          </span>

          {/* Name */}
          <span className={`truncate ml-1 ${
            node.isNew ? 'text-[#73c991] font-medium' : hasNew ? 'text-[#e2c08d]' : ''
          }`}>
            {node.name}
          </span>

          {/* Badge */}
          {node.isNew && !node.isFolder && (
            <span className="ml-auto flex-shrink-0 text-[9px] font-bold px-1.5 py-0.5 rounded-sm bg-[#73c991]/20 text-[#73c991] border border-[#73c991]/30">
              NEW
            </span>
          )}
          {hasNew && node.isFolder && (
            <span className="ml-auto flex-shrink-0 w-2 h-2 rounded-full bg-[#73c991]" />
          )}
        </button>
      </div>

      {node.isFolder && isOpen && node.children.map(child => (
        <TreeRow key={child.path} node={child} depth={depth + 1} selected={selected} onSelect={onSelect} expanded={expanded} onToggle={onToggle} multiSelect={multiSelect} checkedFiles={checkedFiles} onToggleCheck={onToggleCheck} />
      ))}
    </>
  );
}

export default function FileTree({
  files, selectedFile, onSelectFile,
  multiSelect, checkedFiles, onToggleCheck,
}: {
  files: FileEntry[]; selectedFile: string | null; onSelectFile: (p: string) => void;
  multiSelect?: boolean; checkedFiles?: Set<string>; onToggleCheck?: (p: string) => void;
}) {
  const tree = useMemo(() => buildTree(files), [files]);

  const allFolders = useMemo(() => {
    const paths = new Set<string>();
    const collect = (nodes: TreeNode[]) => {
      nodes.forEach(n => { if (n.isFolder) { paths.add(n.path); collect(n.children); } });
    };
    collect(tree);
    return paths;
  }, [tree]);

  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  // Auto-expand when tree changes
  const [prevLen, setPrevLen] = useState(0);
  if (files.length !== prevLen) {
    setPrevLen(files.length);
    setExpanded(new Set(allFolders));
  }

  const toggle = (p: string) => {
    setExpanded(prev => {
      const next = new Set(prev);
      next.has(p) ? next.delete(p) : next.add(p);
      return next;
    });
  };

  const newCount = files.filter(f => f.isNew).length;
  const existCount = files.filter(f => !f.isNew).length;

  return (
    <div className="flex flex-col h-full bg-[#252526]">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 text-[11px] font-semibold uppercase tracking-wider text-[#bbbbbb] border-b border-[#3c3c3c]">
        <span>EXPLORER</span>
        <div className="flex gap-2 text-[10px] font-normal normal-case tracking-normal text-[#858585]">
          {multiSelect && checkedFiles && checkedFiles.size > 0 && (
            <span className="flex items-center gap-1 text-[#c678dd]">
              <span className="w-1.5 h-1.5 rounded-full bg-[#c678dd]" />{checkedFiles.size} selected
            </span>
          )}
          {existCount > 0 && <span className="flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full bg-[#858585]" />{existCount}</span>}
          {newCount > 0 && <span className="flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full bg-[#73c991]" />{newCount}</span>}
        </div>
      </div>

      {/* Tree */}
      <div className="flex-1 overflow-y-auto overflow-x-hidden py-1">
        {tree.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-[#6b6b6b] text-center px-4">
            <Folder className="w-10 h-10 mb-2 opacity-30" />
            <p className="text-xs">No files loaded</p>
            <p className="text-[10px] mt-1 opacity-60">Enter a repo URL and click SCAN</p>
          </div>
        ) : (
          tree.map(node => (
            <TreeRow key={node.path} node={node} depth={0} selected={selectedFile} onSelect={onSelectFile} expanded={expanded} onToggle={toggle} multiSelect={multiSelect} checkedFiles={checkedFiles} onToggleCheck={onToggleCheck} />
          ))
        )}
      </div>
    </div>
  );
}
