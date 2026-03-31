/**
 * Pre-cooking session setup screen.
 * Gathers: meal type, serving count, time, occasion, ingredients (via VLM or manual).
 * Completable in under 30 seconds (BR-CTX-06).
 */

import { useState, useRef, useCallback } from 'react';
import { View, Text, ScrollView, Pressable, TextInput, ActivityIndicator } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useRouter } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import * as Haptics from 'expo-haptics';
import Animated, { useSharedValue, useAnimatedStyle, runOnJS } from 'react-native-reanimated';
import { GestureDetector, Gesture } from 'react-native-gesture-handler';
import { useSession } from '../../src/context/SessionContext';
import { useAuth } from '../../src/context/AuthContext';
import useVlm from '../../src/hooks/useVlm';
import Button from '../../src/components/common/Button';
import Tag from '../../src/components/common/Tag';
import Stepper from '../../src/components/common/Stepper';
import { MEAL_TYPES } from '../../src/constants/mealTypes';
import { SERVING_COUNT_MIN, SERVING_COUNT_MAX, PERISHABLE_URGENCY_DAYS } from '../../src/constants/config';

const OCCASIONS = [
  { id: 'weeknight', label: 'Weeknight' },
  { id: 'date-night', label: 'Date Night' },
  { id: 'holiday', label: 'Holiday' },
  { id: 'meal-prep', label: 'Meal Prep' },
];

const TIME_OPTIONS = [15, 30, 45, 60, 90];

export default function SessionSetupScreen() {
  const router = useRouter();
  const { session, updateSession } = useSession();
  const { ensureRegistered } = useAuth();
  const vlm = useVlm({ ensureRegistered });
  const [showAdvancedTime, setShowAdvancedTime] = useState(false);
  const [manualIngredient, setManualIngredient] = useState('');
  const [noIngredients, setNoIngredients] = useState(false);
  const scrollRef = useRef(null);
  const manualInputRef = useRef(null);
  const [isInputFocused, setIsInputFocused] = useState(false);

  // ── Drag-and-drop state ──────────────────────────────────────────────────
  const [draggingIngredient, setDraggingIngredient] = useState(null);
  const [isDraggingState, setIsDraggingState] = useState(false);
  const isDragging = useSharedValue(false);
  const dragX = useSharedValue(0);
  const dragY = useSharedValue(0);
  const perishableRef = useRef(null);
  const stableRef = useRef(null);
  const perishableBoundsRef = useRef(null);
  const stableBoundsRef = useRef(null);

  const dragOverlayStyle = useAnimatedStyle(() => ({
    opacity: isDragging.value ? 0.9 : 0,
    transform: [
      { translateX: dragX.value - 50 },
      { translateY: dragY.value - 20 },
    ],
  }));

  const startDrag = useCallback((ing, absX, absY) => {
    perishableRef.current?.measureInWindow((x, y, w, h) => {
      perishableBoundsRef.current = { x, y, w, h };
    });
    stableRef.current?.measureInWindow((x, y, w, h) => {
      stableBoundsRef.current = { x, y, w, h };
    });
    dragX.value = absX;
    dragY.value = absY;
    setDraggingIngredient(ing);
    setIsDraggingState(true);
  }, [dragX, dragY]);

  const endDrag = useCallback((ingName, absX, absY) => {
    const pb = perishableBoundsRef.current;
    const sb = stableBoundsRef.current;
    if (pb && absX >= pb.x && absX <= pb.x + pb.w && absY >= pb.y && absY <= pb.y + pb.h) {
      vlm.updateIngredientUrgency(ingName, PERISHABLE_URGENCY_DAYS);
    } else if (sb && absX >= sb.x && absX <= sb.x + sb.w && absY >= sb.y && absY <= sb.y + sb.h) {
      vlm.updateIngredientUrgency(ingName, null);
    }
    setDraggingIngredient(null);
    setIsDraggingState(false);
  }, [vlm]);

  /** Adds the current manual ingredient text input as a confirmed ingredient. */
  const handleAddManual = () => {
    const name = manualIngredient.trim();
    if (!name) return;
    vlm.addIngredient({
      name,
      confidence: 1.0,
      category: 'shelf-stable',
      urgency: null,
      estimated_quantity: 1,
      unit: 'pieces',
      source: 'manual',
      confirmed: true,
    });
    setManualIngredient('');
  };

  /** Opens the camera and auto-identifies ingredients from the captured photo. */
  const handleCameraPress = async () => {
    await vlm.pickFromCamera();
    if (vlm.images.length > 0) {
      await vlm.identifyFromImages();
    }
  };

  /** Opens the photo library; auto-identifies if new images are added and no ingredients exist yet. */
  const handleUploadPress = async () => {
    const prevCount = vlm.images.length;
    await vlm.pickFromLibrary();
    // Auto-identify if new images were added
    if (vlm.images.length > prevCount && vlm.ingredients.length === 0) {
      await vlm.identifyFromImages();
    }
  };

  /** Manually triggers VLM identification on the currently selected images. */
  const handleIdentify = async () => {
    await vlm.identifyFromImages();
  };

  /** Validates that ingredients exist, then navigates to the generating screen. */
  const handleStartDiscovery = () => {
    const confirmedIngredients = vlm.getConfirmedIngredients();
    if (confirmedIngredients.length === 0) {
      setNoIngredients(true);
      scrollRef.current?.scrollTo({ y: 0, animated: true });
      return;
    }
    setNoIngredients(false);
    updateSession({
      availableIngredients: confirmedIngredients,
      sessionReady: true,
    });
    router.replace('/session/generating');
  };

  return (
    <View style={{ flex: 1 }}>
    <SafeAreaView className="flex-1 bg-background">
      <View className="px-6 pt-4 pb-2 flex-row items-center">
        <Pressable onPress={() => router.back()} className="mr-4" accessibilityLabel="Go back">
          <Ionicons name="arrow-back" size={24} color="#1E293B" />
        </Pressable>
        <Text className="text-2xl font-bold text-text-primary">Find my meal</Text>
      </View>

      <ScrollView
        ref={scrollRef}
        className="flex-1 px-6"
        showsVerticalScrollIndicator={false}
        keyboardShouldPersistTaps="handled"
        scrollEnabled={!isInputFocused && !isDraggingState}
      >

        {/* Ingredients — required, moved to top */}
        <View className="py-4">
          <Text className="text-base font-semibold text-text-primary mb-1">Ingredients</Text>
          <Text className="text-sm text-text-secondary mb-3">
            Photo your ingredients and we'll identify them, or add them manually.
          </Text>

          {noIngredients ? (
            <Text className="text-sm text-red-500 mb-3">
              Add at least one ingredient to continue.
            </Text>
          ) : null}

          {/* Camera / Upload buttons */}
          <View className="flex-row gap-3 mb-3">
            <Pressable
              onPress={handleCameraPress}
              className="flex-1 border border-dashed border-border rounded-xl py-5 items-center active:bg-gray-50"
              accessibilityLabel="Take photo of ingredients"
            >
              <Ionicons name="camera-outline" size={28} color="#64748B" />
              <Text className="text-sm text-text-secondary mt-1">Camera</Text>
            </Pressable>
            <Pressable
              onPress={handleUploadPress}
              className="flex-1 border border-dashed border-border rounded-xl py-5 items-center active:bg-gray-50"
              accessibilityLabel="Upload photo of ingredients"
            >
              <Ionicons name="image-outline" size={28} color="#64748B" />
              <Text className="text-sm text-text-secondary mt-1">Upload</Text>
            </Pressable>
          </View>

          {/* Identify button shown when images are loaded but not yet identified */}
          {vlm.images.length > 0 && vlm.ingredients.length === 0 && !vlm.loading ? (
            <Pressable
              onPress={handleIdentify}
              className="bg-primary py-3 rounded-xl items-center mb-3"
            >
              <Text className="text-white text-sm font-semibold">
                Identify {vlm.images.length} Photo{vlm.images.length !== 1 ? 's' : ''}
              </Text>
            </Pressable>
          ) : null}

          {/* VLM loading state */}
          {vlm.loading ? (
            <View className="flex-row items-center gap-2 py-3">
              <ActivityIndicator size="small" color="#214130" />
              <Text className="text-sm text-text-secondary">Identifying ingredients…</Text>
            </View>
          ) : null}

          {/* VLM error */}
          {vlm.error ? (
            <Text className="text-sm text-red-500 mb-2">{vlm.error}</Text>
          ) : null}

          {/* Ingredient tags — Perishable / Non-perishable in separate boxes */}
          {vlm.ingredients.length > 0 ? (() => {
            const perishable = vlm.ingredients.filter(
              (i) => i.urgency != null && i.urgency <= PERISHABLE_URGENCY_DAYS
            );
            const stable = vlm.ingredients.filter(
              (i) => !(i.urgency != null && i.urgency <= PERISHABLE_URGENCY_DAYS)
            );
            return (
              <View className="mb-3 gap-2">
                <View ref={perishableRef} className="rounded-xl border border-border bg-surface p-3">
                  <Text className="text-xs font-semibold text-text-secondary uppercase tracking-wide mb-2">
                    Perishable — use soon
                  </Text>
                  {perishable.length > 0 ? (
                    <View className="flex-row flex-wrap">
                      {perishable.map((ing) => (
                        <DraggableIngredientTag
                          key={ing.name}
                          ingredient={ing}
                          onConfirm={() => { vlm.confirmIngredient(ing.name); setNoIngredients(false); }}
                          onRemove={() => vlm.removeIngredient(ing.name)}
                          dragX={dragX}
                          dragY={dragY}
                          isDragging={isDragging}
                          onDragStart={startDrag}
                          onDragEnd={endDrag}
                        />
                      ))}
                    </View>
                  ) : (
                    <Text className="text-xs text-text-muted italic">Hold &amp; drag an ingredient here to mark as perishable</Text>
                  )}
                </View>
                <View ref={stableRef} className="rounded-xl border border-border bg-surface p-3">
                  <Text className="text-xs font-semibold text-text-secondary uppercase tracking-wide mb-2">
                    Non-perishable
                  </Text>
                  {stable.length > 0 ? (
                    <View className="flex-row flex-wrap">
                      {stable.map((ing) => (
                        <DraggableIngredientTag
                          key={ing.name}
                          ingredient={ing}
                          onConfirm={() => { vlm.confirmIngredient(ing.name); setNoIngredients(false); }}
                          onRemove={() => vlm.removeIngredient(ing.name)}
                          dragX={dragX}
                          dragY={dragY}
                          isDragging={isDragging}
                          onDragStart={startDrag}
                          onDragEnd={endDrag}
                        />
                      ))}
                    </View>
                  ) : (
                    <Text className="text-xs text-text-muted italic">Hold &amp; drag an ingredient here to mark as non-perishable</Text>
                  )}
                </View>
              </View>
            );
          })() : null}

          {/* Manual add */}
          <View className="flex-row gap-2">
            <TextInput
              ref={manualInputRef}
              value={manualIngredient}
              onChangeText={(t) => { setManualIngredient(t); if (t) setNoIngredients(false); }}
              onSubmitEditing={handleAddManual}
              onFocus={() => setIsInputFocused(true)}
              onBlur={() => setIsInputFocused(false)}
              placeholder="Add ingredient manually…"
              placeholderTextColor="#94A3B8"
              className="flex-1 border border-border rounded-xl px-4 py-3 text-sm text-text-primary bg-surface"
              returnKeyType="done"
              accessibilityLabel="Enter ingredient name"
            />
            <Pressable
              onPress={handleAddManual}
              className="w-12 h-12 bg-primary rounded-xl items-center justify-center"
              accessibilityLabel="Add ingredient"
            >
              <Ionicons name="add" size={22} color="white" />
            </Pressable>
          </View>
        </View>

        {/* Meal Type */}
        <View className="py-4 border-t border-border">
          <Text className="text-base font-semibold text-text-primary mb-3">Meal Type</Text>
          <View className="flex-row flex-wrap">
            {MEAL_TYPES.map((meal) => (
              <Tag
                key={meal.id}
                label={meal.label}
                selected={session.mealType === meal.id}
                onPress={() => updateSession({ mealType: meal.id })}
              />
            ))}
          </View>
        </View>

        {/* Serving Count */}
        <View className="py-4 border-t border-border">
          <Stepper
            label="Servings"
            value={session.servingCount}
            onValueChange={(v) => updateSession({ servingCount: v })}
            min={SERVING_COUNT_MIN}
            max={SERVING_COUNT_MAX}
          />
        </View>

        {/* Total Cooking Time */}
        <View className="py-4 border-t border-border">
          <Text className="text-base font-semibold text-text-primary mb-3">
            Available Time: {session.availableTimeMinutes} min
          </Text>
          <View className="flex-row flex-wrap gap-2">
            {TIME_OPTIONS.map((time) => (
              <Pressable
                key={time}
                onPress={() => updateSession({ availableTimeMinutes: time })}
                className={'px-4 py-2 rounded-full border ' + (
                  session.availableTimeMinutes === time
                    ? 'bg-primary border-primary'
                    : 'border-border bg-surface'
                )}
              >
                <Text className={'text-sm font-medium ' + (
                  session.availableTimeMinutes === time ? 'text-white' : 'text-text-primary'
                )}>
                  {time}m
                </Text>
              </Pressable>
            ))}
          </View>

          <Pressable
            onPress={() => setShowAdvancedTime(!showAdvancedTime)}
            className="flex-row items-center mt-3 gap-1"
          >
            <Text className="text-sm text-primary font-medium">Advanced time breakdown</Text>
            <Ionicons
              name={showAdvancedTime ? 'chevron-up' : 'chevron-down'}
              size={16}
              color="#214130"
            />
          </Pressable>

          {showAdvancedTime ? (
            <View className="mt-3 gap-3">
              <View>
                <Text className="text-sm text-text-secondary mb-2">
                  Prep: {session.availablePrepTimeMinutes || 'Any'} min
                </Text>
                <View className="flex-row flex-wrap gap-2">
                  {[null, 10, 15, 20, 30].map((time) => (
                    <Pressable
                      key={String(time)}
                      onPress={() => updateSession({ availablePrepTimeMinutes: time })}
                      className={'px-3 py-1.5 rounded-full border ' + (
                        session.availablePrepTimeMinutes === time
                          ? 'bg-primary border-primary'
                          : 'border-border bg-surface'
                      )}
                    >
                      <Text className={'text-xs font-medium ' + (
                        session.availablePrepTimeMinutes === time ? 'text-white' : 'text-text-primary'
                      )}>
                        {time === null ? 'Any' : time + 'm'}
                      </Text>
                    </Pressable>
                  ))}
                </View>
              </View>
              <View>
                <Text className="text-sm text-text-secondary mb-2">
                  Cook: {session.availableCookTimeMinutes || 'Any'} min
                </Text>
                <View className="flex-row flex-wrap gap-2">
                  {[null, 15, 30, 45, 60].map((time) => (
                    <Pressable
                      key={String(time)}
                      onPress={() => updateSession({ availableCookTimeMinutes: time })}
                      className={'px-3 py-1.5 rounded-full border ' + (
                        session.availableCookTimeMinutes === time
                          ? 'bg-primary border-primary'
                          : 'border-border bg-surface'
                      )}
                    >
                      <Text className={'text-xs font-medium ' + (
                        session.availableCookTimeMinutes === time ? 'text-white' : 'text-text-primary'
                      )}>
                        {time === null ? 'Any' : time + 'm'}
                      </Text>
                    </Pressable>
                  ))}
                </View>
              </View>
            </View>
          ) : null}
        </View>

        {/* Occasion */}
        <View className="py-4 border-t border-border">
          <Text className="text-base font-semibold text-text-primary mb-3">Occasion (optional)</Text>
          <View className="flex-row flex-wrap">
            {OCCASIONS.map((occ) => (
              <Tag
                key={occ.id}
                label={occ.label}
                selected={session.occasion === occ.id}
                onPress={() => updateSession({ occasion: session.occasion === occ.id ? null : occ.id })}
              />
            ))}
          </View>
        </View>

        <View className="h-4" />
      </ScrollView>

      <View className="px-6 pb-6">
        <Button title="Find Recipes" onPress={handleStartDiscovery} />
      </View>
    </SafeAreaView>

    {/* Floating drag overlay — renders above everything, follows the dragged tag */}
    <Animated.View
      style={[{ position: 'absolute', left: 0, top: 0, zIndex: 100 }, dragOverlayStyle]}
      pointerEvents="none"
    >
      <View style={{ backgroundColor: '#214130', borderRadius: 20, paddingHorizontal: 12, paddingVertical: 6 }}>
        <Text style={{ color: 'white', fontSize: 14, fontWeight: '500' }}>
          {draggingIngredient?.name ?? ''}
        </Text>
      </View>
    </Animated.View>
    </View>
  );
}

function DraggableIngredientTag({ ingredient, onConfirm, onRemove, dragX, dragY, isDragging, onDragStart, onDragEnd }) {
  const isConfirmed = ingredient.confirmed;

  const hapticAndStart = useCallback((ing, absX, absY) => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    onDragStart(ing, absX, absY);
  }, [onDragStart]);

  const dragGesture = Gesture.Pan()
    .activateAfterLongPress(350)
    .onStart((e) => {
      isDragging.value = true;
      dragX.value = e.absoluteX;
      dragY.value = e.absoluteY;
      runOnJS(hapticAndStart)(ingredient, e.absoluteX, e.absoluteY);
    })
    .onUpdate((e) => {
      dragX.value = e.absoluteX;
      dragY.value = e.absoluteY;
    })
    .onEnd((e) => {
      isDragging.value = false;
      runOnJS(onDragEnd)(ingredient.name, e.absoluteX, e.absoluteY);
    })
    .onFinalize(() => {
      isDragging.value = false;
    });

  return (
    <GestureDetector gesture={dragGesture}>
      <Animated.View className={'flex-row items-center rounded-full px-3 py-1.5 mr-2 mb-2 border ' + (
        isConfirmed
          ? 'bg-green-50 border-green-300'
          : 'bg-gray-50 border-border'
      )}>
        <Pressable onPress={isConfirmed ? undefined : onConfirm} accessibilityLabel={'Confirm ' + ingredient.name}>
          <Text className={'text-sm font-medium ' + (
            isConfirmed ? 'text-green-700' : 'text-text-secondary'
          )}>
            {ingredient.name}
            {ingredient.source !== 'manual' && ingredient.estimated_quantity && ingredient.estimated_quantity > 0
              ? ' (' + ingredient.estimated_quantity + ' ' + ingredient.unit + ')'
              : ''}
          </Text>
        </Pressable>
        <Pressable onPress={onRemove} className="ml-1.5" accessibilityLabel={'Remove ' + ingredient.name}>
          <Ionicons name="close-circle" size={16} color="#94A3B8" />
        </Pressable>
      </Animated.View>
    </GestureDetector>
  );
}
