import { useState, useEffect, useRef } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { Send, Sparkles, Database, ChevronRight, Loader2 } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import api from '../lib/api';

interface Message {
  role: 'user' | 'assistant';
  content: string;
  intent?: string;
  confidence?: any;
  followUps?: string[];
  actions?: Array<{ label: string; type: string; params: any }>;
  sqlQuery?: string;
}

export default function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Handle initial query from URL
  useEffect(() => {
    const q = searchParams.get('q');
    if (q && messages.length === 0) {
      handleSend(q);
    }
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleSend = async (text?: string) => {
    const msg = text || input.trim();
    if (!msg || loading) return;
    setInput('');

    const userMsg: Message = { role: 'user', content: msg };
    setMessages(prev => [...prev, userMsg]);
    setLoading(true);

    try {
      const res = await api.post('/chat/v2', {
        message: msg,
        history: messages.slice(-10).map(m => ({ role: m.role, content: m.content })),
      });

      const assistantMsg: Message = {
        role: 'assistant',
        content: res.data.answer,
        intent: res.data.intent,
        confidence: res.data.confidence,
        followUps: res.data.follow_ups,
        actions: res.data.actions,
        sqlQuery: res.data.sql_query,
      };
      setMessages(prev => [...prev, assistantMsg]);
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

  const handleAction = (action: { label: string; type: string; params: any }) => {
    if (action.type === 'navigate') {
      navigate(action.params.path);
    }
  };

  return (
    <div className="flex flex-col h-full">
      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-6">
        {messages.length === 0 && (
          <div className="text-center py-20">
            <Sparkles className="w-12 h-12 text-blue-500/50 mx-auto mb-4" />
            <h2 className="text-xl font-semibold text-slate-300 mb-2">Ask anything about pharma deals</h2>
            <p className="text-sm text-slate-500 mb-6 max-w-md mx-auto">
              Get synthesized answers with supporting data from 145K+ deals, 314K+ SEC filings, and 26K contracts.
            </p>
            <div className="flex flex-wrap gap-2 justify-center max-w-lg mx-auto">
              {[
                'What are the largest ADC deals in oncology?',
                'Compare Pfizer and Merck deal activity',
                'Typical Phase 2 oncology deal values?',
                'Who are the most active acquirers this year?',
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

        <div className="max-w-3xl mx-auto space-y-6">
          {messages.map((msg, i) => (
            <div key={i} className={`${msg.role === 'user' ? 'flex justify-end' : ''}`}>
              {msg.role === 'user' ? (
                <div className="bg-blue-600 text-white px-4 py-2.5 rounded-2xl rounded-br-md max-w-lg text-sm">
                  {msg.content}
                </div>
              ) : (
                <div className="space-y-3">
                  {/* Confidence badge */}
                  {msg.confidence && (
                    <div className="flex items-center gap-2 text-xs text-slate-500">
                      <Database className="w-3 h-3" />
                      <span>{msg.confidence.data_completeness}</span>
                      {msg.confidence.disclosure_rate !== null && (
                        <span>• {msg.confidence.disclosure_rate}% with disclosed values</span>
                      )}
                    </div>
                  )}

                  {/* Answer */}
                  <div className="prose prose-invert prose-sm max-w-none text-slate-300
                    prose-headings:text-slate-200 prose-strong:text-slate-200
                    prose-th:text-slate-400 prose-td:text-slate-300
                    prose-a:text-blue-400">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content}</ReactMarkdown>
                  </div>

                  {/* SQL query (collapsible) */}
                  {msg.sqlQuery && (
                    <details className="text-xs">
                      <summary className="text-slate-600 cursor-pointer hover:text-slate-400">View query</summary>
                      <pre className="mt-1 p-2 bg-slate-800 rounded text-slate-400 overflow-x-auto">{msg.sqlQuery}</pre>
                    </details>
                  )}

                  {/* Follow-ups */}
                  {msg.followUps && msg.followUps.length > 0 && (
                    <div className="flex flex-wrap gap-2 pt-2">
                      {msg.followUps.map(q => (
                        <button
                          key={q}
                          onClick={() => handleSend(q)}
                          className="flex items-center gap-1 px-3 py-1.5 bg-slate-800 border border-slate-700 rounded-lg text-xs text-slate-400 hover:text-slate-200 hover:border-slate-600"
                        >
                          <ChevronRight className="w-3 h-3" /> {q}
                        </button>
                      ))}
                    </div>
                  )}

                  {/* Actions */}
                  {msg.actions && msg.actions.length > 0 && (
                    <div className="flex gap-2 pt-1">
                      {msg.actions.map(a => (
                        <button
                          key={a.label}
                          onClick={() => handleAction(a)}
                          className="px-3 py-1.5 bg-blue-600/10 border border-blue-500/30 rounded-lg text-xs text-blue-400 hover:bg-blue-600/20"
                        >
                          {a.label}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}

          {loading && (
            <div className="flex items-center gap-2 text-sm text-slate-500">
              <Loader2 className="w-4 h-4 animate-spin" /> Analyzing...
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>
      </div>

      {/* Input */}
      <div className="border-t border-slate-800 p-4">
        <form
          onSubmit={(e) => { e.preventDefault(); handleSend(); }}
          className="max-w-3xl mx-auto flex gap-2"
        >
          <input
            ref={inputRef}
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask about deals, companies, valuations, trends..."
            className="flex-1 px-4 py-3 bg-slate-800 border border-slate-700 rounded-xl text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-blue-500"
          />
          <button
            type="submit"
            disabled={loading || !input.trim()}
            className="px-4 py-3 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 rounded-xl transition-colors"
          >
            <Send className="w-4 h-4" />
          </button>
        </form>
      </div>
    </div>
  );
}
