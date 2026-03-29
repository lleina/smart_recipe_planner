/**
 * User profile and preferences service.
 */

import { get, put } from './api';

/**
 * Fetches the current user's profile.
 * @param {string} userId
 * @returns {Promise<object>} User profile data.
 */
export const getProfile = async (userId) => {
  return get(`/user/${encodeURIComponent(userId)}/profile`);
};

/**
 * Updates the current user's profile.
 * @param {string} userId
 * @param {object} profileData
 * @returns {Promise<object>} Updated profile.
 */
export const updateProfile = async (userId, profileData) => {
  return put(`/user/${encodeURIComponent(userId)}/profile`, profileData);
};

/**
 * Fetches the current user's preferences.
 * @param {string} userId
 * @returns {Promise<object>} User preferences.
 */
export const getPreferences = async (userId) => {
  return get(`/user/${encodeURIComponent(userId)}/preferences`);
};

/**
 * Updates the current user's preferences.
 * @param {string} userId
 * @param {object} preferences
 * @returns {Promise<object>} Updated preferences.
 */
export const updatePreferences = async (userId, preferences) => {
  return put(`/user/${encodeURIComponent(userId)}/preferences`, preferences);
};
