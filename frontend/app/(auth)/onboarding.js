/**
 * Multi-step onboarding screen.
 * Captures: cuisines, diet, intolerances, health goal, time preference,
 * equipment, meal prep, perishable optimization.
 * Completable in under 1 minute (BR-ONB-07).
 *
 * Design:
 *   - Full-width progress track (StepIndicator) + step name at the top.
 *   - Fixed title/subtitle header below the track — always visible.
 *   - Scrollable list of full-width OptionRow cards for every choice.
 *   - Single Continue/Start button pinned to the bottom.
 *
 * Equipment step intentionally shows only ~10 appliances to avoid
 * decision fatigue. Users can add more from profile settings later.
 */

import { useState, useCallback } from 'react';
import { View, Text, ScrollView, Pressable } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useRouter } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { useAuth } from '../../src/context/AuthContext';
import { updatePreferences } from '../../src/services/userService';
import StepIndicator from '../../src/components/common/StepIndicator';
import Button from '../../src/components/common/Button';
import {
  CUISINE_OPTIONS,
  SPOONACULAR_DIETS,
  INTOLERANCES,
  HEALTH_GOALS,
  TIME_PREFERENCES,
} from '../../src/constants/dietaryOptions';

// ---------------------------------------------------------------------------
// Step metadata
// ---------------------------------------------------------------------------

const TOTAL_STEPS = 4;

const STEP_LABELS = ['Cuisines', 'Dietary', 'Style', 'Kitchen'];

const STEP_TITLES = [
  'What cuisines do you love?',
  'Any dietary preferences?',
  'Your cooking style',
  'Your kitchen setup',
];

const STEP_SUBTITLES = [
  'Pick your favorites — we personalize every suggestion around you.',
  "We'll make sure every suggestion fits your needs.",
  'Help us match recipes to your lifestyle.',
  "We'll only suggest recipes you can actually make.",
];

// ---------------------------------------------------------------------------
// Icon + colour metadata for each selectable option
// ---------------------------------------------------------------------------

/** Accent icon and colour for each cuisine. */
const CUISINE_META = {
  italian:          { icon: 'pizza-outline',              color: '#EF4444' },
  mexican:          { icon: 'flame-outline',              color: '#F97316' },
  chinese:          { icon: 'restaurant-outline',         color: '#EAB308' },
  japanese:         { icon: 'fish-outline',               color: '#3B82F6' },
  indian:           { icon: 'leaf-outline',               color: '#F59E0B' },
  thai:             { icon: 'sunny-outline',              color: '#10B981' },
  mediterranean:    { icon: 'boat-outline',               color: '#06B6D4' },
  korean:           { icon: 'star-outline',               color: '#8B5CF6' },
  american:         { icon: 'home-outline',               color: '#3B82F6' },
  french:           { icon: 'heart-outline',              color: '#EC4899' },
  'middle eastern': { icon: 'moon-outline',               color: '#F59E0B' },
  vietnamese:       { icon: 'leaf-outline',               color: '#10B981' },
  greek:            { icon: 'water-outline',              color: '#06B6D4' },
  caribbean:        { icon: 'sunny-outline',              color: '#F97316' },
  african:          { icon: 'earth-outline',              color: '#EF4444' },
};

/** Accent icon and colour for each diet type. */
const DIET_META = {
  'gluten free':      { icon: 'close-circle-outline',      color: '#F59E0B' },
  ketogenic:          { icon: 'flame-outline',              color: '#EF4444' },
  'lacto-vegetarian': { icon: 'leaf-outline',               color: '#10B981' },
  'low fodmap':       { icon: 'medkit-outline',             color: '#3B82F6' },
  'ovo-vegetarian':   { icon: 'ellipse-outline',            color: '#F59E0B' },
  paleo:              { icon: 'barbell-outline',            color: '#F97316' },
  pescetarian:        { icon: 'fish-outline',               color: '#06B6D4' },
  primal:             { icon: 'leaf-outline',               color: '#78716C' },
  vegan:              { icon: 'leaf-outline',               color: '#10B981' },
  vegetarian:         { icon: 'leaf-outline',               color: '#22C55E' },
  whole30:            { icon: 'checkmark-circle-outline',   color: '#8B5CF6' },
};

/** Accent icon and colour for each intolerance. */
const INTOLERANCE_META = {
  dairy:       { icon: 'water-outline',     color: '#3B82F6' },
  egg:         { icon: 'ellipse-outline',   color: '#F59E0B' },
  gluten:      { icon: 'restaurant-outline',color: '#F59E0B' },
  grain:       { icon: 'restaurant-outline',color: '#F97316' },
  peanut:      { icon: 'ellipse-outline',   color: '#F97316' },
  seafood:     { icon: 'fish-outline',      color: '#06B6D4' },
  sesame:      { icon: 'ellipse-outline',   color: '#EAB308' },
  shellfish:   { icon: 'fish-outline',      color: '#0EA5E9' },
  soy:         { icon: 'leaf-outline',      color: '#10B981' },
  sulfite:     { icon: 'wine-outline',      color: '#8B5CF6' },
  'tree nut':  { icon: 'leaf-outline',      color: '#F97316' },
  wheat:       { icon: 'restaurant-outline',color: '#F59E0B' },
};

/** Accent icon and colour for each health goal. */
const HEALTH_GOAL_META = {
  'weight-loss': { icon: 'arrow-down-circle-outline', color: '#10B981' },
  'muscle-gain': { icon: 'barbell-outline',           color: '#3B82F6' },
  maintenance:   { icon: 'person-outline',            color: '#64748B' },
  none:          { icon: 'happy-outline',             color: '#F59E0B' },
};

/** Accent icon, colour, and sublabel for each time preference. */
const TIME_PREF_META = {
  quick:    { icon: 'flash-outline',  color: '#F97316', sublabel: 'Under 20 minutes' },
  moderate: { icon: 'time-outline',   color: '#3B82F6', sublabel: '20–45 minutes'    },
  extended: { icon: 'timer-outline',  color: '#8B5CF6', sublabel: '45+ minutes'      },
};

/** Curated appliances + their icons — covers 90% of everyday recipes. */
const ONBOARDING_EQUIPMENT = [
  { id: 'stove',        label: 'Stove',        icon: 'flame-outline',      color: '#EF4444' },
  { id: 'oven',         label: 'Oven',         icon: 'cube-outline',        color: '#F97316' },
  { id: 'microwave',    label: 'Microwave',    icon: 'cube-outline',        color: '#64748B' },
  { id: 'frying pan',   label: 'Frying Pan',   icon: 'restaurant-outline', color: '#EF4444' },
  { id: 'pot',          label: 'Pot',          icon: 'restaurant-outline', color: '#3B82F6' },
  { id: 'blender',      label: 'Blender',      icon: 'options-outline',    color: '#8B5CF6' },
  { id: 'airfryer',     label: 'Air Fryer',    icon: 'sunny-outline',      color: '#F97316' },
  { id: 'instant pot',  label: 'Instant Pot',  icon: 'timer-outline',      color: '#3B82F6' },
  { id: 'slow cooker',  label: 'Slow Cooker',  icon: 'time-outline',       color: '#F59E0B' },
  { id: 'grill',        label: 'Grill',        icon: 'flame-outline',      color: '#DC2626' },
];

// ---------------------------------------------------------------------------
// Default preference state
// ---------------------------------------------------------------------------

const DEFAULT_PREFERENCES = {
  cuisinePreferences: [],
  dietaryRestrictions: [],
  diet: null,
  intolerances: [],
  customAllergies: '',
  healthGoal: 'none',
  timePreference: 'moderate',
  mealPrep: false,
  cookingEquipment: [],
  perishableOptimizationPreference: true,
};

// ---------------------------------------------------------------------------
// Main screen
// ---------------------------------------------------------------------------

export default function OnboardingScreen() {
  const [step, setStep] = useState(0);
  const [preferences, setPreferences] = useState(DEFAULT_PREFERENCES);
  const [saving, setSaving] = useState(false);
  const router = useRouter();
  const { completeOnboarding, ensureRegistered } = useAuth();

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
      await AsyncStorage.setItem('@user_preferences', JSON.stringify(preferences));
      await ensureRegistered();
      await updatePreferences(preferences);
      await completeOnboarding();
      router.replace('/(tabs)/discover');
    } catch {
      // Sync failed — still complete onboarding so the user isn't blocked
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
        return (
          <DietaryStep
            preferences={preferences}
            onToggle={toggleArrayItem}
            onSetValue={setSingleValue}
          />
        );
      case 2:
        return <GoalsStep preferences={preferences} onSetValue={setSingleValue} />;
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
      {/* Full-width progress track with step number + label */}
      <StepIndicator
        totalSteps={TOTAL_STEPS}
        currentStep={step}
        label={STEP_LABELS[step]}
      />

      {/* Fixed header — always visible above the scrollable list */}
      <View className="px-6 pb-4">
        <Text className="text-2xl font-bold text-text-primary">{STEP_TITLES[step]}</Text>
        <Text className="text-base text-text-secondary mt-1">{STEP_SUBTITLES[step]}</Text>
      </View>

      {/* Scrollable option list */}
      <ScrollView
        className="flex-1 px-6"
        showsVerticalScrollIndicator={false}
        contentContainerStyle={{ paddingBottom: 16 }}
      >
        {renderStep()}
      </ScrollView>

      {/* Pinned action buttons */}
      <View className="px-6 pb-6 gap-3 border-t border-border pt-4 bg-background">
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

// ---------------------------------------------------------------------------
// Step components
// ---------------------------------------------------------------------------

function CuisineStep({ preferences, onToggle }) {
  return (
    <View>
      {CUISINE_OPTIONS.map((cuisine) => {
        const meta = CUISINE_META[cuisine.id] || { icon: 'restaurant-outline', color: '#64748B' };
        return (
          <OptionRow
            key={cuisine.id}
            label={cuisine.label}
            iconName={meta.icon}
            iconColor={meta.color}
            selected={preferences.cuisinePreferences.includes(cuisine.id)}
            onPress={() => onToggle('cuisinePreferences', cuisine.id)}
          />
        );
      })}
    </View>
  );
}

function DietaryStep({ preferences, onToggle, onSetValue }) {
  return (
    <View>
      {/* ── Diet type (single-select) ── */}
      <SectionHeader title="Diet type" />
      {SPOONACULAR_DIETS.map((diet) => {
        const meta = DIET_META[diet.id] || { icon: 'leaf-outline', color: '#64748B' };
        return (
          <OptionRow
            key={diet.id}
            label={diet.label}
            iconName={meta.icon}
            iconColor={meta.color}
            selected={preferences.diet === diet.id}
            onPress={() => onSetValue('diet', preferences.diet === diet.id ? null : diet.id)}
            isRadio
          />
        );
      })}

      {/* ── Intolerances / Allergies (multi-select) ── */}
      <SectionHeader title="Intolerances & Allergies" />
      {INTOLERANCES.map((item) => {
        const meta = INTOLERANCE_META[item.id] || { icon: 'alert-circle-outline', color: '#F59E0B' };
        return (
          <OptionRow
            key={item.id}
            label={item.label}
            iconName={meta.icon}
            iconColor={meta.color}
            selected={preferences.intolerances.includes(item.id)}
            onPress={() => onToggle('intolerances', item.id)}
          />
        );
      })}
    </View>
  );
}

function GoalsStep({ preferences, onSetValue }) {
  return (
    <View>
      {/* ── Health goal (single-select) ── */}
      <SectionHeader title="Health goal" />
      {HEALTH_GOALS.map((goal) => {
        const meta = HEALTH_GOAL_META[goal.id] || { icon: 'heart-outline', color: '#64748B' };
        return (
          <OptionRow
            key={goal.id}
            label={goal.label}
            iconName={meta.icon}
            iconColor={meta.color}
            selected={preferences.healthGoal === goal.id}
            onPress={() => onSetValue('healthGoal', goal.id)}
            isRadio
          />
        );
      })}

      {/* ── Preferred cooking time (single-select) ── */}
      <SectionHeader title="Preferred cooking time" />
      {TIME_PREFERENCES.map((pref) => {
        const meta = TIME_PREF_META[pref.id] || { icon: 'time-outline', color: '#64748B', sublabel: '' };
        return (
          <OptionRow
            key={pref.id}
            label={pref.label}
            sublabel={meta.sublabel}
            iconName={meta.icon}
            iconColor={meta.color}
            selected={preferences.timePreference === pref.id}
            onPress={() => onSetValue('timePreference', pref.id)}
            isRadio
          />
        );
      })}
    </View>
  );
}

/**
 * Equipment step — tap-to-select appliances + two preference toggles.
 * @param {object}   props
 * @param {object}   props.preferences
 * @param {function} props.onToggle
 * @param {function} props.onSetValue
 */
function EquipmentStep({ preferences, onToggle, onSetValue }) {
  return (
    <View>
      <Text className="text-xs text-text-muted mb-4">
        You can add more equipment anytime from your profile.
      </Text>

      {/* ── Appliances (multi-select) ── */}
      {ONBOARDING_EQUIPMENT.map((item) => (
        <OptionRow
          key={item.id}
          label={item.label}
          iconName={item.icon}
          iconColor={item.color}
          selected={preferences.cookingEquipment.includes(item.id)}
          onPress={() => onToggle('cookingEquipment', item.id)}
        />
      ))}

      {/* ── Cooking habits (boolean toggles styled as option rows) ── */}
      <SectionHeader title="Cooking habits" />

      <OptionRow
        label="Meal prep / batch cooking"
        sublabel="I cook in bulk for the week"
        iconName="layers-outline"
        iconColor="#3B82F6"
        selected={preferences.mealPrep}
        onPress={() => onSetValue('mealPrep', !preferences.mealPrep)}
      />

      <OptionRow
        label="Prioritize expiring ingredients"
        sublabel="Show recipes that use what's about to expire first"
        iconName="calendar-outline"
        iconColor="#F59E0B"
        selected={preferences.perishableOptimizationPreference}
        onPress={() =>
          onSetValue(
            'perishableOptimizationPreference',
            !preferences.perishableOptimizationPreference,
          )
        }
      />
    </View>
  );
}

// ---------------------------------------------------------------------------
// Shared UI sub-components
// ---------------------------------------------------------------------------

/**
 * Full-width selectable option card.
 * Multi-select shows a square checkbox; single-select shows a radio circle.
 *
 * @param {object}   props
 * @param {string}   props.label      - Primary label text.
 * @param {string}   [props.sublabel] - Optional secondary description.
 * @param {string}   props.iconName   - Ionicons icon name.
 * @param {string}   props.iconColor  - Hex accent colour for icon + tinted bg.
 * @param {boolean}  props.selected   - Whether this option is currently chosen.
 * @param {function} props.onPress    - Called when the row is tapped.
 * @param {boolean}  [props.isRadio]  - True for single-select (radio) behaviour.
 */
function OptionRow({ label, sublabel, iconName, iconColor, selected, onPress, isRadio = false }) {
  return (
    <Pressable
      onPress={onPress}
      className={
        'flex-row items-center p-4 rounded-2xl mb-3 border active:opacity-80 ' +
        (selected ? 'bg-blue-50 border-primary' : 'bg-surface border-border')
      }
      accessibilityRole={isRadio ? 'radio' : 'checkbox'}
      accessibilityState={{ checked: selected }}
    >
      {/* Tinted icon circle */}
      <View
        className="w-11 h-11 rounded-full items-center justify-center mr-4 flex-shrink-0"
        style={{ backgroundColor: iconColor + '22' }}
      >
        <Ionicons name={iconName} size={20} color={iconColor} />
      </View>

      {/* Label + optional sublabel */}
      <View className="flex-1 mr-3">
        <Text className={'text-base font-medium ' + (selected ? 'text-primary' : 'text-text-primary')}>
          {label}
        </Text>
        {sublabel ? (
          <Text className="text-sm text-text-muted mt-0.5">{sublabel}</Text>
        ) : null}
      </View>

      {/* Selection indicator: radio dot or square checkbox */}
      <View
        className={
          'w-5 h-5 items-center justify-center border-2 flex-shrink-0 ' +
          (isRadio ? 'rounded-full ' : 'rounded ') +
          (selected ? 'bg-primary border-primary' : 'border-slate-300')
        }
      >
        {selected && (
          isRadio
            ? <View className="w-2 h-2 rounded-full bg-white" />
            : <Ionicons name="checkmark" size={12} color="white" />
        )}
      </View>
    </Pressable>
  );
}

/**
 * Subtle uppercase section header between groups of option rows.
 * @param {object} props
 * @param {string} props.title - Header text.
 */
function SectionHeader({ title }) {
  return (
    <Text className="text-xs font-semibold text-text-muted uppercase tracking-widest mb-3 mt-2">
      {title}
    </Text>
  );
}
