/**
 * Hook for VLM image submission and ingredient result handling.
 * Manages image capture, VLM API calls, and fallback to manual entry.
 */

import { useState, useCallback, useEffect } from 'react';
import * as ImagePicker from 'expo-image-picker';
import { identifyIngredients, setVlmAuthTokenGetter } from '../services/vlmService';
import { filterByConfidence, shouldAutoConfirm, sortByUrgency } from '../utils/ingredients';
import { validateImageFile } from '../utils/validation';
import { compressImage } from '../utils/imageCompression';
import { IMAGE_COMPRESSION_QUALITY } from '../constants/config';
import { getAccessToken } from '../services/api';

export default function useVlm() {
  const [images, setImages] = useState([]);
  const [ingredients, setIngredients] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // Wire up VLM auth so it reuses the same token as the main API client
  useEffect(() => {
    setVlmAuthTokenGetter(getAccessToken);
  }, []);

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

  const identifyFromImages = useCallback(async () => {
    if (images.length === 0) return;
    setLoading(true);
    setError(null);
    try {
      const response = await identifyIngredients(images);
      const filtered = filterByConfidence(response.ingredients);
      const withConfirmState = filtered.map((ing) => ({
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

  const confirmIngredient = useCallback((name) => {
    setIngredients((prev) =>
      prev.map((i) => (i.name === name ? { ...i, confirmed: true } : i)),
    );
  }, []);

  const removeIngredient = useCallback((name) => {
    setIngredients((prev) => prev.filter((i) => i.name !== name));
  }, []);

  const addIngredient = useCallback((ingredient) => {
    setIngredients((prev) => [...prev, ingredient]);
  }, []);

  const getConfirmedIngredients = useCallback(() => {
    return ingredients.filter((i) => i.confirmed);
  }, [ingredients]);

  const removeImage = useCallback((index) => {
    setImages((prev) => prev.filter((_, i) => i !== index));
  }, []);

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
    addIngredient,
    getConfirmedIngredients,
    removeImage,
    reset,
  };
}
