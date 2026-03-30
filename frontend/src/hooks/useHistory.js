/**
 * Hook for cook history CRUD operations.
 */

import { useState, useEffect, useCallback } from 'react';
import { useAuth } from '../context/AuthContext';
import { getHistory, addHistoryEntry, deleteHistoryEntry } from '../services/historyService';
import { trackEvent } from '../services/eventService';

export default function useHistory() {
  const { user } = useAuth();
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  /**
   * Fetches cook history entries from the backend and updates local state.
   * No-ops when no user is authenticated.
   */
  const loadHistory = useCallback(async () => {
    if (!user?.id) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    try {
      const data = await getHistory(user.id);
      if (!cancelled) setHistory(data);
    } catch (err) {
      // AbortError means logout cleared this request — silently ignore
      if (!cancelled && err?.name !== 'AbortError' && err?.code !== 'ERR_TIMEOUT') {
        setError(err.message || 'Failed to load history');
      }
    } finally {
      if (!cancelled) setLoading(false);
    }
    return () => { cancelled = true; };
  }, [user?.id]);

  useEffect(() => {
    loadHistory();
  }, [loadHistory]);

  /**
   * Records a recipe as cooked and fires a `recipe_cooked` behavior event.
   * @param {string} recipeId - Recipe that was cooked.
   * @param {string} mealType - Meal occasion (e.g., 'dinner').
   * @param {number} servingCount - Number of servings made.
   * @param {string} sessionId - Active session pool id for event attribution.
   */
  const addEntry = useCallback(async (recipeId, mealType, servingCount, sessionId) => {
    if (!user?.id) return;
    try {
      const entry = await addHistoryEntry({
        userId: user.id,
        recipeId,
        mealType,
        servingCount,
        sessionId,
      });
      setHistory((prev) => [entry, ...prev]);
      await trackEvent({
        userId: user.id,
        sessionId,
        recipeId,
        eventType: 'recipe_cooked',
        metadata: { mealType, servingCount },
      });
    } catch (err) {
      setError(err.message || 'Failed to record cooking');
    }
  }, [user?.id]);

  /**
   * Deletes a cook history entry from the backend and removes it from local state.
   * @param {string} entryId - ID of the CookHistory entry to delete.
   */
  const removeEntry = useCallback(async (entryId) => {
    try {
      await deleteHistoryEntry(entryId);
      setHistory((prev) => prev.filter((entry) => entry.id !== entryId));
    } catch (err) {
      setError(err.message || 'Failed to delete history entry');
    }
  }, []);

  return { history, loading, error, addEntry, removeEntry, reload: loadHistory };
}
