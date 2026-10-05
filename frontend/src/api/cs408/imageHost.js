import request from '@/api/axiosInstance'

export function getHostedImages(beforeId) {
  return request.get('/image-host', { params: beforeId ? { before_id: beforeId } : {} })
}

export function uploadHostedImage(image) {
  return request.post('/image-host', image, { timeout: 120000 })
}
