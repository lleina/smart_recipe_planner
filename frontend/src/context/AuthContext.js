/**
 * Auth state provider.
 * Manages authentication state, token storage, and login/logout flow.
 *
 * Supports offline-first onboarding:
 *   - localSetup() creates a local-only user (no server call)
 *   - ensureRegistered() lazily registers with backend when server is needed
 */

import { createContext, useContext, useState, useEffect, useCallback, useMemo, useRef } from 'react';
import * as SecureStore from 'expo-secure-store';
import { setAccessToken, setRefreshTokenHandler, abortAllPendingRequests } from '../services/api';
import { register } from '../services/authService';

const AuthContext = createContext(null);

const ACCESS_TOKEN_KEY = 'access_token';
const REFRESH_TOKEN_KEY = 'refresh_token';
const USER_ID_KEY = 'user_id';
const LOCAL_ONLY_KEY = 'local_only';

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isOnboarded, setIsOnboarded] = useState(false);

  useEffect(() => {
    loadStoredAuth();
  }, []);

  const loadStoredAuth = async () => {
    try {
      const [token, userId, onboarded, localOnly] = await Promise.all([
        SecureStore.getItemAsync(ACCESS_TOKEN_KEY),
        SecureStore.getItemAsync(USER_ID_KEY),
        SecureStore.getItemAsync('onboarded'),
        SecureStore.getItemAsync(LOCAL_ONLY_KEY),
      ]);

      if (token && userId) {
        // Fully registered user with JWT
        setAccessToken(token);
        setUser({ id: userId });
        setIsOnboarded(onboarded === 'true');
      } else if (localOnly === 'true' && userId) {
        // Local-only user (not yet registered with backend)
        setUser({ id: userId, localOnly: true });
        setIsOnboarded(onboarded === 'true');
      }
    } catch {
      // Token retrieval failed - user will need to log in
    } finally {
      setIsLoading(false);
    }
  };

  /**
   * Creates a local-only user identity. No server call required.
   * Used during offline-first onboarding.
   */
  const localSetup = useCallback(async () => {
    const localId = `local_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
    await Promise.all([
      SecureStore.setItemAsync(USER_ID_KEY, localId),
      SecureStore.setItemAsync(LOCAL_ONLY_KEY, 'true'),
    ]);
    setUser({ id: localId, localOnly: true });
  }, []);

  /**
   * Full login with real JWT tokens from the backend.
   */
  const login = useCallback(async (accessToken, refreshToken, userId) => {
    await Promise.all([
      SecureStore.setItemAsync(ACCESS_TOKEN_KEY, accessToken),
      SecureStore.setItemAsync(REFRESH_TOKEN_KEY, refreshToken),
      SecureStore.setItemAsync(USER_ID_KEY, userId),
      SecureStore.deleteItemAsync(LOCAL_ONLY_KEY),
    ]);
    setAccessToken(accessToken);
    setUser({ id: userId });
  }, []);

  /**
   * Lazily registers with backend when server access is first needed.
   * If already registered, returns immediately. Throws on network failure.
   */
  const registeringRef = useRef(null);
  const ensureRegistered = useCallback(async () => {
    // Already have a real JWT
    const token = await SecureStore.getItemAsync(ACCESS_TOKEN_KEY);
    if (token) return;

    // Deduplicate concurrent calls
    if (registeringRef.current) return registeringRef.current;

    registeringRef.current = (async () => {
      try {
        const email = `guest_${Date.now()}@app.local`;
        const password = `guest_${Date.now()}`;
        const data = await register(email, password);
        await login(data.accessToken, data.refreshToken, data.userId);
      } finally {
        registeringRef.current = null;
      }
    })();

    return registeringRef.current;
  }, [login]);

  const logout = useCallback(async () => {
    // Cancel every in-flight API request immediately so no stale calls
    // complete after the user's session is cleared.
    abortAllPendingRequests();
    await Promise.all([
      SecureStore.deleteItemAsync(ACCESS_TOKEN_KEY),
      SecureStore.deleteItemAsync(REFRESH_TOKEN_KEY),
      SecureStore.deleteItemAsync(USER_ID_KEY),
      SecureStore.deleteItemAsync('onboarded'),
      SecureStore.deleteItemAsync(LOCAL_ONLY_KEY),
    ]);
    setAccessToken(null);
    setUser(null);
    setIsOnboarded(false);
  }, []);

  const completeOnboarding = useCallback(async () => {
    await SecureStore.setItemAsync('onboarded', 'true');
    setIsOnboarded(true);
  }, []);

  const refreshToken = useCallback(async () => {
    try {
      const stored = await SecureStore.getItemAsync(REFRESH_TOKEN_KEY);
      if (!stored) return null;
      const response = await fetch(`${require('../constants/config').API_BASE_URL}/auth/refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: stored }),
      });
      if (!response.ok) {
        await logout();
        return null;
      }
      const data = await response.json();
      const newToken = data.access_token;
      await SecureStore.setItemAsync(ACCESS_TOKEN_KEY, newToken);
      setAccessToken(newToken);
      return newToken;
    } catch {
      await logout();
      return null;
    }
  }, [logout]);

  useEffect(() => {
    setRefreshTokenHandler(refreshToken);
  }, [refreshToken]);

  const value = useMemo(() => ({
    user,
    isLoading,
    isOnboarded,
    isAuthenticated: !!user,
    localSetup,
    login,
    logout,
    completeOnboarding,
    ensureRegistered,
  }), [user, isLoading, isOnboarded, localSetup, login, logout, completeOnboarding, ensureRegistered]);

  return (
    <AuthContext.Provider value={value}>
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};
