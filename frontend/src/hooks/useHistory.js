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

  const removeEntry = useCallback(async (entryId) => {
    try {
      await deleteHistoryEntry(entryId);
      setHistory((prev) => prev.filter((h) => h.id !== entryId));
    } catch (err) {
      setError(err.message || 'Failed to delete history entry');
    }
  }, []);

  return { history, loading, error, addEntry, removeEntry, reload: loadHistory };
}
