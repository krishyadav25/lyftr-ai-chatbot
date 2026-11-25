import { useEffect, useRef, useState } from 'react';
import { fetchHealth, sendChatMessage } from './api/chatApi';
import { ChatComposer } from './components/ChatComposer';
import { ChatMessage } from './components/ChatMessage';
import { Sidebar } from './components/Sidebar';
import { generateSessionId } from './utils/session';
import './App.css';

const SUGGESTED_PROMPTS = [
  'What is the capital of France?',
  'Explain API key failover in 2 sentences.',
  'Why does response caching reduce LLM latency?',
  'Give me 3 tips for writing clean FastAPI endpoints.',
];

function App() {
  const [sessionId, setSessionId] = useState(() => generateSessionId());
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [systemPrompt, setSystemPrompt] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [healthStatus, setHealthStatus] = useState(null);
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);

  const messagesEndRef = useRef(null);

  useEffect(() => {
    let active = true;
    fetchHealth()
      .then((result) => {
        if (active) {
          setHealthStatus(result);
        }
      })
      .catch(() => {
        if (active) {
          setHealthStatus({ ok: false, status: 0, data: null });
        }
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isLoading]);

  const handleNewChat = () => {
    if (isLoading) return;
    setSessionId(generateSessionId());
    setMessages([]);
    setInput('');
  };

  const handleSend = async (overrideMessage) => {
    const rawMessage = typeof overrideMessage === 'string' ? overrideMessage : input;
    const trimmed = rawMessage.trim();
    if (!trimmed || isLoading) return;

    const userMsgId = `u-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
    const userMessageItem = {
      id: userMsgId,
      role: 'user',
      content: trimmed,
    };

    setMessages((prev) => [...prev, userMessageItem]);
    setIsLoading(true);

    try {
      const response = await sendChatMessage({
        sessionId,
        message: trimmed,
        systemPrompt,
      });

      const assistantItem = {
        id: `a-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
        role: 'assistant',
        content: response.reply,
        metadata: response.metadata,
      };

      setMessages((prev) => [...prev, assistantItem]);
      // Clear composer only after successful submission
      if (typeof overrideMessage !== 'string') {
        setInput('');
      }
    } catch (error) {
      const errorItem = {
        id: `e-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
        role: 'error',
        status: error.status || 0,
        content: error.message || 'An unexpected error occurred.',
      };
      setMessages((prev) => [...prev, errorItem]);
      // Keep failed message text in the composer so the user can edit or retry
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="app-shell">
      <Sidebar
        sessionId={sessionId}
        systemPrompt={systemPrompt}
        onSystemPromptChange={setSystemPrompt}
        onNewChat={handleNewChat}
        healthStatus={healthStatus}
        isOpen={isSidebarOpen}
        onClose={() => setIsSidebarOpen(false)}
        isLoading={isLoading}
      />

      <main className="chat-main">
        <header className="mobile-header">
          <button
            type="button"
            className="menu-toggle-btn"
            onClick={() => setIsSidebarOpen(true)}
            aria-label="Open menu"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <line x1="3" y1="6" x2="21" y2="6" />
              <line x1="3" y1="12" x2="21" y2="12" />
              <line x1="3" y1="18" x2="21" y2="18" />
            </svg>
          </button>
          <span className="mobile-brand">Lyftr AI</span>
          <button
            type="button"
            className="mobile-new-chat-btn"
            onClick={handleNewChat}
            disabled={isLoading}
          >
            + New
          </button>
        </header>

        <div className="chat-scroll-area">
          {messages.length === 0 ? (
            <div className="empty-state">
              <div className="empty-badge">LiteLLM Gateway &bull; Key Failover &bull; Caching</div>
              <h2 className="empty-title">How can I help you today?</h2>
              <p className="empty-subtitle">
                Every response displays real-time inference source, model, latency, and
                per-request token usage.
              </p>
              <div className="suggested-grid">
                {SUGGESTED_PROMPTS.map((prompt) => (
                  <button
                    key={prompt}
                    type="button"
                    className="suggested-card"
                    onClick={() => handleSend(prompt)}
                    disabled={isLoading}
                  >
                    {prompt}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="messages-list">
              {messages.map((item) => (
                <ChatMessage key={item.id} item={item} />
              ))}

              {isLoading && (
                <div className="message-row message-row-assistant" aria-live="polite">
                  <div className="assistant-avatar" aria-hidden="true">
                    L
                  </div>
                  <div className="loading-bubble">
                    <span className="typing-dot" />
                    <span className="typing-dot" />
                    <span className="typing-dot" />
                    <span className="loading-label">Generating reply...</span>
                  </div>
                </div>
              )}
              <div ref={messagesEndRef} />
            </div>
          )}
        </div>

        <footer className="composer-container">
          <ChatComposer
            input={input}
            onInputChange={setInput}
            onSubmit={() => handleSend()}
            isLoading={isLoading}
          />
        </footer>
      </main>
    </div>
  );
}

export default App;
