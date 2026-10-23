// ========= Copyright 2025-2026 @ Eigent.ai All Rights Reserved. =========
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.
// ========= Copyright 2025-2026 @ Eigent.ai All Rights Reserved. =========

import { proxyFetchPost } from '@/api/http';
import { isDesktop } from '@/client/platform';
import { useAuthStore } from '@/store/authStore';
import { lazy, useEffect, useReducer } from 'react';
import { Navigate, Outlet, Route, Routes } from 'react-router-dom';

import Layout from '@/components/Layout';
// Lazy load page components
const Workspace = lazy(() => import('@/pages/Workspace'));
const History = lazy(() => import('@/pages/History'));
const NotFound = lazy(() => import('@/pages/NotFound'));
const RemoteControl = lazy(() => import('@/pages/RemoteControl'));

const IS_LOCAL_MODE = import.meta.env.VITE_USE_LOCAL_PROXY === 'true';
const ENABLE_DESKTOP_REMOTE_CONTROL_FALLBACK = isDesktop();

interface AuthState {
  loading: boolean;
  isAuthenticated: boolean;
  initialized: boolean;
}

type AuthAction =
  | { type: 'INITIALIZE'; payload: { isAuthenticated: boolean } }
  | { type: 'LOGOUT' };

const authReducer = (state: AuthState, action: AuthAction): AuthState => {
  switch (action.type) {
    case 'INITIALIZE':
      return {
        loading: false,
        isAuthenticated: action.payload.isAuthenticated,
        initialized: true,
      };
    case 'LOGOUT':
      return {
        loading: false,
        isAuthenticated: false,
        initialized: true,
      };
    default:
      return state;
  }
};

// Route guard: Check if user is logged in
const ProtectedRoute = () => {
  const [state, dispatch] = useReducer(authReducer, {
    loading: false,
    isAuthenticated: false,
    initialized: false,
  });

  const {
    token,
    localProxyValue,
    logout,
    setAuth,
    setLocalProxyValue,
    setInitState,
    setIsFirstLaunch,
    setModelType,
  } = useAuthStore();
  useEffect(() => {
    // Check VITE_USE_LOCAL_PROXY value on app startup
    if (token) {
      const currentProxyValue = import.meta.env.VITE_USE_LOCAL_PROXY || null;
      const storedProxyValue = localProxyValue;

      // If stored value exists and differs from current, logout
      if (storedProxyValue !== null && storedProxyValue !== currentProxyValue) {
        console.warn('VITE_USE_LOCAL_PROXY value changed, logging out user');
        logout();
        dispatch({ type: 'LOGOUT' });
        return;
      }
    }

    // Local mode: auto-login when no token
    if (IS_LOCAL_MODE && !token) {
      proxyFetchPost('/api/v1/user/auto-login', {})
        .then((data) => {
          if (data && data.token) {
            setAuth({ email: data.email, ...data });
            setLocalProxyValue(import.meta.env.VITE_USE_LOCAL_PROXY || null);
            setModelType('custom');
            setInitState('done');
            setIsFirstLaunch(false);
            dispatch({
              type: 'INITIALIZE',
              payload: { isAuthenticated: true },
            });
          } else {
            dispatch({
              type: 'INITIALIZE',
              payload: { isAuthenticated: false },
            });
          }
        })
        .catch(() => {
          dispatch({
            type: 'INITIALIZE',
            payload: { isAuthenticated: false },
          });
        });
      return;
    }

    dispatch({ type: 'INITIALIZE', payload: { isAuthenticated: !!token } });
  }, [
    token,
    localProxyValue,
    logout,
    setAuth,
    setLocalProxyValue,
    setInitState,
    setIsFirstLaunch,
    setModelType,
  ]);

  if (state.loading || !state.initialized) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-b-2 border-blue-600"></div>
      </div>
    );
  }
  if (state.isAuthenticated) {
    return <Outlet />;
  }

  // The auth pages are gone, so there is nowhere to redirect. If the local
  // auto-login cannot reach the brain, say so and offer a retry instead of
  // routing to a /login that no longer exists.
  return (
    <div className="flex h-screen flex-col items-center justify-center gap-2 px-6 text-center">
      <div className="text-body-sm text-ds-text-neutral-default-default">
        Can&apos;t reach the local brain
      </div>
      <div className="max-w-sm text-label-xs text-ds-text-neutral-subtle-default">
        Undisclosed could not sign in to the brain on this machine. Start it,
        then retry.
      </div>
      <button
        type="button"
        onClick={() => window.location.reload()}
        className="mt-1 rounded-md bg-ds-bg-information-default-default px-3 py-1 text-label-xs font-semibold text-ds-text-information-inverse-default outline-none transition-colors hover:bg-ds-bg-information-default-hover"
      >
        Retry
      </button>
    </div>
  );
};

// Main route configuration
const AppRoutes = () => (
  <Routes>
    {ENABLE_DESKTOP_REMOTE_CONTROL_FALLBACK ? (
      <Route path="/remote-control/:sessionId" element={<RemoteControl />} />
    ) : null}
    <Route element={<ProtectedRoute />}>
      <Route element={<Layout />}>
        <Route path="/" element={<Workspace />} />
        <Route path="/history" element={<History />} />
        <Route
          path="/setting"
          element={<Navigate to="/history?tab=settings" replace />}
        />
        <Route
          path="/setting/*"
          element={<Navigate to="/history?tab=settings" replace />}
        />
      </Route>
    </Route>
    <Route path="*" element={<NotFound />} />
  </Routes>
);

export default AppRoutes;
