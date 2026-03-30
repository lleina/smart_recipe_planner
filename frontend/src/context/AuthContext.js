/**
 * Authentication state provider for the Smart Recipe Planner.
 *
 * Manages the full auth lifecycle — local-only onboarding, lazy backend
 * registration, JWT token storage, transparent token refresh, and logout.
 *
 * Offline-first design:
 *   1. localSetup() — creates a local-only user identity (no server call).
 *      Used during onboarding so users can complete setup without a network
 *      connection.
 *   2. ensureRegistered() — lazily creates a real backend account the first
 *      time server state is required (e.g. on the first recipe fetch).
 *      Subsequent calls are no-ops if the user is already registered.
 *
 * Token lifecycle:
 *   - Access tokens (JWT, ~1-day TTL) are stored in expo-secure-store.
 *   - Refresh tokens (~30-day TTL) are used for transparent renewal via the
 *     refreshToken callback registered with the API client.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import * as SecureStore from 'expo-secure-store';

import { abortAllPendingRequests, setAccessToken, setRefreshTokenHandler } from '../services/api';
import { register } from '../services/authService';
import { API_BASE_URL } from '../constants/config';

const AuthContext = createContext(null);

const SECURE_STORE_KEYS = {
  ACCESS_TOKEN: 'access_token',
  REFRESH_TOKEN: 'refresh_token',
  USER_ID: 'user_id',
  LOCAL_ONLY: 'local_only',
  ONBOARDED: 'onboarded',
};

/**
 * Provides authentication state and actions to the component tree.
 *
 * @param {{ children: React.ReactNode }} props
 */
export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isOnboarded, setIsOnboarded] = useState(false);

  // Used to deduplicate concurrent ensureRegistered() calls.
  const pendingRegistrationRef = useRef(null);

  // ── Initialization ────────────────────────────────────────────────────────

  /**
   * Restore auth state from secure storage on cold start.
   * Handles both fully-registered users (JWT tokens) and local-only users.
   */
  const loadStoredAuthState = useCallback(async () => {
    try {
      const [accessToken, storedUserId, onboardedFlag, localOnlyFlag] = await Promise.all([
        SecureStore.getItemAsync(SECURE_STORE_KEYS.ACCESS_TOKEN),
        SecureStore.getItemAsync(SECURE_STORE_KEYS.USER_ID),
        SecureStore.getItemAsync(SECURE_STORE_KEYS.ONBOARDED),
        SecureStore.getItemAsync(SECURE_STORE_KEYS.LOCAL_ONLY),
      ]);

      if (accessToken && storedUserId) {
        // Fully registered user — restore JWT and user identity.
        setAccessToken(accessToken);
        setUser({ id: storedUserId });
        setIsOnboarded(onboardedFlag === 'true');
      } else if (localOnlyFlag === 'true' && storedUserId) {
        // Local-only user — no JWT yet; pending backend registration.
        setUser({ id: storedUserId, localOnly: true });
        setIsOnboarded(onboardedFlag === 'true');
      }
    } catch {
      // Secure store read failed (e.g. keychain unavailable) — user must log in.
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadStoredAuthState();
  }, [loadStoredAuthState]);

  // ── Auth actions ──────────────────────────────────────────────────────────

  /**
   * Create a local-only user identity without contacting the backend.
   *
   * The local ID is a timestamp + random suffix; it is replaced with the
   * real backend user ID when ensureRegistered() is called.
   */
  const localSetup = useCallback(async () => {
    const localUserId = `local_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
    await Promise.all([
      SecureStore.setItemAsync(SECURE_STORE_KEYS.USER_ID, localUserId),
      SecureStore.setItemAsync(SECURE_STORE_KEYS.LOCAL_ONLY, 'true'),
    ]);
    setUser({ id: localUserId, localOnly: true });
  }, []);

  /**
   * Store JWT tokens from the backend and set the user as fully authenticated.
   *
   * @param {string} accessToken - Short-lived JWT access token.
   * @param {string} refreshTokenValue - Long-lived refresh token.
   * @param {string} userId - Backend user ID (UUID).
   */
  const login = useCallback(async (accessToken, refreshTokenValue, userId) => {
    await Promise.all([
      SecureStore.setItemAsync(SECURE_STORE_KEYS.ACCESS_TOKEN, accessToken),
      SecureStore.setItemAsync(SECURE_STORE_KEYS.REFRESH_TOKEN, refreshTokenValue),
      SecureStore.setItemAsync(SECURE_STORE_KEYS.USER_ID, userId),
      SecureStore.deleteItemAsync(SECURE_STORE_KEYS.LOCAL_ONLY),
    ]);
    setAccessToken(accessToken);
    setUser({ id: userId });
  }, []);

  /**
   * Lazily register the local-only user with the backend.
   *
   * Safe to call multiple times concurrently — deduplicates in-flight requests
   * so only one registration call is made even if called simultaneously.
   * Returns immediately if the user is already fully registered.
   *
   * @throws {Error} If the backend registration request fails.
   */
  const ensureRegistered = useCallback(async () => {
    const storedToken = await SecureStore.getItemAsync(SECURE_STORE_KEYS.ACCESS_TOKEN);
    if (storedToken) return; // Already registered — nothing to do.

    if (pendingRegistrationRef.current) {
      return pendingRegistrationRef.current; // Deduplicate concurrent calls.
    }

    pendingRegistrationRef.current = (async () => {
      try {
        const guestEmail = `guest_${Date.now()}@app.local`;
        const guestPassword = `guest_${Date.now()}`;
        const registrationData = await register(guestEmail, guestPassword);
        await login(
          registrationData.accessToken,
          registrationData.refreshToken,
          registrationData.userId,
        );
      } finally {
        pendingRegistrationRef.current = null;
      }
    })();

    return pendingRegistrationRef.current;
  }, [login]);

  /**
   * Clear all stored auth state and cancel any in-flight API requests.
   *
   * Cancels pending requests immediately to prevent stale API calls from
   * completing after the session is cleared.
   */
  const logout = useCallback(async () => {
    abortAllPendingRequests();
    await Promise.all([
      SecureStore.deleteItemAsync(SECURE_STORE_KEYS.ACCESS_TOKEN),
      SecureStore.deleteItemAsync(SECURE_STORE_KEYS.REFRESH_TOKEN),
      SecureStore.deleteItemAsync(SECURE_STORE_KEYS.USER_ID),
      SecureStore.deleteItemAsync(SECURE_STORE_KEYS.ONBOARDED),
      SecureStore.deleteItemAsync(SECURE_STORE_KEYS.LOCAL_ONLY),
    ]);
    setAccessToken(null);
    setUser(null);
    setIsOnboarded(false);
  }, []);

  /**
   * Mark the onboarding flow as complete and persist the flag to secure storage.
   */
  const completeOnboarding = useCallback(async () => {
    await SecureStore.setItemAsync(SECURE_STORE_KEYS.ONBOARDED, 'true');
    setIsOnboarded(true);
  }, []);

  /**
   * Silently refresh the access token using the stored refresh token.
   *
   * Called automatically by the API client on any 401 response. If the
   * refresh token is missing or the refresh request fails, logs the user out.
   *
   * @returns {Promise<string|null>} The new access token, or null on failure.
   */
  const refreshAccessToken = useCallback(async () => {
    try {
      const storedRefreshToken = await SecureStore.getItemAsync(SECURE_STORE_KEYS.REFRESH_TOKEN);
      if (!storedRefreshToken) return null;

      const response = await fetch(`${API_BASE_URL}/auth/refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: storedRefreshToken }),
      });

      if (!response.ok) {
        await logout();
        return null;
      }

      const responseData = await response.json();
      const newAccessToken = responseData.access_token;
      await SecureStore.setItemAsync(SECURE_STORE_KEYS.ACCESS_TOKEN, newAccessToken);
      setAccessToken(newAccessToken);
      return newAccessToken;
    } catch {
      await logout();
      return null;
    }
  }, [logout]);

  // Register the refresh callback with the API client whenever it changes.
  useEffect(() => {
    setRefreshTokenHandler(refreshAccessToken);
  }, [refreshAccessToken]);

  // ── Context value ─────────────────────────────────────────────────────────

  const contextValue = useMemo(() => ({
    user,
    isLoading,
    isOnboarded,
    isAuthenticated: !!user,
    localSetup,
    login,
    logout,
    completeOnboarding,
    ensureRegistered,
  }), [
    user,
    isLoading,
    isOnboarded,
    localSetup,
    login,
    logout,
    completeOnboarding,
    ensureRegistered,
  ]);

  return (
    <AuthContext.Provider value={contextValue}>
      {children}
    </AuthContext.Provider>
  );
}

/**
 * Hook to consume AuthContext.
 *
 * @returns {object} Auth state and actions from the nearest AuthProvider.
 * @throws {Error} If called outside an AuthProvider.
 */
export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used inside an AuthProvider');
  }
  return context;
};
