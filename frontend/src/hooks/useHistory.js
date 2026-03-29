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

  useEffect(() => {
    if (user?.id) loadHistory();
  }, [user?.id]);

  const loadHistory = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getHistory(user.id);
      setHistory(data);
    } catch (err) {
      setError(err.message || 'Failed to load history');
    } finally {
      setLoading(false);
    }
  };

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
