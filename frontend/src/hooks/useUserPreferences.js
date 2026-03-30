/**
 * Hook for reading and writing user preferences.
 * Manages local cache with backend sync.
 */

import { useState, useEffect, useCallback } from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { useAuth } from '../context/AuthContext';
import { getPreferences, updatePreferences } from '../services/userService';

const PREFS_CACHE_KEY = '@user_preferences';

const DEFAULT_PREFERENCES = {
  cuisinePreferences: [],
  dietaryRestrictions: [],
  intolerances: [],
  diet: null,
  healthGoal: 'none',
  timePreference: 'moderate',
  mealPrep: false,
  cookingEquipment: [],
  perishableOptimizationPreference: true,
};

export default function useUserPreferences() {
  const { user } = useAuth();
  const [preferences, setPreferences] = useState(DEFAULT_PREFERENCES);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (user?.id) loadPreferences();
  }, [user?.id]);

  /**
   * Loads user preferences from local cache first, then syncs from the backend.
   * Sets loading/error state accordingly.
   */
  const loadPreferences = async () => {
    setLoading(true);
    setError(null);
    try {
      const cached = await AsyncStorage.getItem(PREFS_CACHE_KEY);
      if (cached) setPreferences(JSON.parse(cached));

      const remote = await getPreferences();
      setPreferences(remote);
      await AsyncStorage.setItem(PREFS_CACHE_KEY, JSON.stringify(remote));
    } catch (err) {
      setError(err.message || 'Failed to load preferences');
    } finally {
      setLoading(false);
    }
  };

  /**
   * Merges `updated` fields into current preferences and persists to cache and backend.
   * @param {Partial<object>} updated - Fields to update.
   */
  const savePreferences = useCallback(async (updated) => {
    setError(null);
    try {
      const merged = { ...preferences, ...updated };
      setPreferences(merged);
      await AsyncStorage.setItem(PREFS_CACHE_KEY, JSON.stringify(merged));

      if (user?.id) {
        await updatePreferences(merged);
      }
    } catch (err) {
      setError(err.message || 'Failed to save preferences');
    }
  }, [preferences, user?.id]);

  return { preferences, loading, error, savePreferences, reload: loadPreferences };
}
