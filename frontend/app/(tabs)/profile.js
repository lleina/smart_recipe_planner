/**
 * User profile and preference editing screen.
 * All onboarding preferences editable here (BR-ONB-08).
 */

import { useState } from 'react';
import { View, Text, ScrollView, Pressable, Alert, ActivityIndicator } from 'react-native';
import { useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import * as SecureStore from 'expo-secure-store';
import AsyncStorage from'@react-native-async-storage/async-storage';
import { useAuth } from '../../src/context/AuthContext';
import { useSession } from '../../src/context/SessionContext';

export default function ProfileScreen() {
  const { user, logout } = useAuth();
  const { resetSession } = useSession();
  const router = useRouter();
  const [showDevMode, setShowDevMode] = useState(false);
  const [clearing, setClearing] = useState(false);

  const menuItems = [
    { icon: 'heart-outline', label: 'Cuisine Preferences', route: null },
    { icon: 'nutrition-outline', label: 'Dietary Restrictions', route: null },
    { icon: 'fitness-outline', label: 'Health Goal', route: null },
    { icon: 'timer-outline', label: 'Time Preference', route: null },
    { icon: 'hardware-chip-outline', label: 'Kitchen Equipment', route: null },
    { icon: 'download-outline', label: 'Export My Data', route: null },
    { icon: 'trash-outline', label: 'Delete Account', route: null, danger: true },
  ];

  return (
    <SafeAreaView className="flex-1 bg-background">
      <View className="px-6 pt-4 pb-2">
        <Text className="text-2xl font-bold text-text-primary">Profile</Text>
      </View>

      <ScrollView className="flex-1 px-6" showsVerticalScrollIndicator={false}>
        <View className="py-6 items-center border-b border-border mb-4">
          <View className="w-16 h-16 rounded-full bg-primary items-center justify-center mb-3">
            <Text className="text-white text-2xl font-bold">
              {user?.id?.charAt(5)?.toUpperCase() || 'U'}
            </Text>
          </View>
          <Text className="text-base text-text-secondary">{user?.id || 'User'}</Text>
        </View>

        {menuItems.map((item) => (
          <Pressable
            key={item.label}
            className="flex-row items-center py-4 border-b border-border active:bg-gray-50"
            accessibilityLabel={item.label}
          >
            <Ionicons
              name={item.icon}
              size={22}
              color={item.danger ? '#EF4444' : '#64748B'}
            />
            <Text
              className={`flex-1 ml-4 text-base ${
                item.danger ? 'text-danger' : 'text-text-primary'
              }`}
            >
              {item.label}
            </Text>
            <Ionicons name="chevron-forward" size={20} color="#94A3B8" />
          </Pressable>
        ))}

        <Pressable
          onPress={logout}
          className="flex-row items-center py-4 mt-4 active:bg-gray-50"
        >
          <Ionicons name="log-out-outline" size={22} color="#EF4444" />
          <Text className="ml-4 text-base text-danger">Log Out</Text>
        </Pressable>

        {/* Dev Mode Section */}
        <View className="mt-8 pt-6 border-t border-border">
          <Pressable
            onPress={() => setShowDevMode(!showDevMode)}
            className="flex-row items-center pb-4"
          >
            <Text className="text-xs font-semibold text-text-secondary uppercase tracking-wide">
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
                For testing: Clears ALL app data including auth, preferences, and cache.
              </Text>
              <Pressable
                onPress={async () => {
                  Alert.alert(
                    'Clear All Data?',
                    'This will log you out and erase all settings, saved recipes, and history. You\'ll need to re-onboard.',
                    [
                      { text: 'Cancel', style: 'cancel' },
                      {
                        text: 'Clear All',
                        style: 'destructive',
                        onPress: async () => {
                          setClearing(true);
                          try {
                            // Clear AsyncStorage keys individually (iOS blocks .clear())
                            const allKeys = await AsyncStorage.getAllKeys();
                            if (allKeys.length > 0) {
                              await AsyncStorage.multiRemove(allKeys);
                            }
                            // Clear SecureStore + onboarding flag
                            await SecureStore.deleteItemAsync('onboarded');
                            resetSession();
                            // logout() clears tokens + resets auth state
                            await logout();
                            // Navigate to welcome screen immediately
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
      </ScrollView>
    </SafeAreaView>
  );
}
