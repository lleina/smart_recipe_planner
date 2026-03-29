/**
 * Multi-step onboarding screen.
 * Captures: cuisines, dietary restrictions, health goal, time preference,
 * equipment, meal prep, perishable optimization.
 * Completable in under 1 minute (BR-ONB-07).
 */

import { useState, useCallback } from 'react';
import { View, Text, ScrollView, Pressable } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useRouter } from 'expo-router';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { useAuth } from '../../src/context/AuthContext';
import StepIndicator from '../../src/components/common/StepIndicator';
import Button from '../../src/components/common/Button';
import Tag from '../../src/components/common/Tag';
import {
  CUISINE_OPTIONS,
  DIETARY_RESTRICTIONS,
  HEALTH_GOALS,
  TIME_PREFERENCES,
  COOKING_EQUIPMENT,
} from '../../src/constants/dietaryOptions';

const TOTAL_STEPS = 4;

const DEFAULT_PREFERENCES = {
  cuisinePreferences: [],
  dietaryRestrictions: [],
  customAllergies: '',
  healthGoal: 'none',
  timePreference: 'moderate',
  mealPrep: false,
  cookingEquipment: [],
  perishableOptimizationPreference: true,
};

export default function OnboardingScreen() {
  const [step, setStep] = useState(0);
  const [preferences, setPreferences] = useState(DEFAULT_PREFERENCES);
  const [saving, setSaving] = useState(false);
  const router = useRouter();
  const { completeOnboarding, user } = useAuth();

  const toggleArrayItem = useCallback((key, itemId) => {
    setPreferences((prev) => {
      const list = prev[key];
      const updated = list.includes(itemId)
        ? list.filter((id) => id !== itemId)
        : [...list, itemId];
      return { ...prev, [key]: updated };
    });
  }, []);

  const setSingleValue = useCallback((key, value) => {
    setPreferences((prev) => ({ ...prev, [key]: value }));
  }, []);

  const handleNext = () => {
    if (step < TOTAL_STEPS - 1) setStep(step + 1);
  };

  const handleBack = () => {
    if (step > 0) setStep(step - 1);
  };

  const handleFinish = async () => {
    setSaving(true);
    try {
      // Save preferences locally — backend sync happens lazily when server is needed
      await AsyncStorage.setItem('@user_preferences', JSON.stringify(preferences));
      await completeOnboarding();
      router.replace('/(tabs)/discover');
    } catch {
      // Still complete onboarding so user is not blocked
      await completeOnboarding();
      router.replace('/(tabs)/discover');
    } finally {
      setSaving(false);
    }
  };

  const renderStep = () => {
    switch (step) {
      case 0:
        return <CuisineStep preferences={preferences} onToggle={toggleArrayItem} />;
      case 1:
        return <DietaryStep preferences={preferences} onToggle={toggleArrayItem} />;
      case 2:
        return (
          <GoalsStep
            preferences={preferences}
            onSetValue={setSingleValue}
          />
        );
      case 3:
        return (
          <EquipmentStep
            preferences={preferences}
            onToggle={toggleArrayItem}
            onSetValue={setSingleValue}
          />
        );
      default:
        return null;
    }
  };

  const isLastStep = step === TOTAL_STEPS - 1;

  return (
    <SafeAreaView className="flex-1 bg-background">
      <StepIndicator totalSteps={TOTAL_STEPS} currentStep={step} />

      <ScrollView className="flex-1 px-6" showsVerticalScrollIndicator={false}>
        {renderStep()}
      </ScrollView>

      <View className="px-6 pb-6 gap-3">
        <Button
          title={isLastStep ? 'Start Cooking' : 'Continue'}
          onPress={isLastStep ? handleFinish : handleNext}
          loading={saving}
        />
        {step > 0 && (
          <Button title="Back" variant="outline" onPress={handleBack} />
        )}
        {!isLastStep && (
          <Pressable onPress={handleFinish} className="items-center py-2">
            <Text className="text-text-muted text-sm">Skip for now</Text>
          </Pressable>
        )}
      </View>
    </SafeAreaView>
  );
}

function CuisineStep({ preferences, onToggle }) {
  return (
    <View className="py-4">
      <Text className="text-2xl font-bold text-text-primary mb-2">
        What cuisines do you love?
      </Text>
      <Text className="text-base text-text-secondary mb-6">
        Select all that apply. We will personalize your recipes.
      </Text>
      <View className="flex-row flex-wrap">
        {CUISINE_OPTIONS.map((cuisine) => (
          <Tag
            key={cuisine.id}
            label={cuisine.label}
            selected={preferences.cuisinePreferences.includes(cuisine.id)}
            onPress={() => onToggle('cuisinePreferences', cuisine.id)}
          />
        ))}
      </View>
    </View>
  );
}

function DietaryStep({ preferences, onToggle }) {
  return (
    <View className="py-4">
      <Text className="text-2xl font-bold text-text-primary mb-2">
        Any dietary restrictions?
      </Text>
      <Text className="text-base text-text-secondary mb-6">
        We will never suggest recipes that violate these.
      </Text>
      <View className="flex-row flex-wrap">
        {DIETARY_RESTRICTIONS.map((item) => (
          <Tag
            key={item.id}
            label={item.label}
            selected={preferences.dietaryRestrictions.includes(item.id)}
            onPress={() => onToggle('dietaryRestrictions', item.id)}
          />
        ))}
      </View>
    </View>
  );
}

function GoalsStep({ preferences, onSetValue }) {
  return (
    <View className="py-4">
      <Text className="text-2xl font-bold text-text-primary mb-2">
        Your cooking style
      </Text>
      <Text className="text-base text-text-secondary mb-6">
        Help us match recipes to your lifestyle.
      </Text>

      <Text className="text-base font-semibold text-text-primary mb-3">Health Goal</Text>
      <View className="flex-row flex-wrap mb-6">
        {HEALTH_GOALS.map((goal) => (
          <Tag
            key={goal.id}
            label={goal.label}
            selected={preferences.healthGoal === goal.id}
            onPress={() => onSetValue('healthGoal', goal.id)}
          />
        ))}
      </View>

      <Text className="text-base font-semibold text-text-primary mb-3">
        Preferred Cooking Time
      </Text>
      <View className="flex-row flex-wrap">
        {TIME_PREFERENCES.map((pref) => (
          <Tag
            key={pref.id}
            label={`${pref.label} (${pref.description})`}
            selected={preferences.timePreference === pref.id}
            onPress={() => onSetValue('timePreference', pref.id)}
          />
        ))}
      </View>
    </View>
  );
}

function EquipmentStep({ preferences, onToggle, onSetValue }) {
  return (
    <View className="py-4">
      <Text className="text-2xl font-bold text-text-primary mb-2">
        Your kitchen setup
      </Text>
      <Text className="text-base text-text-secondary mb-6">
        Optional. Helps us suggest recipes you can actually make.
      </Text>

      <Text className="text-base font-semibold text-text-primary mb-3">Equipment</Text>
      <View className="flex-row flex-wrap mb-6">
        {COOKING_EQUIPMENT.map((item) => (
          <Tag
            key={item.id}
            label={item.label}
            selected={preferences.cookingEquipment.includes(item.id)}
            onPress={() => onToggle('cookingEquipment', item.id)}
          />
        ))}
      </View>

      <Pressable
        onPress={() => onSetValue('mealPrep', !preferences.mealPrep)}
        className="flex-row items-center justify-between py-4 border-t border-border"
      >
        <Text className="text-base text-text-primary">I do meal prep / batch cooking</Text>
        <View
          className={`w-6 h-6 rounded border-2 items-center justify-center ${
            preferences.mealPrep ? 'bg-primary border-primary' : 'border-border'
          }`}
        >
          {preferences.mealPrep && <Text className="text-white text-xs font-bold">✓</Text>}
        </View>
      </Pressable>

      <Pressable
        onPress={() =>
          onSetValue('perishableOptimizationPreference', !preferences.perishableOptimizationPreference)
        }
        className="flex-row items-center justify-between py-4 border-t border-border"
      >
        <View className="flex-1 mr-4">
          <Text className="text-base text-text-primary">Prioritize expiring ingredients</Text>
          <Text className="text-sm text-text-muted">
            Suggest recipes using ingredients about to expire first
          </Text>
        </View>
        <View
          className={`w-6 h-6 rounded border-2 items-center justify-center ${
            preferences.perishableOptimizationPreference ? 'bg-primary border-primary' : 'border-border'
          }`}
        >
          {preferences.perishableOptimizationPreference && (
            <Text className="text-white text-xs font-bold">✓</Text>
          )}
        </View>
      </Pressable>
    </View>
  );
}
