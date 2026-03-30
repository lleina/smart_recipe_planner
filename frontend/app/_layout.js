/**
 * Root layout — wraps the entire app with providers and global config.
 *
 * GestureHandlerRootView must be the outermost wrapper so that
 * react-native-gesture-handler's GestureDetector works on any screen.
 */

import { useEffect } from 'react';
import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import * as SplashScreen from 'expo-splash-screen';
import { GestureHandlerRootView } from 'react-native-gesture-handler';
import { AuthProvider } from '../src/context/AuthContext';
import { SessionProvider } from '../src/context/SessionContext';
import { RecipeProvider } from '../src/context/RecipeContext';
import { SavedRecipesProvider } from '../src/context/SavedRecipesContext';
import '../global.css';

SplashScreen.preventAutoHideAsync();

export default function RootLayout() {
  useEffect(() => {
    SplashScreen.hideAsync();
  }, []);

  return (
    <GestureHandlerRootView style={{ flex: 1 }}>
    <AuthProvider>
      <SessionProvider>
        <SavedRecipesProvider>
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
        </SavedRecipesProvider>
      </SessionProvider>
    </AuthProvider>
    </GestureHandlerRootView>
  );
}
