/**
 * Cooking history screen.
 * Shows previously cooked recipes in reverse chronological order.
 * Per BR-HST-01 through BR-HST-05.
 */

import { View, Text, FlatList, Pressable, Image } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useRouter } from 'expo-router';
import { useFocusEffect } from 'expo-router';
import { useCallback } from 'react';
import { Ionicons } from '@expo/vector-icons';
import useHistory from '../../src/hooks/useHistory';
import Skeleton from '../../src/components/common/Skeleton';
import { formatMinutes } from '../../src/utils/time';

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

  // Reload whenever this tab comes into focus so newly cooked recipes appear immediately
  useFocusEffect(
    useCallback(() => {
      reload();
    }, [reload])
  );

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
              onPress={() => router.push('/recipe/' + item.recipeId)}
              onDelete={() => removeEntry(item.id)}
            />
          )}
        />
      )}
    </SafeAreaView>
  );
}

function HistoryRow({ item, onPress, onDelete }) {
  const mealLabel = MEAL_LABELS[item.mealType] || item.mealType || '';
  const dateStr = item.cookedAt ? new Date(item.cookedAt).toLocaleDateString(undefined, {
    month: 'short', day: 'numeric', year: 'numeric'
  }) : '';

  return (
    <Pressable
      onPress={onPress}
      className="flex-row items-center py-3 border-b border-border active:bg-gray-50"
      accessibilityRole="button"
      accessibilityLabel={item.recipeTitle || 'Cooked recipe'}
    >
      <View className="rounded-xl bg-gray-200 overflow-hidden mr-4 flex-shrink-0" style={{ width: 72, height: 72 }}>
        {item.recipeImage ? (
          <Image source={{ uri: item.recipeImage }} style={{ width: 72, height: 72 }} resizeMode="cover" />
        ) : (
          <View className="flex-1 items-center justify-center">
            <Ionicons name="restaurant-outline" size={24} color="#CBD5E1" />
          </View>
        )}
      </View>
      <View className="flex-1">
        <Text className="text-sm font-semibold text-text-primary" numberOfLines={2}>
          {item.recipeTitle || item.recipeId}
        </Text>
        <Text className="text-xs text-text-secondary mt-0.5">
          {mealLabel}{item.servingCount ? ' · ' + item.servingCount + ' serving' + (item.servingCount !== 1 ? 's' : '') : ''}
        </Text>
        {dateStr ? <Text className="text-xs text-text-muted mt-0.5">{dateStr}</Text> : null}
      </View>
      <Pressable
        onPress={onDelete}
        className="w-8 h-8 items-center justify-center ml-2"
        accessibilityLabel="Delete history entry"
        hitSlop={8}
      >
        <Ionicons name="trash-outline" size={18} color="#94A3B8" />
      </Pressable>
      <Ionicons name="chevron-forward" size={16} color="#CBD5E1" />
    </Pressable>
  );
}
