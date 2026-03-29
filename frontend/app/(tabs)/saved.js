/**
 * Saved recipes list screen.
 * Shows all bookmarked recipes. Per BR-SAV-01 through BR-SAV-05.
 */

import { View, Text, FlatList, Pressable, Image } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useRouter } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import useSavedRecipes from '../../src/hooks/useSavedRecipes';
import Skeleton from '../../src/components/common/Skeleton';
import { formatMinutes } from '../../src/utils/time';

export default function SavedScreen() {
  const { savedRecipes, loading, remove } = useSavedRecipes();
  const router = useRouter();

  if (loading) {
    return (
      <SafeAreaView className="flex-1 bg-background">
        <View className="px-6 pt-4 pb-2">
          <Text className="text-2xl font-bold text-text-primary">Saved Recipes</Text>
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
          Saved Recipes
          {savedRecipes.length > 0 ? (
            <Text className="text-base font-normal text-text-muted"> ({savedRecipes.length})</Text>
          ) : null}
        </Text>
      </View>

      {savedRecipes.length === 0 ? (
        <View className="flex-1 items-center justify-center px-8">
          <Ionicons name="bookmark-outline" size={64} color="#94A3B8" />
          <Text className="text-xl font-semibold text-text-primary mt-6 mb-2 text-center">
            No saved recipes yet
          </Text>
          <Text className="text-base text-text-secondary text-center leading-6">
            Tap the bookmark icon on any recipe card to save it here.
          </Text>
        </View>
      ) : (
        <FlatList
          data={savedRecipes}
          keyExtractor={(item) => item.id}
          contentContainerStyle={{ paddingHorizontal: 24, paddingBottom: 24 }}
          renderItem={({ item }) => (
            <SavedRecipeRow
              item={item}
              onPress={() => router.push('/recipe/' + item.recipeId)}
              onRemove={() => remove(item.id)}
            />
          )}
        />
      )}
    </SafeAreaView>
  );
}

function SavedRecipeRow({ item, onPress, onRemove }) {
  return (
    <Pressable
      onPress={onPress}
      className="flex-row items-center py-3 border-b border-border active:bg-gray-50"
      accessibilityRole="button"
      accessibilityLabel={item.recipeTitle || 'Saved recipe'}
    >
      <View className="w-18 h-18 rounded-xl bg-gray-200 overflow-hidden mr-4 flex-shrink-0" style={{ width: 72, height: 72 }}>
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
        {item.recipeCookTime ? (
          <Text className="text-xs text-text-muted mt-0.5">
            {formatMinutes(item.recipeCookTime)}
          </Text>
        ) : null}
        <Text className="text-xs text-text-muted mt-0.5">
          Saved {item.savedAt ? new Date(item.savedAt).toLocaleDateString() : ''}
        </Text>
      </View>
      <Pressable
        onPress={onRemove}
        className="w-8 h-8 items-center justify-center ml-2"
        accessibilityLabel="Remove from saved"
        hitSlop={8}
      >
        <Ionicons name="trash-outline" size={18} color="#94A3B8" />
      </Pressable>
      <Ionicons name="chevron-forward" size={16} color="#CBD5E1" className="ml-1" />
    </Pressable>
  );
}
