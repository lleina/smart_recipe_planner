/**
 * Cook history service.
 */

import { get, post, del } from './api';

/**
 * Fetches cook history for a user.
 * @param {string} userId
 * @returns {Promise<Array>} List of cook history entries.
 */
export const getHistory = async (userId) => {
  return get(`/history?userId=${encodeURIComponent(userId)}`);
};

/**
 * Records a "Cook This" event.
 * @param {object} entry - { userId, recipeId, mealType, servingCount, sessionId }
 * @returns {Promise<object>} Created history entry.
 */
export const addHistoryEntry = async (entry) => {
  return post('/history', entry);
};

/**
 * Deletes a cook history entry.
 * @param {string} entryId
 * @returns {Promise<void>}
 */
export const deleteHistoryEntry = async (entryId) => {
  return del(`/history/${encodeURIComponent(entryId)}`);
};
