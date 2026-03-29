/**
 * User profile and preferences service.
 */

import { get, put } from './api';

/**
 * Fetches the current user's profile.
 * Auth is handled via JWT — no need to pass userId in the URL.
 */
export const getProfile = async () => {
  return get('/user/profile');
};

/**
 * Updates the current user's profile.
 */
export const updateProfile = async (profileData) => {
  return put('/user/profile', profileData);
};

/**
 * Fetches the current user's preferences.
 */
export const getPreferences = async () => {
  return get('/user/preferences');
};

/**
 * Updates the current user's preferences.
 * @param {object} preferences - camelCase preference keys (e.g. cuisinePreferences)
 */
export const updatePreferences = async (preferences) => {
  return put('/user/preferences', preferences);
};
