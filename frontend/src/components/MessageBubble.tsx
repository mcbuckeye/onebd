import { useState } from 'react';
import { User, Sparkles, Database, Brain, ChevronDown, ChevronUp, Code, ExternalLink } from 'lucide-react';
import ReactMarkdown, { Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Message } from '../types';

interface MessageBubbleProps {
  message: Message;
  onDealClick?: (dealId: number) => void;
}

export default function MessageBubble({ message, onDealClick }: MessageBubbleProps) {
  const [showSql, setShowSql] = useState(false);
  const [showResults, setShowResults] = useState(false);

  const isUser = message.role === 'user';

  // Custom markdown components to make deal IDs clickable
  const markdownComponents: Components = {
    table: ({ children }) => (
      <div className="overflow-x-auto my-2">
        <table className="w-full text-sm table-fixed">{children}</table>
      </div>
    ),
    thead: ({ children }) => (
      <thead className="bg-slate-700/50">{children}</thead>
    ),
    tbody: ({ children }) => (
      <tbody className="divide-y divide-slate-700">{children}</tbody>
    ),
    tr: ({ children }) => (
      <tr className="hover:bg-slate-700/30 transition-colors">{children}</tr>
    ),
    th: ({ children }) => {
      const content = String(children ?? '').toLowerCase();
      // Narrow columns for specific headers
      const isNarrow = ['id', 'date_start', 'date_end', 'status', 'total_projected_current_amount'].some(
        h => content.includes(h.replace('_', ''))
      ) || content === 'id';
      return (
        <th className={`px-3 py-2 text-left text-xs font-medium text-slate-400 uppercase tracking-wider ${
          isNarrow ? 'w-24 whitespace-nowrap' : ''
        }`}>
          {children}
        </th>
      );
    },
    td: ({ children }) => {
      const content = String(children ?? '');
      const isNumeric = /^\d+$/.test(content.trim());
      // Short content (dates, numbers, short text) should not wrap
      const isShort = content.length < 20 || /^\d{4}-\d{2}/.test(content.trim());

      // Check if this is likely a deal ID column (numeric values that look like IDs)
      if (isNumeric && onDealClick) {
        const dealId = parseInt(content.trim(), 10);
        // Only make it clickable if it looks like a reasonable deal ID
        if (dealId > 0 && dealId < 10000000) {
          return (
            <td className="px-3 py-2 whitespace-nowrap w-24">
              <button
                onClick={() => onDealClick(dealId)}
                className="text-blue-400 hover:text-blue-300 hover:underline flex items-center gap-1 transition-colors"
                title={`View deal ${dealId} details`}
              >
                {content}
                <ExternalLink className="w-3 h-3 opacity-50" />
              </button>
            </td>
          );
        }
      }
      // Allow text to wrap for longer content (like titles)
      return (
        <td className={`px-3 py-2 ${isShort ? 'whitespace-nowrap' : ''}`}>
          {children}
        </td>
      );
    },
  };

  return (
    <div className={`flex items-start gap-3 ${isUser ? 'flex-row-reverse' : ''}`}>
      {/* Avatar */}
      <div className={`w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 ${
        isUser ? 'bg-green-500/20' : 'bg-blue-500/20'
      }`}>
        {isUser ? (
          <User className="w-4 h-4 text-green-400" />
        ) : (
          <Sparkles className="w-4 h-4 text-blue-400" />
        )}
      </div>

      {/* Content */}
      <div className={`flex flex-col ${isUser ? 'items-end' : 'items-start'} max-w-[80%]`}>
        {/* Mode Badge */}
        {!isUser && message.mode && (
          <div className="flex items-center gap-1 mb-1">
            {message.mode === 'sql' ? (
              <span className="flex items-center gap-1 text-xs text-blue-400 bg-blue-500/10 px-2 py-0.5 rounded">
                <Database className="w-3 h-3" />
                SQL Query
              </span>
            ) : message.mode === 'rag' ? (
              <span className="flex items-center gap-1 text-xs text-purple-400 bg-purple-500/10 px-2 py-0.5 rounded">
                <Brain className="w-3 h-3" />
                RAG Search
              </span>
            ) : null}
          </div>
        )}

        {/* Message Bubble */}
        <div className={`rounded-lg px-4 py-3 ${
          isUser
            ? 'bg-blue-600 text-white'
            : 'bg-slate-800 text-slate-100'
        }`}>
          {isUser ? (
            <p className="whitespace-pre-wrap">{message.content}</p>
          ) : (
            <div className="markdown-content">
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={markdownComponents}
              >
                {message.content}
              </ReactMarkdown>
            </div>
          )}
        </div>

        {/* SQL Query Expandable */}
        {message.sqlQuery && (
          <div className="mt-2 w-full">
            <button
              onClick={() => setShowSql(!showSql)}
              className="flex items-center gap-1 text-xs text-slate-400 hover:text-slate-300"
            >
              <Code className="w-3 h-3" />
              {showSql ? 'Hide SQL' : 'Show SQL'}
              {showSql ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
            </button>
            {showSql && (
              <pre className="mt-2 bg-slate-900 border border-slate-700 rounded-lg p-3 text-sm text-slate-300 overflow-x-auto">
                <code>{message.sqlQuery}</code>
              </pre>
            )}
          </div>
        )}

        {/* Search Results Expandable */}
        {message.searchResults && message.searchResults.length > 0 && (
          <div className="mt-2 w-full">
            <button
              onClick={() => setShowResults(!showResults)}
              className="flex items-center gap-1 text-xs text-slate-400 hover:text-slate-300"
            >
              <Brain className="w-3 h-3" />
              {showResults ? 'Hide' : 'Show'} {message.searchResults.length} contract excerpts
              {showResults ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
            </button>
            {showResults && (
              <div className="mt-2 space-y-2">
                {message.searchResults.map((result, idx) => (
                  <div key={idx} className="bg-slate-900 border border-slate-700 rounded-lg p-3">
                    <div className="flex items-center justify-between mb-2">
                      <button
                        onClick={() => onDealClick?.(result.deal_id)}
                        className="text-sm font-medium text-blue-400 hover:text-blue-300 hover:underline text-left flex items-center gap-1"
                      >
                        Deal {result.deal_id}: {result.deal_title.slice(0, 50)}...
                        <ExternalLink className="w-3 h-3 opacity-50" />
                      </button>
                      <span className="text-xs text-purple-400">
                        {(result.relevance * 100).toFixed(1)}% match
                      </span>
                    </div>
                    {result.contract_types && (
                      <span className="text-xs text-slate-500 block mb-2">
                        Type: {result.contract_types}
                      </span>
                    )}
                    <p className="text-sm text-slate-400">{result.snippet}</p>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Timestamp */}
        <span className="text-xs text-slate-500 mt-1">
          {message.timestamp.toLocaleTimeString()}
        </span>
      </div>
    </div>
  );
}
