export function ChatComposer({ input, onInputChange, onSubmit, isLoading }) {
  const trimmedLength = input.trim().length;
  const isOverLimit = trimmedLength > 4000;
  const canSend = !isLoading && trimmedLength > 0;

  const handleKeyDown = (event) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      if (canSend) {
        onSubmit();
      }
    }
  };

  const handleFormSubmit = (event) => {
    event.preventDefault();
    if (canSend) {
      onSubmit();
    }
  };

  return (
    <form className="composer-form" onSubmit={handleFormSubmit}>
      <div className={`composer-box ${isOverLimit ? 'composer-box-warning' : ''}`}>
        <textarea
          data-testid="chat-input"
          className="composer-textarea"
          value={input}
          onChange={(e) => onInputChange(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask Lyftr AI anything... (Enter to send, Shift+Enter for new line)"
          rows={1}
          disabled={isLoading}
          aria-label="Message input"
        />
        <div className="composer-actions">
          <span className={`char-counter ${isOverLimit ? 'char-counter-over' : ''}`}>
            {trimmedLength > 0 ? `${trimmedLength}/4000` : ''}
          </span>
          <button
            data-testid="send-button"
            type="submit"
            className="send-btn"
            disabled={!canSend}
            aria-label="Send message"
          >
            {isLoading ? (
              <span className="send-spinner" aria-hidden="true" />
            ) : (
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <line x1="22" y1="2" x2="11" y2="13" />
                <polygon points="22 2 15 22 11 13 2 9 22 2" />
              </svg>
            )}
            <span>{isLoading ? 'Sending' : 'Send'}</span>
          </button>
        </div>
      </div>
    </form>
  );
}
