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
import { View, Text, ScrollView, Pressable, Image, ActivityIndicator } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Stack, useLocalSearchParams, useRouter } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import * as Haptics from 'expo-haptics';
import { useAuth } from '../../src/context/AuthContext';
import { useSession } from '../../src/context/SessionContext';
import { useSavedRecipesContext } from '../../src/context/SavedRecipesContext';
import { useRecipeContext } from '../../src/context/RecipeContext';
import useHistory from '../../src/hooks/useHistory';
import { getRecipeById, getSubstitutions } from '../../src/services/recipeService';
import { trackEvent } from '../../src/services/eventService';
import { formatMinutes } from '../../src/utils/time';
import Skeleton from '../../src/components/common/Skeleton';
import Stepper from '../../src/components/common/Stepper';

const DIFFICULTY_LABEL = { easy: 'Easy', medium: 'Medium', hard: 'Hard' };

// ---------------------------------------------------------------------------
// Common pantry staples — assumed to be available in any home kitchen.
// These are highlighted green even when not in the user's scanned ingredients.
// ONLY: salt, black pepper, oil, vinegar, water.
// ---------------------------------------------------------------------------
// Do NOT assume the user has: flour, sugar, baking soda, baking powder,
// cornstarch, butter, milk, eggs, cream, cheese, honey, soy sauce,
// vanilla extract, spices, seasonings, or any fresh produce/perishables.
const PANTRY_STAPLES = new Set([
  // salt
  'salt', 'sea salt', 'kosher salt',
  // pepper
  'black pepper', 'white pepper', 'ground pepper', 'pepper',
  // oils
  'vegetable oil', 'canola oil', 'olive oil', 'extra virgin olive oil',
  'oil', 'cooking oil',
  // vinegar
  'white vinegar', 'apple cider vinegar', 'red wine vinegar', 'vinegar',
  // water
  'water',
]);

// Ingredients that are genuinely in every kitchen
// (NOT butter, milk, eggs, honey — not everyone has these)

// Keyword-based fallback: ingredient names ending in a staple word
// Deliberately conservative — ONLY salt, pepper, oil, vinegar, water
const _STAPLE_ENDING = new Set([
  'salt', 'pepper', 'oil', 'vinegar', 'water',
]);

function isPantryStaple(name) {
  const key = name
    .toLowerCase()
    .trim()
    // strip leading helper words that don't change the ingredient
    .replace(/^(fresh|freshly|finely|coarsely|roughly|lightly|optionally|to taste|a pinch of|pinch of)\s+/, '')
    .trim();
  if (PANTRY_STAPLES.has(key)) return true;
  // e.g. "kosher salt", "olive oil", "dark brown sugar" — last word is a staple keyword
  const lastWord = key.split(' ').pop();
  return _STAPLE_ENDING.has(lastWord);
}

// ---------------------------------------------------------------------------
// Quick local fallback while LLM substitutions are loading
// Uses token-based fuzzy matching to align with backend ranking_service.py
// ---------------------------------------------------------------------------
const _MODIFIERS = new Set([
  'fresh', 'dried', 'ground', 'chopped', 'minced', 'sliced', 'diced',
  'crushed', 'large', 'small', 'medium', 'whole', 'boneless', 'skinless',
  'organic', 'frozen', 'canned', 'raw', 'cooked', 'shredded', 'grated',
  'melted', 'softened', 'packed', 'finely', 'roughly', 'thinly', 'thick',
  'thin', 'ripe', 'firm', 'extra', 'plain', 'unsalted', 'salted',
  'unsweetened', 'sweetened', 'light', 'dark', 'lean', 'trimmed',
  'peeled', 'deveined', 'pitted', 'toasted', 'roasted', 'smoked',
  'pickled', 'marinated', 'halved', 'quartered',
]);

function _normalizeToken(t) {
  if (t.length <= 2) return t;
  if (t.endsWith('ies') && t.length > 4) return t.slice(0, -3) + 'y';
  if (t.endsWith('oes') && t.length > 4) return t.slice(0, -2);
  if (t.endsWith('es') && t.length > 4) {
    const base = t.slice(0, -2);
    if (/(?:s|x|z|ch|sh)$/.test(base)) return base;
    return t.slice(0, -1);
  }
  if (t.endsWith('s') && !t.endsWith('ss') && t.length > 3) return t.slice(0, -1);
  return t;
}

function _tokenize(name) {
  const raw = new Set(name.toLowerCase().replace(/-/g, ' ').split(/\s+/).filter(Boolean));
  const meaningful = new Set([...raw].filter(w => !_MODIFIERS.has(w)));
  const tokens = meaningful.size > 0 ? meaningful : raw;
  return new Set([...tokens].map(_normalizeToken));
}

function _buildAvailableTokens(availableNames) {
  const tokens = new Set();
  for (const name of availableNames) {
    for (const t of _tokenize(name)) tokens.add(t);
  }
  return tokens;
}

// ── Equivalence families (mirrors backend ranking_service.py) ────────────
// Items in the same family are interchangeable for "have it" matching.
const _EQUIVALENCE_FAMILIES = [
  new Set(['pasta','spaghetti','linguine','fettuccine','penne','rigatoni','rotini','fusilli','farfalle','macaroni','ziti','orzo','tagliatelle','pappardelle','bucatini','angel hair','elbow macaroni','cavatappi','orecchiette','shells','egg noodles','noodles','ramen noodles','udon noodles','rice noodles','lo mein noodles','soba noodles']),
  new Set(['milk','whole milk','2% milk','skim milk','low-fat milk','cream','heavy cream','heavy whipping cream','whipping cream','half and half','half-and-half','light cream','evaporated milk','coconut milk','oat milk','almond milk','soy milk','plant milk']),
  new Set(['rice','white rice','brown rice','jasmine rice','basmati rice','long grain rice','short grain rice','sushi rice','arborio rice','wild rice','instant rice']),
  new Set(['chicken','chicken breast','chicken thigh','chicken thighs','chicken leg','chicken legs','chicken drumstick','chicken drumsticks','chicken wing','chicken wings','chicken tender','chicken tenders','rotisserie chicken','boneless chicken']),
  new Set(['beef','ground beef','steak','beef stew meat','chuck roast','sirloin','flank steak','skirt steak','ribeye','beef chuck','stewing beef']),
  new Set(['pork','pork chops','pork loin','pork tenderloin','pork shoulder','ground pork','pork belly']),
  new Set(['cheese','cheddar cheese','cheddar','mozzarella','mozzarella cheese','parmesan','parmesan cheese','swiss cheese','provolone','monterey jack','colby jack','pepper jack','american cheese','cream cheese','gouda','gruyere','feta','feta cheese','ricotta','ricotta cheese','cottage cheese']),
  new Set(['onion','onions','yellow onion','white onion','red onion','sweet onion','shallot','shallots','green onion','green onions','scallion','scallions','spring onion','spring onions']),
  new Set(['potato','potatoes','russet potato','russet potatoes','yukon gold potato','yukon gold potatoes','red potato','red potatoes','sweet potato','sweet potatoes','baby potatoes','fingerling potatoes','new potatoes']),
  new Set(['tomato','tomatoes','cherry tomatoes','grape tomatoes','roma tomatoes','plum tomatoes','canned tomatoes','diced tomatoes','crushed tomatoes','tomato sauce','tomato paste','tomato puree','stewed tomatoes']),
  new Set(['bread','white bread','wheat bread','whole wheat bread','sourdough bread','sandwich bread','french bread','italian bread','ciabatta','baguette','rolls','dinner rolls','hamburger buns','hot dog buns','buns','pita','pita bread','naan','flatbread','tortilla','tortillas','flour tortilla','flour tortillas','corn tortilla','corn tortillas','taco shell','taco shells']),
  new Set(['bell pepper','bell peppers','green bell pepper','red bell pepper','yellow bell pepper','orange bell pepper','green pepper','red pepper','sweet pepper']),
  new Set(['yogurt','greek yogurt','plain yogurt','vanilla yogurt','sour cream']),
  new Set(['lemon','lemons','lemon juice','lime','limes','lime juice']),
  new Set(['garlic','garlic clove','garlic cloves','minced garlic','fresh garlic','crushed garlic']),
  new Set(['butter','unsalted butter','salted butter']),
  new Set(['egg','eggs','large egg','large eggs']),
  new Set(['sugar','white sugar','granulated sugar','cane sugar']),
  new Set(['flour','all-purpose flour','all purpose flour','ap flour','plain flour','whole wheat flour','wheat flour']),
  new Set(['soy sauce','low sodium soy sauce','light soy sauce','dark soy sauce','tamari','coconut aminos']),
];

// Build lookup: ingredient → family index
const _INGREDIENT_TO_FAMILY = {};
_EQUIVALENCE_FAMILIES.forEach((family, idx) => {
  for (const member of family) {
    _INGREDIENT_TO_FAMILY[member] = idx;
  }
});

function _buildUserFamilies(availableNames) {
  const families = new Set();
  for (const name of availableNames) {
    const lower = name.toLowerCase().trim();
    if (_INGREDIENT_TO_FAMILY[lower] !== undefined) families.add(_INGREDIENT_TO_FAMILY[lower]);
    // Also check with modifiers stripped
    const stripped = lower.split(/\s+/).filter(w => !_MODIFIERS.has(w)).join(' ');
    if (_INGREDIENT_TO_FAMILY[stripped] !== undefined) families.add(_INGREDIENT_TO_FAMILY[stripped]);
  }
  return families;
}

function _userHasEquivalent(recipeName, userFamilies) {
  const lower = recipeName.toLowerCase().trim();
  const fam = _INGREDIENT_TO_FAMILY[lower];
  if (fam !== undefined && userFamilies.has(fam)) return true;
  const stripped = lower.split(/\s+/).filter(w => !_MODIFIERS.has(w)).join(' ');
  const fam2 = _INGREDIENT_TO_FAMILY[stripped];
  if (fam2 !== undefined && userFamilies.has(fam2)) return true;
  return false;
}

function quickIngredientMatch(recipeName, availableNames, availableTokens, userFamilies) {
  const rn = recipeName.toLowerCase().trim();
  if (availableNames.has(rn)) return true;
  // Token-based fuzzy match (same as backend)
  const nameTokens = _tokenize(rn);
  for (const t of nameTokens) {
    if (availableTokens.has(t)) return true;
  }
  // Equivalence family match (pasta ↔ fettuccine, milk ↔ cream, etc.)
  if (userFamilies && _userHasEquivalent(rn, userFamilies)) return true;
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
  const { save, remove, isSaved, savedRecipes } = useSavedRecipesContext();
  const { recipes: allRecipes, substitutionsCache, prefetchSubstitutions } = useRecipeContext();
  const { addEntry } = useHistory();

  const [recipe, setRecipe] = useState(null);
  const [loading, setLoading] = useState(true);
  const [servings, setServings] = useState(null);
  const [cooked, setCooked] = useState(false);
  const [imageError, setImageError] = useState(false);

  // LLM substitution results: maps ingredient name → {have, substitution}
  const [llmSubs, setLlmSubs] = useState(null);
  const [subsLoading, setSubsLoading] = useState(false);
  const subsRequested = useRef(false);

  useEffect(() => {
    if (!id) return;
    // Try to find the recipe in the already-loaded context cache first.
    // This makes navigation instant — no round-trip needed.
    const cached = allRecipes.find((r) => r.id === id);
    if (cached) {
      setRecipe(cached);
      setServings(session.servingCount || cached.servings || 2);
      setLoading(false);
    } else {
      // Fallback for deep links or bookmarks — fetch from API
      loadRecipe();
    }
    if (user?.id && session.sessionPoolId) {
      trackEvent({ userId: user.id, sessionId: session.sessionPoolId, recipeId: id, eventType: 'recipe_viewed' }).catch(() => {});
    }
  }, [id]);

  // Read substitutions from context cache (pre-fetched by discover.js).
  // If the cache entry is already done, apply it immediately with no wait.
  // If it's still loading in the background, show the spinner and apply when done.
  // If not in cache at all (e.g. user opened via deep link), fetch now.
  useEffect(() => {
    if (!recipe || subsRequested.current) return;

    const cached = substitutionsCache[id];

    if (cached?.done && cached.substitutions) {
      // ✅ Already in cache — instant, no spinner
      subsRequested.current = true;
      const map = {};
      for (const s of cached.substitutions) {
        if (s.ingredient) {
          map[s.ingredient.toLowerCase().trim()] = {
            have: !!s.have,
            substitution: s.substitution || null,
          };
        }
      }
      setLlmSubs(map);
      return;
    }

    if (cached?.loading) {
      // In flight from discover pre-fetch — show spinner, wait for it to finish
      setSubsLoading(true);
      return;
    }

    // Not in cache (deep link, direct navigation) — fetch now
    const ingredients = (recipe.ingredients || []).map((ing) => ing.name || '').filter(Boolean);
    const userIngs = (session.availableIngredients || []).map((i) => i.name).filter(Boolean);
    if (ingredients.length === 0) return;
    subsRequested.current = true;
    setSubsLoading(true);
    prefetchSubstitutions(id, ingredients, userIngs);
  }, [recipe, substitutionsCache, id]);

  // Watch for cache to finish loading (covers the "loading" branch above)
  useEffect(() => {
    const cached = substitutionsCache[id];
    if (!cached?.done || !cached.substitutions) return;
    const map = {};
    for (const s of cached.substitutions) {
      if (s.ingredient) {
        map[s.ingredient.toLowerCase().trim()] = {
          have: !!s.have,
          substitution: s.substitution || null,
        };
      }
    }
    setLlmSubs(map);
    setSubsLoading(false);
  }, [substitutionsCache, id]);

  const loadRecipe = async () => {
    setLoading(true);
    try {
      const data = await getRecipeById(id);
      setRecipe(data);
      setServings(session.servingCount || data.servings || 2);
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
    // No immediate review prompt — people don't cook that fast.
    // The History tab lets them rate and add notes whenever they're ready.
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

  const saved = isSaved(id);
  const availableNames = new Set(
    (session.availableIngredients || []).map((i) => i.name.toLowerCase().trim())
  );
  const availableTokens = _buildAvailableTokens(availableNames);
  const userFamilies = _buildUserFamilies(availableNames);

  // Pre-compute ingredient status for each recipe ingredient.
  // Uses LLM results when available; falls back to quick local matching.
  // Pantry staples are always "have it" regardless of scanned ingredients.
  const ingredientStatus = (recipe?.ingredients || []).map((ing) => {
    const name = (ing.name || '').trim();
    const nameKey = name.toLowerCase().trim();

    // Pantry staples (salt, pepper, oil, vinegar) — assumed always on hand
    if (isPantryStaple(name)) {
      return { haveIt: true, substitution: null, isPantry: true };
    }
    // LLM results take priority
    if (llmSubs && llmSubs[nameKey]) {
      return {
        haveIt: llmSubs[nameKey].have,
        substitution: llmSubs[nameKey].substitution,
        isPantry: false,
      };
    }
    // Fallback: token-based fuzzy match + equivalence families
    const haveIt = quickIngredientMatch(name, availableNames, availableTokens, userFamilies);
    return { haveIt, substitution: null, isPantry: false };
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
      {/* Override header: reliable explicit back button that always works */}
      <Stack.Screen
        options={{
          headerLeft: () => (
            <Pressable
              onPress={() => (router.canGoBack() ? router.back() : router.replace('/(tabs)/discover'))}
              hitSlop={16}
              style={{ paddingHorizontal: 4 }}
            >
              <Ionicons name="chevron-back" size={28} color="#1E293B" />
            </Pressable>
          ),
          headerTitle: '',
          headerShadowVisible: false,
        }}
      />
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
              <Text className="text-sm font-bold text-text-primary mt-1">{servings || recipe.servings || 4}</Text>
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
              const { haveIt, substitution, isPantry } = ingredientStatus[i] || {};
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
                    {haveIt && isPantry ? (
                      <View className="ml-2 bg-green-50 px-2 py-0.5 rounded-full border border-green-200">
                        <Text className="text-xs text-green-600 font-semibold">Pantry ✓</Text>
                      </View>
                    ) : haveIt ? (
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
          <Text className="text-xs text-text-muted mb-1">
            {(recipe.instructions || []).length} steps
          </Text>
          {servings && recipe.servings && servings !== recipe.servings ? (
            <View className="flex-row items-center gap-1 mb-3 bg-blue-50 border border-blue-200 rounded-lg px-3 py-2">
              <Ionicons name="information-circle-outline" size={14} color="#2563EB" />
              <Text className="text-xs text-blue-700">
                Quantities in steps are written for {recipe.servings} servings — you scaled to {servings}.
                Adjust measurements proportionally ({servings > recipe.servings ? '×' : '÷'}{Math.abs(Math.round((servings / recipe.servings) * 10) / 10)})
              </Text>
            </View>
          ) : <View className="mb-3" />}
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
          <View className="py-4 rounded-xl bg-green-50 border border-green-200 px-4">
            <View className="flex-row items-center gap-2 mb-1">
              <Ionicons name="checkmark-circle" size={20} color="#16A34A" />
              <Text className="text-green-700 font-semibold">Added to cooking history!</Text>
            </View>
            <Text className="text-xs text-green-600 ml-7">
              Head to the History tab whenever you're done to rate it and add notes.
            </Text>
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
    </SafeAreaView>
  );
}
