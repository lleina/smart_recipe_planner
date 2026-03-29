/**
 * Input validation helpers.
 * All functions are pure and return boolean or sanitized values.
 */

import { SERVING_COUNT_MIN, SERVING_COUNT_MAX, COOKING_TIME_MIN, COOKING_TIME_MAX, ALLOWED_IMAGE_TYPES, IMAGE_MAX_SIZE_BYTES } from '../constants/config';

/**
 * Validates serving count is within allowed range.
 * @param {number} count - Serving count.
 * @returns {boolean}
 */
export const isValidServingCount = (count) => {
  return Number.isInteger(count) && count >= SERVING_COUNT_MIN && count <= SERVING_COUNT_MAX;
};

/**
 * Clamps serving count to valid range.
 * @param {number} count - Input count.
 * @returns {number} Clamped value.
 */
export const clampServingCount = (count) => {
  const num = parseInt(count, 10);
  if (isNaN(num)) return SERVING_COUNT_MIN;
  return Math.max(SERVING_COUNT_MIN, Math.min(SERVING_COUNT_MAX, num));
};

/**
 * Validates cooking time is within allowed range.
 * @param {number} minutes - Time in minutes.
 * @returns {boolean}
 */
export const isValidCookingTime = (minutes) => {
  return Number.isFinite(minutes) && minutes >= COOKING_TIME_MIN && minutes <= COOKING_TIME_MAX;
};

/**
 * Validates image file for upload.
 * @param {object} file - File object with uri, mimeType, fileSize from Expo ImagePicker.
 * @returns {{ valid: boolean, error: string|null }}
 */
export const validateImageFile = (file) => {
  if (!file || !file.uri) {
    return { valid: false, error: 'No file selected' };
  }
  if (file.fileSize && file.fileSize > IMAGE_MAX_SIZE_BYTES) {
    return { valid: false, error: 'Image exceeds 5MB limit' };
  }
  // Expo ImagePicker returns mimeType, not type. Only validate if present.
  const mime = file.mimeType || file.type;
  if (mime && !ALLOWED_IMAGE_TYPES.includes(mime)) {
    return { valid: false, error: 'Only JPEG, PNG, and HEIC images are allowed' };
  }
  // If no mimeType is provided (some Android cases), accept it - backend will validate
  return { valid: true, error: null };
};

/**
 * Sanitizes a user-provided string to prevent injection.
 * Strips HTML tags and trims whitespace.
 * @param {string} input - Raw user input.
 * @returns {string} Sanitized string.
 */
export const sanitizeInput = (input) => {
  if (typeof input !== 'string') return '';
  return input
    .replace(/<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>/gi, '')
    .replace(/<style\b[^<]*(?:(?!<\/style>)<[^<]*)*<\/style>/gi, '')
    .replace(/<[^>]*>/g, '')
    .trim();
};

/**
 * Validates email format.
 * @param {string} email - Email address.
 * @returns {boolean}
 */
export const isValidEmail = (email) => {
  if (typeof email !== 'string') return false;
  const pattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  return pattern.test(email);
};
