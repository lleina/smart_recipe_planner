/**
 * Root layout - wraps the entire app with providers and global config.
 */

import { useEffect } from 'react';
import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import * as SplashScreen from 'expo-splash-screen';
import { AuthProvider } from '../src/context/AuthContext';
import { SessionProvider } from '../src/context/SessionContext';
import { RecipeProvider } from '../src/context/RecipeContext';
import '../global.css';

SplashScreen.preventAutoHideAsync();

export default function RootLayout() {
  useEffect(() => {
    SplashScreen.hideAsync();
  }, []);

  return (
    <AuthProvider>
      <SessionProvider>
        <RecipeProvider>
          <StatusBar style="dark" />
          <Stack screenOptions={{ headerShown: false }}>
            <Stack.Screen name="index" />
            <Stack.Screen name="(auth)" />
            <Stack.Screen name="(tabs)" />
            <Stack.Screen name="session/setup" />
            <Stack.Screen name="session/generating" />
            <Stack.Screen
              name="recipe/[id]"
              options={{ headerShown: true, headerTitle: '', headerBackTitle: 'Back' }}
            />
          </Stack>
        </RecipeProvider>
      </SessionProvider>
    </AuthProvider>
  );
}
