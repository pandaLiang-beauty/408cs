import axios from 'axios'

// 单例 axios。后端返回原始 JSON（非 {code,msg,data} 包裹），
// 这里请求发 JSON、响应直接返回 data。不复制参考项目里强制 multipart/FormData 的写法。
// withCredentials：携带后端下发的 HttpOnly 会话 cookie，业务接口据此鉴权。
const instance = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api',
  timeout: 15000,
  withCredentials: true,
  headers: { 'Content-Type': 'application/json' },
})

instance.interceptors.response.use(
  (response) => response.data,
  (error) => {
    // 401：会话缺失或失效。不在此处硬跳转、也不抛全局异常导致崩溃，
    // 直接 reject，交给调用方或路由守卫决定是否重定向到登录页。
    return Promise.reject(error)
  },
)

export default instance
