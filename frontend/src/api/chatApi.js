const RAW_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';
export const API_BASE_URL = RAW_BASE_URL.replace(/\/+$/, '');

/**
 * Custom error carrying HTTP status code and parsed backend detail.
 */
export class ApiError extends Error {
  constructor(message, status = 0) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

/**
 * Format FastAPI error payloads into a clean, readable message.
 */
function formatErrorDetail(detail, status) {
  if (typeof detail === 'string' && detail.trim()) {
    return detail;
  }
  if (Array.isArray(detail) && detail.length > 0) {
    const messages = detail
      .map((item) => {
        if (item && typeof item === 'object' && item.msg) {
          return item.msg;
        }
        return String(item);
      })
      .filter(Boolean);
    if (messages.length > 0) {
      return messages.join('; ');
    }
  }
  if (status === 422) {
    return 'Invalid request. Please check your message length and format.';
  }
  if (status === 503) {
    return 'all providers unavailable';
  }
  return `Request failed with status ${status}`;
}

/**
 * Check backend health status via GET /health.
 */
export async function fetchHealth() {
  const response = await fetch(`${API_BASE_URL}/health`, {
    method: 'GET',
    headers: { Accept: 'application/json' },
  });
  const data = await response.json().catch(() => null);
  return { ok: response.ok, status: response.status, data };
}

/**
 * Send a chat turn to POST /chat using the exact backend API contract.
 */
export async function sendChatMessage({ sessionId, message, systemPrompt }) {
  const payload = {
    session_id: sessionId,
    message,
  };

  if (typeof systemPrompt === 'string' && systemPrompt.trim()) {
    payload.system_prompt = systemPrompt.trim();
  }

  let response;
  try {
    response = await fetch(`${API_BASE_URL}/chat`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/json',
      },
      body: JSON.stringify(payload),
    });
  } catch {
    throw new ApiError(
      'Unable to reach the backend server. Please ensure the API is running.',
      0,
    );
  }

  const data = await response.json().catch(() => null);

  if (!response.ok) {
    const detail = formatErrorDetail(data?.detail, response.status);
    throw new ApiError(detail, response.status);
  }

  return data;
}
