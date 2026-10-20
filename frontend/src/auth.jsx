import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { apiErrorMessage, apiFetch, setAccessToken } from './api';
import { AuthContext, useAuth } from './auth-context';

let googleScriptPromise;

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);

  useEffect(() => {
    const handleUnauthorized = () => setUser(null);
    window.addEventListener('personal-agent:unauthorized', handleUnauthorized);
    return () => window.removeEventListener('personal-agent:unauthorized', handleUnauthorized);
  }, []);

  const signIn = useCallback(async (credential) => {
    const response = await apiFetch('/api/v1/auth/google', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ credential }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data.success) {
      throw new Error(apiErrorMessage(data, 'Google Sign-In could not be completed.'));
    }
    setAccessToken(data.access_token);
    setUser(data.user);
  }, []);

  const signOut = useCallback(() => {
    setAccessToken(null);
    setUser(null);
  }, []);

  const value = useMemo(() => ({ user, signIn, signOut }), [user, signIn, signOut]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

function loadGoogleIdentityScript() {
  if (window.google?.accounts?.id) return Promise.resolve();
  if (!googleScriptPromise) {
    googleScriptPromise = new Promise((resolve, reject) => {
      const existing = document.querySelector('script[data-google-identity]');
      if (existing) {
        existing.addEventListener('load', resolve, { once: true });
        existing.addEventListener('error', reject, { once: true });
        return;
      }
      const script = document.createElement('script');
      script.src = 'https://accounts.google.com/gsi/client';
      script.async = true;
      script.defer = true;
      script.dataset.googleIdentity = 'true';
      script.onload = resolve;
      script.onerror = reject;
      document.head.appendChild(script);
    });
  }
  return googleScriptPromise;
}

export function GoogleSignInButton() {
  const { signIn } = useAuth();
  const clientId = import.meta.env.VITE_GOOGLE_CLIENT_ID;
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(Boolean(clientId));
  const containerRef = useRef(null);

  useEffect(() => {
    let active = true;
    if (!clientId) return () => { active = false; };

    loadGoogleIdentityScript()
      .then(() => {
        if (!active || !containerRef.current) return;
        window.google.accounts.id.initialize({
          client_id: clientId,
          callback: async ({ credential }) => {
            setError('');
            try {
              await signIn(credential);
            } catch (signInError) {
              setError(signInError.message);
            }
          },
        });
        window.google.accounts.id.renderButton(containerRef.current, {
          theme: 'outline',
          size: 'large',
          text: 'signin_with',
          shape: 'rectangular',
          width: 280,
        });
        setLoading(false);
      })
      .catch(() => {
        if (active) {
          setError('Google Sign-In could not load. Check your network and try again.');
          setLoading(false);
        }
      });
    return () => { active = false; };
  }, [clientId, signIn]);

  return (
    <div className="google-sign-in">
      {loading && <p>Loading Google Sign-In…</p>}
      <div ref={containerRef} />
      {(error || (!clientId && 'Set VITE_GOOGLE_CLIENT_ID to the Google Web OAuth client ID.')) && (
        <p className="auth-error" role="alert">
          {error || 'Set VITE_GOOGLE_CLIENT_ID to the Google Web OAuth client ID.'}
        </p>
      )}
    </div>
  );
}
