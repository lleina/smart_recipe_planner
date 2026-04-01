/**
 * Welcome/splash screen — entry point for unauthenticated users.
 * Offline-first: creates a local identity with no server call.
 */

import { useState } from 'react';
import { ScrollView, View, Text, Pressable, ActivityIndicator } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useRouter } from 'expo-router';
import { useAuth } from '../../src/context/AuthContext';

const BG = '#214130';

export default function WelcomeScreen() {
  const router = useRouter();
  const { localSetup } = useAuth();
  const [loading, setLoading] = useState(false);

  const handleCreateAccount = async () => {
    if (loading) return;
    setLoading(true);
    try {
      await localSetup();
    } catch {
      // ignore — still navigate
    }
    router.replace('/(auth)/onboarding');
  };

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: BG }}>
      {/*
        ScrollView with flexGrow: 1 + justifyContent: 'flex-end' is the most
        reliable way to pin content to the bottom on every device size.
        scrollEnabled is false since there is no overflow content.
      */}
      <ScrollView
        contentContainerStyle={{
          flexGrow: 1,
          justifyContent: 'flex-end',
          paddingHorizontal: 32,
          paddingBottom: 52,
        }}
        scrollEnabled={false}
        keyboardShouldPersistTaps="handled"
      >
        {/* Display headline */}
        <Text
          style={{
            fontFamily: 'Mohave_700Bold',
            fontSize: 50,
            color: '#FFFFFF',
            lineHeight: 56,
            letterSpacing: -1,
            marginBottom: 14,
          }}
        >
          Smart Recipe Planner
        </Text>

        {/* Subtitle */}
        <Text
          style={{
            fontSize: 16,
            color: 'rgba(255,255,255,0.72)',
            lineHeight: 24,
            marginBottom: 44,
          }}
        >
          Snap your ingredients, get personalized recipes, and start cooking in seconds.
        </Text>

        {/* CTA button — static style so there are no render ambiguities */}
        <Pressable
          onPress={handleCreateAccount}
          disabled={loading}
          style={{
            backgroundColor: '#FFFFFF',
            paddingVertical: 18,
            borderRadius: 16,
            alignItems: 'center',
            opacity: loading ? 0.7 : 1,
          }}
          accessibilityRole="button"
          accessibilityLabel="Create my account and set preferences"
        >
          {loading ? (
            <ActivityIndicator color={BG} />
          ) : (
            <Text
              style={{
                fontFamily: 'Mohave_700Bold',
                color: BG,
                fontSize: 18,
                letterSpacing: 0.3,
              }}
            >
              Create My Account
            </Text>
          )}
        </Pressable>
      </ScrollView>
    </SafeAreaView>
  );
}
