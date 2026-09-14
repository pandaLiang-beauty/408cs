export function questionSource(question) {
  if (question.source_label) return question.source_label
  if (question.source === 'exercise') return '经典练习'
  if (question.source === 'simulate') return `模拟卷 ${question.year}`
  return `${question.year} 年真题`
}
