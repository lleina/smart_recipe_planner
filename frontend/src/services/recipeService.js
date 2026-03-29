/**
 * Recipe detail service.
 * Fetches individual recipe data and LLM-powered substitution suggestions.
 */

import { get, post } from './api';

/**
 * Fetches a single recipe by ID.
 * @param {string} recipeId
 * @returns {Promise<object>} Full recipe object from local cache.
 */
export const getRecipeById = async (recipeId) => {
  return get(`/recipes/${encodeURIComponent(recipeId)}`);
};

/**
 * Ask the LLM to analyse recipe ingredients against the user's pantry
 * and suggest substitutions for missing items.
 *
 * @param {string} recipeId
 * @param {string[]} recipeIngredients - ingredient names from the recipe
 * @param {string[]} userIngredients   - ingredient names the user has
 * @returns {Promise<{substitutions: Array<{ingredient: string, have: boolean, substitution: string|null}>}>}
 */
export const getSubstitutions = async (recipeId, recipeIngredients, userIngredients) => {
  return post(`/recipes/${encodeURIComponent(recipeId)}/substitutions`, {
    recipe_ingredients: recipeIngredients,
    user_ingredients: userIngredients,
  });
};
