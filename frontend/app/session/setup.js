/**
 * Pre-cooking session setup screen.
 * Gathers: meal type, serving count, time, occasion, ingredients (via VLM or manual).
 * Completable in under 30 seconds (BR-CTX-06).
 */

import { useState } from 'react';
import { View, Text, ScrollView, Pressable, TextInput, ActivityIndicator } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useRouter } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
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
      confirmed: true,
    });
    setManualIngredient('');
  };

  const handleCameraPress = async () => {
    await vlm.pickFromCamera();
    if (vlm.images.length > 0) {
      await vlm.identifyFromImages();
    }
  };

  const handleUploadPress = async () => {
    const prevCount = vlm.images.length;
    await vlm.pickFromLibrary();
    // Auto-identify if new images were added
    if (vlm.images.length > prevCount && vlm.ingredients.length === 0) {
      await vlm.identifyFromImages();
    }
  };

  const handleIdentify = async () => {
    await vlm.identifyFromImages();
  };

  const handleStartDiscovery = () => {
    const confirmedIngredients = vlm.getConfirmedIngredients();
    updateSession({
      availableIngredients: confirmedIngredients,
      sessionReady: true,
    });
    router.replace('/session/generating');
  };

  return (
    <SafeAreaView className="flex-1 bg-background">
      <View className="px-6 pt-4 pb-2 flex-row items-center">
        <Pressable onPress={() => router.back()} className="mr-4" accessibilityLabel="Go back">
          <Ionicons name="arrow-back" size={24} color="#1E293B" />
        </Pressable>
        <Text className="text-2xl font-bold text-text-primary">New Session</Text>
      </View>

      <ScrollView className="flex-1 px-6" showsVerticalScrollIndicator={false}>

        {/* Meal Type */}
        <View className="py-4">
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
              color="#2563EB"
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

        {/* Ingredients via VLM */}
        <View className="py-4 border-t border-border">
          <Text className="text-base font-semibold text-text-primary mb-1">Ingredients (optional)</Text>
          <Text className="text-sm text-text-secondary mb-3">
            Photo your ingredients and we'll identify them, or add them manually.
          </Text>

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
              <ActivityIndicator size="small" color="#2563EB" />
              <Text className="text-sm text-text-secondary">Identifying ingredients...</Text>
            </View>
          ) : null}

          {/* VLM error */}
          {vlm.error ? (
            <Text className="text-sm text-red-500 mb-2">{vlm.error}</Text>
          ) : null}

          {/* Ingredient tags */}
          {vlm.ingredients.length > 0 ? (
            <View className="mb-3">
              <Text className="text-sm font-medium text-text-secondary mb-2">
                Tap to confirm or remove:
              </Text>
              <View className="flex-row flex-wrap">
                {vlm.ingredients.map((ing) => (
                  <IngredientTag
                    key={ing.name}
                    ingredient={ing}
                    onConfirm={() => vlm.confirmIngredient(ing.name)}
                    onRemove={() => vlm.removeIngredient(ing.name)}
                  />
                ))}
              </View>
            </View>
          ) : null}

          {/* Manual add */}
          <View className="flex-row gap-2">
            <TextInput
              value={manualIngredient}
              onChangeText={setManualIngredient}
              onSubmitEditing={handleAddManual}
              placeholder="Add ingredient manually..."
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

        <View className="h-4" />
      </ScrollView>

      <View className="px-6 pb-6">
        <Button title="Find Recipes" onPress={handleStartDiscovery} />
      </View>
    </SafeAreaView>
  );
}

function IngredientTag({ ingredient, onConfirm, onRemove }) {
  const isUrgent = ingredient.urgency != null && ingredient.urgency <= PERISHABLE_URGENCY_DAYS;
  const isConfirmed = ingredient.confirmed;

  return (
    <View className={'flex-row items-center rounded-full px-3 py-1.5 mr-2 mb-2 border ' + (
      isUrgent
        ? 'bg-orange-50 border-orange-300'
        : isConfirmed
          ? 'bg-green-50 border-green-300'
          : 'bg-gray-50 border-border'
    )}>
      {isUrgent ? (
        <Ionicons name="alert-circle-outline" size={14} color="#C2410C" style={{ marginRight: 4 }} />
      ) : null}
      <Pressable onPress={isConfirmed ? undefined : onConfirm} accessibilityLabel={'Confirm ' + ingredient.name}>
        <Text className={'text-sm font-medium ' + (
          isUrgent ? 'text-orange-700' : isConfirmed ? 'text-green-700' : 'text-text-secondary'
        )}>
          {ingredient.name}
          {ingredient.estimated_quantity && ingredient.estimated_quantity > 0
            ? ' (' + ingredient.estimated_quantity + ' ' + ingredient.unit + ')'
            : ''}
        </Text>
      </Pressable>
      <Pressable onPress={onRemove} className="ml-1.5" accessibilityLabel={'Remove ' + ingredient.name}>
        <Ionicons name="close-circle" size={16} color={isUrgent ? '#C2410C' : '#94A3B8'} />
      </Pressable>
    </View>
  );
}
