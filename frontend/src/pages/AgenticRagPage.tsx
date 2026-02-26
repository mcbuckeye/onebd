import { useState, useEffect, useRef } from 'react';
import { Send, Brain, ChevronRight, ChevronDown, Loader2, Database, Network, FileText, CheckCircle, AlertCircle } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import api from '../lib/api';

interface ReasoningStep {
  hop_number: number;
  thought: string;
  tool_type: string;
  query: string;
  result_summary: string;
  retry_count: number;
  error?: string;
  duration_ms?: number;
}

interface Message {
  role: 'user' | 'assistant';
  content: string;
  reasoning_steps?: ReasoningStep[];
  total_hops?: number;
  partial?: boolean;
  latency_ms?: number;
}

const ToolIcon = ({ tool }: { tool: string }) => {
  switch (tool) {
    case 'neo4j': return <Network className="w-4 h-4 text-purple-400" />;
    case 'sql': return <Database className="w-4 h-4 text-blue-400" />;
    case 'pgvector': return <FileText className="w-4 h-4 text-green-400" />;
    default: return <Brain className="w-4 h-4 text-slate-400" />;
  }
};

const ToolBadge = ({ tool }: { tool: string }) => {
  const colors: Record<string, string> = {
    neo4j: 'bg-purple-500/10 text-purple-400 border-purple-500/30',
    sql: 'bg-blue-500/10 text-blue-400 border-blue-500/30',
    pgvector: 'bg-green-500/10 text-green-400 border-green-500/30',
    synthesize: 'bg-amber-500/10 text-amber-400 border-amber-500/30',
  };

  return (
    <span className={`px-2 py-0.5 text-xs border rounded ${colors[tool] || colors.synthesize}`}>
      {tool}
    </span>
  );
};

const ReasoningStepCard = ({ step, isExpanded, onToggle }: { step: ReasoningStep; isExpanded: boolean; onToggle: () => void }) => {
  const hasError = !!step.error;
  const hasRetry = step.retry_count > 0;

  return (
    <div className={`border rounded-lg overflow-hidden ${hasError ? 'border-red-500/30 bg-red-500/5' : 'border-slate-700 bg-slate-800/50'}`}>
      <button
        onClick={onToggle}
        className="w-full px-3 py-2 flex items-center gap-3 hover:bg-slate-700/50 transition-colors"
      >
        {isExpanded ? <ChevronDown className="w-4 h-4 text-slate-500" /> : <ChevronRight className="w-4 h-4 text-slate-500" />}
        
        <span className="flex-shrink-0 w-6 h-6 flex items-center justify-center bg-slate-700 rounded-full text-xs font-medium text-slate-300">
          {step.hop_number}
        </span>

        <ToolIcon tool={step.tool_type} />

        <span className="flex-1 text-left text-sm text-slate-300 truncate">
          {step.thought}
        </span>

        <div className="flex items-center gap-2">
          {hasError && <AlertCircle className="w-4 h-4 text-red-400" />}
          {hasRetry && <span className="text-xs text-amber-400">retry {step.retry_count}</span>}
          <ToolBadge tool={step.tool_type} />
          {step.duration_ms && (
            <span className="text-xs text-slate-500">{step.duration_ms}ms</span>
          )}
        </div>
      </button>

      {isExpanded && (
        <div className="px-3 pb-3 pt-1 border-t border-slate-700/50 space-y-3">
          {/* Query */}
          <div>
            <div className="text-xs text-slate-500 mb-1">Query</div>
            <pre className="p-2 bg-slate-900 rounded text-xs text-slate-300 overflow-x-auto">{step.query}</pre>
          </div>

          {/* Result */}
          <div>
            <div className="text-xs text-slate-500 mb-1">Result</div>
            {hasError ? (
              <div className="p-2 bg-red-900/20 border border-red-500/30 rounded text-xs text-red-300">
                {step.error}
              </div>
            ) : (
              <div className="p-2 bg-slate-900/50 rounded text-xs text-slate-300">
                <CheckCircle className="w-3 h-3 inline text-green-400 mr-1" />
                {step.result_summary}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

export default function AgenticRagPage() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [expandedSteps, setExpandedSteps] = useState<Set<number>>(new Set());
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const toggleStep = (hopNumber: number) => {
    setExpandedSteps(prev => {
      const next = new Set(prev);
      if (next.has(hopNumber)) {
        next.delete(hopNumber);
      } else {
        next.add(hopNumber);
      }
      return next;
    });
  };

  const handleSend = async (text?: string) => {
    const msg = text || input.trim();
    if (!msg || loading) return;
    setInput('');

    const userMsg: Message = { role: 'user', content: msg };
    setMessages(prev => [...prev, userMsg]);
    setLoading(true);
    setExpandedSteps(new Set()); // Collapse all on new query

    try {
      const res = await api.post('/agentic-rag/chat', {
        message: msg,
        history: messages.slice(-6).map(m => ({ role: m.role, content: m.content })),
        max_hops: 5,
      });

      const assistantMsg: Message = {
        role: 'assistant',
        content: res.data.answer,
        reasoning_steps: res.data.reasoning_steps,
        total_hops: res.data.total_hops,
        partial: res.data.partial,
        latency_ms: res.data.latency_ms,
      };
      setMessages(prev => [...prev, assistantMsg]);

      // Auto-expand first step if there is one
      if (res.data.reasoning_steps?.length > 0) {
        setExpandedSteps(new Set([res.data.reasoning_steps[0].hop_number]));
      }
    } catch (err: any) {
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: `Error: ${err.response?.data?.detail || err.message || 'Request failed'}`,
      }]);
    } finally {
      setLoading(false);
      inputRef.current?.focus();
    }
  };

  return (
    <div className="flex flex-col h-full">
      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-6">
        {messages.length === 0 && (
          <div className="text-center py-20">
            <Brain className="w-12 h-12 text-purple-500/50 mx-auto mb-4" />
            <h2 className="text-xl font-semibold text-slate-300 mb-2">Agentic RAG Intelligence</h2>
            <p className="text-sm text-slate-500 mb-6 max-w-md mx-auto">
              Multi-hop reasoning across Neo4j graph, SQL database, and semantic search.
              Watch the agent think through complex queries step by step.
            </p>
            <div className="flex flex-wrap gap-2 justify-center max-w-lg mx-auto">
              {[
                'What companies have partnered with both Pfizer and Merck?',
                'Find oncology deals involving ADCs with disclosed values',
                'Which acquisitions in 2024 had earnout provisions?',
                'Compare Phase 3 deal terms across therapy areas',
              ].map(q => (
                <button
                  key={q}
                  onClick={() => handleSend(q)}
                  className="px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-xs text-slate-400 hover:text-slate-200 hover:border-slate-600 transition-colors text-left"
                >
                  {q}
                </button>
              ))}
            </div>
          </div>
        )}

        <div className="max-w-4xl mx-auto space-y-8">
          {messages.map((msg, i) => (
            <div key={i} className={`${msg.role === 'user' ? 'flex justify-end' : ''}`}>
              {msg.role === 'user' ? (
                <div className="bg-blue-600 text-white px-4 py-2.5 rounded-2xl rounded-br-md max-w-lg text-sm">
                  {msg.content}
                </div>
              ) : (
                <div className="space-y-4">
                  {/* Reasoning Trace */}
                  {msg.reasoning_steps && msg.reasoning_steps.length > 0 && (
                    <div className="space-y-2">
                      <div className="flex items-center gap-2 text-xs text-slate-500">
                        <Brain className="w-3 h-3" />
                        <span>Reasoning Trace</span>
                        <span className="text-slate-600">•</span>
                        <span>{msg.total_hops} hops</span>
                        {msg.latency_ms && (
                          <>
                            <span className="text-slate-600">•</span>
                            <span>{msg.latency_ms}ms</span>
                          </>
                        )}
                        {msg.partial && (
                          <span className="text-amber-400">(partial - max hops reached)</span>
                        )}
                      </div>

                      <div className="space-y-2">
                        {msg.reasoning_steps.map(step => (
                          <ReasoningStepCard
                            key={step.hop_number}
                            step={step}
                            isExpanded={expandedSteps.has(step.hop_number)}
                            onToggle={() => toggleStep(step.hop_number)}
                          />
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Final Answer */}
                  <div className="prose prose-invert prose-sm max-w-none text-slate-300
                    prose-headings:text-slate-200 prose-strong:text-slate-200
                    prose-th:text-slate-400 prose-td:text-slate-300
                    prose-a:text-blue-400">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content}</ReactMarkdown>
                  </div>
                </div>
              )}
            </div>
          ))}

          {loading && (
            <div className="flex items-center gap-2 text-sm text-slate-500">
              <Loader2 className="w-4 h-4 animate-spin" />
              <span>Agent reasoning...</span>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>
      </div>

      {/* Input */}
      <div className="border-t border-slate-800 p-4">
        <form
          onSubmit={(e) => { e.preventDefault(); handleSend(); }}
          className="max-w-4xl mx-auto flex gap-2"
        >
          <input
            ref={inputRef}
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask a complex question requiring multi-hop reasoning..."
            className="flex-1 px-4 py-3 bg-slate-800 border border-slate-700 rounded-xl text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-purple-500"
          />
          <button
            type="submit"
            disabled={loading || !input.trim()}
            className="px-4 py-3 bg-purple-600 hover:bg-purple-500 disabled:opacity-50 rounded-xl transition-colors"
          >
            <Send className="w-4 h-4" />
          </button>
        </form>
      </div>
    </div>
  );
}