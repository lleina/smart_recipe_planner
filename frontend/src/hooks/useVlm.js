/**
 * Hook for VLM image submission and ingredient result handling.
 * Manages image capture, VLM API calls, and fallback to manual entry.
 */

import { useState, useCallback, useEffect } from 'react';
import * as ImagePicker from 'expo-image-picker';
import { identifyIngredients, setVlmAuthTokenGetter } from '../services/vlmService';
import { filterByConfidence, shouldAutoConfirm, sortByUrgency, deduplicateIngredients } from '../utils/ingredients';
import { validateImageFile } from '../utils/validation';
import { compressImage } from '../utils/imageCompression';
import { IMAGE_COMPRESSION_QUALITY } from '../constants/config';
import { getAccessToken } from '../services/api';

export default function useVlm({ ensureRegistered } = {}) {
  const [images, setImages] = useState([]);
  const [ingredients, setIngredients] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // Wire up VLM auth so it reuses the same token as the main API client
  useEffect(() => {
    setVlmAuthTokenGetter(getAccessToken);
  }, []);

  /** Requests camera permission, captures a photo, compresses it, and appends to images list. */
  const pickFromCamera = useCallback(async () => {
    const permission = await ImagePicker.requestCameraPermissionsAsync();
    if (!permission.granted) {
      setError('Camera permission is required to take photos');
      return;
    }

    setError(null);
    const result = await ImagePicker.launchCameraAsync({
      mediaTypes: ['images'],
      quality: IMAGE_COMPRESSION_QUALITY,
      allowsEditing: false,
    });

    if (!result.canceled && result.assets?.[0]) {
      let asset = result.assets[0];
      // Compress if too large
      asset = await compressImage(asset);
      const validation = validateImageFile(asset);
      if (!validation.valid) {
        setError(validation.error);
        return;
      }
      setImages((prev) => [...prev, asset]);
    }
  }, []);

  /** Requests photo library permission and appends valid, compressed selected images. */
  const pickFromLibrary = useCallback(async () => {
    const permission = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!permission.granted) {
      setError('Photo library access is required');
      return;
    }

    setError(null);
    const result = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ['images'],
      quality: IMAGE_COMPRESSION_QUALITY,
      allowsMultipleSelection: true,
    });

    if (!result.canceled && result.assets?.length > 0) {
      // Compress all images in parallel, then validate
      const compressed = await Promise.all(
        result.assets.map((asset) => compressImage(asset))
      );
      const validResults = compressed.map((asset) => ({
        ...asset,
        validation: validateImageFile(asset)
      }));
      const valid = validResults.filter((a) => a.validation.valid);
      const invalid = validResults.filter((a) => !a.validation.valid);
      
      if (invalid.length > 0) {
        setError(invalid[0].validation.error);
      }
      if (valid.length > 0) {
        setImages((prev) => [...prev, ...valid]);
      }
    }
  }, []);

  /**
   * Sends the current images to the VLM backend for ingredient identification.
   * Results are filtered by confidence, deduplicated, and sorted by urgency.
   */
  const identifyFromImages = useCallback(async () => {
    if (images.length === 0) return;
    setLoading(true);
    setError(null);
    try {
      // Lazy-register with backend if not yet authenticated
      if (ensureRegistered) await ensureRegistered();
      const response = await identifyIngredients(images);
      const filtered = filterByConfidence(response.ingredients);
      const deduplicated = deduplicateIngredients(filtered);
      const withConfirmState = deduplicated.map((ing) => ({
        ...ing,
        confirmed: shouldAutoConfirm(ing),
      }));
      setIngredients(sortByUrgency(withConfirmState));
    } catch (err) {
      setError(err.message || 'Failed to identify ingredients. Please add manually.');
    } finally {
      setLoading(false);
    }
  }, [images]);

  /**
   * Marks a specific ingredient as confirmed by name.
   * @param {string} name - Ingredient name to confirm.
   */
  const confirmIngredient = useCallback((name) => {
    setIngredients((prev) =>
      prev.map((ingredient) => (ingredient.name === name ? { ...ingredient, confirmed: true } : ingredient)),
    );
  }, []);

  /**
   * Removes an ingredient from the list by name.
   * @param {string} name - Ingredient name to remove.
   */
  const removeIngredient = useCallback((name) => {
    setIngredients((prev) => prev.filter((ingredient) => ingredient.name !== name));
  }, []);

  /**
   * Updates the urgency of an ingredient by name (used for drag-and-drop between sections).
   * @param {string} name - Ingredient name to update.
   * @param {number|null} urgency - New urgency value, or null for non-perishable.
   */
  const updateIngredientUrgency = useCallback((name, urgency) => {
    setIngredients((prev) =>
      prev.map((ing) => ing.name === name ? { ...ing, urgency } : ing)
    );
  }, []);

  /**
   * Appends a manually-created ingredient to the list.
   * @param {object} ingredient - Ingredient object matching the VLM response schema.
   */
  const addIngredient = useCallback((ingredient) => {
    setIngredients((prev) => [...prev, ingredient]);
  }, []);

  /**
   * Returns only the ingredients the user has confirmed.
   * @returns {object[]} Filtered ingredient list.
   */
  const getConfirmedIngredients = useCallback(() => {
    return ingredients.filter((ingredient) => ingredient.confirmed);
  }, [ingredients]);

  /**
   * Removes an image from the list by its index.
   * @param {number} index - Zero-based position in the images array.
   */
  const removeImage = useCallback((index) => {
    setImages((prev) => prev.filter((_, imageIndex) => imageIndex !== index));
  }, []);

  /** Clears all images, ingredients, and error state. */
  const reset = useCallback(() => {
    setImages([]);
    setIngredients([]);
    setError(null);
  }, []);

  return {
    images,
    ingredients,
    loading,
    error,
    pickFromCamera,
    pickFromLibrary,
    identifyFromImages,
    confirmIngredient,
    removeIngredient,
    updateIngredientUrgency,
    addIngredient,
    getConfirmedIngredients,
    removeImage,
    reset,
  };
}
