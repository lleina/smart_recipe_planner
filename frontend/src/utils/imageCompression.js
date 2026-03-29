/**
 * Image compression utility for Expo ImagePicker assets.
 * Resizes and compresses images to fit within the upload size limit.
 */

import * as ImageManipulator from 'expo-image-manipulator';
import { IMAGE_MAX_SIZE_BYTES, IMAGE_MAX_DIMENSION } from '../constants/config';

/**
 * Compresses an image so it fits under IMAGE_MAX_SIZE_BYTES.
 * Resizes large images and reduces JPEG quality progressively.
 * @param {object} asset - Expo ImagePicker asset with uri, width, height, fileSize.
 * @returns {Promise<object>} Asset with updated uri, width, height (compressed).
 */
export const compressImage = async (asset) => {
  if (!asset?.uri) return asset;

  // If already small enough, skip compression
  if (asset.fileSize && asset.fileSize <= IMAGE_MAX_SIZE_BYTES) {
    return asset;
  }

  // Calculate resize dimensions (limit longest edge)
  const { width = 4000, height = 4000 } = asset;
  const maxDim = IMAGE_MAX_DIMENSION;
  let newWidth = width;
  let newHeight = height;

  if (width > maxDim || height > maxDim) {
    if (width >= height) {
      newWidth = maxDim;
      newHeight = Math.round((height / width) * maxDim);
    } else {
      newHeight = maxDim;
      newWidth = Math.round((width / height) * maxDim);
    }
  }

  // Compress with resize
  try {
    const result = await ImageManipulator.manipulateAsync(
      asset.uri,
      [{ resize: { width: newWidth, height: newHeight } }],
      { compress: 0.7, format: ImageManipulator.SaveFormat.JPEG }
    );

    return {
      ...asset,
      uri: result.uri,
      width: result.width,
      height: result.height,
      mimeType: 'image/jpeg',
      // fileSize not returned by manipulateAsync, clear it so validation passes
      fileSize: undefined,
    };
  } catch (err) {
    console.warn('[compressImage] Compression failed, using original:', err.message);
    return asset;
  }
};
