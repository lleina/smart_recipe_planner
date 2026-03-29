/**
 * Tests for clearAllPersistedData — the "Clear All App Data" logic.
 *
 * Verifies that every piece of persisted state (AsyncStorage + SecureStore)
 * is wiped so the app restarts in a truly fresh state after the operation.
 */

// --- Module mocks (must come before any import of the module under test) ------

jest.mock('@react-native-async-storage/async-storage', () => ({
  getAllKeys: jest.fn(),
  multiRemove: jest.fn(),
}));

jest.mock('expo-secure-store', () => ({
  deleteItemAsync: jest.fn(),
}));

// --- Now import the module under test ----------------------------------------

import { clearAllPersistedData, SECURE_STORE_KEYS } from '../../src/services/storageService';

// Import the mocked modules to access their jest.fn() instances
import AsyncStorage from '@react-native-async-storage/async-storage';
import * as SecureStore from 'expo-secure-store';

const mockGetAllKeys = AsyncStorage.getAllKeys;
const mockMultiRemove = AsyncStorage.multiRemove;
const mockDeleteItemAsync = SecureStore.deleteItemAsync;

// ---------------------------------------------------------------------------

beforeEach(() => {
  jest.clearAllMocks();
  // Happy-path defaults
  mockGetAllKeys.mockResolvedValue([]);
  mockMultiRemove.mockResolvedValue(undefined);
  mockDeleteItemAsync.mockResolvedValue(undefined);
});

// ---------------------------------------------------------------------------

describe('SECURE_STORE_KEYS', () => {
  test('contains all keys written by AuthContext', () => {
    expect(SECURE_STORE_KEYS).toEqual(
      expect.arrayContaining([
        'access_token',
        'refresh_token',
        'user_id',
        'onboarded',
        'local_only',
      ]),
    );
    // Exact length check — update both files if a new key is added to AuthContext
    expect(SECURE_STORE_KEYS).toHaveLength(5);
  });
});

describe('clearAllPersistedData', () => {
  // --- AsyncStorage --------------------------------------------------------

  test('clears all AsyncStorage keys when keys exist', async () => {
    const keys = ['@prefs', '@history', '@saved'];
    mockGetAllKeys.mockResolvedValue(keys);

    await clearAllPersistedData();

    expect(mockGetAllKeys).toHaveBeenCalledTimes(1);
    expect(mockMultiRemove).toHaveBeenCalledWith(keys);
  });

  test('does not call multiRemove when AsyncStorage is already empty', async () => {
    mockGetAllKeys.mockResolvedValue([]);

    await clearAllPersistedData();

    expect(mockMultiRemove).not.toHaveBeenCalled();
  });

  test('handles AsyncStorage with many keys', async () => {
    const manyKeys = Array.from({ length: 50 }, (_, i) => `@key_${i}`);
    mockGetAllKeys.mockResolvedValue(manyKeys);

    await clearAllPersistedData();

    expect(mockMultiRemove).toHaveBeenCalledWith(manyKeys);
  });

  // --- SecureStore ---------------------------------------------------------

  test('deletes every key in SECURE_STORE_KEYS', async () => {
    await clearAllPersistedData();

    expect(mockDeleteItemAsync).toHaveBeenCalledTimes(SECURE_STORE_KEYS.length);
    for (const key of SECURE_STORE_KEYS) {
      expect(mockDeleteItemAsync).toHaveBeenCalledWith(key);
    }
  });

  test('deletes access_token', async () => {
    await clearAllPersistedData();
    expect(mockDeleteItemAsync).toHaveBeenCalledWith('access_token');
  });

  test('deletes refresh_token', async () => {
    await clearAllPersistedData();
    expect(mockDeleteItemAsync).toHaveBeenCalledWith('refresh_token');
  });

  test('deletes user_id', async () => {
    await clearAllPersistedData();
    expect(mockDeleteItemAsync).toHaveBeenCalledWith('user_id');
  });

  test('deletes onboarded flag (used by index.js for routing)', async () => {
    await clearAllPersistedData();
    expect(mockDeleteItemAsync).toHaveBeenCalledWith('onboarded');
  });

  test('deletes local_only flag', async () => {
    await clearAllPersistedData();
    expect(mockDeleteItemAsync).toHaveBeenCalledWith('local_only');
  });

  // --- Order guarantees ----------------------------------------------------

  test('clears AsyncStorage before SecureStore', async () => {
    const callOrder = [];
    mockGetAllKeys.mockImplementation(async () => { callOrder.push('getAllKeys'); return ['@x']; });
    mockMultiRemove.mockImplementation(async () => { callOrder.push('multiRemove'); });
    mockDeleteItemAsync.mockImplementation(async () => { callOrder.push('deleteItem'); });

    await clearAllPersistedData();

    expect(callOrder[0]).toBe('getAllKeys');
    expect(callOrder[1]).toBe('multiRemove');
    // SecureStore deletes come after
    expect(callOrder.slice(2)).toEqual(
      expect.arrayContaining(['deleteItem']),
    );
  });

  // --- Error propagation ---------------------------------------------------

  test('throws if AsyncStorage.getAllKeys fails', async () => {
    mockGetAllKeys.mockRejectedValue(new Error('AsyncStorage unavailable'));

    await expect(clearAllPersistedData()).rejects.toThrow('AsyncStorage unavailable');
  });

  test('throws if AsyncStorage.multiRemove fails', async () => {
    mockGetAllKeys.mockResolvedValue(['@key']);
    mockMultiRemove.mockRejectedValue(new Error('multiRemove failed'));

    await expect(clearAllPersistedData()).rejects.toThrow('multiRemove failed');
  });

  test('throws if any SecureStore deletion fails', async () => {
    mockDeleteItemAsync.mockRejectedValue(new Error('SecureStore locked'));

    await expect(clearAllPersistedData()).rejects.toThrow('SecureStore locked');
  });

  // --- Completeness (regression against previous partial-clear bug) --------

  test('regression: does not skip any SecureStore key (old bug: only deleted onboarded)', async () => {
    await clearAllPersistedData();

    // The old inline code only called SecureStore.deleteItemAsync('onboarded').
    // This verifies ALL five keys are now deleted, not just one.
    const deletedKeys = mockDeleteItemAsync.mock.calls.map(([k]) => k);
    expect(deletedKeys).toContain('access_token');
    expect(deletedKeys).toContain('refresh_token');
    expect(deletedKeys).toContain('user_id');
    expect(deletedKeys).toContain('onboarded');
    expect(deletedKeys).toContain('local_only');
    // And nothing was duplicated
    expect(new Set(deletedKeys).size).toBe(deletedKeys.length);
  });

  test('regression: AsyncStorage is cleared, not just SecureStore', async () => {
    const keys = ['@prefs/cuisines', '@prefs/dietary'];
    mockGetAllKeys.mockResolvedValue(keys);

    await clearAllPersistedData();

    // Ensures full AsyncStorage wipe, not partial
    expect(mockMultiRemove).toHaveBeenCalledWith(keys);
  });
});
