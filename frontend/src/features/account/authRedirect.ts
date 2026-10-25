/** Confirmation links do not create a browser session: sign in through the server. */
export function authRedirectLocation(href: string): string | null {
  const url = new URL(href);
  const hash = new URLSearchParams(url.hash.replace(/^#/, ''));
  const hasToken = hash.has('access_token') || hash.has('refresh_token');
  const hasError = hash.has('error') || hash.has('error_code');
  if (!hasToken && !hasError) return null;
  url.hash = '';
  url.search = '';
  url.searchParams.set('view', 'mypage');
  url.searchParams.set('auth', hasError ? 'error' : 'return');
  return url.href;
}
