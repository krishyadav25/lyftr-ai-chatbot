export function ChatMessage({ item }) {
  if (item.role === 'user') {
    return (
      <div className="message-row message-row-user">
        <div className="message-bubble message-bubble-user">
          <div className="message-content">{item.content}</div>
        </div>
      </div>
    );
  }

  if (item.role === 'error') {
    return (
      <div className="message-row message-row-error" role="alert">
        <div className="error-card">
          <div className="error-header">
            <span className="error-badge">
              {item.status ? `HTTP ${item.status}` : 'Error'}
            </span>
            <span className="error-title">Request failed</span>
          </div>
          <p className="error-body">{item.content}</p>
        </div>
      </div>
    );
  }

  const meta = item.metadata || {};
  const isCacheHit = meta.resolution_source === 'LLM_CACHE';

  return (
    <div className="message-row message-row-assistant">
      <div className="assistant-avatar" aria-hidden="true">
        L
      </div>
      <div className="assistant-card" data-testid="assistant-message">
        <div className="message-bubble message-bubble-assistant">
          <div className="message-content">{item.content}</div>
        </div>

        <div className="metadata-bar" aria-label="Response metadata">
          <span
            data-testid="meta-source"
            className={`meta-badge ${isCacheHit ? 'meta-badge-cache' : 'meta-badge-live'}`}
          >
            {meta.resolution_source}
          </span>

          <span className="meta-item">
            <span className="meta-label">Model</span>
            <span data-testid="meta-model" className="meta-value">
              {meta.model}
            </span>
          </span>

          <span className="meta-item">
            <span className="meta-label">Latency</span>
            <span data-testid="meta-latency" className="meta-value">
              {`${meta.latency_ms} ms`}
            </span>
          </span>

          <span className="meta-item">
            <span className="meta-label">In</span>
            <span data-testid="meta-input-tokens" className="meta-value">
              {meta.input_tokens}
            </span>
          </span>

          <span className="meta-item">
            <span className="meta-label">Out</span>
            <span data-testid="meta-output-tokens" className="meta-value">
              {meta.output_tokens}
            </span>
          </span>
        </div>
      </div>
    </div>
  );
}
