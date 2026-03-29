/**
 * Saved recipes service.
 */

import { get, post, del } from './api';

/**
 * Fetches all saved recipes for a user.
 * @param {string} userId
 * @returns {Promise<Array>} List of saved recipe entries.
 */
export const getSavedRecipes = async (userId) => {
  return get(`/saved?userId=${encodeURIComponent(userId)}`);
};

/**
 * Saves a recipe for a user.
 * @param {string} userId
 * @param {string} recipeId
 * @returns {Promise<object>} Created saved entry.
 */
export const saveRecipe = async (userId, recipeId) => {
  return post('/saved', { userId, recipeId });
};

/**
 * Removes a recipe from saved list.
 * @param {string} savedEntryId
 * @returns {Promise<void>}
 */
export const unsaveRecipe = async (savedEntryId) => {
  return del(`/saved/${encodeURIComponent(savedEntryId)}`);
};
