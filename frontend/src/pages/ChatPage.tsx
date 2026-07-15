import { useState, useEffect, useRef } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { Send, Sparkles, Database, ChevronRight, Loader2, MessageSquare, Plus, Trash2 } from 'lucide-react';
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

interface ConversationSummary {
  id: number;
  title: string;
  message_count: number;
  created_at: string;
  updated_at: string;
}

export default function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [conversationId, setConversationId] = useState<number | null>(null);
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [showHistory, setShowHistory] = useState(false);
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Load conversation list on mount
  useEffect(() => {
    loadConversationList();
  }, []);

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

  const loadConversationList = async () => {
    try {
      const res = await api.get('/conversations?limit=20');
      setConversations(res.data);
    } catch (e) {
      console.error('Failed to load conversations:', e);
    }
  };

  const loadConversation = async (id: number) => {
    try {
      const res = await api.get(`/conversations/${id}`);
      setMessages(res.data.messages.map((m: any) => ({
        role: m.role,
        content: m.content,
        intent: m.intent,
      })));
      setConversationId(id);
      setShowHistory(false);
    } catch (e) {
      console.error('Failed to load conversation:', e);
    }
  };

  const startNewChat = () => {
    setMessages([]);
    setConversationId(null);
    setShowHistory(false);
    inputRef.current?.focus();
  };

  const deleteConversation = async (id: number, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!confirm('Delete this conversation?')) return;
    
    try {
      await api.delete(`/conversations/${id}`);
      setConversations(prev => prev.filter(c => c.id !== id));
      if (conversationId === id) {
        startNewChat();
      }
    } catch (e) {
      console.error('Failed to delete conversation:', e);
    }
  };

  const handleSend = async (text?: string) => {
    const msg = text || input.trim();
    if (!msg || loading) return;
    setInput('');

    const userMsg: Message = { role: 'user', content: msg };
    setMessages(prev => [...prev, userMsg]);
    setLoading(true);

    try {
      // Save user message (fire-and-forget, non-blocking)
      api.post('/conversations/message', {
        conversation_id: conversationId,
        role: 'user',
        content: msg,
      }).then(saveRes => {
        const convId = saveRes.data.conversation_id;
        if (!conversationId) {
          setConversationId(convId);
          loadConversationList(); // Refresh list to show new conversation
        }

        // Get AI response
        api.post('/chat/v2', {
          message: msg,
          history: messages.slice(-10).map(m => ({ role: m.role, content: m.content })),
        }).then(res => {
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

          // Save assistant message (fire-and-forget)
          api.post('/conversations/message', {
            conversation_id: convId,
            role: 'assistant',
            content: res.data.answer,
            intent: res.data.intent,
          }).catch(() => {});

          loadConversationList(); // Refresh to update message count
        }).catch((err: any) => {
          setMessages(prev => [...prev, {
            role: 'assistant',
            content: `Error: ${err.response?.data?.detail || err.message || 'Request failed'}`,
          }]);
        }).finally(() => {
          setLoading(false);
          inputRef.current?.focus();
        });
      }).catch(() => {
        // If save fails, still try to get response
        api.post('/chat/v2', {
          message: msg,
          history: messages.slice(-10).map(m => ({ role: m.role, content: m.content })),
        }).then(res => {
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
        }).catch((err: any) => {
          setMessages(prev => [...prev, {
            role: 'assistant',
            content: `Error: ${err.response?.data?.detail || err.message || 'Request failed'}`,
          }]);
        }).finally(() => {
          setLoading(false);
          inputRef.current?.focus();
        });
      });
    } catch (err: any) {
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: `Error: ${err.response?.data?.detail || err.message || 'Request failed'}`,
      }]);
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
    <div className="flex h-full">
      {/* History Sidebar */}
      {showHistory && (
        <div className="w-64 border-r border-slate-800 overflow-y-auto flex flex-col">
          <div className="p-3 border-b border-slate-800 flex items-center justify-between">
            <span className="text-sm font-medium text-slate-300">Conversations</span>
            <button
              onClick={startNewChat}
              className="flex items-center gap-1 text-xs text-blue-400 hover:text-blue-300"
            >
              <Plus className="w-3 h-3" /> New Chat
            </button>
          </div>
          <div className="flex-1 overflow-y-auto">
            {conversations.map(conv => (
              <button
                key={conv.id}
                onClick={() => loadConversation(conv.id)}
                className={`w-full text-left px-3 py-2 border-b border-slate-800/50 hover:bg-slate-800/50 group relative
                  ${conversationId === conv.id ? 'bg-slate-800' : ''}`}
              >
                <div className="text-sm text-slate-300 truncate pr-6">{conv.title}</div>
                <div className="text-xs text-slate-500">
                  {new Date(conv.updated_at).toLocaleDateString()} • {conv.message_count} msgs
                </div>
                <button
                  onClick={(e) => deleteConversation(conv.id, e)}
                  className="absolute right-2 top-1/2 -translate-y-1/2 opacity-0 group-hover:opacity-100 text-slate-500 hover:text-red-400"
                >
                  <Trash2 className="w-3 h-3" />
                </button>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Main Chat Area */}
      <div className="flex-1 flex flex-col">
        {/* Header with History Toggle */}
        <div className="border-b border-slate-800 px-4 py-3 flex items-center gap-3">
          <button
            onClick={() => setShowHistory(!showHistory)}
            className="flex items-center gap-2 px-3 py-1.5 text-sm text-slate-400 hover:text-slate-200 bg-slate-800 hover:bg-slate-700 rounded-lg transition-colors"
          >
            <MessageSquare className="w-4 h-4" />
            {showHistory ? 'Hide History' : 'Show History'}
          </button>
          {conversationId && !showHistory && (
            <button
              onClick={startNewChat}
              className="flex items-center gap-1 px-3 py-1.5 text-sm text-blue-400 hover:text-blue-300"
            >
              <Plus className="w-3 h-3" /> New Chat
            </button>
          )}
        </div>

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
                  'Compare Pfizer and Merck & Co deal activity',
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
    </div>
  );
}
