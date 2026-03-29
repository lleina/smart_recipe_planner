/**
 * Recipe detail screen — structured layout per BR-DET-01 through BR-DET-08.
 * Shows hero image, time summary, full ingredient list with pantry matches,
 * numbered instructions, and Cook This / Save actions.
 *
 * Ingredient substitutions are powered by the LLM via the backend
 * POST /api/recipes/:id/substitutions endpoint. A lightweight local fallback
 * (simple containment matching) covers the loading period.
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import { View, Text, ScrollView, Pressable, Image, TextInput, Modal, ActivityIndicator } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import * as Haptics from 'expo-haptics';
import { useAuth } from '../../src/context/AuthContext';
import { useSession } from '../../src/context/SessionContext';
import useSavedRecipes from '../../src/hooks/useSavedRecipes';
import useHistory from '../../src/hooks/useHistory';
import { getRecipeById, getSubstitutions } from '../../src/services/recipeService';
import { trackEvent } from '../../src/services/eventService';
import { formatMinutes } from '../../src/utils/time';
import Skeleton from '../../src/components/common/Skeleton';
import Stepper from '../../src/components/common/Stepper';

const DIFFICULTY_LABEL = { easy: 'Easy', medium: 'Medium', hard: 'Hard' };

// ---------------------------------------------------------------------------
// Quick local fallback while LLM substitutions are loading
// ---------------------------------------------------------------------------
function quickIngredientMatch(recipeName, availableNames) {
  const rn = recipeName.toLowerCase().trim();
  if (availableNames.has(rn)) return true;
  const stripped = rn.replace(
    /^(fresh|frozen|dried|canned|cooked|raw|boneless|skinless|chopped|minced|diced|sliced|grated|shredded|large|small|medium|ripe|peeled|trimmed|halved|quartered)\s+/gi,
    ''
  );
  if (availableNames.has(stripped)) return true;
  for (const avail of availableNames) {
    if (stripped.includes(avail) || avail.includes(stripped)) return true;
  }
  return false;
}

/**
 * Format a quantity for display: "1" not "", fractions where nice.
 */
function formatQuantity(qty) {
  if (qty == null || qty === 0) return '';
  // Common fraction display
  const fractionMap = {
    0.25: '¼', 0.33: '⅓', 0.333: '⅓', 0.5: '½', 0.67: '⅔', 0.667: '⅔', 0.75: '¾',
    0.125: '⅛',
  };
  if (Number.isInteger(qty)) return String(qty);
  const whole = Math.floor(qty);
  const frac = Math.round((qty - whole) * 1000) / 1000;
  const fracStr = fractionMap[frac];
  if (fracStr) return whole > 0 ? `${whole} ${fracStr}` : fracStr;
  // Fall back to decimal, trim trailing zeros
  return qty % 1 === 0 ? String(qty) : String(Math.round(qty * 100) / 100);
}

/**
 * Parse instruction text into rich segments — highlight times, temps, ingredients.
 */
function parseInstructionSegments(text) {
  if (!text) return [{ type: 'text', value: text || '' }];
  const segments = [];
  // Split on time/temp patterns
  const pattern = /(\d+[-–]\d+\s*(?:minutes?|mins?|hours?|hrs?|seconds?|secs?)|\d+\s*(?:minutes?|mins?|hours?|hrs?|seconds?|secs?)|(?:\d+\s*°[FC]|\d+\s*degrees?\s*(?:fahrenheit|celsius)?))/gi;
  let lastIndex = 0;
  let match;
  while ((match = pattern.exec(text)) !== null) {
    if (match.index > lastIndex) {
      segments.push({ type: 'text', value: text.slice(lastIndex, match.index) });
    }
    segments.push({ type: 'highlight', value: match[0] });
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex < text.length) {
    segments.push({ type: 'text', value: text.slice(lastIndex) });
  }
  return segments.length > 0 ? segments : [{ type: 'text', value: text }];
}

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
  const [imageError, setImageError] = useState(false);

  // LLM substitution results: maps ingredient name → {have, substitution}
  const [llmSubs, setLlmSubs] = useState(null);
  const [subsLoading, setSubsLoading] = useState(false);
  const subsRequested = useRef(false);

  useEffect(() => {
    if (!id) return;
    loadRecipe();
    if (user?.id && session.sessionPoolId) {
      trackEvent({ userId: user.id, sessionId: session.sessionPoolId, recipeId: id, eventType: 'recipe_viewed' }).catch(() => {});
    }
  }, [id]);

  // Fire LLM substitution request once recipe is loaded
  useEffect(() => {
    if (!recipe || subsRequested.current) return;
    const ingredients = (recipe.ingredients || []).map((ing) => ing.name || '').filter(Boolean);
    const userIngs = (session.availableIngredients || []).map((i) => i.name).filter(Boolean);
    if (ingredients.length === 0) return;
    subsRequested.current = true;
    setSubsLoading(true);
    getSubstitutions(id, ingredients, userIngs)
      .then((res) => {
        if (res?.substitutions && Array.isArray(res.substitutions)) {
          // Build a lookup map by ingredient name (lowercased)
          const map = {};
          for (const s of res.substitutions) {
            if (s.ingredient) {
              map[s.ingredient.toLowerCase().trim()] = {
                have: !!s.have,
                substitution: s.substitution || null,
              };
            }
          }
          setLlmSubs(map);
        }
      })
      .catch(() => {
        // LLM unavailable — local fallback stays active
      })
      .finally(() => setSubsLoading(false));
  }, [recipe]);

  const loadRecipe = async () => {
    setLoading(true);
    try {
      const data = await getRecipeById(id);
      setRecipe(data);
      setServings(data.servings || session.servingCount || 2);
    } catch {
      // recipe stays null → shows error state
    } finally {
      setLoading(false);
    }
  };

  const scaledQty = useCallback((baseQty, baseServings) => {
    if (!baseQty || !baseServings || !servings) return baseQty;
    const scaled = (baseQty / baseServings) * servings;
    return Math.round(scaled * 100) / 100;
  }, [servings]);

  const handleCookThis = async () => {
    Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
    setCooked(true);
    if (user?.id) await addEntry(id, session.mealType, servings, session.sessionPoolId);
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
        userId: user.id, sessionId: session.sessionPoolId, recipeId: id,
        eventType: 'recipe_reviewed', metadata: { rating, note: reviewNote },
      }).catch(() => {});
    }
    setShowReview(false);
    router.back();
  };

  const saved = isSaved(id);
  const availableNames = new Set(
    (session.availableIngredients || []).map((i) => i.name.toLowerCase().trim())
  );

  // Pre-compute ingredient status for each recipe ingredient.
  // Uses LLM results when available; falls back to quick local matching.
  const ingredientStatus = (recipe?.ingredients || []).map((ing) => {
    const name = (ing.name || '').trim();
    const nameKey = name.toLowerCase().trim();

    // LLM results take priority
    if (llmSubs && llmSubs[nameKey]) {
      return {
        haveIt: llmSubs[nameKey].have,
        substitution: llmSubs[nameKey].substitution,
      };
    }
    // Fallback: simple local match (no substitution suggestions)
    const haveIt = quickIngredientMatch(name, availableNames);
    return { haveIt, substitution: null };
  });

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

  // Time helpers — use real prep/cook when available, fall back to total
  const prepTime = recipe.prepTime > 0 ? recipe.prepTime : null;
  const cookTime = recipe.cookTime > 0 ? recipe.cookTime : null;
  const totalTime = recipe.totalTime || 0;

  return (
    <SafeAreaView className="flex-1 bg-background" edges={['bottom']}>
      <ScrollView className="flex-1" showsVerticalScrollIndicator={false}>

        {/* Hero image */}
        <View className="relative">
          <View className="h-64 bg-gray-200">
            {recipe.image && !imageError ? (
              <Image
                source={{ uri: recipe.image }}
                className="w-full h-full"
                resizeMode="cover"
                onError={() => setImageError(true)}
                accessibilityLabel={recipe.title}
              />
            ) : (
              <View className="flex-1 items-center justify-center">
                <Ionicons name="restaurant-outline" size={56} color="#CBD5E1" />
              </View>
            )}
          </View>
          <Pressable
            onPress={() => router.back()}
            className="absolute top-4 left-4 w-10 h-10 bg-white/90 rounded-full items-center justify-center"
            accessibilityLabel="Go back"
          >
            <Ionicons name="arrow-back" size={20} color="#1E293B" />
          </Pressable>
          <Pressable
            onPress={handleSaveToggle}
            className="absolute top-4 right-4 w-10 h-10 bg-white/90 rounded-full items-center justify-center"
            accessibilityLabel={saved ? 'Remove from saved' : 'Save recipe'}
          >
            <Ionicons name={saved ? 'bookmark' : 'bookmark-outline'} size={20} color={saved ? '#2563EB' : '#1E293B'} />
          </Pressable>
        </View>

        {/* Title + description */}
        <View className="px-6 pt-5 pb-2">
          <Text className="text-2xl font-bold text-text-primary mb-1">{recipe.title}</Text>
          {recipe.cuisine ? (
            <Text className="text-sm text-text-muted capitalize mb-2">{recipe.cuisine} cuisine</Text>
          ) : null}
          {recipe.description ? (
            <Text className="text-base text-text-secondary leading-6">{recipe.description}</Text>
          ) : null}
        </View>

        {/* Time + difficulty summary bar */}
        <View className="mx-6 mt-3 mb-1 rounded-2xl bg-gray-50 border border-border overflow-hidden">
          <View className="flex-row">
            {prepTime ? (
              <View className="flex-1 items-center py-3 border-r border-border">
                <Ionicons name="time-outline" size={18} color="#2563EB" />
                <Text className="text-sm font-bold text-text-primary mt-1">{formatMinutes(prepTime)}</Text>
                <Text className="text-xs text-text-muted">Prep</Text>
              </View>
            ) : null}
            {cookTime ? (
              <View className="flex-1 items-center py-3 border-r border-border">
                <Ionicons name="flame-outline" size={18} color="#EA580C" />
                <Text className="text-sm font-bold text-text-primary mt-1">{formatMinutes(cookTime)}</Text>
                <Text className="text-xs text-text-muted">Cook</Text>
              </View>
            ) : null}
            {!prepTime && !cookTime ? (
              <View className="flex-1 items-center py-3 border-r border-border">
                <Ionicons name="time-outline" size={18} color="#2563EB" />
                <Text className="text-sm font-bold text-text-primary mt-1">{formatMinutes(totalTime)}</Text>
                <Text className="text-xs text-text-muted">Total</Text>
              </View>
            ) : null}
            <View className="flex-1 items-center py-3 border-r border-border">
              <Ionicons name="speedometer-outline" size={18} color="#64748B" />
              <Text className="text-sm font-bold text-text-primary mt-1 capitalize">
                {DIFFICULTY_LABEL[recipe.difficulty] || 'Medium'}
              </Text>
              <Text className="text-xs text-text-muted">Level</Text>
            </View>
            <View className="flex-1 items-center py-3 border-r border-border">
              <Ionicons name="people-outline" size={18} color="#64748B" />
              <Text className="text-sm font-bold text-text-primary mt-1">{recipe.servings || 4}</Text>
              <Text className="text-xs text-text-muted">Serves</Text>
            </View>
            {recipe.rating > 0 ? (
              <View className="flex-1 items-center py-3">
                <Ionicons name="star" size={18} color="#F59E0B" />
                <Text className="text-sm font-bold text-text-primary mt-1">{Number(recipe.rating).toFixed(1)}</Text>
                <Text className="text-xs text-text-muted">Rating</Text>
              </View>
            ) : null}
          </View>
        </View>

        {/* Serving adjuster */}
        <View className="px-6 py-4 border-b border-border">
          <Stepper label="Servings" value={servings} onValueChange={setServings} min={1} max={12} />
        </View>

        {/* Ingredients */}
        <View className="px-6 py-4 border-b border-border">
          <View className="flex-row items-center justify-between mb-1">
            <View className="flex-row items-center gap-2">
              <Text className="text-lg font-bold text-text-primary">Ingredients</Text>
              {subsLoading ? (
                <ActivityIndicator size="small" color="#64748B" />
              ) : null}
            </View>
            {ingredientStatus.filter(s => s.haveIt).length > 0 ? (
              <View className="bg-green-50 px-2.5 py-1 rounded-full">
                <Text className="text-xs font-semibold text-green-700">
                  {ingredientStatus.filter(s => s.haveIt).length}/{(recipe.ingredients || []).length} in pantry
                </Text>
              </View>
            ) : null}
          </View>
          <Text className="text-xs text-text-muted mb-3">
            {(recipe.ingredients || []).length} items
            {servings !== recipe.servings ? ` · scaled for ${servings} servings` : ''}
            {subsLoading ? ' · checking pantry…' : ''}
          </Text>
          {(recipe.ingredients || []).length === 0 ? (
            <Text className="text-sm text-text-muted">No ingredients available.</Text>
          ) : (
            recipe.ingredients.map((ing, i) => {
              const { haveIt, substitution } = ingredientStatus[i] || {};
              const qty = scaledQty(ing.quantity, recipe.servings);
              const qtyStr = formatQuantity(qty);
              const unitStr = ing.unit && ing.unit !== 'as needed' ? ing.unit : '';
              const nameStr = ing.name || '';
              return (
                <View
                  key={i}
                  className={'py-3 border-b border-border/30 ' + (haveIt ? 'bg-green-50/50' : '')}
                >
                  <View className="flex-row items-center">
                    {/* Status icon */}
                    <View className="w-6 items-center mr-2 flex-shrink-0">
                      {haveIt ? (
                        <Ionicons name="checkmark-circle" size={18} color="#16A34A" />
                      ) : substitution ? (
                        <Ionicons name="swap-horizontal" size={18} color="#D97706" />
                      ) : (
                        <Ionicons name="cart-outline" size={16} color="#94A3B8" />
                      )}
                    </View>
                    {/* Quantity + name */}
                    <Text className="text-sm text-text-primary flex-1 leading-5">
                      {qtyStr ? (
                        <Text className="font-bold text-text-primary">{qtyStr} </Text>
                      ) : null}
                      {unitStr ? (
                        <Text className="text-text-secondary">{unitStr} </Text>
                      ) : null}
                      <Text className="text-text-primary">{nameStr}</Text>
                    </Text>
                    {/* Status label */}
                    {haveIt ? (
                      <View className="ml-2 bg-green-100 px-2 py-0.5 rounded-full">
                        <Text className="text-xs text-green-700 font-semibold">Have it</Text>
                      </View>
                    ) : substitution ? (
                      <View className="ml-2 bg-amber-100 px-2 py-0.5 rounded-full">
                        <Text className="text-xs text-amber-700 font-semibold">Can swap</Text>
                      </View>
                    ) : (
                      <View className="ml-2 bg-gray-100 px-2 py-0.5 rounded-full">
                        <Text className="text-xs text-text-muted">Need</Text>
                      </View>
                    )}
                  </View>
                  {/* Substitution suggestion from LLM */}
                  {substitution ? (
                    <View className="flex-row items-center ml-8 mt-1.5">
                      <Ionicons name="swap-horizontal-outline" size={13} color="#D97706" />
                      <Text className="text-xs text-amber-600 ml-1">
                        {substitution.startsWith('use ') || substitution.startsWith('Use ')
                          ? substitution
                          : `Try ${substitution} instead`}
                      </Text>
                    </View>
                  ) : null}
                </View>
              );
            })
          )}
        </View>

        {/* Instructions */}
        <View className="px-6 py-4 border-b border-border">
          <Text className="text-lg font-bold text-text-primary mb-1">Instructions</Text>
          <Text className="text-xs text-text-muted mb-4">
            {(recipe.instructions || []).length} steps
          </Text>
          {(recipe.instructions || []).length === 0 ? (
            <Text className="text-sm text-text-muted">No instructions available.</Text>
          ) : (
            recipe.instructions.map((step, i) => {
              const segments = parseInstructionSegments(step.text);
              const isLast = i === recipe.instructions.length - 1;
              return (
                <View key={i} className={'flex-row mb-0 ' + (!isLast ? 'pb-4' : '')}>
                  {/* Step number column with connector line */}
                  <View className="items-center mr-4">
                    <View className="w-8 h-8 rounded-full bg-primary items-center justify-center flex-shrink-0">
                      <Text className="text-white text-xs font-bold">{step.step || i + 1}</Text>
                    </View>
                    {!isLast ? (
                      <View className="w-0.5 flex-1 bg-gray-200 mt-1" />
                    ) : null}
                  </View>
                  {/* Step content */}
                  <View className="flex-1 pb-2">
                    <Text className="text-sm text-text-primary leading-6">
                      {segments.map((seg, j) =>
                        seg.type === 'highlight' ? (
                          <Text key={j} className="font-bold text-primary bg-blue-50 rounded">
                            {seg.value}
                          </Text>
                        ) : (
                          <Text key={j}>{seg.value}</Text>
                        )
                      )}
                    </Text>
                    {step.image ? (
                      <Image
                        source={{ uri: step.image }}
                        className="w-full h-40 rounded-lg mt-2"
                        resizeMode="cover"
                      />
                    ) : null}
                  </View>
                </View>
              );
            })
          )}
        </View>

        {/* Source */}
        {recipe.sourceUrl ? (
          <View className="px-6 py-3">
            <Text className="text-xs text-text-muted" numberOfLines={1}>
              Recipe from: {recipe.sourceUrl}
            </Text>
          </View>
        ) : null}

        <View className="h-6" />
      </ScrollView>

      {/* Action buttons */}
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
          >
            <Ionicons name="flame-outline" size={20} color="white" />
            <Text className="text-white text-base font-semibold">Cook This</Text>
          </Pressable>
        )}
        <Pressable
          onPress={handleSaveToggle}
          className={'py-4 rounded-xl items-center border flex-row justify-center gap-2 active:bg-gray-50 '
            + (saved ? 'border-primary bg-blue-50' : 'border-border bg-surface')}
          accessibilityRole="button"
        >
          <Ionicons name={saved ? 'bookmark' : 'bookmark-outline'} size={18} color={saved ? '#2563EB' : '#64748B'} />
          <Text className={'text-base font-semibold ' + (saved ? 'text-primary' : 'text-text-primary')}>
            {saved ? 'Saved' : 'Save for Later'}
          </Text>
        </Pressable>
      </View>

      {/* Post-cook review modal */}
      <Modal visible={showReview} transparent animationType="fade" onRequestClose={() => setShowReview(false)}>
        <View className="flex-1 bg-black/50 justify-end">
          <View className="bg-background rounded-t-3xl p-6">
            <Text className="text-xl font-bold text-text-primary mb-1">How did it go?</Text>
            <Text className="text-sm text-text-secondary mb-4">Rate this recipe to improve future recommendations.</Text>
            <View className="flex-row justify-center gap-3 mb-4">
              {[1, 2, 3, 4, 5].map((star) => (
                <Pressable key={star} onPress={() => setRating(star)} accessibilityLabel={star + ' stars'}>
                  <Ionicons name={star <= rating ? 'star' : 'star-outline'} size={36} color={star <= rating ? '#F59E0B' : '#CBD5E1'} />
                </Pressable>
              ))}
            </View>
            <TextInput
              value={reviewNote}
              onChangeText={setReviewNote}
              placeholder="Optional note (e.g. too salty, kids loved it)"
              placeholderTextColor="#94A3B8"
              className="border border-border rounded-xl px-4 py-3 text-sm text-text-primary mb-4 bg-surface"
              multiline
              maxLength={200}
            />
            <Pressable onPress={handleSubmitReview} className="bg-primary py-4 rounded-xl items-center">
              <Text className="text-white font-semibold">{rating > 0 ? 'Submit Rating' : 'Skip'}</Text>
            </Pressable>
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}
