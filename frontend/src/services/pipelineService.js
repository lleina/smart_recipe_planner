/**
 * Recipe pipeline service.
 * Handles recipe recommendation, next batch, and re-ranking.
 */

import { post, get } from './api';

/**
 * Triggers the full recipe pipeline.
 * @param {string} userId
 * @param {object} sessionContext - Meal type, serving count, time, ingredients.
 * @returns {Promise<{sessionPoolId: string, recipes: Array, poolSize: number, shownCount: number}>}
 */
export const getRecommendations = async (userId, sessionContext) => {
  return post('/recommend', { userId, sessionContext });
};

/**
 * Fetches the next batch of recipes from an active session pool.
 * @param {string} sessionPoolId
 * @returns {Promise<{recipes: Array, shownCount: number, poolSize: number, refetchTriggered: boolean}>}
 */
export const getNextBatch = async (sessionPoolId) => {
  return get(`/recommend/next?sessionPoolId=${encodeURIComponent(sessionPoolId)}`);
};

/**
 * Triggers re-ranking after a user likes/saves a recipe.
 * @param {string} userId
 * @param {string} sessionPoolId
 * @param {string} likedRecipeId
 * @param {string} action - 'saved' | 'liked'.
 * @returns {Promise<{message: string, preferenceInference: string}>}
 */
export const rerankPool = async (userId, sessionPoolId, likedRecipeId, action) => {
  return post('/rerank', { userId, sessionPoolId, likedRecipeId, action });
};

/**
 * Polls the current backend pipeline stage for the authenticated user.
 * @returns {Promise<{step: number, label: string, detail: string, total_steps: number}>}
 */
export const getPipelineStatus = async () => {
  return get('/recommend/status');
};
