import { apiOrigin } from './client';
import type { components } from './workspace-schema';
export type AccountUser = components['schemas']['PublicUser'];
export type AccountSession = components['schemas']['Session'];
export type AccountSignup = components['schemas']['SignupResult'];

let refreshing: Promise<Response> | null = null;
export async function refreshAccountSession(): Promise<boolean> {
  refreshing ??= fetch(`${apiOrigin}/api/account/refresh`, { method: 'POST', credentials: 'include' }).finally(() => { refreshing = null; });
  return (await refreshing).ok;
}
export async function accountRequest<T>(path: string, init: RequestInit = {}, retry = true): Promise<T> {
  let response: Response;
  try { response = await fetch(`${apiOrigin}/api/account${path}`, { ...init, credentials: 'include', headers: { 'Content-Type': 'application/json', ...init.headers } }); }
  catch { throw new Error('계정 서버에 연결하지 못했습니다. 서버 실행 상태를 확인한 뒤 새로고침해주세요.'); }
  if (response.status === 401 && retry && !['/login', '/signup', '/refresh', '/logout'].includes(path)) {
    const refreshed=await refreshAccountSession();
    if (refreshed || path==='/session') return accountRequest<T>(path, init, false);
  }
  const value = await response.json();
  if (!response.ok) throw new Error(value.error?.message || value.detail || '계정 정보를 저장하지 못했습니다.');
  return value as T;
}
