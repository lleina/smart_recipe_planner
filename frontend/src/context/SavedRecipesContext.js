/**
 * Shared saved-recipes state.
 * Lifts useSavedRecipes into a context so all screens share the same list —
 * saves/removes from recipe detail or discover both reflect on the Saved tab.
 */

import { createContext, useContext, useState, useEffect, useCallback, useMemo } from 'react';
import { useAuth } from './AuthContext';
import { getSavedRecipes, saveRecipe, unsaveRecipe } from '../services/savedService';
import { trackEvent } from '../services/eventService';

const SavedRecipesContext = createContext(null);

export function SavedRecipesProvider({ children }) {
  const { user } = useAuth();
  const [savedRecipes, setSavedRecipes] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const loadSaved = useCallback(async () => {
    if (!user?.id || user?.localOnly) return;
    setLoading(true);
    setError(null);
    try {
      const data = await getSavedRecipes(user.id);
      setSavedRecipes(data);
    } catch (err) {
      if (err?.name !== 'AbortError' && err?.code !== 'ERR_TIMEOUT') {
        setError(err.message || 'Failed to load saved recipes');
      }
    } finally {
      setLoading(false);
    }
  }, [user?.id, user?.localOnly]);

  useEffect(() => {
    loadSaved();
  }, [loadSaved]);

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

  const remove = useCallback(async (savedEntryId) => {
    try {
      await unsaveRecipe(savedEntryId);
      setSavedRecipes((prev) => prev.filter((s) => s.id !== savedEntryId));
    } catch (err) {
      setError(err.message || 'Failed to remove saved recipe');
    }
  }, []);

  const savedIdSet = useMemo(
    () => new Set(savedRecipes.map((s) => s.recipeId)),
    [savedRecipes],
  );

  const isSaved = useCallback((recipeId) => savedIdSet.has(recipeId), [savedIdSet]);

  const value = useMemo(() => ({
    savedRecipes,
    loading,
    error,
    save,
    remove,
    isSaved,
    reload: loadSaved,
  }), [savedRecipes, loading, error, save, remove, isSaved, loadSaved]);

  return (
    <SavedRecipesContext.Provider value={value}>
      {children}
    </SavedRecipesContext.Provider>
  );
}

export function useSavedRecipesContext() {
  const ctx = useContext(SavedRecipesContext);
  if (!ctx) throw new Error('useSavedRecipesContext must be used within SavedRecipesProvider');
  return ctx;
}
