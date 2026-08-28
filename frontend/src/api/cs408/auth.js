import axiosInstance from '../axiosInstance'

// 单用户登录鉴权接口。baseURL 已含 /api，会话靠 HttpOnly cookie 维持。
// 每个函数返回 Promise<后端 JSON>。
export const login = (password) => axiosInstance.post('/auth/login', { password })

export const logout = () => axiosInstance.post('/auth/logout')

export const me = () => axiosInstance.get('/auth/me')
