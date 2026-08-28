// 按模块聚合 api：import.meta.glob 自动收集 ./<模块>/*.js，
// 用法 api.cs408.quiz.getPaper(...)（沿用参考项目的聚合约定）。
const modules = {}
const contexts = [import.meta.glob('./cs408/*.js', { eager: true })]

contexts.forEach((context) => {
  for (const path in context) {
    const [, group, name] = path.match(/\.\/(.*)\/(.*)\.js$/)
    if (!modules[group]) modules[group] = {}
    modules[group][name] = context[path]
  }
})

export default modules
