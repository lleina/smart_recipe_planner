/**
 * Local review storage service.
 *
 * Persists user ratings and personal notes for cooked recipes in AsyncStorage.
 * Reviews are keyed by recipeId and stored as a flat map so look-ups are O(1).
 *
 * Why AsyncStorage rather than the backend: the rating modal was previously
 * firing a trackEvent only (no persistent record). This service gives the
 * frontend a durable, immediately readable copy that can be displayed in the
 * History screen without any network round-trip.
 */

import AsyncStorage from '@react-native-async-storage/async-storage';

/** AsyncStorage key for the reviews map. Versioned to allow future migrations. */
const REVIEWS_STORAGE_KEY = '@recipe_reviews_v1';

/**
 * Saves (or overwrites) a user review for a recipe.
 * @param {string} recipeId - ID of the recipe being reviewed.
 * @param {number} rating - Star rating from 1 to 5.
 * @param {string} note - Optional personal note (may be empty string).
 * @returns {Promise<void>}
 */
export const saveReview = async (recipeId, rating, note) => {
  const existing = await getAllReviews();
  const updated = {
    ...existing,
    [recipeId]: {
      rating,
      note: note || '',
      reviewedAt: new Date().toISOString(),
    },
  };
  await AsyncStorage.setItem(REVIEWS_STORAGE_KEY, JSON.stringify(updated));
};

/**
 * Retrieves a single review for a recipe.
 * @param {string} recipeId - ID of the recipe to look up.
 * @returns {Promise<{rating: number, note: string, reviewedAt: string}|null>}
 *   Review object, or null if the user has not reviewed this recipe.
 */
export const getReview = async (recipeId) => {
  const all = await getAllReviews();
  return all[recipeId] || null;
};

/**
 * Retrieves all stored reviews as a map keyed by recipeId.
 * Returns an empty object when no reviews have been saved yet.
 * @returns {Promise<Record<string, {rating: number, note: string, reviewedAt: string}>>}
 */
export const getAllReviews = async () => {
  try {
    const raw = await AsyncStorage.getItem(REVIEWS_STORAGE_KEY);
    return raw ? JSON.parse(raw) : {};
  } catch {
    // Corrupt storage — return empty so the app stays functional
    return {};
  }
};
