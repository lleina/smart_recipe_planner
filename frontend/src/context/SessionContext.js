/**
 * Current cooking session provider.
 * Manages ephemeral session state: meal type, time, ingredients, shown recipes.
 */

import { createContext, useContext, useState, useCallback, useMemo } from 'react';
import { getMealTypeByTime } from '../utils/time';
import { SERVING_COUNT_DEFAULT } from '../constants/config';

const SessionContext = createContext(null);

const createInitialSession = () => ({
  mealType: getMealTypeByTime(),
  servingCount: SERVING_COUNT_DEFAULT,
  availableTimeMinutes: 30,
  availablePrepTimeMinutes: null,
  availableCookTimeMinutes: null,
  occasion: null,
  availableIngredients: [],
  sessionPoolId: null,
  shownRecipeIds: [],
  // Set to true after session setup is submitted; triggers pipeline on discover screen.
  sessionReady: false,
});

export function SessionProvider({ children }) {
  const [session, setSession] = useState(createInitialSession);

  const updateSession = useCallback((updates) => {
    setSession((prev) => ({ ...prev, ...updates }));
  }, []);

  const setIngredients = useCallback((ingredients) => {
    setSession((prev) => ({ ...prev, availableIngredients: ingredients }));
  }, []);

  const addShownRecipeId = useCallback((recipeId) => {
    setSession((prev) => ({
      ...prev,
      shownRecipeIds: [...prev.shownRecipeIds, recipeId],
    }));
  }, []);

  const resetSession = useCallback(() => {
    setSession(createInitialSession());
  }, []);

  /** Returns only the context fields needed for the pipeline request. */
  const getSessionContext = useCallback(() => {
    const { sessionPoolId, shownRecipeIds, sessionReady, ...context } = session;
    return context;
  }, [session]);

  const value = useMemo(() => ({
    session,
    updateSession,
    setIngredients,
    addShownRecipeId,
    resetSession,
    getSessionContext,
  }), [session, updateSession, setIngredients, addShownRecipeId, resetSession, getSessionContext]);

  return (
    <SessionContext.Provider value={value}>
      {children}
    </SessionContext.Provider>
  );
}

export const useSession = () => {
  const context = useContext(SessionContext);
  if (!context) {
    throw new Error('useSession must be used within a SessionProvider');
  }
  return context;
};
