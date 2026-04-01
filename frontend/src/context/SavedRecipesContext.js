/**
 * Saved recipes state provider.
 *
 * Lifts the saved-recipe list into shared context so all screens (Discover,
 * Recipe Detail, and the Saved tab) operate on the same collection. Any save
 * or unsave action — regardless of which screen triggers it — is immediately
 * reflected everywhere via the shared state.
 *
 * Design notes:
 * - Optimistic UI: state is updated immediately on save/remove; the API call
 *   runs concurrently. On failure, the error state is set and can be displayed.
 * - The ``savedIdSet`` derived value provides O(1) ``isSaved`` lookups without
 *   iterating the array on every render.
 * - Local-only users (not yet registered with the backend) skip the initial
 *   load and save/remove calls.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from 'react';

import { useAuth } from './AuthContext';
import { getSavedRecipes, saveRecipe, unsaveRecipe } from '../services/savedService';
import { trackEvent } from '../services/eventService';

const SavedRecipesContext = createContext(null);

/**
 * Provides saved recipe state and actions to the component tree.
 *
 * @param {{ children: React.ReactNode }} props
 */
export function SavedRecipesProvider({ children }) {
  const { user } = useAuth();
  const [savedRecipes, setSavedRecipes] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);

  // ── Data loading ──────────────────────────────────────────────────────────

  /**
   * Fetch the user's saved recipes from the backend.
   * No-op for local-only (unregistered) users.
   */
  const loadSavedRecipes = useCallback(async () => {
    if (!user?.id || user?.localOnly) return;
    setIsLoading(true);
    setError(null);
    try {
      const fetchedSavedRecipes = await getSavedRecipes(user.id);
      setSavedRecipes(fetchedSavedRecipes);
    } catch (fetchError) {
      // AbortError and timeouts are expected during navigation — suppress them.
      if (fetchError?.name !== 'AbortError' && fetchError?.code !== 'ERR_TIMEOUT') {
        setError(fetchError.message || 'Failed to load saved recipes');
      }
    } finally {
      setIsLoading(false);
    }
  }, [user?.id, user?.localOnly]);

  useEffect(() => {
    loadSavedRecipes();
  }, [loadSavedRecipes]);

  // ── Mutations ─────────────────────────────────────────────────────────────

  /**
   * Save a recipe to the user's collection.
   *
   * Prepends the new entry to the saved list immediately (optimistic update)
   * and fires an analytics event in the background.
   *
   * @param {string} recipeId - The recipe cache ID to save.
   * @param {string|null} sessionId - The current session pool ID for analytics.
   */
  const saveRecipeToCollection = useCallback(async (recipeId, sessionId) => {
    if (!user?.id) return;
    // Prevent duplicate saves
    if (savedRecipeIdSet.has(recipeId)) return;

    // Optimistic: insert a temporary entry so the UI updates instantly.
    const tempId = `__temp_${recipeId}_${Date.now()}`;
    const optimisticEntry = { id: tempId, recipeId, userId: user.id, savedAt: new Date().toISOString() };
    setSavedRecipes((previousEntries) => [optimisticEntry, ...previousEntries]);

    try {
      const newSavedEntry = await saveRecipe(user.id, recipeId);
      // Replace the temporary entry with the real server-returned entry.
      setSavedRecipes((previousEntries) =>
        previousEntries.map((entry) => (entry.id === tempId ? newSavedEntry : entry))
      );
      trackEvent({
        userId: user.id,
        sessionId,
        recipeId,
        eventType: 'recipe_saved',
      }).catch(() => {}); // Fire-and-forget; analytics must not affect UX.
    } catch (saveError) {
      // Rollback the optimistic entry on failure.
      setSavedRecipes((previousEntries) =>
        previousEntries.filter((entry) => entry.id !== tempId)
      );
      setError(saveError.message || 'Failed to save recipe');
    }
  }, [user?.id, savedRecipeIdSet]);

  /**
   * Remove a saved recipe from the user's collection.
   *
   * Removes the entry from local state immediately (optimistic update).
   *
   * @param {string} savedEntryId - The ``SavedRecipe.id`` (primary key) to remove.
   */
  const removeRecipeFromCollection = useCallback(async (savedEntryId) => {
    // Optimistic: remove from local state immediately so the UI updates instantly.
    let removedEntry = null;
    setSavedRecipes((previousEntries) => {
      removedEntry = previousEntries.find((entry) => entry.id === savedEntryId);
      return previousEntries.filter((entry) => entry.id !== savedEntryId);
    });

    try {
      await unsaveRecipe(savedEntryId);
    } catch (removeError) {
      // Rollback: re-insert the removed entry on failure.
      if (removedEntry) {
        setSavedRecipes((previousEntries) => [removedEntry, ...previousEntries]);
      }
      setError(removeError.message || 'Failed to remove saved recipe');
    }
  }, []);

  // ── Derived values ────────────────────────────────────────────────────────

  /** O(1) lookup set of saved recipe IDs. Recomputed only when savedRecipes changes. */
  const savedRecipeIdSet = useMemo(
    () => new Set(savedRecipes.map((entry) => entry.recipeId)),
    [savedRecipes],
  );

  /**
   * Check whether a recipe is in the user's saved collection.
   *
   * @param {string} recipeId - The recipe's cache ID.
   * @returns {boolean} True if the recipe is saved.
   */
  const isSaved = useCallback(
    (recipeId) => savedRecipeIdSet.has(recipeId),
    [savedRecipeIdSet],
  );

  // ── Context value ─────────────────────────────────────────────────────────

  const contextValue = useMemo(() => ({
    savedRecipes,
    isLoading,
    error,
    save: saveRecipeToCollection,
    remove: removeRecipeFromCollection,
    isSaved,
    reload: loadSavedRecipes,
  }), [
    savedRecipes,
    isLoading,
    error,
    saveRecipeToCollection,
    removeRecipeFromCollection,
    isSaved,
    loadSavedRecipes,
  ]);

  return (
    <SavedRecipesContext.Provider value={contextValue}>
      {children}
    </SavedRecipesContext.Provider>
  );
}

/**
 * Hook to consume SavedRecipesContext.
 *
 * @returns {object} Saved recipe state and actions from the nearest SavedRecipesProvider.
 * @throws {Error} If called outside a SavedRecipesProvider.
 */
export function useSavedRecipesContext() {
  const context = useContext(SavedRecipesContext);
  if (!context) {
    throw new Error('useSavedRecipesContext must be used inside a SavedRecipesProvider');
  }
  return context;
}
