/**
 * Hook for save/unsave recipe actions and saved recipe list management.
 */

import { useState, useEffect, useCallback, useMemo } from 'react';
import { useAuth } from '../context/AuthContext';
import { getSavedRecipes, saveRecipe, unsaveRecipe } from '../services/savedService';
import { trackEvent } from '../services/eventService';

export default function useSavedRecipes() {
  const { user } = useAuth();
  const [savedRecipes, setSavedRecipes] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  /**
   * Fetches the saved recipe list from the backend and updates local state.
   * No-ops for unauthenticated or local-only users.
   */
  const loadSaved = useCallback(async () => {
    if (!user?.id || user?.localOnly) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    try {
      const data = await getSavedRecipes(user.id);
      if (!cancelled) setSavedRecipes(data);
    } catch (err) {
      // AbortError means logout cleared this request — silently ignore
      if (!cancelled && err?.name !== 'AbortError' && err?.code !== 'ERR_TIMEOUT') {
        setError(err.message || 'Failed to load saved recipes');
      }
    } finally {
      if (!cancelled) setLoading(false);
    }
    return () => { cancelled = true; };
  }, [user?.id, user?.localOnly]);  

  useEffect(() => {
    loadSaved();
  }, [loadSaved]);

  /**
   * Saves a recipe and fires a `recipe_saved` behavior event.
   * @param {string} recipeId - ID of the recipe to save.
   * @param {string} sessionId - Active session pool id for event attribution.
   */
  const save = useCallback(async (recipeId, sessionId) => {
    if (!user?.id) return;
    try {
      const entry = await saveRecipe(user.id, recipeId);
      setSavedRecipes((prev) => [entry, ...prev]);
      await trackEvent({
        userId: user.id,
        sessionId,
        recipeId,
        eventType: 'recipe_saved',
      });
    } catch (err) {
      setError(err.message || 'Failed to save recipe');
    }
  }, [user?.id]);

  /**
   * Removes a saved recipe entry from the backend and local state.
   * @param {string} savedEntryId - ID of the SavedRecipe entry (not the recipe id).
   */
  const remove = useCallback(async (savedEntryId) => {
    try {
      await unsaveRecipe(savedEntryId);
      setSavedRecipes((prev) => prev.filter((entry) => entry.id !== savedEntryId));
    } catch (err) {
      setError(err.message || 'Failed to remove saved recipe');
    }
  }, []);

  // O(1) Set lookup — avoids scanning the full array on every card render
  const savedIdSet = useMemo(
    () => new Set(savedRecipes.map((entry) => entry.recipeId)),
    [savedRecipes],
  );

  /**
   * Returns true if the given recipe id is in the saved set.
   * @param {string} recipeId
   * @returns {boolean}
   */
  const isSaved = useCallback((recipeId) => savedIdSet.has(recipeId), [savedIdSet]);

  return { savedRecipes, loading, error, save, remove, isSaved, reload: loadSaved };
}
