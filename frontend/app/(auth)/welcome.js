/**
 * Welcome/splash screen - entry point for unauthenticated users.
 */

import { View, Text, Pressable } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useRouter } from 'expo-router';
import { useAuth } from '../../src/context/AuthContext';

export default function WelcomeScreen() {
  const router = useRouter();
  const { login } = useAuth();

  const handleGetStarted = async () => {
    // TODO: Replace with real auth flow when backend is ready
    const mockUserId = `user_${Date.now()}`;
    await login('mock_access_token', 'mock_refresh_token', mockUserId);
    router.replace('/(auth)/onboarding');
  };

  return (
    <SafeAreaView className="flex-1 bg-background">
      <View className="flex-1 justify-center items-center px-8">
        <View className="mb-12 items-center">
          <Text className="text-4xl font-bold text-text-primary mb-3">
            Smart Recipe Planner
          </Text>
          <Text className="text-lg text-text-secondary text-center leading-7">
            Snap your ingredients, get personalized recipes, and start cooking in seconds.
          </Text>
        </View>

        <View className="w-full gap-4">
          <Pressable
            onPress={handleGetStarted}
            className="bg-primary py-4 rounded-xl items-center active:bg-primary-dark"
          >
            <Text className="text-white text-lg font-semibold">Get Started</Text>
          </Pressable>

          <Pressable
            onPress={handleGetStarted}
            className="py-4 rounded-xl items-center border border-border active:bg-gray-50"
          >
            <Text className="text-text-primary text-lg font-semibold">I Have an Account</Text>
          </Pressable>
        </View>
      </View>

      <View className="pb-6 items-center">
        <Text className="text-text-muted text-sm">
          By continuing, you agree to our Terms and Privacy Policy
        </Text>
      </View>
    </SafeAreaView>
  );
}
