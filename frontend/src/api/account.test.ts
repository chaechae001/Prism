import { afterEach, describe, expect, it, vi } from 'vitest';
import { accountRequest } from './account';

afterEach(() => vi.unstubAllGlobals());
describe('cookie authenticated account boundary', () => {
  it('sends cookies and retries an expired session once', async () => {
    const fetch = vi.fn().mockResolvedValueOnce(new Response('{}', { status: 401 }))
      .mockResolvedValueOnce(new Response('{}')).mockResolvedValueOnce(new Response('{"bookmarks":["news"]}'));
    vi.stubGlobal('fetch', fetch);
    expect(await accountRequest('/workspace')).toEqual({ bookmarks: ['news'] });
    expect(fetch).toHaveBeenCalledTimes(3);
    expect(fetch.mock.calls[0][1].credentials).toBe('include');
    expect(fetch.mock.calls[1][0]).toContain('/api/account/refresh');
  });
  it('never retries rejected login credentials or returns a fake user', async () => {
    const fetch = vi.fn().mockResolvedValue(new Response('{"detail":"다시 확인해주세요"}', { status: 401 }));
    vi.stubGlobal('fetch', fetch);
    await expect(accountRequest('/login', { method: 'POST', body: '{}' })).rejects.toThrow('다시 확인해주세요');
    expect(fetch).toHaveBeenCalledTimes(1);
  });
});


it('allows a new login after an invalid refresh cookie is cleared',async()=>{
 const fetch=vi.fn().mockResolvedValueOnce(new Response('{}',{status:401})).mockResolvedValueOnce(new Response('{}',{status:401})).mockResolvedValueOnce(new Response('{"enabled":true,"configured":true,"user":null}'));
 vi.stubGlobal('fetch',fetch);expect(await accountRequest('/session')).toEqual({enabled:true,configured:true,user:null});expect(fetch).toHaveBeenCalledTimes(3);
});
