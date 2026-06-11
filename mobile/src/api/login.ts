import type { IDoubleTokenRes, IUserInfoRes } from './types/login'
import { http } from '@/http/http'

/**
 * 登录表单
 */
export interface ILoginForm {
  username: string
  password: string
}

/** BWS 后端 /auth/token 与 /auth/refresh 的响应 (snake_case) */
interface IBwsTokenRes {
  token_type: string
  access_token: string
  expires_in: number
  refresh_token: string
  refresh_expires_in: number
  user: IBwsUser
}

/** BWS 后端 /auth/me 的用户结构 */
interface IBwsUser {
  id: number
  username: string
  display_name: string | null
  role: string
  agency_id: number | null
  agency_name: string | null
  email: string | null
  phone: string | null
  [key: string]: any
}

/** BWS snake_case → 模板 IDoubleTokenRes camelCase */
function mapTokenRes(res: IBwsTokenRes): IDoubleTokenRes {
  return {
    accessToken: res.access_token,
    refreshToken: res.refresh_token,
    accessExpiresIn: res.expires_in,
    refreshExpiresIn: res.refresh_expires_in,
  }
}

function mapUser(u: IBwsUser): IUserInfoRes {
  return {
    userId: u.id,
    username: u.username,
    nickname: u.display_name || u.username,
    role: u.role,
    agencyId: u.agency_id,
    agencyName: u.agency_name,
  }
}

/**
 * 用户登录 — BWS POST /auth/token (双 token: access 30min + refresh 14d)
 */
export async function login(loginForm: ILoginForm) {
  const res = await http.post<IBwsTokenRes>('/auth/token', loginForm)
  return mapTokenRes(res)
}

/**
 * 旋转刷新 token — BWS POST /auth/refresh (旧 refresh 作废, 发新对)
 */
export async function refreshToken(refreshToken: string) {
  const res = await http.post<IBwsTokenRes>('/auth/refresh', { refresh_token: refreshToken })
  return mapTokenRes(res)
}

/**
 * 获取当前用户信息 — BWS GET /auth/me
 */
export async function getUserInfo() {
  const res = await http.get<IBwsUser>('/auth/me')
  return mapUser(res)
}

/**
 * 退出登录 — BWS POST /auth/logout (带 refresh_token 则服务端一并撤销)
 */
export function logout(refreshTokenValue?: string) {
  return http.post<{ ok: boolean }>(
    '/auth/logout',
    refreshTokenValue ? { refresh_token: refreshTokenValue } : {},
  )
}
