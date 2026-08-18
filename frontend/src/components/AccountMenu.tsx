import React, { useEffect, useRef, useState } from "react";
import { useAuthStore } from "../store/authStore";
import { getAvatarColor, getInitials } from "../lib/avatar";

interface AccountMenuProps {
  className?: string;
}

export const AccountMenu: React.FC<AccountMenuProps> = ({ className = "" }) => {
  const { user, fetchMe, login, register, logout } = useAuthStore();
  const [isOpen, setIsOpen] = useState(false);
  const [activeTab, setActiveTab] = useState<"register" | "login">("register");

  // Form fields
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    fetchMe();
  }, [fetchMe]);

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    }
    if (isOpen) {
      document.addEventListener("mousedown", handleClickOutside);
    }
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, [isOpen]);

  const isGuest = !user || user.isAnonymous;
  const currentUsername = user?.username || user?.displayName || "Guest";
  const avatarBg = getAvatarColor(isGuest, user?.nameColor);
  const initials = getInitials(currentUsername);

  async function handleRegister(e: React.FormEvent) {
    e.preventDefault();
    setFormError(null);
    if (!username.trim() || !password) {
      setFormError("Username and password are required.");
      return;
    }
    setIsSubmitting(true);
    const res = await register(username.trim(), password);
    setIsSubmitting(false);
    if (res.ok) {
      setUsername("");
      setPassword("");
      setIsOpen(false);
    } else {
      setFormError(res.error || "Registration failed");
    }
  }

  async function handleLogin(e: React.FormEvent) {
    e.preventDefault();
    setFormError(null);
    if (!username.trim() || !password) {
      setFormError("Username and password are required.");
      return;
    }
    setIsSubmitting(true);
    const res = await login(username.trim(), password);
    setIsSubmitting(false);
    if (res.ok) {
      setUsername("");
      setPassword("");
      setIsOpen(false);
    } else {
      setFormError(res.error || "Login failed");
    }
  }

  async function handleLogout() {
    setIsSubmitting(true);
    await logout();
    setIsSubmitting(false);
    setIsOpen(false);
  }

  return (
    <div className={`account-menu-container ${className}`} ref={menuRef}>
      <button
        type="button"
        id="account-menu-button"
        className="account-menu-btn"
        onClick={() => {
          setIsOpen(!isOpen);
          setFormError(null);
        }}
        aria-haspopup="dialog"
        aria-expanded={isOpen}
      >
        <div
          className="account-avatar"
          style={{ backgroundColor: avatarBg }}
        >
          {initials}
        </div>
        <span className={`account-name${isGuest ? " is-guest" : ""}`}>
          {currentUsername}
        </span>
        {isGuest && (
          <span className="account-guest-badge">
            Guest
          </span>
        )}
      </button>

      {isOpen && (
        <div
          id="account-dialog"
          className="account-dialog"
          role="dialog"
          aria-label="Account Settings"
        >
          {isGuest ? (
            <div>
              <div className="account-tabs">
                <button
                  type="button"
                  className={`account-tab-btn${activeTab === "register" ? " active" : ""}`}
                  onClick={() => {
                    setActiveTab("register");
                    setFormError(null);
                  }}
                >
                  Create Account
                </button>
                <button
                  type="button"
                  className={`account-tab-btn${activeTab === "login" ? " active" : ""}`}
                  onClick={() => {
                    setActiveTab("login");
                    setFormError(null);
                  }}
                >
                  Sign In
                </button>
              </div>

              {formError && (
                <div className="account-error-banner" role="alert">
                  {formError}
                </div>
              )}

              {activeTab === "register" ? (
                <form key="register-form" onSubmit={handleRegister} className="account-form">
                  <div className="account-form-field">
                    <label htmlFor="reg-username" className="account-form-label">
                      Username
                    </label>
                    <input
                      key="reg-username"
                      id="reg-username"
                      name="username"
                      type="text"
                      className="account-form-input"
                      value={username}
                      onChange={(e) => setUsername(e.target.value)}
                      placeholder="e.g. speedy_artist"
                      autoComplete="username"
                      required
                    />
                  </div>

                  <div className="account-form-field">
                    <label htmlFor="reg-password" className="account-form-label">
                      Password (min 6 chars)
                    </label>
                    <input
                      key="reg-password"
                      id="reg-password"
                      name="password"
                      type="password"
                      className="account-form-input"
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      autoComplete="new-password"
                      required
                      minLength={6}
                    />
                  </div>

                  <button
                    type="submit"
                    className="account-submit-btn"
                    disabled={isSubmitting}
                  >
                    {isSubmitting ? "Creating Account..." : "Create Account"}
                  </button>
                </form>
              ) : (
                <form key="login-form" onSubmit={handleLogin} className="account-form">
                  <div className="account-form-field">
                    <label htmlFor="login-username" className="account-form-label">
                      Username
                    </label>
                    <input
                      key="login-username"
                      id="login-username"
                      name="username"
                      type="text"
                      className="account-form-input"
                      value={username}
                      onChange={(e) => setUsername(e.target.value)}
                      autoComplete="username"
                      required
                    />
                  </div>

                  <div className="account-form-field">
                    <label htmlFor="login-password" className="account-form-label">
                      Password
                    </label>
                    <input
                      key="login-password"
                      id="login-password"
                      name="password"
                      type="password"
                      className="account-form-input"
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      autoComplete="current-password"
                      required
                    />
                  </div>

                  <button
                    type="submit"
                    className="account-submit-btn"
                    disabled={isSubmitting}
                  >
                    {isSubmitting ? "Signing In..." : "Sign In"}
                  </button>
                </form>
              )}
            </div>
          ) : (
            <div>
              <div className="account-profile-header">
                <div
                  className="account-profile-avatar"
                  style={{ backgroundColor: avatarBg }}
                >
                  {initials}
                </div>
                <div>
                  <div className="account-profile-name">{user.username || user.displayName}</div>
                </div>
              </div>

              {user.stats && (
                <div className="account-stats-grid">
                  <div>
                    <div className="account-stat-label">Games</div>
                    <div className="account-stat-value">{user.stats.gamesPlayed}</div>
                  </div>
                  <div>
                    <div className="account-stat-label">Wins</div>
                    <div className="account-stat-value">{user.stats.gamesWon}</div>
                  </div>
                  <div>
                    <div className="account-stat-label">Win Rate</div>
                    <div className="account-stat-value">
                      {(user.stats.winRate * 100).toFixed(0)}%
                    </div>
                  </div>
                  <div>
                    <div className="account-stat-label">Total Score</div>
                    <div className="account-stat-value">{user.stats.totalScore}</div>
                  </div>
                </div>
              )}

              <button
                type="button"
                className="account-secondary-btn"
                onClick={handleLogout}
                disabled={isSubmitting}
              >
                Sign Out
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
