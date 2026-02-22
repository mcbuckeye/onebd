import { useState, useRef, useEffect } from 'react';
import { Send, Database, Brain, Sparkles, RotateCcw } from 'lucide-react';
import MessageBubble from './MessageBubble';
import DealDetailPanel from './DealDetailPanel';
import EntityDetailPanel from './EntityDetailPanel';
import { Message, SearchMode, ChatResponse, SelectedEntity } from '../types';

interface ChatInterfaceProps {
  apiBase: string;
}

export default function ChatInterface({ apiBase }: ChatInterfaceProps) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [mode, setMode] = useState<SearchMode>('auto');
  const [selectedDealId, setSelectedDealId] = useState<number | null>(null);
  const [selectedEntity, setSelectedEntity] = useState<SelectedEntity | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const sendMessage = async () => {
    if (!input.trim() || isLoading) return;

    const userMessage: Message = {
      id: Date.now().toString(),
      role: 'user',
      content: input.trim(),
      timestamp: new Date(),
    };

    setMessages(prev => [...prev, userMessage]);
    setInput('');
    setIsLoading(true);

    try {
      // Build history from previous messages (limit to last 10 for context)
      // Include full user messages and substantial assistant context
      const history = messages.slice(-10).map(m => ({
        role: m.role,
        content: m.role === 'assistant'
          ? `[Assistant response: ${m.content.slice(0, 800)}${m.content.length > 800 ? '...' : ''}]`
          : m.content,  // Send full user messages to preserve entity references
      }));

      const response = await fetch(`${apiBase}/chat`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          message: userMessage.content,
          mode: mode,
          history: history.length > 0 ? history : undefined,
        }),
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const data: ChatResponse = await response.json();

      const assistantMessage: Message = {
        id: (Date.now() + 1).toString(),
        role: 'assistant',
        content: data.response,
        mode: data.mode_used,
        sqlQuery: data.sql_query,
        searchResults: data.search_results,
        timestamp: new Date(),
      };

      setMessages(prev => [...prev, assistantMessage]);
    } catch (error) {
      const errorMessage: Message = {
        id: (Date.now() + 1).toString(),
        role: 'assistant',
        content: `Error: ${error instanceof Error ? error.message : 'Failed to get response'}`,
        timestamp: new Date(),
      };
      setMessages(prev => [...prev, errorMessage]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  const clearChat = () => {
    setMessages([]);
    setInput('');
  };

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <header className="pl-14 lg:pl-6 pr-4 lg:pr-6 py-3 lg:py-4 border-b border-slate-700 bg-slate-800/50 flex items-center justify-between">
        <div className="min-w-0 flex-1">
          <h2 className="text-base lg:text-lg font-semibold text-white truncate">Chat with your data</h2>
          <p className="text-xs lg:text-sm text-slate-400 truncate">
            Ask questions about pharmaceutical deals and contracts
          </p>
        </div>
        {messages.length > 0 && (
          <button
            onClick={clearChat}
            className="flex-shrink-0 flex items-center gap-1 lg:gap-2 px-2 lg:px-3 py-1.5 lg:py-2 text-xs lg:text-sm text-slate-400 hover:text-white hover:bg-slate-700 rounded-lg transition-colors ml-2"
            title="New chat"
          >
            <RotateCcw className="w-4 h-4" />
            <span className="hidden sm:inline">New Chat</span>
          </button>
        )}
      </header>

      {/* Messages Area */}
      <div className="flex-1 overflow-y-auto p-3 lg:p-6 space-y-4 lg:space-y-6">
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full text-center px-4">
            <Sparkles className="w-10 lg:w-12 h-10 lg:h-12 text-blue-400 mb-3 lg:mb-4" />
            <h3 className="text-lg lg:text-xl font-semibold text-white mb-2">
              Welcome to Cortellis Search
            </h3>
            <p className="text-sm lg:text-base text-slate-400 max-w-md mb-4 lg:mb-6">
              Ask questions about pharmaceutical deals, companies, financials, or search through contract documents.
            </p>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-2 lg:gap-3 max-w-2xl w-full">
              <ExampleQuery
                query="What are the largest deals in 2024?"
                onClick={() => setInput("What are the largest deals in 2024?")}
              />
              <ExampleQuery
                query="Show me deals involving cancer therapies"
                onClick={() => setInput("Show me deals involving cancer therapies")}
              />
              <ExampleQuery
                query="What royalty rates are common in contracts?"
                onClick={() => setInput("What royalty rates are common in contracts?")}
              />
              <ExampleQuery
                query="Find contracts with milestone payment terms"
                onClick={() => setInput("Find contracts with milestone payment terms")}
              />
            </div>
          </div>
        )}

        {messages.map((message) => (
          <MessageBubble
            key={message.id}
            message={message}
            onDealClick={setSelectedDealId}
          />
        ))}

        {isLoading && (
          <div className="flex items-start gap-3">
            <div className="w-8 h-8 rounded-full bg-blue-500/20 flex items-center justify-center">
              <Sparkles className="w-4 h-4 text-blue-400" />
            </div>
            <div className="bg-slate-800 rounded-lg px-4 py-3">
              <div className="flex gap-1">
                <div className="w-2 h-2 bg-slate-500 rounded-full typing-dot" />
                <div className="w-2 h-2 bg-slate-500 rounded-full typing-dot" />
                <div className="w-2 h-2 bg-slate-500 rounded-full typing-dot" />
              </div>
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input Area */}
      <div className="border-t border-slate-700 bg-slate-800/50 p-3 lg:p-4">
        {/* Mode Selector */}
        <div className="flex gap-1.5 lg:gap-2 mb-2 lg:mb-3">
          <ModeButton
            active={mode === 'auto'}
            onClick={() => setMode('auto')}
            icon={<Sparkles className="w-3.5 lg:w-4 h-3.5 lg:h-4" />}
            label="Auto"
            testId="mode-auto"
          />
          <ModeButton
            active={mode === 'sql'}
            onClick={() => setMode('sql')}
            icon={<Database className="w-3.5 lg:w-4 h-3.5 lg:h-4" />}
            label="SQL"
            testId="mode-sql"
          />
          <ModeButton
            active={mode === 'rag'}
            onClick={() => setMode('rag')}
            icon={<Brain className="w-3.5 lg:w-4 h-3.5 lg:h-4" />}
            label="RAG"
            testId="mode-rag"
          />
        </div>

        {/* Input Field */}
        <div className="flex gap-2 lg:gap-3">
          <textarea
            data-testid="chat-input"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask a question..."
            className="flex-1 bg-slate-700 border border-slate-600 rounded-lg px-3 lg:px-4 py-2.5 lg:py-3 text-sm lg:text-base text-white placeholder-slate-400 focus:outline-none focus:border-blue-500 resize-none"
            rows={1}
            disabled={isLoading}
          />
          <button
            data-testid="send-button"
            onClick={sendMessage}
            disabled={!input.trim() || isLoading}
            className="px-3 lg:px-4 py-2.5 lg:py-3 bg-blue-600 hover:bg-blue-500 disabled:bg-slate-600 disabled:cursor-not-allowed rounded-lg text-white transition-colors"
          >
            <Send className="w-4 lg:w-5 h-4 lg:h-5" />
          </button>
        </div>
      </div>

      {/* Deal Detail Panel */}
      {selectedDealId && (
        <DealDetailPanel
          dealId={selectedDealId}
          apiBase={apiBase}
          onClose={() => setSelectedDealId(null)}
          onEntityClick={(entity) => {
            setSelectedDealId(null);
            setSelectedEntity(entity);
          }}
        />
      )}

      {/* Entity Detail Panel */}
      {selectedEntity && (
        <EntityDetailPanel
          entity={selectedEntity}
          apiBase={apiBase}
          onClose={() => setSelectedEntity(null)}
          onDealClick={(dealId) => {
            setSelectedEntity(null);
            setSelectedDealId(dealId);
          }}
        />
      )}
    </div>
  );
}

function ModeButton({ active, onClick, icon, label, testId }: {
  active: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  label: string;
  testId?: string;
}) {
  return (
    <button
      data-testid={testId}
      onClick={onClick}
      className={`flex items-center gap-1 lg:gap-2 px-2 lg:px-3 py-1 lg:py-1.5 rounded-lg text-xs lg:text-sm transition-colors ${
        active
          ? 'bg-blue-600 text-white'
          : 'bg-slate-700 text-slate-300 hover:bg-slate-600'
      }`}
    >
      {icon}
      {label}
    </button>
  );
}

function ExampleQuery({ query, onClick }: { query: string; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="text-left px-3 lg:px-4 py-2 lg:py-3 bg-slate-800 hover:bg-slate-700 border border-slate-700 rounded-lg text-xs lg:text-sm text-slate-300 transition-colors"
    >
      {query}
    </button>
  );
}
