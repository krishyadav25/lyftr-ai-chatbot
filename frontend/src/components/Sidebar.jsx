import { useState } from 'react';

export function Sidebar({
  sessionId,
  systemPrompt,
  onSystemPromptChange,
  onNewChat,
  healthStatus,
  isOpen,
  onClose,
  isLoading,
}) {
  const [isPromptExpanded, setIsPromptExpanded] = useState(true);

  const shortSessionId =
    sessionId.length > 16 ? `${sessionId.slice(0, 8)}...${sessionId.slice(-4)}` : sessionId;

  const isHealthy = healthStatus?.ok && healthStatus?.data?.status === 'ok';

  return (
    <>
      {isOpen && <div className="sidebar-backdrop" onClick={onClose} aria-hidden="true" />}
      <aside className={`sidebar ${isOpen ? 'sidebar-open' : ''}`} aria-label="Chat controls">
        <div className="sidebar-header">
          <div className="brand">
            <div className="brand-icon" aria-hidden="true">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M12 2L2 7l10 5 10-5-10-5z" />
                <path d="M2 17l10 5 10-5" />
                <path d="M2 12l10 5 10-5" />
              </svg>
            </div>
            <div>
              <h1 className="brand-title">Lyftr AI</h1>
              <p className="brand-subtitle">Resilient LLM Gateway</p>
            </div>
          </div>
          <button
            type="button"
            className="sidebar-close-btn"
            onClick={onClose}
            aria-label="Close sidebar"
          >
            &times;
          </button>
        </div>

        <button
          type="button"
          className="new-chat-btn"
          onClick={() => {
            onNewChat();
            onClose();
          }}
          disabled={isLoading}
        >
          <span className="new-chat-plus" aria-hidden="true">+</span>
          New Chat
        </button>

        <div className="sidebar-section">
          <button
            type="button"
            className="collapsible-header"
            onClick={() => setIsPromptExpanded((prev) => !prev)}
            aria-expanded={isPromptExpanded}
          >
            <span>System Prompt</span>
            <span className={`chevron ${isPromptExpanded ? 'chevron-open' : ''}`} aria-hidden="true">
              ▾
            </span>
          </button>

          {isPromptExpanded && (
            <div className="system-prompt-body">
              <textarea
                data-testid="system-prompt-input"
                className="system-prompt-textarea"
                value={systemPrompt}
                onChange={(e) => onSystemPromptChange(e.target.value)}
                placeholder="Optional instructions for the assistant (e.g., Be concise and technical)..."
                rows={4}
                aria-label="System prompt for this session"
              />
              <p className="system-prompt-hint">
                Applied to requests in this session when non-empty.
              </p>
            </div>
          )}
        </div>

        <div className="sidebar-footer">
          <div className="status-card">
            <div className="status-row">
              <span className="status-label">Gateway</span>
              <span className={`status-pill ${isHealthy ? 'status-online' : 'status-offline'}`}>
                <span className="status-dot" aria-hidden="true" />
                {healthStatus === null ? 'Checking...' : isHealthy ? 'Online' : 'Unavailable'}
              </span>
            </div>
            {isHealthy && healthStatus?.data && (
              <div className="status-details">
                <span>Keys: {healthStatus.data.keys_configured}</span>
                <span>Cache: {healthStatus.data.cache_enabled ? 'On' : 'Off'}</span>
              </div>
            )}
            <div className="status-row session-row" title={sessionId}>
              <span className="status-label">Session</span>
              <code className="session-code">{shortSessionId}</code>
            </div>
          </div>
        </div>
      </aside>
    </>
  );
}
