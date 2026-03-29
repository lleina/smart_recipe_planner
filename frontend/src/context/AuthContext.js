/**
 * Auth state provider.
 * Manages authentication state, token storage, and login/logout flow.
 */

import { createContext, useContext, useState, useEffect, useCallback, useMemo } from 'react';
import * as SecureStore from 'expo-secure-store';
import { setAccessToken, setRefreshTokenHandler } from '../services/api';

const AuthContext = createContext(null);

const ACCESS_TOKEN_KEY = 'access_token';
const REFRESH_TOKEN_KEY = 'refresh_token';
const USER_ID_KEY = 'user_id';

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isOnboarded, setIsOnboarded] = useState(false);

  useEffect(() => {
    loadStoredAuth();
  }, []);

  const loadStoredAuth = async () => {
    try {
      const [token, userId, onboarded] = await Promise.all([
        SecureStore.getItemAsync(ACCESS_TOKEN_KEY),
        SecureStore.getItemAsync(USER_ID_KEY),
        SecureStore.getItemAsync('onboarded'),
      ]);

      if (token && userId) {
        setAccessToken(token);
        setUser({ id: userId });
        setIsOnboarded(onboarded === 'true');
      }
    } catch {
      // Token retrieval failed - user will need to log in
    } finally {
      setIsLoading(false);
    }
  };

  const login = useCallback(async (accessToken, refreshToken, userId) => {
    await Promise.all([
      SecureStore.setItemAsync(ACCESS_TOKEN_KEY, accessToken),
      SecureStore.setItemAsync(REFRESH_TOKEN_KEY, refreshToken),
      SecureStore.setItemAsync(USER_ID_KEY, userId),
    ]);
    setAccessToken(accessToken);
    setUser({ id: userId });
  }, []);

  const logout = useCallback(async () => {
    await Promise.all([
      SecureStore.deleteItemAsync(ACCESS_TOKEN_KEY),
      SecureStore.deleteItemAsync(REFRESH_TOKEN_KEY),
      SecureStore.deleteItemAsync(USER_ID_KEY),
    ]);
    setAccessToken(null);
    setUser(null);
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
    login,
    logout,
    completeOnboarding,
  }), [user, isLoading, isOnboarded, login, logout, completeOnboarding]);

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
