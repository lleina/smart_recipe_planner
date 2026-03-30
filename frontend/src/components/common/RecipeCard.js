/**
 * Recipe card component used in the discovery feed.
 * Shows image, title, cook time, difficulty, cuisine, rating, and save action.
 * Supports skeleton loading state per BR-DSC-07.
 */

import { memo, useState } from 'react';
import { View, Text, Pressable, Image } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { formatMinutes } from '../../utils/time';
import Skeleton from './Skeleton';

const DIFFICULTY_COLORS = {
  easy: 'bg-emerald-100 text-emerald-700',
  medium: 'bg-amber-100 text-amber-700',
  hard: 'bg-red-100 text-red-700',
};

const DIFFICULTY_LABELS = {
  easy: 'Easy',
  medium: 'Medium',
  hard: 'Hard',
};

/**
 * Compact ingredient-match indicator shown on each recipe card.
 * Green (≥80%), amber (≥60%), red (<60%).  Shows swap hint for the
 * first missing key ingredient when available.
 */
function IngredientMatchBadge({ recipe }) {
  const pct = recipe.ingredientMatchPct ?? 0;
  const matched = recipe.matchedIngredientCount ?? 0;
  const total = recipe.totalIngredientCount ?? 0;
  const swaps = recipe.swapSuggestions ?? [];
  const missingKeys = recipe.missingKeyIngredients ?? [];

  const isHigh = pct >= 80;
  const isMid = pct >= 60 && pct < 80;

  const iconName = isHigh
    ? 'checkmark-circle'
    : isMid
      ? 'alert-circle-outline'
      : 'close-circle-outline';
  const iconColor = isHigh ? '#10B981' : isMid ? '#F59E0B' : '#EF4444';
  const labelColor = isHigh
    ? 'text-emerald-600'
    : isMid
      ? 'text-amber-600'
      : 'text-red-500';

  // Build swap hint text
  let hint = null;
  if (swaps.length > 0 && swaps[0].swap) {
    hint = `${capitalize(swaps[0].ingredient)} → try ${swaps[0].swap}`;
  } else if (missingKeys.length > 0) {
    const names = missingKeys.slice(0, 2).map(capitalize).join(', ');
    hint = `Need: ${names}`;
  }

  return (
    <View className="mb-1">
      <View className="flex-row items-center gap-1.5">
        <Ionicons name={iconName} size={14} color={iconColor} />
        <Text className={`text-xs font-semibold ${labelColor}`}>
          {matched}/{total} ingredients
        </Text>
      </View>
      {hint && (
        <Text
          className="text-xs text-text-secondary mt-0.5 ml-5"
          numberOfLines={1}
        >
          {hint}
        </Text>
      )}
    </View>
  );
}

/**
 * Capitalises the first character of a string.
 * @param {string} str - Input string.
 * @returns {string} String with first letter uppercased.
 */
function capitalize(str) {
  if (!str) return str;
  return str.charAt(0).toUpperCase() + str.slice(1);
}

/**
 * @param {object} props
 * @param {object} props.recipe - Recipe data from pipeline.
 * @param {boolean} props.isSaved - Whether the user has saved this recipe.
 * @param {function} props.onPress - Called when card body is tapped.
 * @param {function} props.onSave - Called when bookmark icon is tapped.
 * @param {boolean} [props.loading] - Show skeleton if true.
 * @param {string} [props.badge] - Optional badge label (e.g., "Quick", "Surprise!").
 */
function RecipeCard({ recipe, isSaved, onPress, onSave, loading = false, badge }) {
  const [imageError, setImageError] = useState(false);

  if (loading) {
    return <RecipeCardSkeleton />;
  }

  const difficultyStyle = DIFFICULTY_COLORS[recipe.difficulty] || DIFFICULTY_COLORS.medium;
  const showImage = recipe.image && !imageError;

  return (
    <Pressable
      onPress={onPress}
      className="bg-surface rounded-2xl overflow-hidden mb-4 shadow-sm active:opacity-90"
      accessibilityRole="button"
      accessibilityLabel={`${recipe.title}. ${formatMinutes(recipe.totalTime)}. ${DIFFICULTY_LABELS[recipe.difficulty] || 'Medium'}.`}
    >
      {/* Hero image */}
      <View className="h-48 bg-gray-200 relative">
        {showImage ? (
          <Image
            source={{ uri: recipe.image }}
            className="w-full h-full"
            resizeMode="cover"
            accessibilityLabel={recipe.title}
            onError={() => setImageError(true)}
          />
        ) : (
          <View className="flex-1 items-center justify-center">
            <Ionicons name="restaurant-outline" size={40} color="#CBD5E1" />
          </View>
        )}

        {/* Badge overlay */}
        {badge && (
          <View className="absolute top-3 left-3 bg-primary px-2 py-1 rounded-full">
            <Text className="text-white text-xs font-bold">{badge}</Text>
          </View>
        )}

        {/* Save button overlay */}
        <Pressable
          onPress={onSave}
          hitSlop={12}
          className="absolute top-3 right-3 w-9 h-9 bg-white/90 rounded-full items-center justify-center"
          accessibilityRole="button"
          accessibilityLabel={isSaved ? 'Remove from saved' : 'Save recipe'}
        >
          <Ionicons
            name={isSaved ? 'bookmark' : 'bookmark-outline'}
            size={18}
            color={isSaved ? '#2563EB' : '#64748B'}
          />
        </Pressable>

        {/* Rating pill */}
        {recipe.rating != null && (
          <View className="absolute bottom-3 right-3 bg-white/90 px-2 py-0.5 rounded-full flex-row items-center gap-1">
            <Ionicons name="star" size={11} color="#F59E0B" />
            <Text className="text-xs font-semibold text-text-primary">
              {Number(recipe.rating).toFixed(1)}
            </Text>
          </View>
        )}
      </View>

      {/* Card body */}
      <View className="p-4">
        <Text
          className="text-base font-bold text-text-primary mb-1"
          numberOfLines={2}
        >
          {recipe.title}
        </Text>

        {recipe.description ? (
          <Text className="text-sm text-text-secondary mb-3 leading-5" numberOfLines={2}>
            {recipe.description}
          </Text>
        ) : null}

        {/* Ingredient match indicator */}
        {recipe.totalIngredientCount > 0 && (
          <IngredientMatchBadge recipe={recipe} />
        )}

        {/* Meta row */}
        <View className="flex-row items-center gap-3 flex-wrap mt-2">
          <View className="flex-row items-center gap-1">
            <Ionicons name="time-outline" size={14} color="#64748B" />
            <Text className="text-xs text-text-secondary font-medium">
              {formatMinutes(recipe.totalTime)}
            </Text>
          </View>

          {recipe.cuisine ? (
            <View className="flex-row items-center gap-1">
              <Ionicons name="globe-outline" size={14} color="#64748B" />
              <Text className="text-xs text-text-secondary font-medium capitalize">
                {recipe.cuisine}
              </Text>
            </View>
          ) : null}

          <View className={`px-2 py-0.5 rounded-full ${difficultyStyle.split(' ')[0]}`}>
            <Text className={`text-xs font-semibold ${difficultyStyle.split(' ')[1]}`}>
              {DIFFICULTY_LABELS[recipe.difficulty] || 'Medium'}
            </Text>
          </View>
        </View>
      </View>
    </Pressable>
  );
}

const MemoRecipeCardSkeleton = memo(RecipeCardSkeleton);

/** Placeholder skeleton shown while a recipe card is loading. */
function RecipeCardSkeleton() {
  return (
    <View className="bg-surface rounded-2xl overflow-hidden mb-4">
      <Skeleton className="h-48 w-full" />
      <View className="p-4 gap-2">
        <Skeleton className="h-5 w-3/4 rounded" />
        <Skeleton className="h-4 w-full rounded" />
        <Skeleton className="h-4 w-2/3 rounded" />
        <View className="flex-row gap-3 mt-1">
          <Skeleton className="h-4 w-16 rounded" />
          <Skeleton className="h-4 w-16 rounded" />
          <Skeleton className="h-5 w-14 rounded-full" />
        </View>
      </View>
    </View>
  );
}

// Custom comparator: only re-render when visible data or saved state changes.
// Ignores new callback references (onPress/onSave) since the logic is identical.
export default memo(RecipeCard, (prev, next) => {
  return (
    prev.loading === next.loading &&
    prev.isSaved === next.isSaved &&
    prev.badge === next.badge &&
    prev.recipe?.id === next.recipe?.id &&
    prev.recipe?.title === next.recipe?.title &&
    prev.recipe?.image === next.recipe?.image &&
    prev.recipe?.totalTime === next.recipe?.totalTime &&
    prev.recipe?.rating === next.recipe?.rating &&
    prev.recipe?.ingredientMatchPct === next.recipe?.ingredientMatchPct &&
    prev.recipe?.matchedIngredientCount === next.recipe?.matchedIngredientCount
  );
});