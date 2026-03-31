/**
 * Cooking history screen.
 * Shows previously cooked recipes in reverse chronological order.
 * Per BR-HST-01 through BR-HST-05.
 *
 * Each history card surfaces the user's own star rating and personal note
 * (stored locally via reviewStorageService). Tapping a card opens the full
 * recipe detail. Unrated entries show a "Rate it" nudge so the user can add
 * a review when they're ready — not forced immediately after cooking.
 */

import { View, Text, FlatList, Pressable, Image, Modal, TextInput, KeyboardAvoidingView, Platform } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useRouter } from 'expo-router';
import { useFocusEffect } from 'expo-router';
import { useCallback, useState } from 'react';
import { Ionicons } from '@expo/vector-icons';
import * as Haptics from 'expo-haptics';
import useHistory from '../../src/hooks/useHistory';
import Skeleton from '../../src/components/common/Skeleton';
import { formatMinutes } from '../../src/utils/time';
import {
  getAllReviews,
  saveReview,
} from '../../src/services/reviewStorageService';

const MEAL_LABELS = {
  breakfast: 'Breakfast',
  brunch: 'Brunch',
  lunch: 'Lunch',
  dinner: 'Dinner',
  snack: 'Snack',
  dessert: 'Dessert',
};

export default function HistoryScreen() {
  const { history, loading, removeEntry, reload } = useHistory();
  const router = useRouter();

  // All locally-stored reviews keyed by recipeId
  const [reviews, setReviews] = useState({});

  // Controls the review modal: null when closed, or { recipeId, recipeTitle }
  const [reviewTarget, setReviewTarget] = useState(null);
  const [pendingRating, setPendingRating] = useState(0);
  const [pendingNote, setPendingNote] = useState('');
  const [savingReview, setSavingReview] = useState(false);

  /** Loads history and all stored reviews whenever this tab comes into focus. */
  const refreshAll = useCallback(async () => {
    reload();
    const stored = await getAllReviews();
    setReviews(stored);
  }, [reload]);

  useFocusEffect(
    useCallback(() => {
      refreshAll();
    }, [refreshAll])
  );

  /** Opens the review modal pre-populated with any existing review for this recipe. */
  const handleOpenReview = useCallback((recipeId, recipeTitle) => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    const existing = reviews[recipeId];
    setPendingRating(existing?.rating ?? 0);
    setPendingNote(existing?.note ?? '');
    setReviewTarget({ recipeId, recipeTitle });
  }, [reviews]);

  /** Persists the rating/note and refreshes the reviews map. */
  const handleSubmitReview = useCallback(async () => {
    if (!reviewTarget || pendingRating === 0) return;
    setSavingReview(true);
    try {
      await saveReview(reviewTarget.recipeId, pendingRating, pendingNote);
      const updated = await getAllReviews();
      setReviews(updated);
    } finally {
      setSavingReview(false);
      setReviewTarget(null);
    }
  }, [reviewTarget, pendingRating, pendingNote]);

  const handleCloseReview = useCallback(() => {
    setReviewTarget(null);
  }, []);

  if (loading) {
    return (
      <SafeAreaView className="flex-1 bg-background">
        <View className="px-6 pt-4 pb-2">
          <Text className="text-2xl font-bold text-text-primary">History</Text>
        </View>
        <View className="px-6 gap-3 mt-2">
          {[1, 2, 3].map((i) => (
            <View key={i} className="flex-row gap-3 py-3 border-b border-border">
              <Skeleton width={72} height={72} borderRadius={10} />
              <View className="flex-1 gap-2 justify-center">
                <Skeleton height={16} width="80%" borderRadius={4} />
                <Skeleton height={13} width="50%" borderRadius={4} />
              </View>
            </View>
          ))}
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView className="flex-1 bg-background">
      <View className="px-6 pt-4 pb-2">
        <Text className="text-2xl font-bold text-text-primary">
          History
          {history.length > 0 ? (
            <Text className="text-base font-normal text-text-muted"> ({history.length} cooked)</Text>
          ) : null}
        </Text>
      </View>

      {history.length === 0 ? (
        <View className="flex-1 items-center justify-center px-8">
          <Ionicons name="time-outline" size={64} color="#94A3B8" />
          <Text className="text-xl font-semibold text-text-primary mt-6 mb-2 text-center">
            No cooking history yet
          </Text>
          <Text className="text-base text-text-secondary text-center leading-6">
            Tap "Cook This" on any recipe and it will appear here.
          </Text>
        </View>
      ) : (
        <FlatList
          data={history}
          keyExtractor={(item) => item.id}
          contentContainerStyle={{ paddingHorizontal: 24, paddingBottom: 24 }}
          renderItem={({ item }) => (
            <HistoryRow
              item={item}
              review={reviews[item.recipeId] || null}
              onPress={() => router.push('/recipe/' + item.recipeId)}
              onDelete={() => removeEntry(item.id)}
              onRate={() => handleOpenReview(item.recipeId, item.recipeTitle)}
            />
          )}
        />
      )}

      {/* Review modal — surfaces when the user taps "Rate it" on a history card */}
      <Modal
        visible={reviewTarget !== null}
        transparent
        animationType="slide"
        onRequestClose={handleCloseReview}
      >
        <KeyboardAvoidingView
          behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
          className="flex-1 justify-end"
        >
          <View className="bg-black/50 absolute inset-0" />
          <View className="bg-background rounded-t-3xl p-6">
            <View className="flex-row items-center justify-between mb-1">
              <Text className="text-xl font-bold text-text-primary">How did it go?</Text>
              <Pressable onPress={handleCloseReview} hitSlop={12}>
                <Ionicons name="close" size={22} color="#94A3B8" />
              </Pressable>
            </View>
            {reviewTarget?.recipeTitle ? (
              <Text className="text-sm text-text-muted mb-4" numberOfLines={1}>
                {reviewTarget.recipeTitle}
              </Text>
            ) : null}

            {/* Star picker */}
            <View className="flex-row justify-center gap-3 mb-4">
              {[1, 2, 3, 4, 5].map((star) => (
                <Pressable
                  key={star}
                  onPress={() => setPendingRating(star)}
                  accessibilityLabel={`${star} star${star !== 1 ? 's' : ''}`}
                >
                  <Ionicons
                    name={star <= pendingRating ? 'star' : 'star-outline'}
                    size={36}
                    color={star <= pendingRating ? '#F59E0B' : '#CBD5E1'}
                  />
                </Pressable>
              ))}
            </View>

            {/* Personal note */}
            <TextInput
              value={pendingNote}
              onChangeText={setPendingNote}
              placeholder="Add a personal note (e.g. add more garlic next time)"
              placeholderTextColor="#94A3B8"
              className="border border-border rounded-xl px-4 py-3 text-sm text-text-primary mb-4 bg-surface"
              multiline
              maxLength={200}
            />

            <Pressable
              onPress={handleSubmitReview}
              disabled={pendingRating === 0 || savingReview}
              className={
                'py-4 rounded-xl items-center ' +
                (pendingRating > 0 ? 'bg-primary' : 'bg-gray-200')
              }
            >
              <Text className={
                'font-semibold ' + (pendingRating > 0 ? 'text-white' : 'text-text-muted')
              }>
                {savingReview ? 'Saving…' : pendingRating > 0 ? 'Save Review' : 'Select a rating first'}
              </Text>
            </Pressable>
          </View>
        </KeyboardAvoidingView>
      </Modal>
    </SafeAreaView>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

/**
 * Renders a read-only row of stars.
 * @param {object} props
 * @param {number} props.rating - Filled star count (1–5).
 */
function StarDisplay({ rating }) {
  return (
    <View className="flex-row gap-0.5">
      {[1, 2, 3, 4, 5].map((star) => (
        <Ionicons
          key={star}
          name={star <= rating ? 'star' : 'star-outline'}
          size={12}
          color={star <= rating ? '#F59E0B' : '#CBD5E1'}
        />
      ))}
    </View>
  );
}

/**
 * Single row in the cooking history list.
 * Shows the user's own rating and personal note (not the scraped recipe rating).
 * @param {object} props
 * @param {object} props.item - CookHistory entry from the backend.
 * @param {{rating: number, note: string}|null} props.review - User's stored review, if any.
 * @param {function} props.onPress - Navigate to recipe detail.
 * @param {function} props.onDelete - Delete this history entry.
 * @param {function} props.onRate - Open the review modal for this entry.
 */
function HistoryRow({ item, review, onPress, onDelete, onRate }) {
  const mealLabel = MEAL_LABELS[item.mealType] || item.mealType || '';
  const dateStr = item.cookedAt ? new Date(item.cookedAt).toLocaleDateString(undefined, {
    month: 'short', day: 'numeric', year: 'numeric'
  }) : '';

  return (
    <Pressable
      onPress={onPress}
      className="py-3 border-b border-border active:bg-gray-50"
      accessibilityRole="button"
      accessibilityLabel={item.recipeTitle || 'Cooked recipe'}
    >
      <View className="flex-row items-center">
        {/* Thumbnail */}
        <View className="rounded-xl bg-gray-200 overflow-hidden mr-4 flex-shrink-0" style={{ width: 72, height: 72 }}>
          {item.recipeImage ? (
            <Image source={{ uri: item.recipeImage }} style={{ width: 72, height: 72 }} resizeMode="cover" />
          ) : (
            <View className="flex-1 items-center justify-center">
              <Ionicons name="restaurant-outline" size={24} color="#CBD5E1" />
            </View>
          )}
        </View>

        {/* Text content */}
        <View className="flex-1">
          <Text className="text-sm font-semibold text-text-primary" numberOfLines={2}>
            {item.recipeTitle || item.recipeId}
          </Text>
          <Text className="text-xs text-text-secondary mt-0.5">
            {mealLabel}{item.servingCount ? ' · ' + item.servingCount + ' serving' + (item.servingCount !== 1 ? 's' : '') : ''}
          </Text>
          {dateStr ? <Text className="text-xs text-text-muted mt-0.5">{dateStr}</Text> : null}

          {/* User's own rating and note, or a nudge to rate */}
          {review ? (
            <View className="mt-1.5">
              <StarDisplay rating={review.rating} />
              {review.note ? (
                <Text className="text-xs text-text-secondary mt-0.5 italic" numberOfLines={1}>
                  "{review.note}"
                </Text>
              ) : null}
            </View>
          ) : (
            <Pressable
              onPress={(e) => { e.stopPropagation?.(); onRate(); }}
              className="mt-1.5 self-start"
              hitSlop={8}
              accessibilityLabel="Rate this recipe"
            >
              <Text className="text-xs text-primary font-medium">+ Rate it</Text>
            </Pressable>
          )}
        </View>

        {/* Actions */}
        <View className="flex-row items-center ml-2 gap-1">
          <Pressable
            onPress={onDelete}
            className="w-8 h-8 items-center justify-center"
            accessibilityLabel="Delete history entry"
            hitSlop={8}
          >
            <Ionicons name="trash-outline" size={18} color="#94A3B8" />
          </Pressable>
          <Ionicons name="chevron-forward" size={16} color="#CBD5E1" />
        </View>
      </View>
    </Pressable>
  );
}
