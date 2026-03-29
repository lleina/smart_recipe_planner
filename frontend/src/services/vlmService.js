/**
 * VLM (Vision Language Model) service.
 * Handles image upload for ingredient identification.
 * Endpoint: POST /api/vlm/identify
 */

import { API_BASE_URL, VLM_TIMEOUT_MS } from '../constants/config';

/** @type {() => string|null} */
let getToken = () => null;

/**
 * Registers a function that returns the current access token.
 * Called once from useVlm after auth context is available.
 */
export const setVlmAuthTokenGetter = (fn) => {
  getToken = fn;
};

/**
 * Sends ingredient images to the VLM service for identification.
 * @param {Array<{uri: string, mimeType: string, fileName: string}>} images - Image assets from Expo ImagePicker.
 * @returns {Promise<{ingredients: Array}>} Identified ingredients list.
 * @throws {Error} On VLM failure or timeout.
 */
export const identifyIngredients = async (images) => {
  const formData = new FormData();

  images.forEach((image, index) => {
    formData.append('images', {
      uri: image.uri,
      type: image.mimeType || image.type || 'image/jpeg',
      name: image.fileName || image.name || `ingredient_${index}.jpg`,
    });
  });

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), VLM_TIMEOUT_MS);

  const headers = {};
  const token = getToken();
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  try {
    const response = await fetch(`${API_BASE_URL}/vlm/identify`, {
      method: 'POST',
      body: formData,
      headers,
      signal: controller.signal,
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      throw new Error(errorData.detail || errorData.error || `VLM request failed (${response.status})`);
    }

    return await response.json();
  } catch (error) {
    if (error.name === 'AbortError') {
      throw new Error('VLM processing timed out. Please enter ingredients manually.');
    }
    throw error;
  } finally {
    clearTimeout(timeout);
  }
};
