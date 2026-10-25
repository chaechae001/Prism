import { describe, expect, it } from 'vitest';
import { authRedirectLocation } from './authRedirect';

describe('confirmation return URL', () => {
  it('strips auth tokens from the URL and returns to login without consuming them', () => {
    const url=authRedirectLocation('http://127.0.0.1:5186/#access_token=private-token&refresh_token=private-refresh&type=signup');
    expect(url).toBe('http://127.0.0.1:5186/?view=mypage&auth=return');
    expect(url).not.toContain('private');
  });
  it('shows a generic error and preserves ordinary navigation', () => {
    expect(authRedirectLocation('http://127.0.0.1:5186/#error=access_denied&error_description=expired')).toContain('auth=error');
    expect(authRedirectLocation('http://127.0.0.1:5186/?view=categories')).toBeNull();
  });
});
