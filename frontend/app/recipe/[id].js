/**
 * Recipe detail screen (dynamic route).
 * Full recipe info: hero image, summary bar, scaled ingredients, instructions.
 * Per BR-DET-01 through BR-DET-08.
 */

import { useState, useEffect, useCallback } from 'react';
import { View, Text, ScrollView, Pressable, Image, TextInput, Modal, ActivityIndicator } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import * as Haptics from 'expo-haptics';
import { useAuth } from '../../src/context/AuthContext';
import { useSession } from '../../src/context/SessionContext';
import useSavedRecipes from '../../src/hooks/useSavedRecipes';
import useHistory from '../../src/hooks/useHistory';
import { getRecipeById } from '../../src/services/recipeService';
import { trackEvent } from '../../src/services/eventService';
import { formatMinutes } from '../../src/utils/time';
import { PERISHABLE_URGENCY_DAYS } from '../../src/constants/config';
import Skeleton from '../../src/components/common/Skeleton';
import Stepper from '../../src/components/common/Stepper';

export default function RecipeDetailScreen() {
  const { id } = useLocalSearchParams();
  const router = useRouter();
  const { user } = useAuth();
  const { session } = useSession();
  const { save, remove, isSaved, savedRecipes } = useSavedRecipes();
  const { addEntry } = useHistory();

  const [recipe, setRecipe] = useState(null);
  const [loading, setLoading] = useState(true);
  const [servings, setServings] = useState(null);
  const [cooked, setCooked] = useState(false);
  const [showReview, setShowReview] = useState(false);
  const [rating, setRating] = useState(0);
  const [reviewNote, setReviewNote] = useState('');

  useEffect(() => {
    if (!id) return;
    loadRecipe();
    if (user?.id && session.sessionPoolId) {
      trackEvent({ userId: user.id, sessionId: session.sessionPoolId, recipeId: id, eventType: 'recipe_viewed' }).catch(() => {});
    }
  }, [id]);

  const loadRecipe = async () => {
    setLoading(true);
    try {
      const data = await getRecipeById(id);
      setRecipe(data);
      setServings(data.servings || session.servingCount || 1);
    } catch {
      // fallback - recipe stays null and we show error state
    } finally {
      setLoading(false);
    }
  };

  const scaledQuantity = useCallback((baseQuantity, baseServings) => {
    if (!baseQuantity || !baseServings || !servings) return baseQuantity;
    const scaled = (baseQuantity / baseServings) * servings;
    return Math.round(scaled * 10) / 10;
  }, [servings]);

  const handleCookThis = async () => {
    Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
    setCooked(true);
    if (user?.id) {
      await addEntry(id, session.mealType, servings, session.sessionPoolId);
    }
    setTimeout(() => setShowReview(true), 500);
  };

  const handleSaveToggle = async () => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    if (isSaved(id)) {
      const entry = savedRecipes.find((s) => s.recipeId === id);
      if (entry) remove(entry.id);
    } else {
      await save(id, session.sessionPoolId);
    }
  };

  const handleSubmitReview = async () => {
    if (user?.id && rating > 0) {
      await trackEvent({
        userId: user.id,
        sessionId: session.sessionPoolId,
        recipeId: id,
        eventType: 'recipe_reviewed',
        metadata: { rating, note: reviewNote },
      }).catch(() => {});
    }
    setShowReview(false);
    router.back();
  };

  const saved = isSaved(id);
  const availableIngredientNames = new Set(
    (session.availableIngredients || []).map((i) => i.name.toLowerCase())
  );

  if (loading) {
    return (
      <SafeAreaView className="flex-1 bg-background">
        <ScrollView className="flex-1">
          <Skeleton height={260} borderRadius={0} />
          <View className="p-6 gap-3">
            <Skeleton height={28} width="75%" borderRadius={6} />
            <Skeleton height={18} width="100%" borderRadius={6} />
            <Skeleton height={18} width="90%" borderRadius={6} />
          </View>
        </ScrollView>
      </SafeAreaView>
    );
  }

  if (!recipe) {
    return (
      <SafeAreaView className="flex-1 bg-background items-center justify-center px-8">
        <Ionicons name="warning-outline" size={48} color="#94A3B8" />
        <Text className="text-lg font-semibold text-text-primary mt-4 mb-2">Recipe not found</Text>
        <Pressable onPress={() => router.back()} className="bg-primary px-6 py-3 rounded-xl mt-2">
          <Text className="text-white font-semibold">Go Back</Text>
        </Pressable>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView className="flex-1 bg-background" edges={['bottom']}>
      <ScrollView className="flex-1" showsVerticalScrollIndicator={false}>
        {/* Hero image (BR-DET-01) */}
        <View className="relative">
          <View className="h-64 bg-gray-200">
            {recipe.image ? (
              <Image
                source={{ uri: recipe.image }}
                className="w-full h-full"
                resizeMode="cover"
                accessibilityLabel={recipe.title}
              />
            ) : (
              <View className="flex-1 items-center justify-center">
                <Ionicons name="restaurant-outline" size={56} color="#CBD5E1" />
              </View>
            )}
          </View>
          {/* Back button overlay */}
          <Pressable
            onPress={() => router.back()}
            className="absolute top-4 left-4 w-10 h-10 bg-white/90 rounded-full items-center justify-center"
            accessibilityLabel="Go back"
          >
            <Ionicons name="arrow-back" size={20} color="#1E293B" />
          </Pressable>
          {/* Save overlay */}
          <Pressable
            onPress={handleSaveToggle}
            className="absolute top-4 right-4 w-10 h-10 bg-white/90 rounded-full items-center justify-center"
            accessibilityLabel={saved ? 'Remove from saved' : 'Save recipe'}
          >
            <Ionicons name={saved ? 'bookmark' : 'bookmark-outline'} size={20} color={saved ? '#2563EB' : '#1E293B'} />
          </Pressable>
        </View>

        <View className="px-6 pt-5">
          <Text className="text-2xl font-bold text-text-primary mb-2">{recipe.title}</Text>
          {recipe.description ? (
            <Text className="text-base text-text-secondary leading-6 mb-4">{recipe.description}</Text>
          ) : null}
        </View>

        {/* Summary bar (BR-DET-02) */}
        <View className="flex-row px-6 py-3 border-y border-border">
          <SummaryItem icon="time-outline" value={formatMinutes(recipe.cookTime)} label="Cook" />
          <SummaryItem icon="hourglass-outline" value={formatMinutes(recipe.prepTime)} label="Prep" />
          <SummaryItem icon="speedometer-outline" value={recipe.difficulty || 'Medium'} label="Level" capitalize />
          <SummaryItem icon="star-outline" value={recipe.rating ? Number(recipe.rating).toFixed(1) : '—'} label="Rating" />
        </View>

        {/* Serving size adjuster (BR-DET-03) */}
        <View className="px-6 py-4 border-b border-border">
          <Stepper
            label="Servings"
            value={servings}
            onValueChange={setServings}
            min={1}
            max={12}
          />
        </View>

        {/* Ingredients (BR-DET-04) */}
        <View className="px-6 py-4 border-b border-border">
          <Text className="text-lg font-bold text-text-primary mb-3">Ingredients</Text>
          {(recipe.ingredients || []).length === 0 ? (
            <Text className="text-text-muted text-sm">No ingredients listed.</Text>
          ) : (
            recipe.ingredients.map((ing, i) => {
              const haveIt = availableIngredientNames.has(ing.name?.toLowerCase());
              const scaled = scaledQuantity(ing.quantity, recipe.servings);
              return (
                <View key={i} className={'flex-row items-center py-2 border-b border-border/50 ' + (haveIt ? 'opacity-100' : 'opacity-70')}>
                  <View className={'w-2 h-2 rounded-full mr-3 ' + (haveIt ? 'bg-green-500' : 'bg-gray-300')} />
                  <Text className="text-sm text-text-primary flex-1">
                    <Text className="font-semibold">
                      {scaled ? scaled + ' ' + (ing.unit || '') + ' ' : ''}
                    </Text>
                    {ing.name}
                  </Text>
                  {haveIt ? (
                    <Text className="text-xs text-green-600 font-medium">have it</Text>
                  ) : null}
                </View>
              );
            })
          )}
        </View>

        {/* Instructions (BR-DET-05) */}
        <View className="px-6 py-4">
          <Text className="text-lg font-bold text-text-primary mb-3">Instructions</Text>
          {(recipe.instructions || []).length === 0 ? (
            <Text className="text-text-muted text-sm">No instructions available.</Text>
          ) : (
            recipe.instructions.map((step, i) => (
              <View key={i} className="flex-row mb-4">
                <View className="w-7 h-7 rounded-full bg-primary items-center justify-center mr-3 mt-0.5 flex-shrink-0">
                  <Text className="text-white text-xs font-bold">{step.step || i + 1}</Text>
                </View>
                <Text className="text-sm text-text-primary leading-6 flex-1">{step.text}</Text>
              </View>
            ))
          )}
        </View>

        {/* Source attribution (BR-DET-07) */}
        {recipe.sourceUrl ? (
          <View className="px-6 pb-4">
            <Text className="text-xs text-text-muted">Source: Spoonacular · {recipe.sourceUrl}</Text>
          </View>
        ) : null}

        <View className="h-4" />
      </ScrollView>

      {/* Action buttons (BR-DET-06) */}
      <View className="px-6 pb-6 gap-3 border-t border-border pt-4 bg-background">
        {cooked ? (
          <View className="py-4 rounded-xl bg-green-50 border border-green-200 items-center flex-row justify-center gap-2">
            <Ionicons name="checkmark-circle" size={20} color="#16A34A" />
            <Text className="text-green-700 font-semibold">Added to your history!</Text>
          </View>
        ) : (
          <Pressable
            onPress={handleCookThis}
            className="bg-primary py-4 rounded-xl items-center flex-row justify-center gap-2 active:opacity-90"
            accessibilityRole="button"
            accessibilityLabel="Cook this recipe"
          >
            <Ionicons name="flame-outline" size={20} color="white" />
            <Text className="text-white text-base font-semibold">Cook This</Text>
          </Pressable>
        )}
        <Pressable
          onPress={handleSaveToggle}
          className={'py-4 rounded-xl items-center border flex-row justify-center gap-2 active:bg-gray-50 ' + (saved ? 'border-primary bg-blue-50' : 'border-border bg-surface')}
          accessibilityRole="button"
          accessibilityLabel={saved ? 'Remove from saved' : 'Save for later'}
        >
          <Ionicons name={saved ? 'bookmark' : 'bookmark-outline'} size={18} color={saved ? '#2563EB' : '#64748B'} />
          <Text className={'text-base font-semibold ' + (saved ? 'text-primary' : 'text-text-primary')}>
            {saved ? 'Saved' : 'Save for Later'}
          </Text>
        </Pressable>
      </View>

      {/* Post-cook review modal (BR-DET-08) */}
      <Modal visible={showReview} transparent animationType="fade" onRequestClose={() => setShowReview(false)}>
        <View className="flex-1 bg-black/50 justify-end">
          <View className="bg-background rounded-t-3xl p-6">
            <Text className="text-xl font-bold text-text-primary mb-1">How did it go?</Text>
            <Text className="text-sm text-text-secondary mb-4">Quick rating to improve your recommendations.</Text>
            <View className="flex-row justify-center gap-3 mb-4">
              {[1, 2, 3, 4, 5].map((star) => (
                <Pressable key={star} onPress={() => setRating(star)} accessibilityLabel={star + ' stars'}>
                  <Ionicons
                    name={star <= rating ? 'star' : 'star-outline'}
                    size={36}
                    color={star <= rating ? '#F59E0B' : '#CBD5E1'}
                  />
                </Pressable>
              ))}
            </View>
            <TextInput
              value={reviewNote}
              onChangeText={setReviewNote}
              placeholder="Optional note (e.g. Too salty, Kids loved it)"
              placeholderTextColor="#94A3B8"
              className="border border-border rounded-xl px-4 py-3 text-sm text-text-primary mb-4 bg-surface"
              multiline
              maxLength={200}
              accessibilityLabel="Review note"
            />
            <Pressable onPress={handleSubmitReview} className="bg-primary py-4 rounded-xl items-center">
              <Text className="text-white font-semibold">
                {rating > 0 ? 'Submit Rating' : 'Skip'}
              </Text>
            </Pressable>
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}

function SummaryItem({ icon, value, label, capitalize }) {
  return (
    <View className="flex-1 items-center">
      <Ionicons name={icon} size={18} color="#64748B" />
      <Text className={'text-sm font-semibold text-text-primary mt-1 ' + (capitalize ? 'capitalize' : '')}>
        {value}
      </Text>
      <Text className="text-xs text-text-muted">{label}</Text>
    </View>
  );
}
