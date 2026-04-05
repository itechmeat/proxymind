import { type ReactNode, useEffect, useRef, useState } from "react";
import {
  Link,
  Navigate,
  useLocation,
  useNavigate,
  useSearchParams,
} from "react-router";

import { Button } from "@/components/ui/button";
import { useUserAuth } from "@/hooks/useUserAuth";
import { strings } from "@/lib/strings";

const inputClassName =
  "mt-2 w-full rounded-2xl border border-stone-200 bg-white px-4 py-3 text-sm text-stone-950 shadow-sm outline-none transition focus:border-amber-400 focus:ring-4 focus:ring-amber-100";

function AuthLayout({
  body,
  description,
  eyebrow,
  footer,
  title,
}: {
  body: ReactNode;
  description: string;
  eyebrow: string;
  footer?: ReactNode;
  title: string;
}) {
  return (
    <main className="min-h-dvh bg-[radial-gradient(circle_at_top_left,_rgba(245,158,11,0.18),_transparent_28%),radial-gradient(circle_at_bottom_right,_rgba(14,165,233,0.14),_transparent_30%),linear-gradient(180deg,_rgba(255,251,235,0.98)_0%,_rgba(248,250,252,1)_100%)]">
      <div className="mx-auto flex min-h-dvh max-w-6xl flex-col justify-center gap-10 px-6 py-10 lg:flex-row lg:items-center lg:gap-16">
        <section className="max-w-xl">
          <p className="text-xs font-semibold uppercase tracking-[0.26em] text-amber-700/80">
            {eyebrow}
          </p>
          <h1 className="mt-4 font-serif text-5xl leading-none tracking-[-0.06em] text-stone-950 sm:text-6xl">
            {title}
          </h1>
          <p className="mt-5 max-w-lg text-base leading-7 text-stone-600">
            {description}
          </p>
        </section>

        <section className="w-full max-w-md rounded-[2rem] border border-white/75 bg-white/82 p-8 shadow-2xl shadow-stone-900/5 backdrop-blur-sm">
          {body}
          {footer ? (
            <div className="mt-6 text-sm text-stone-600">{footer}</div>
          ) : null}
        </section>
      </div>
    </main>
  );
}

function StatusCallout({
  detail,
  tone = "neutral",
}: {
  detail: string;
  tone?: "neutral" | "success" | "error";
}) {
  const className =
    tone === "success"
      ? "border-emerald-200 bg-emerald-50 text-emerald-800"
      : tone === "error"
        ? "border-rose-200 bg-rose-50 text-rose-800"
        : "border-stone-200 bg-stone-50 text-stone-700";

  return (
    <div
      className={`rounded-2xl border px-4 py-3 text-sm leading-6 ${className}`}
    >
      {detail}
    </div>
  );
}

function resolveRedirectTarget(state: unknown) {
  if (
    typeof state === "object" &&
    state !== null &&
    "from" in state &&
    typeof state.from === "string" &&
    state.from.startsWith("/")
  ) {
    return state.from;
  }

  return "/";
}

export function SignInPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const { signIn } = useUserAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const redirectTarget = resolveRedirectTarget(location.state);

  return (
    <AuthLayout
      eyebrow={strings.authEyebrow}
      title={strings.signInTitle}
      description={strings.signInDescription}
      body={
        <form
          className="space-y-5"
          onSubmit={(event) => {
            event.preventDefault();
            setIsSubmitting(true);
            setError(null);

            void (async () => {
              try {
                await signIn({
                  email,
                  password,
                });
                navigate(redirectTarget, { replace: true });
              } catch (submitError) {
                setError(
                  submitError instanceof Error
                    ? submitError.message
                    : strings.authRequestFailed,
                );
              } finally {
                setIsSubmitting(false);
              }
            })();
          }}
        >
          <div>
            <label
              className="text-sm font-medium text-stone-700"
              htmlFor="auth-email"
            >
              {strings.emailLabel}
            </label>
            <input
              autoComplete="email"
              className={inputClassName}
              id="auth-email"
              onChange={(event) => {
                setEmail(event.currentTarget.value);
                setError(null);
              }}
              placeholder="jane@example.com"
              required
              type="email"
              value={email}
            />
          </div>

          <div>
            <label
              className="text-sm font-medium text-stone-700"
              htmlFor="auth-password"
            >
              {strings.passwordLabel}
            </label>
            <input
              autoComplete="current-password"
              className={inputClassName}
              id="auth-password"
              minLength={8}
              onChange={(event) => {
                setPassword(event.currentTarget.value);
                setError(null);
              }}
              placeholder={strings.passwordPlaceholder}
              required
              type="password"
              value={password}
            />
          </div>

          {error ? <StatusCallout detail={error} tone="error" /> : null}

          <Button className="w-full" disabled={isSubmitting} type="submit">
            {isSubmitting ? strings.signingIn : strings.signInAction}
          </Button>
        </form>
      }
      footer={
        <div className="space-y-2">
          <p>
            {strings.noAccountYet}{" "}
            <Link
              className="font-medium text-stone-950 underline"
              to="/auth/register"
            >
              {strings.registerAction}
            </Link>
          </p>
          <p>
            <Link
              className="font-medium text-stone-950 underline"
              to="/auth/forgot-password"
            >
              {strings.forgotPasswordAction}
            </Link>
          </p>
        </div>
      }
    />
  );
}

export function RegisterPage() {
  const { register } = useUserAuth();
  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [successDetail, setSuccessDetail] = useState<string | null>(null);

  return (
    <AuthLayout
      eyebrow={strings.authEyebrow}
      title={strings.registerTitle}
      description={strings.registerDescription}
      body={
        <form
          className="space-y-5"
          onSubmit={(event) => {
            event.preventDefault();
            if (successDetail) {
              return;
            }
            setError(null);

            if (password !== confirmPassword) {
              setError(strings.passwordConfirmationMismatch);
              return;
            }

            setIsSubmitting(true);

            void (async () => {
              try {
                const detail = await register({
                  display_name: displayName || undefined,
                  email,
                  password,
                });
                setSuccessDetail(detail);
              } catch (submitError) {
                setError(
                  submitError instanceof Error
                    ? submitError.message
                    : strings.authRequestFailed,
                );
              } finally {
                setIsSubmitting(false);
              }
            })();
          }}
        >
          <div>
            <label
              className="text-sm font-medium text-stone-700"
              htmlFor="register-display-name"
            >
              {strings.displayNameLabel}
            </label>
            <input
              className={inputClassName}
              id="register-display-name"
              onChange={(event) => setDisplayName(event.currentTarget.value)}
              placeholder={strings.displayNamePlaceholder}
              type="text"
              value={displayName}
            />
          </div>

          <div>
            <label
              className="text-sm font-medium text-stone-700"
              htmlFor="register-email"
            >
              {strings.emailLabel}
            </label>
            <input
              autoComplete="email"
              className={inputClassName}
              id="register-email"
              onChange={(event) => setEmail(event.currentTarget.value)}
              placeholder="jane@example.com"
              required
              type="email"
              value={email}
            />
          </div>

          <div>
            <label
              className="text-sm font-medium text-stone-700"
              htmlFor="register-password"
            >
              {strings.passwordLabel}
            </label>
            <input
              autoComplete="new-password"
              className={inputClassName}
              id="register-password"
              minLength={8}
              onChange={(event) => {
                setPassword(event.currentTarget.value);
                setError(null);
              }}
              placeholder={strings.passwordPlaceholder}
              required
              type="password"
              value={password}
            />
          </div>

          <div>
            <label
              className="text-sm font-medium text-stone-700"
              htmlFor="register-confirm-password"
            >
              {strings.confirmPasswordLabel}
            </label>
            <input
              autoComplete="new-password"
              className={inputClassName}
              id="register-confirm-password"
              minLength={8}
              onChange={(event) => {
                setConfirmPassword(event.currentTarget.value);
                setError(null);
              }}
              placeholder={strings.passwordPlaceholder}
              required
              type="password"
              value={confirmPassword}
            />
          </div>

          {successDetail ? (
            <StatusCallout detail={successDetail} tone="success" />
          ) : null}
          {error ? <StatusCallout detail={error} tone="error" /> : null}

          <Button
            className="w-full"
            disabled={isSubmitting || Boolean(successDetail)}
            type="submit"
          >
            {isSubmitting ? strings.registering : strings.registerAction}
          </Button>
        </form>
      }
      footer={
        <p>
          {strings.alreadyHaveAccount}{" "}
          <Link
            className="font-medium text-stone-950 underline"
            to="/auth/sign-in"
          >
            {strings.signInAction}
          </Link>
        </p>
      }
    />
  );
}

export function ForgotPasswordPage() {
  const { forgotPassword } = useUserAuth();
  const [email, setEmail] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [successDetail, setSuccessDetail] = useState<string | null>(null);

  return (
    <AuthLayout
      eyebrow={strings.authEyebrow}
      title={strings.forgotPasswordTitle}
      description={strings.forgotPasswordDescription}
      body={
        <form
          className="space-y-5"
          onSubmit={(event) => {
            event.preventDefault();
            if (successDetail) {
              return;
            }
            setError(null);
            setIsSubmitting(true);

            void (async () => {
              try {
                const detail = await forgotPassword(email);
                setSuccessDetail(detail);
              } catch (submitError) {
                setError(
                  submitError instanceof Error
                    ? submitError.message
                    : strings.authRequestFailed,
                );
              } finally {
                setIsSubmitting(false);
              }
            })();
          }}
        >
          <div>
            <label
              className="text-sm font-medium text-stone-700"
              htmlFor="forgot-email"
            >
              {strings.emailLabel}
            </label>
            <input
              autoComplete="email"
              className={inputClassName}
              id="forgot-email"
              onChange={(event) => setEmail(event.currentTarget.value)}
              placeholder="jane@example.com"
              required
              type="email"
              value={email}
            />
          </div>

          {successDetail ? (
            <StatusCallout detail={successDetail} tone="success" />
          ) : null}
          {error ? <StatusCallout detail={error} tone="error" /> : null}

          <Button
            className="w-full"
            disabled={isSubmitting || Boolean(successDetail)}
            type="submit"
          >
            {isSubmitting ? strings.sendingResetLink : strings.sendResetLink}
          </Button>
        </form>
      }
      footer={
        <p>
          <Link
            className="font-medium text-stone-950 underline"
            to="/auth/sign-in"
          >
            {strings.backToSignIn}
          </Link>
        </p>
      }
    />
  );
}

export function ResetPasswordPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { resetPassword } = useUserAuth();
  const [token, setToken] = useState(searchParams.get("token") ?? "");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [successDetail, setSuccessDetail] = useState<string | null>(null);

  return (
    <AuthLayout
      eyebrow={strings.authEyebrow}
      title={strings.resetPasswordTitle}
      description={strings.resetPasswordDescription}
      body={
        <form
          className="space-y-5"
          onSubmit={(event) => {
            event.preventDefault();
            if (successDetail) {
              return;
            }
            setError(null);

            if (newPassword !== confirmPassword) {
              setError(strings.passwordConfirmationMismatch);
              return;
            }

            setIsSubmitting(true);

            void (async () => {
              try {
                const detail = await resetPassword(token, newPassword);
                setSuccessDetail(detail);
              } catch (submitError) {
                setError(
                  submitError instanceof Error
                    ? submitError.message
                    : strings.authRequestFailed,
                );
              } finally {
                setIsSubmitting(false);
              }
            })();
          }}
        >
          <div>
            <label
              className="text-sm font-medium text-stone-700"
              htmlFor="reset-token"
            >
              {strings.resetTokenLabel}
            </label>
            <input
              className={inputClassName}
              id="reset-token"
              onChange={(event) => setToken(event.currentTarget.value)}
              required
              type="text"
              value={token}
            />
          </div>

          <div>
            <label
              className="text-sm font-medium text-stone-700"
              htmlFor="reset-password"
            >
              {strings.newPasswordLabel}
            </label>
            <input
              autoComplete="new-password"
              className={inputClassName}
              id="reset-password"
              minLength={8}
              onChange={(event) => {
                setNewPassword(event.currentTarget.value);
                setError(null);
              }}
              placeholder={strings.passwordPlaceholder}
              required
              type="password"
              value={newPassword}
            />
          </div>

          <div>
            <label
              className="text-sm font-medium text-stone-700"
              htmlFor="reset-confirm-password"
            >
              {strings.confirmPasswordLabel}
            </label>
            <input
              autoComplete="new-password"
              className={inputClassName}
              id="reset-confirm-password"
              minLength={8}
              onChange={(event) => {
                setConfirmPassword(event.currentTarget.value);
                setError(null);
              }}
              placeholder={strings.passwordPlaceholder}
              required
              type="password"
              value={confirmPassword}
            />
          </div>

          {successDetail ? (
            <StatusCallout detail={successDetail} tone="success" />
          ) : null}
          {error ? <StatusCallout detail={error} tone="error" /> : null}

          <Button
            className="w-full"
            disabled={isSubmitting || Boolean(successDetail)}
            type="submit"
          >
            {isSubmitting
              ? strings.resettingPassword
              : strings.resetPasswordAction}
          </Button>
        </form>
      }
      footer={
        successDetail ? (
          <Button
            className="w-full"
            onClick={() => {
              navigate("/auth/sign-in", { replace: true });
            }}
            type="button"
            variant="outline"
          >
            {strings.backToSignIn}
          </Button>
        ) : (
          <p>
            <Link
              className="font-medium text-stone-950 underline"
              to="/auth/sign-in"
            >
              {strings.backToSignIn}
            </Link>
          </p>
        )
      }
    />
  );
}

export function VerifyEmailPage() {
  const [searchParams] = useSearchParams();
  const { verifyEmail } = useUserAuth();
  const [detail, setDetail] = useState<string | null>(null);
  const [status, setStatus] = useState<"loading" | "success" | "error">(
    "loading",
  );
  const submittedTokenRef = useRef<string | null>(null);
  const token = searchParams.get("token");

  useEffect(() => {
    if (!token) {
      setStatus("error");
      setDetail(strings.invalidVerificationLink);
      return;
    }

    if (submittedTokenRef.current === token) {
      return;
    }
    submittedTokenRef.current = token;

    void (async () => {
      try {
        const responseDetail = await verifyEmail(token);
        setStatus("success");
        setDetail(responseDetail);
      } catch (error) {
        setStatus("error");
        setDetail(
          error instanceof Error ? error.message : strings.authRequestFailed,
        );
      }
    })();
  }, [token, verifyEmail]);

  return (
    <AuthLayout
      eyebrow={strings.authEyebrow}
      title={strings.verifyEmailTitle}
      description={strings.verifyEmailDescription}
      body={
        <div className="space-y-5">
          <StatusCallout
            detail={detail ?? strings.verifyingEmail}
            tone={
              status === "success"
                ? "success"
                : status === "error"
                  ? "error"
                  : "neutral"
            }
          />

          {status !== "loading" ? (
            <Button asChild className="w-full" type="button">
              <Link to="/auth/sign-in">{strings.backToSignIn}</Link>
            </Button>
          ) : null}
        </div>
      }
      footer={
        status === "error" ? (
          <p>
            <Link
              className="font-medium text-stone-950 underline"
              to="/auth/register"
            >
              {strings.registerAction}
            </Link>
          </p>
        ) : null
      }
    />
  );
}

export function AuthIndexRedirect() {
  return <Navigate replace to="/auth/sign-in" />;
}
