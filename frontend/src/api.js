const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/+$/, '');
let accessToken = null;

export function setAccessToken(token) {
  accessToken = token;
}

export function getAccessToken() {
  return accessToken;
}

export function apiUrl(path) {
  return path.startsWith('http') ? path : `${API_BASE_URL}${path}`;
}

export async function apiFetch(path, options = {}) {
  const headers = new Headers(options.headers || {});
  const url = apiUrl(path);
  const targetOrigin = new URL(url, window.location.origin).origin;
  const apiOrigin = API_BASE_URL
    ? new URL(API_BASE_URL, window.location.origin).origin
    : window.location.origin;
  const isApiRequest = targetOrigin === apiOrigin;
  if (accessToken && isApiRequest) headers.set('Authorization', `Bearer ${accessToken}`);
  const response = await fetch(url, { ...options, headers, credentials: 'omit' });
  if (response.status === 401 && isApiRequest && !path.includes('/api/v1/auth/google')) {
    accessToken = null;
    window.dispatchEvent(new Event('personal-agent:unauthorized'));
  }
  return response;
}

export function apiErrorMessage(data, fallback = 'The request failed.') {
  return data?.error?.message || data?.detail || data?.error || data?.reply || fallback;
}
