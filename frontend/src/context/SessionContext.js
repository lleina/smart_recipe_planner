/**
 * Ephemeral cooking session state provider.
 *
 * Manages the user's current recipe session: meal type, time budget,
 * serving count, occasion, and the list of available ingredients returned
 * by the VLM or entered manually. Also tracks which recipe IDs have already
 * been shown so the discovery screen never shows duplicates.
 *
 * Session state is reset on every new session start (via resetSession()). It
 * is intentionally NOT persisted to storage — if the user closes the app mid-
 * session, they start a fresh session on re-open.
 */

import { createContext, useCallback, useContext, useMemo, useState } from 'react';

import { SERVING_COUNT_DEFAULT } from '../constants/config';
import { getMealTypeByTime } from '../utils/time';

const SessionContext = createContext(null);

/**
 * Build the default session state inferred from the current time of day.
 *
 * @returns {object} Fresh session state object with sensible defaults.
 */
function buildInitialSessionState() {
  return {
    mealType: getMealTypeByTime(),
    servingCount: SERVING_COUNT_DEFAULT,
    availableTimeMinutes: 30,
    availablePrepTimeMinutes: null,
    availableCookTimeMinutes: null,
    occasion: null,
    availableIngredients: [],
    sessionPoolId: null,
    shownRecipeIds: [],
    // Becomes true after the session setup form is submitted, which triggers
    // the pipeline on the Discover screen.
    sessionReady: false,
  };
}

/**
 * Provides session state and mutation actions to the component tree.
 *
 * @param {{ children: React.ReactNode }} props
 */
export function SessionProvider({ children }) {
  const [session, setSession] = useState(buildInitialSessionState);

  // ── Session mutations ─────────────────────────────────────────────────────

  /**
   * Merge a partial update into the current session state.
   *
   * @param {Partial<object>} updates - Key/value pairs to merge into session.
   */
  const updateSession = useCallback((updates) => {
    setSession((previousSession) => ({ ...previousSession, ...updates }));
  }, []);

  /**
   * Replace the entire available ingredients list.
   *
   * @param {object[]} ingredients - New ingredient list from VLM or manual entry.
   */
  const setIngredients = useCallback((ingredients) => {
    setSession((previousSession) => ({
      ...previousSession,
      availableIngredients: ingredients,
    }));
  }, []);

  /**
   * Mark a single recipe ID as shown in this session.
   *
   * @param {string} recipeId - The recipe's unique cache ID.
   */
  const addShownRecipeId = useCallback((recipeId) => {
    setSession((previousSession) => ({
      ...previousSession,
      shownRecipeIds: [...previousSession.shownRecipeIds, recipeId],
    }));
  }, []);

  /**
   * Mark multiple recipe IDs as shown in a single state update.
   * Preferred over calling addShownRecipeId in a loop.
   *
   * @param {string[]} recipeIds - Array of recipe IDs to mark as shown.
   */
  const batchAddShownRecipeIds = useCallback((recipeIds) => {
    if (!recipeIds || recipeIds.length === 0) return;
    setSession((previousSession) => ({
      ...previousSession,
      shownRecipeIds: [...previousSession.shownRecipeIds, ...recipeIds],
    }));
  }, []);

  /**
   * Reset the session to its initial state, ready for a new recipe search.
   */
  const resetSession = useCallback(() => {
    setSession(buildInitialSessionState());
  }, []);

  /**
   * Return only the fields required by the backend pipeline request.
   *
   * Avoids leaking UI-only state (sessionPoolId, shownRecipeIds, etc.) into
   * the API request body.
   *
   * @returns {object} Pipeline-ready session context object.
   */
  const getSessionContext = useCallback(() => ({
    mealType: session.mealType,
    servingCount: session.servingCount,
    availableTimeMinutes: session.availableTimeMinutes,
    availablePrepTimeMinutes: session.availablePrepTimeMinutes,
    availableCookTimeMinutes: session.availableCookTimeMinutes,
    occasion: session.occasion,
    availableIngredients: session.availableIngredients,
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }), [
    session.mealType,
    session.servingCount,
    session.availableTimeMinutes,
    session.availablePrepTimeMinutes,
    session.availableCookTimeMinutes,
    session.occasion,
    session.availableIngredients,
  ]);

  // ── Context value ─────────────────────────────────────────────────────────

  const contextValue = useMemo(() => ({
    session,
    updateSession,
    setIngredients,
    addShownRecipeId,
    batchAddShownRecipeIds,
    resetSession,
    getSessionContext,
  }), [
    session,
    updateSession,
    setIngredients,
    addShownRecipeId,
    batchAddShownRecipeIds,
    resetSession,
    getSessionContext,
  ]);

  return (
    <SessionContext.Provider value={contextValue}>
      {children}
    </SessionContext.Provider>
  );
}

/**
 * Hook to consume SessionContext.
 *
 * @returns {object} Session state and mutation actions from the nearest SessionProvider.
 * @throws {Error} If called outside a SessionProvider.
 */
export const useSession = () => {
  const context = useContext(SessionContext);
  if (!context) {
    throw new Error('useSession must be used inside a SessionProvider');
  }
  return context;
};
