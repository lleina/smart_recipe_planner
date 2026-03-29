/**
 * Recipe detail service.
 * Fetches individual recipe data.
 */

import { get } from './api';

/**
 * Fetches a single recipe by ID.
 * @param {string} recipeId
 * @returns {Promise<object>} Full recipe object from cache/Spoonacular.
 */
export const getRecipeById = async (recipeId) => {
  return get(`/recipes/${encodeURIComponent(recipeId)}`);
};
