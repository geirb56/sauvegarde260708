/**
 * OAuthButtons — Google sign-in button.
 *
 * Handles the entire OAuth flow:
 *   1. Loads the Google GSI SDK on mount.
 *   2. Triggers the provider's auth dialog when the button is clicked.
 *   3. Receives the provider's ID token client-side.
 *   4. Sends only the ID token to the RunIndex backend for server-side
 *      verification — the frontend never derives identity from the token.
 *   5. Stores the RunIndex JWT returned by the backend.
 *   6. Calls loginWithToken() to update AuthContext.
 *
 * Security notes:
 *   - REACT_APP_GOOGLE_CLIENT_ID is a public OAuth identifier, not a secret.
 *     It is safe to include in the frontend bundle.
 *   - The frontend never reads claims from the provider ID token.
 *   - No Google session is created on the client side.
 */

import { useEffect, useState, useCallback } from "react";
import axios from "axios";
import { API_BASE_URL } from "@/config";
import { useAuth } from "@/context/AuthContext";
import { useLanguage } from "@/context/LanguageContext";
import { Button } from "@/components/ui/button";
import { Loader2 } from "lucide-react";
import { getAuthErrorMessage } from "@/lib/authErrors";

// ── Configuration (public IDs, not secrets) ───────────────────────────────────

const GOOGLE_CLIENT_ID = process.env.REACT_APP_GOOGLE_CLIENT_ID || "";
async function fetchOAuthChallenge(provider) {
  const res = await axios.post(`${API_BASE_URL}/auth/oauth/challenge/${provider}`);
  return res.data;
}

// ── Google Sign-In ────────────────────────────────────────────────────────────

function useGoogleSignIn({ onSuccess, onError, t }) {
  const [ready, setReady] = useState(false);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!GOOGLE_CLIENT_ID) return;

    // Load Google Identity Services script
    if (document.getElementById("google-gsi-script")) {
      if (window.google?.accounts) setReady(true);
      return;
    }

    const script = document.createElement("script");
    script.id = "google-gsi-script";
    script.src = "https://accounts.google.com/gsi/client";
    script.async = true;
    script.defer = true;
    script.onload = () => {
      setReady(true);
    };
    script.onerror = () => {
      onError(t("auth.googleLoadFailed"));
    };
    document.head.appendChild(script);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleGoogleCredential = useCallback(async (idToken, state) => {
   try {
     const res = await axios.post(`${API_BASE_URL}/auth/google`, {
       id_token: idToken,
       state,
     });
     onSuccess(res.data);
   } catch (err) {
     onError(getAuthErrorMessage(t, err, "auth.googleFailed"));
   } finally {
     setLoading(false);
   }
  }, [onSuccess, onError, t]);

  const signIn = useCallback(() => {
    if (!GOOGLE_CLIENT_ID) {
      onError(t("auth.googleNotConfigured"));
      return;
    }
    if (!window.google?.accounts) {
      onError(t("auth.googleUnavailable"));
      return;
    }
    setLoading(true);
    fetchOAuthChallenge("google")
      .then((challenge) => {
        window.google.accounts.id.initialize({
          client_id: GOOGLE_CLIENT_ID,
          nonce: challenge.nonce,
          callback: (response) => {
            if (response.credential) {
              handleGoogleCredential(response.credential, challenge.state);
            } else {
              setLoading(false);
              onError(t("auth.googleCancelled"));
            }
          },
          cancel_on_tap_outside: true,
        });
        window.google.accounts.id.prompt((notification) => {
          if (
            notification.isNotDisplayed() ||
            notification.isSkippedMoment()
          ) {
            const btn = document.createElement("div");
            btn.style.display = "none";
            document.body.appendChild(btn);
            window.google.accounts.id.renderButton(btn, {
              theme: "outline",
              size: "large",
              click_listener: () => {},
            });
            btn.querySelector("div[role='button']")?.click();
            document.body.removeChild(btn);
          }
        });
      })
      .catch((err) => {
        setLoading(false);
        onError(getAuthErrorMessage(t, err, "auth.googleFailed"));
      });
  }, [handleGoogleCredential, onError, t]);

  return { signIn, ready: ready && !!GOOGLE_CLIENT_ID, loading };
}

// ── OAuthButtons component ────────────────────────────────────────────────────

/**
 * @param {{ onError: (msg: string) => void, onSuccess: () => void }} props
 */
export default function OAuthButtons({ onError, onSuccess }) {
  const { loginWithToken } = useAuth();
  const { t } = useLanguage();

  const handleSuccess = useCallback(
    (data) => {
      // data = { access_token, token_type, user }
      loginWithToken(data.access_token, data.user);
      onSuccess?.();
    },
    [loginWithToken, onSuccess]
  );

  const google = useGoogleSignIn({ onSuccess: handleSuccess, onError, t });

  return (
    <div className="space-y-2">
      <Button
        type="button"
        variant="outline"
        className="w-full flex items-center justify-center gap-2"
        onClick={google.signIn}
        disabled={google.loading}
        aria-label={t("auth.continueWithGoogle")}
      >
        {google.loading ? (
          <Loader2 className="w-4 h-4 animate-spin" />
        ) : (
          <GoogleIcon />
        )}
        {t("auth.continueWithGoogle")}
      </Button>
    </div>
  );
}

// ── Provider icons ────────────────────────────────────────────────────────────

function GoogleIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true">
      <path
        fill="#EA4335"
        d="M24 9.5c3.5 0 6.6 1.2 9 3.2l6.7-6.7C35.8 2.5 30.2 0 24 0 14.6 0 6.6 5.4 2.7 13.2l7.8 6C12.3 13.2 17.7 9.5 24 9.5z"
      />
      <path
        fill="#4285F4"
        d="M46.5 24.5c0-1.6-.1-3.1-.4-4.5H24v8.5h12.7c-.6 3-2.3 5.5-4.8 7.2l7.5 5.8C43.7 37.6 46.5 31.5 46.5 24.5z"
      />
      <path
        fill="#FBBC05"
        d="M10.5 28.7c-.5-1.5-.8-3-.8-4.7s.3-3.2.8-4.7L2.7 13.2C1 16.5 0 20.1 0 24s1 7.5 2.7 10.8l7.8-6.1z"
      />
      <path
        fill="#34A853"
        d="M24 48c6.2 0 11.4-2 15.2-5.5l-7.5-5.8c-2 1.4-4.6 2.2-7.7 2.2-6.3 0-11.7-3.7-13.5-9l-7.8 6C6.6 42.6 14.6 48 24 48z"
      />
    </svg>
  );
}
