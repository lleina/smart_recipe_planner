/**
 * Shared recipe state provider.
 * Centralises pipeline results so they persist across screen navigations
 * (e.g. generating → discover).
 */

import { createContext, useContext, useState, useCallback, useMemo } from 'react';
import { useAuth } from './AuthContext';
import { useSession } from './SessionContext';
import { getRecommendations, getNextBatch, rerankPool } from '../services/pipelineService';
import { trackEvent } from '../services/eventService';

const RecipeContext = createContext(null);

export function RecipeProvider({ children }) {
  const { user } = useAuth();
  const { session, updateSession, batchAddShownRecipeIds } = useSession();
  const [recipes, setRecipes] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [poolInfo, setPoolInfo] = useState({ poolSize: 0, shownCount: 0 });

  const startPipeline = useCallback(async (sessionContext) => {
    if (!user?.id) {
      console.error('[RecipeContext] Cannot start pipeline: user not authenticated');
      setError('Please log in to get recipe recommendations.');
      return;
    }
    setLoading(true);
    setError(null);
    setRecipes([]);
    try {
      const result = await getRecommendations(user.id, sessionContext);
      setRecipes(result.recipes || []);
      updateSession({ sessionPoolId: result.sessionPoolId });
      setPoolInfo({ poolSize: result.poolSize, shownCount: result.shownCount });

      batchAddShownRecipeIds((result.recipes || []).map((r) => r.id));
      trackEvent({
        userId: user.id,
        sessionId: result.sessionPoolId,
        eventType: 'session_started',
        metadata: { mealType: sessionContext.mealType },
      }).catch(() => {});
    } catch (err) {
      console.error('[RecipeContext] Pipeline error:', err.message, err);
      setError(err.message || 'Failed to load recipes. Please try again.');
    } finally {
      setLoading(false);
    }
  }, [user?.id, updateSession, batchAddShownRecipeIds]);

  const loadNextBatch = useCallback(async () => {
    if (!session.sessionPoolId) return;
    setLoading(true);
    setError(null);
    try {
      const result = await getNextBatch(session.sessionPoolId);
      setRecipes(result.recipes);
      setPoolInfo({ poolSize: result.poolSize, shownCount: result.shownCount });
      batchAddShownRecipeIds(result.recipes.map((r) => r.id));
    } catch (err) {
      setError(err.message || 'Failed to load next batch');
    } finally {
      setLoading(false);
    }
  }, [session.sessionPoolId, batchAddShownRecipeIds]);

  const rerank = useCallback(async (likedRecipeId, action) => {
    if (!user?.id || !session.sessionPoolId) return;
    try {
      await rerankPool(user.id, session.sessionPoolId, likedRecipeId, action);
    } catch {
      // Re-ranking failure is non-blocking per spec
    }
  }, [user?.id, session.sessionPoolId]);

  const resetRecipes = useCallback(() => {
    setRecipes([]);
    setError(null);
    setPoolInfo({ poolSize: 0, shownCount: 0 });
  }, []);

  const value = useMemo(() => ({
    recipes,
    loading,
    error,
    poolInfo,
    startPipeline,
    loadNextBatch,
    rerank,
    resetRecipes,
  }), [recipes, loading, error, poolInfo, startPipeline, loadNextBatch, rerank, resetRecipes]);

  return (
    <RecipeContext.Provider value={value}>
      {children}
    </RecipeContext.Provider>
  );
}

export const useRecipeContext = () => {
  const context = useContext(RecipeContext);
  if (!context) {
    throw new Error('useRecipeContext must be used within a RecipeProvider');
  }
  return context;
};
