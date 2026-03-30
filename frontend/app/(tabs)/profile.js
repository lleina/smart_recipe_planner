/**
 * User profile — shows user info and all editable preferences.
 * Each preference category opens a bottom-sheet modal for editing.
 */

import { useState, useCallback } from 'react';
import {
  View, Text, ScrollView, Pressable, Alert, ActivityIndicator, Modal,
  FlatList, TextInput,
} from 'react-native';
import { useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useAuth } from '../../src/context/AuthContext';
import { useSession } from '../../src/context/SessionContext';
import { useRecipeContext } from '../../src/context/RecipeContext';
import useUserPreferences from '../../src/hooks/useUserPreferences';
import { clearAllPersistedData } from '../../src/services/storageService';
import {
  CUISINE_OPTIONS,
  SPOONACULAR_DIETS,
  INTOLERANCES,
  HEALTH_GOALS,
  TIME_PREFERENCES,
  COOKING_EQUIPMENT,
} from '../../src/constants/dietaryOptions';

// --------------------------------------------------------------------------
// Helpers
// --------------------------------------------------------------------------

function summariseList(items, max = 3) {
  if (!items || items.length === 0) return 'None';
  const shown = items.slice(0, max).join(', ');
  return items.length > max ? `${shown} +${items.length - max} more` : shown;
}

function labelFor(id, options) {
  const found = options.find((o) => o.id === id);
  return found ? found.label : id;
}

// --------------------------------------------------------------------------
// Reusable preference row
// --------------------------------------------------------------------------

function PrefRow({ icon, label, summary, onPress, danger }) {
  return (
    <Pressable
      onPress={onPress}
      className="flex-row items-center py-4 border-b border-border active:bg-gray-50"
      accessibilityLabel={label}
    >
      <Ionicons name={icon} size={22} color={danger ? '#EF4444' : '#64748B'} />
      <View className="flex-1 ml-4">
        <Text className={`text-base ${danger ? 'text-danger' : 'text-text-primary'}`}>{label}</Text>
        {summary ? (
          <Text className="text-xs text-text-muted mt-0.5" numberOfLines={1}>{summary}</Text>
        ) : null}
      </View>
      <Ionicons name="chevron-forward" size={20} color="#94A3B8" />
    </Pressable>
  );
}

// --------------------------------------------------------------------------
// Generic multi-select modal
// --------------------------------------------------------------------------

function MultiSelectModal({ visible, title, options, selected, onToggle, onConfirm, onCancel, searchable }) {
  const [query, setQuery] = useState('');
  const filtered = searchable && query
    ? options.filter((o) => o.label.toLowerCase().includes(query.toLowerCase()))
    : options;

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onCancel}>
      <View className="flex-1 bg-black/40 justify-end">
        <View className="bg-background rounded-t-3xl" style={{ maxHeight: '80%' }}>
          <View className="flex-row items-center justify-between px-6 pt-5 pb-3 border-b border-border">
            <Text className="text-lg font-bold text-text-primary">{title}</Text>
            <Pressable onPress={onCancel} hitSlop={8}>
              <Ionicons name="close" size={24} color="#64748B" />
            </Pressable>
          </View>
          {searchable ? (
            <View className="px-6 py-3 border-b border-border">
              <TextInput
                value={query}
                onChangeText={setQuery}
                placeholder="Search..."
                placeholderTextColor="#94A3B8"
                className="bg-gray-100 rounded-xl px-4 py-2.5 text-sm text-text-primary"
              />
            </View>
          ) : null}
          <FlatList
            data={filtered}
            keyExtractor={(item) => item.id}
            renderItem={({ item }) => {
              const isSelected = selected.includes(item.id);
              return (
                <Pressable
                  onPress={() => onToggle(item.id)}
                  className="flex-row items-center px-6 py-3.5 border-b border-border/50 active:bg-gray-50"
                >
                  <View className={`w-5 h-5 rounded-md border-2 items-center justify-center mr-3 ${isSelected ? 'bg-primary border-primary' : 'border-border'}`}>
                    {isSelected ? <Ionicons name="checkmark" size={14} color="white" /> : null}
                  </View>
                  <Text className="flex-1 text-sm text-text-primary">{item.label}</Text>
                </Pressable>
              );
            }}
          />
          <View className="px-6 py-4 border-t border-border">
            <Pressable
              onPress={onConfirm}
              className="bg-primary py-3.5 rounded-xl items-center active:opacity-90"
            >
              <Text className="text-white font-semibold">
                Save {selected.length > 0 ? `(${selected.length})` : ''}
              </Text>
            </Pressable>
          </View>
        </View>
      </View>
    </Modal>
  );
}

// --------------------------------------------------------------------------
// Generic single-select modal
// --------------------------------------------------------------------------

function SingleSelectModal({ visible, title, options, selected, onSelect, onConfirm, onCancel, nullable, nullLabel }) {
  const allOptions = nullable ? [{ id: null, label: nullLabel || 'None' }, ...options] : options;
  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onCancel}>
      <View className="flex-1 bg-black/40 justify-end">
        <View className="bg-background rounded-t-3xl" style={{ maxHeight: '70%' }}>
          <View className="flex-row items-center justify-between px-6 pt-5 pb-3 border-b border-border">
            <Text className="text-lg font-bold text-text-primary">{title}</Text>
            <Pressable onPress={onCancel} hitSlop={8}>
              <Ionicons name="close" size={24} color="#64748B" />
            </Pressable>
          </View>
          <FlatList
            data={allOptions}
            keyExtractor={(item) => String(item.id)}
            renderItem={({ item }) => {
              const isSelected = selected === item.id;
              return (
                <Pressable
                  onPress={() => onSelect(item.id)}
                  className="flex-row items-center px-6 py-4 border-b border-border/50 active:bg-gray-50"
                >
                  <View className={`w-5 h-5 rounded-full border-2 items-center justify-center mr-3 ${isSelected ? 'border-primary' : 'border-border'}`}>
                    {isSelected ? <View className="w-2.5 h-2.5 rounded-full bg-primary" /> : null}
                  </View>
                  <Text className="flex-1 text-sm text-text-primary">{item.label}</Text>
                </Pressable>
              );
            }}
          />
          <View className="px-6 py-4 border-t border-border">
            <Pressable
              onPress={onConfirm}
              className="bg-primary py-3.5 rounded-xl items-center active:opacity-90"
            >
              <Text className="text-white font-semibold">Save</Text>
            </Pressable>
          </View>
        </View>
      </View>
    </Modal>
  );
}

// --------------------------------------------------------------------------
// Main screen
// --------------------------------------------------------------------------

export default function ProfileScreen() {
  const { user, logout } = useAuth();
  const { resetSession } = useSession();
  const { resetRecipes } = useRecipeContext();
  const { preferences, loading: prefsLoading, savePreferences } = useUserPreferences();
  const router = useRouter();

  const [saving, setSaving] = useState(false);
  const [activeModal, setActiveModal] = useState(null);
  const [draft, setDraft] = useState(null);
  const [showDevMode, setShowDevMode] = useState(false);
  const [clearing, setClearing] = useState(false);

  // Open a modal with the current value as the draft
  const openModal = useCallback((key, currentValue) => {
    setDraft(currentValue);
    setActiveModal(key);
  }, []);

  const closeModal = useCallback(() => {
    setActiveModal(null);
    setDraft(null);
  }, []);

  const confirmSave = useCallback(async (key, value) => {
    setSaving(true);
    try {
      await savePreferences({ [key]: value });
    } catch {
      Alert.alert('Error', 'Failed to save preferences. Please try again.');
    } finally {
      setSaving(false);
    }
    closeModal();
  }, [savePreferences, closeModal]);

  const toggleInDraft = useCallback((id) => {
    setDraft((prev) => {
      const arr = Array.isArray(prev) ? prev : [];
      return arr.includes(id) ? arr.filter((x) => x !== id) : [...arr, id];
    });
  }, []);

  // Preference display summaries
  const cuisineSummary = summariseList(
    (preferences.cuisinePreferences || []).map((id) => labelFor(id, CUISINE_OPTIONS))
  );
  const dietSummary = preferences.diet
    ? labelFor(preferences.diet, SPOONACULAR_DIETS)
    : 'None';
  const intoleranceSummary = summariseList(
    (preferences.intolerances || []).map((id) => labelFor(id, INTOLERANCES))
  );
  const healthSummary = labelFor(preferences.healthGoal || 'none', HEALTH_GOALS);
  const timeSummary = labelFor(preferences.timePreference || 'moderate', TIME_PREFERENCES);
  const equipmentCount = (preferences.cookingEquipment || []).length;
  const equipmentSummary = equipmentCount === 0 ? 'None selected' : `${equipmentCount} item${equipmentCount !== 1 ? 's' : ''} selected`;

  if (prefsLoading) {
    return (
      <SafeAreaView className="flex-1 bg-background">
        <View className="px-6 pt-4 pb-2">
          <Text className="text-2xl font-bold text-text-primary">Profile</Text>
        </View>
        <View className="flex-1 items-center justify-center">
          <ActivityIndicator color="#2563EB" />
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView className="flex-1 bg-background">
      <View className="px-6 pt-4 pb-2">
        <Text className="text-2xl font-bold text-text-primary">Profile</Text>
      </View>

      <ScrollView className="flex-1 px-6" showsVerticalScrollIndicator={false}>

        {/* Avatar */}
        <View className="py-6 items-center border-b border-border mb-4">
          <View className="w-16 h-16 rounded-full bg-primary items-center justify-center mb-3">
            <Text className="text-white text-2xl font-bold">
              {user?.id?.charAt(5)?.toUpperCase() || 'U'}
            </Text>
          </View>
          <Text className="text-base text-text-secondary">{user?.id || 'User'}</Text>
        </View>

        {/* Preferences section */}
        <Text className="text-xs font-semibold text-text-muted uppercase tracking-wide mb-1">
          Preferences
        </Text>

        <PrefRow
          icon="heart-outline"
          label="Cuisine Preferences"
          summary={cuisineSummary}
          onPress={() => openModal('cuisinePreferences', preferences.cuisinePreferences || [])}
        />
        <PrefRow
          icon="leaf-outline"
          label="Diet"
          summary={dietSummary}
          onPress={() => openModal('diet', preferences.diet || null)}
        />
        <PrefRow
          icon="alert-circle-outline"
          label="Intolerances"
          summary={intoleranceSummary}
          onPress={() => openModal('intolerances', preferences.intolerances || [])}
        />
        <PrefRow
          icon="fitness-outline"
          label="Health Goal"
          summary={healthSummary}
          onPress={() => openModal('healthGoal', preferences.healthGoal || 'none')}
        />
        <PrefRow
          icon="timer-outline"
          label="Cooking Time"
          summary={timeSummary}
          onPress={() => openModal('timePreference', preferences.timePreference || 'moderate')}
        />
        <PrefRow
          icon="hardware-chip-outline"
          label="Kitchen Equipment"
          summary={equipmentSummary}
          onPress={() => openModal('cookingEquipment', preferences.cookingEquipment || [])}
        />

        {/* Account section */}
        <Text className="text-xs font-semibold text-text-muted uppercase tracking-wide mt-6 mb-1">
          Account
        </Text>

        <Pressable
          onPress={logout}
          className="flex-row items-center py-4 border-b border-border active:bg-gray-50"
        >
          <Ionicons name="log-out-outline" size={22} color="#EF4444" />
          <Text className="ml-4 text-base text-danger">Log Out</Text>
        </Pressable>

        {/* Dev Mode */}
        <View className="mt-8 pt-4 border-t border-border">
          <Pressable
            onPress={() => setShowDevMode(!showDevMode)}
            className="flex-row items-center pb-3"
          >
            <Text className="text-xs font-semibold text-text-muted uppercase tracking-wide">
              Developer Mode
            </Text>
            <Ionicons
              name={showDevMode ? 'chevron-up' : 'chevron-down'}
              size={16}
              color="#94A3B8"
              style={{ marginLeft: 8 }}
            />
          </Pressable>

          {showDevMode && (
            <View className="bg-gray-50 border border-gray-200 rounded-xl p-4">
              <Text className="text-sm text-text-secondary mb-3">
                Clears ALL app data including auth, preferences, and cache.
              </Text>
              <Pressable
                onPress={() => {
                  Alert.alert(
                    'Clear All Data?',
                    'This will log you out and erase all settings. You\'ll need to re-onboard.',
                    [
                      { text: 'Cancel', style: 'cancel' },
                      {
                        text: 'Clear All',
                        style: 'destructive',
                        onPress: async () => {
                          setClearing(true);
                          try {
                            await clearAllPersistedData();
                            resetRecipes();
                            resetSession();
                            await logout();
                            router.replace('/(auth)/welcome');
                          } catch (error) {
                            setClearing(false);
                            Alert.alert('Error', 'Failed to clear data: ' + error.message);
                          }
                        },
                      },
                    ]
                  );
                }}
                disabled={clearing}
                className={`py-3 rounded-xl items-center ${clearing ? 'bg-red-400' : 'bg-red-600'}`}
              >
                {clearing ? (
                  <ActivityIndicator color="#fff" size="small" />
                ) : (
                  <Text className="text-white text-sm font-semibold">Clear All App Data</Text>
                )}
              </Pressable>
            </View>
          )}
        </View>

        <View className="h-8" />
      </ScrollView>

      {/* Cuisine multi-select */}
      <MultiSelectModal
        visible={activeModal === 'cuisinePreferences'}
        title="Cuisine Preferences"
        options={CUISINE_OPTIONS}
        selected={Array.isArray(draft) ? draft : []}
        onToggle={toggleInDraft}
        onConfirm={() => confirmSave('cuisinePreferences', draft || [])}
        onCancel={closeModal}
        searchable={false}
      />

      {/* Diet single-select */}
      <SingleSelectModal
        visible={activeModal === 'diet'}
        title="Diet"
        options={SPOONACULAR_DIETS}
        selected={draft}
        onSelect={(id) => setDraft(id)}
        onConfirm={() => confirmSave('diet', draft)}
        onCancel={closeModal}
        nullable
        nullLabel="No specific diet"
      />

      {/* Intolerances multi-select */}
      <MultiSelectModal
        visible={activeModal === 'intolerances'}
        title="Intolerances"
        options={INTOLERANCES}
        selected={Array.isArray(draft) ? draft : []}
        onToggle={toggleInDraft}
        onConfirm={() => confirmSave('intolerances', draft || [])}
        onCancel={closeModal}
        searchable={false}
      />

      {/* Health goal single-select */}
      <SingleSelectModal
        visible={activeModal === 'healthGoal'}
        title="Health Goal"
        options={HEALTH_GOALS}
        selected={draft}
        onSelect={(id) => setDraft(id)}
        onConfirm={() => confirmSave('healthGoal', draft || 'none')}
        onCancel={closeModal}
        nullable={false}
      />

      {/* Time preference single-select */}
      <SingleSelectModal
        visible={activeModal === 'timePreference'}
        title="Cooking Time Preference"
        options={TIME_PREFERENCES}
        selected={draft}
        onSelect={(id) => setDraft(id)}
        onConfirm={() => confirmSave('timePreference', draft || 'moderate')}
        onCancel={closeModal}
        nullable={false}
      />

      {/* Equipment multi-select */}
      <MultiSelectModal
        visible={activeModal === 'cookingEquipment'}
        title="Kitchen Equipment"
        options={COOKING_EQUIPMENT}
        selected={Array.isArray(draft) ? draft : []}
        onToggle={toggleInDraft}
        onConfirm={() => confirmSave('cookingEquipment', draft || [])}
        onCancel={closeModal}
        searchable={true}
      />

      {/* Saving overlay */}
      {saving ? (
        <View className="absolute inset-0 bg-black/20 items-center justify-center">
          <View className="bg-background rounded-2xl px-6 py-4 flex-row items-center gap-3">
            <ActivityIndicator color="#2563EB" />
            <Text className="text-sm font-medium text-text-primary">Saving...</Text>
          </View>
        </View>
      ) : null}
    </SafeAreaView>
  );
}
