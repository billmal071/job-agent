"""Auth selectors for each job platform.

Centralises login form selectors, logged-in checks, and auth URLs so that
browser/auth.py doesn't contain inline selector strings.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AuthSelectors:
    """Selectors for a platform's login flow."""

    login_url: str
    username_field: str
    password_field: str
    submit_button: str
    logged_in_check: str
    # Optional — platforms with extra auth steps
    google_auth_button: str = ""
    homepage_url: str = ""
    homepage_logged_in_check: str = ""


LINKEDIN_AUTH = AuthSelectors(
    login_url="https://www.linkedin.com/login",
    username_field="#username",
    password_field="#password",
    submit_button='[type="submit"]',
    logged_in_check=(
        ".global-nav__me, "
        '[data-control-name="identity_welcome_message"], '
        ".feed-identity-module, "
        'nav[aria-label="Primary"]'
    ),
    homepage_url="https://www.linkedin.com/feed/",
)

INDEED_AUTH = AuthSelectors(
    login_url="https://secure.indeed.com/auth",
    username_field='[name="__email"]',
    password_field='[name="__password"]',
    submit_button='[data-tn-element="auth-page-sign-in-submit"]',
    logged_in_check='[data-gnav-element-name="AccountMenu"]',
    google_auth_button=(
        'button:has-text("Google"), '
        '[data-tn-element="auth-page-google-button"], '
        'a[href*="accounts.google.com"]'
    ),
    homepage_url="https://www.indeed.com",
    homepage_logged_in_check=(
        '[data-gnav-element-name="AccountMenu"], '
        'a[href*="/account"], '
        '[data-testid="gnav-header-account"], '
        "#AccountMenu"
    ),
)

GLASSDOOR_AUTH = AuthSelectors(
    login_url="https://www.glassdoor.com/profile/login_input.htm",
    username_field='[name="username"], [name="email"], #userEmail',
    password_field='[name="password"]',
    submit_button='[type="submit"]',
    logged_in_check='[data-test="header-profile"]',
    google_auth_button=(
        'button:has-text("Google"), '
        '[data-provider="google"], '
        'a[href*="accounts.google.com"]'
    ),
    homepage_url="https://www.glassdoor.com",
    homepage_logged_in_check=(
        '[data-test="profile-button"], '
        'a[href*="/member/profile"], '
        "#ProfileButton, "
        '[data-test="header-profile"]'
    ),
)

ZIPRECRUITER_AUTH = AuthSelectors(
    login_url="https://www.ziprecruiter.com/authn/login",
    username_field='[name="email"], #email',
    password_field='[name="password"], #password',
    submit_button='[type="submit"]',
    logged_in_check='.navbar-user-menu, [data-testid="user-menu"]',
)

DICE_AUTH = AuthSelectors(
    login_url="https://www.dice.com/dashboard/login",
    username_field='[name="email"], #email',
    password_field='[name="password"], #password',
    submit_button='[type="submit"], button:has-text("Sign In")',
    logged_in_check='[data-testid="header-user-menu"], .user-menu',
)

WELLFOUND_AUTH = AuthSelectors(
    login_url="https://wellfound.com/login",
    username_field='[name="email"], #user_email',
    password_field='[name="password"], #user_password',
    submit_button='[type="submit"], button:has-text("Log in")',
    logged_in_check='[data-test="UserMenu"], .styles_component__NavBarAvatar',
)

# Map Platform enum values to auth selectors
AUTH_SELECTORS = {
    "linkedin": LINKEDIN_AUTH,
    "indeed": INDEED_AUTH,
    "glassdoor": GLASSDOOR_AUTH,
    "ziprecruiter": ZIPRECRUITER_AUTH,
    "dice": DICE_AUTH,
    "wellfound": WELLFOUND_AUTH,
}
