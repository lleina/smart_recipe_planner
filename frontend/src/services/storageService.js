/**
 * Storage service - helpers for clearing persisted app data.
 *
 * Extracted so the clear-all flow can be unit-tested independently of
 * any React context or component.
 */

import AsyncStorage from '@react-native-async-storage/async-storage';
import * as SecureStore from 'expo-secure-store';

/**
 * All SecureStore keys written by AuthContext.
 * Must stay in sync with the constants defined there.
 */
export const SECURE_STORE_KEYS = [
  'access_token',
  'refresh_token',
  'user_id',
  'onboarded',
  'local_only',
];

/**
 * Clears every piece of persisted app data:
 *   1. All AsyncStorage keys (preferences, user data, cache).
 *   2. All SecureStore authentication keys.
 *
 * Throws if any deletion fails so callers can surface the error to the user.
 *
 * NOTE: This only handles persistence. Callers are responsible for also
 * resetting in-memory React state (auth, session, recipes) by calling
 * logout(), resetSession(), and resetRecipes() from their respective contexts.
 */
export const clearAllPersistedData = async () => {
  // 1. AsyncStorage — clear all keys (iOS blocks .clear() in some environments,
  //    so we always enumerate and multiRemove).
  const allKeys = await AsyncStorage.getAllKeys();
  if (allKeys.length > 0) {
    await AsyncStorage.multiRemove(allKeys);
  }

  // 2. SecureStore — delete each key individually (no batch API).
  await Promise.all(
    SECURE_STORE_KEYS.map((key) => SecureStore.deleteItemAsync(key)),
  );
};
