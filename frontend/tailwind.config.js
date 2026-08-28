/** cs408 前端主题：考试试卷风（暖灰纸面 + 朱红主色）。修正了参考项目里 primary 未定义的问题。 */
export default {
  content: ['./index.html', './src/**/*.{vue,js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        paper: '#fdfdfb',
        ink: '#1c1a17',
        muted: '#6d675d',
        line: '#ddd7cc',
        bgwarm: '#e7e4dd',
        primary: { DEFAULT: '#b04a2f', soft: '#f3e4de' },
        ok: { DEFAULT: '#2f7d47', soft: '#e3f1e6' },
        bad: { DEFAULT: '#c23b3b', soft: '#f7e3e2' },
        amber: { DEFAULT: '#b8791d', soft: '#f6ecd7' },
      },
      fontFamily: {
        song: ['"Times New Roman"', 'Times', '"SimSun"', '"Songti SC"', '"STSong"', '"宋体"', 'serif'],
      },
    },
  },
  plugins: [],
}
