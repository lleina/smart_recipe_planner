/**
 * Hook for fetching and managing recipe batches from the pipeline.
 * Handles initial recommendations, next batch loading, and re-ranking.
 */

import { useState, useCallback } from 'react';
import { useAuth } from '../context/AuthContext';
import { useSession } from '../context/SessionContext';
import { getRecommendations, getNextBatch, rerankPool } from '../services/pipelineService';
import { trackEvent } from '../services/eventService';

export default function useRecipes() {
  const { user } = useAuth();
  const { session, updateSession, batchAddShownRecipeIds } = useSession();
  const [recipes, setRecipes] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [poolInfo, setPoolInfo] = useState({ poolSize: 0, shownCount: 0 });

  /**
   * Starts the full recommendation pipeline for the authenticated user.
   * @param {object} sessionContext - Meal type, servings, ingredients, and time budget.
   */
  const startPipeline = useCallback(async (sessionContext) => {
    if (!user?.id) {
      console.error('[useRecipes] Cannot start pipeline: user not authenticated', { user });
      setError('Please log in to get recipe recommendations.');
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const result = await getRecommendations(user.id, sessionContext);
      setRecipes(result.recipes || []);
      updateSession({ sessionPoolId: result.sessionPoolId });
      setPoolInfo({ poolSize: result.poolSize, shownCount: result.shownCount });

      batchAddShownRecipeIds((result.recipes || []).map((recipe) => recipe.id));
      await trackEvent({
        userId: user.id,
        sessionId: result.sessionPoolId,
        eventType: 'session_started',
        metadata: { mealType: sessionContext.mealType },
      }).catch(() => {}); // Non-blocking
    } catch (err) {
      console.error('[useRecipes] Pipeline error:', err.message, err);
      setError(err.message || 'Failed to load recipes. Please try again.');
    } finally {
      setLoading(false);
    }
  }, [user?.id, updateSession, batchAddShownRecipeIds]);

  /**
   * Appends the next batch of recipes from the active session pool to local state.
   * No-ops when no session pool is active.
   */
  const loadNextBatch = useCallback(async () => {
    if (!session.sessionPoolId) return;
    setLoading(true);
    setError(null);
    try {
      const result = await getNextBatch(session.sessionPoolId);
      setRecipes((prev) => [...prev, ...result.recipes]);
      setPoolInfo({ poolSize: result.poolSize, shownCount: result.shownCount });
      batchAddShownRecipeIds(result.recipes.map((recipe) => recipe.id));
    } catch (err) {
      setError(err.message || 'Failed to load next batch');
    } finally {
      setLoading(false);
    }
  }, [session.sessionPoolId, batchAddShownRecipeIds]);

  /**
   * Signals a user preference to the backend to re-rank the session pool.
   * Failures are silently swallowed — re-ranking is non-blocking per spec.
   * @param {string} likedRecipeId - The recipe the user interacted with.
   * @param {'saved'|'liked'} action - Type of interaction.
   */
  const rerank = useCallback(async (likedRecipeId, action) => {
    if (!user?.id || !session.sessionPoolId) return;
    try {
      await rerankPool(user.id, session.sessionPoolId, likedRecipeId, action);
    } catch {
      // Re-ranking failure is non-blocking per spec
    }
  }, [user?.id, session.sessionPoolId]);

  return {
    recipes,
    loading,
    error,
    poolInfo,
    startPipeline,
    loadNextBatch,
    rerank,
  };
}
