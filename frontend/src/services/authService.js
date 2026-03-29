/**
 * Authentication service.
 * Handles register, login, and token refresh with the backend.
 */

import { API_BASE_URL, API_TIMEOUT_MS } from '../constants/config';

/**
 * Register a new user account.
 * @param {string} email
 * @param {string} password
 * @returns {Promise<{accessToken: string, refreshToken: string, userId: string}>}
 */
export const register = async (email, password) => {
  const resp = await fetch(`${API_BASE_URL}/auth/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  });
  const data = await resp.json();
  if (!resp.ok) {
    throw new Error(data.detail || data.error?.message || 'Registration failed');
  }
  return data;
};

/**
 * Log in with existing credentials.
 * @param {string} email
 * @param {string} password
 * @returns {Promise<{accessToken: string, refreshToken: string, userId: string}>}
 */
export const loginUser = async (email, password) => {
  const resp = await fetch(`${API_BASE_URL}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  });
  const data = await resp.json();
  if (!resp.ok) {
    throw new Error(data.detail || data.error?.message || 'Login failed');
  }
  return data;
};
