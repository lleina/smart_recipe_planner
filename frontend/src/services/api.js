/**
 * Base HTTP client for all backend communication.
 * Handles auth headers, error formatting, and retry logic.
 */

import { API_BASE_URL, API_TIMEOUT_MS } from '../constants/config';

let accessToken = null;
let refreshTokenFn = null;

/**
 * Sets the current access token for authenticated requests.
 * @param {string|null} token
 */
export const setAccessToken = (token) => {
  accessToken = token;
};

/**
 * Returns the current access token (used by services that don't go through apiRequest).
 * @returns {string|null}
 */
export const getAccessToken = () => accessToken;

/**
 * Registers a refresh token callback for transparent token renewal.
 * @param {Function} fn - Async function that returns a new access token.
 */
export const setRefreshTokenHandler = (fn) => {
  refreshTokenFn = fn;
};

/**
 * Makes an HTTP request to the backend API.
 * @param {string} endpoint - Path relative to API_BASE_URL (e.g., '/auth/login').
 * @param {object} options - Fetch options override.
 * @returns {Promise<object>} Parsed JSON response.
 * @throws {ApiError} On non-2xx response or network failure.
 */
export const apiRequest = async (endpoint, options = {}) => {
  const url = `${API_BASE_URL}${endpoint}`;
  const headers = {
    'Content-Type': 'application/json',
    ...options.headers,
  };

  if (accessToken && !options.skipAuth) {
    headers['Authorization'] = `Bearer ${accessToken}`;
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), options.timeout || API_TIMEOUT_MS);

  try {
    const response = await fetch(url, {
      ...options,
      headers,
      signal: controller.signal,
    });

    if (response.status === 401 && refreshTokenFn && !options._isRetry) {
      const newToken = await refreshTokenFn();
      if (newToken) {
        setAccessToken(newToken);
        return apiRequest(endpoint, { ...options, _isRetry: true });
      }
    }

    const data = await response.json().catch(() => null);

    if (!response.ok) {
      throw new ApiError(
        data?.error?.message || `Request failed with status ${response.status}`,
        data?.error?.code || `HTTP_${response.status}`,
        response.status,
        data?.error?.retryable || false,
      );
    }

    return data;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (error.name === 'AbortError') {
      throw new ApiError('Request timed out', 'ERR_TIMEOUT', 408, true);
    }
    throw new ApiError(error.message || 'Network error', 'ERR_NETWORK', 0, true);
  } finally {
    clearTimeout(timeout);
  }
};

/**
 * Standardized API error per NFR-REL-04.
 */
export class ApiError extends Error {
  constructor(message, code, status, retryable) {
    super(message);
    this.name = 'ApiError';
    this.code = code;
    this.status = status;
    this.retryable = retryable;
  }
}

export const get = (endpoint, options) => apiRequest(endpoint, { method: 'GET', ...options });

export const post = (endpoint, body, options) =>
  apiRequest(endpoint, { method: 'POST', body: JSON.stringify(body), ...options });

export const put = (endpoint, body, options) =>
  apiRequest(endpoint, { method: 'PUT', body: JSON.stringify(body), ...options });

export const del = (endpoint, options) => apiRequest(endpoint, { method: 'DELETE', ...options });
