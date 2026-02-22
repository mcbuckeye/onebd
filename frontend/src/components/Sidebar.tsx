import { Database, FileText, Brain, Activity, CheckCircle, XCircle, X } from 'lucide-react';
import { IndexStatus } from '../types';

interface SidebarProps {
  indexStatus: IndexStatus | null;
  isHealthy: boolean | null;
  onClose?: () => void;
}

export default function Sidebar({ indexStatus, isHealthy, onClose }: SidebarProps) {
  return (
    <aside data-testid="sidebar" className="w-72 h-full bg-slate-800 border-r border-slate-700 flex flex-col">
      {/* Logo/Header */}
      <div className="p-4 border-b border-slate-700">
        <div className="flex items-center justify-between">
          <h1 className="text-xl font-bold text-white flex items-center gap-2">
            <Database className="w-6 h-6 text-blue-400" />
            Cortellis Search
          </h1>
          {/* Mobile close button */}
          {onClose && (
            <button
              onClick={onClose}
              className="lg:hidden p-1 text-slate-400 hover:text-white transition-colors"
            >
              <X className="w-5 h-5" />
            </button>
          )}
        </div>
        <p className="text-sm text-slate-400 mt-1">
          AI-powered deals database
        </p>
      </div>

      {/* Status Section */}
      <div className="p-4 border-b border-slate-700">
        <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wider mb-3">
          System Status
        </h2>

        <div className="space-y-2">
          <StatusItem
            icon={isHealthy ? <CheckCircle className="w-4 h-4 text-green-400" /> : <XCircle className="w-4 h-4 text-red-400" />}
            label="API"
            value={isHealthy === null ? 'Checking...' : isHealthy ? 'Healthy' : 'Unavailable'}
            valueColor={isHealthy ? 'text-green-400' : 'text-red-400'}
          />
        </div>
      </div>

      {/* Index Status Section */}
      {indexStatus && (
        <div className="p-4 border-b border-slate-700">
          <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wider mb-3">
            Index Status
          </h2>

          <div className="space-y-4">
            <div>
              <div className="flex items-center gap-2 mb-1">
                <FileText className="w-4 h-4 text-blue-400" />
                <span className="text-sm text-slate-300">Full-Text Search</span>
              </div>
              <div className="flex justify-between text-xs text-slate-400 mb-1">
                <span>{indexStatus.indexed_for_fulltext.toLocaleString()} contracts</span>
                <span>{indexStatus.fulltext_pct}%</span>
              </div>
              <ProgressBar value={indexStatus.fulltext_pct} color="blue" />
            </div>

            <div>
              <div className="flex items-center gap-2 mb-1">
                <Brain className="w-4 h-4 text-purple-400" />
                <span className="text-sm text-slate-300">RAG Embeddings</span>
              </div>
              <div className="flex justify-between text-xs text-slate-400 mb-1">
                <span>{indexStatus.embedded_chunks.toLocaleString()} chunks</span>
                <span>{indexStatus.embedding_pct}%</span>
              </div>
              <ProgressBar value={indexStatus.embedding_pct} color="purple" />
            </div>
          </div>
        </div>
      )}

      {/* Search Modes Info */}
      <div className="p-4 flex-1">
        <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wider mb-3">
          Search Modes
        </h2>

        <div className="space-y-3 text-sm">
          <ModeInfo
            icon={<Activity className="w-4 h-4 text-green-400" />}
            title="Auto"
            description="Automatically detects query type"
          />
          <ModeInfo
            icon={<Database className="w-4 h-4 text-blue-400" />}
            title="SQL"
            description="Structured queries on deals data"
          />
          <ModeInfo
            icon={<Brain className="w-4 h-4 text-purple-400" />}
            title="RAG"
            description="Semantic search in contracts"
          />
        </div>
      </div>

      {/* Footer */}
      <div className="p-4 border-t border-slate-700">
        <p className="text-xs text-slate-500 text-center">
          Powered by OpenAI + pgvector
        </p>
      </div>
    </aside>
  );
}

function StatusItem({ icon, label, value, valueColor = 'text-slate-300' }: {
  icon: React.ReactNode;
  label: string;
  value: string;
  valueColor?: string;
}) {
  return (
    <div className="flex items-center justify-between">
      <div className="flex items-center gap-2 text-sm text-slate-400">
        {icon}
        {label}
      </div>
      <span data-testid={`status-${label.toLowerCase()}`} className={`text-sm font-medium ${valueColor}`}>{value}</span>
    </div>
  );
}

function ProgressBar({ value, color }: { value: number; color: 'blue' | 'purple' }) {
  const colorClass = color === 'blue' ? 'bg-blue-500' : 'bg-purple-500';
  return (
    <div className="h-1.5 bg-slate-700 rounded-full overflow-hidden">
      <div
        className={`h-full ${colorClass} transition-all duration-300`}
        style={{ width: `${Math.min(100, value)}%` }}
      />
    </div>
  );
}

function ModeInfo({ icon, title, description }: {
  icon: React.ReactNode;
  title: string;
  description: string;
}) {
  return (
    <div className="flex items-start gap-2">
      <div className="mt-0.5">{icon}</div>
      <div>
        <div className="font-medium text-slate-300">{title}</div>
        <div className="text-xs text-slate-500">{description}</div>
      </div>
    </div>
  );
}
