// Reproducible, offline assets from the project's locked Lucide dependency.
import { createElement } from 'react'
import * as icons from 'lucide-react'
import { readFile, writeFile, mkdir, copyFile, readdir } from 'node:fs/promises'
import { renderToStaticMarkup } from 'react-dom/server'

const groups = {
  常用: [
    ['Sparkles', '智能'],
    ['Bot', '助手'],
    ['Search', '搜索'],
    ['Globe', '网页'],
    ['Lightbulb', '创意'],
    ['Puzzle', '技能'],
    ['Star', '星标'],
    ['Heart', '喜爱'],
    ['Bookmark', '书签'],
    ['Zap', '闪电'],
    ['Rocket', '启动'],
    ['Target', '目标'],
    ['Compass', '探索'],
    ['House', '主页'],
    ['Settings', '设置'],
    ['LayoutGrid', '应用'],
  ],
  文档与办公: [
    ['FileText', '文档'],
    ['NotebookPen', '笔记'],
    ['Presentation', '演示'],
    ['Sheet', '表格'],
    ['CalendarDays', '日程'],
    ['ClipboardList', '任务'],
    ['Languages', '翻译'],
    ['BookOpen', '知识'],
    ['Folder', '文件夹'],
    ['Files', '文件'],
    ['FileSearch', '文档搜索'],
    ['FileCheck', '文档检查'],
    ['FileSpreadsheet', '电子表格'],
    ['ClipboardCheck', '待办'],
    ['Archive', '归档'],
    ['GraduationCap', '学习'],
  ],
  开发与工具: [
    ['CodeXml', '代码'],
    ['Terminal', '终端'],
    ['Bug', '调试'],
    ['Database', '数据库'],
    ['GitBranch', '版本管理'],
    ['Braces', '接口'],
    ['Workflow', '工作流'],
    ['Wrench', '工具'],
    ['Cpu', '计算'],
    ['Server', '服务器'],
    ['Plug', '连接'],
    ['Blocks', '模块'],
    ['Binary', '二进制'],
    ['GitPullRequest', '代码审查'],
    ['SquareCode', '开发'],
    ['Cog', '自动化'],
  ],
  图表与财务: [
    ['ChartNoAxesCombined', '分析'],
    ['ChartColumn', '柱状图'],
    ['ChartLine', '折线图'],
    ['ChartPie', '饼图'],
    ['Activity', '监测'],
    ['TrendingUp', '趋势'],
    ['Calculator', '计算器'],
    ['Percent', '百分比'],
    ['Gauge', '指标'],
    ['Wallet', '钱包'],
    ['CreditCard', '支付'],
    ['Banknote', '现金'],
    ['Landmark', '银行'],
    ['Receipt', '票据'],
    ['ShoppingCart', '购物'],
    ['CircleDollarSign', '金额'],
  ],
  设计与多媒体: [
    ['Palette', '设计'],
    ['Image', '图片'],
    ['PenTool', '写作'],
    ['Video', '视频'],
    ['Music', '音频'],
    ['Camera', '摄影'],
    ['Brush', '画笔'],
    ['Pencil', '绘制'],
    ['Shapes', '形状'],
    ['Layers', '图层'],
    ['LayoutTemplate', '布局'],
    ['Crop', '裁剪'],
    ['ImagePlus', '添加图片'],
    ['Film', '影片'],
    ['Mic', '录音'],
    ['Headphones', '聆听'],
  ],
  沟通与安全: [
    ['Mail', '邮件'],
    ['Megaphone', '营销'],
    ['MessageCircle', '聊天'],
    ['MessageSquare', '消息'],
    ['MessagesSquare', '讨论'],
    ['Send', '发送'],
    ['Users', '团队'],
    ['UserRound', '用户'],
    ['Contact', '联系人'],
    ['Bell', '通知'],
    ['Phone', '电话'],
    ['Share2', '分享'],
    ['Link', '链接'],
    ['ShieldCheck', '安全'],
    ['Lock', '权限'],
    ['KeyRound', '密钥'],
  ],
}
// Expand from canonical modules in the locked package, keeping all saved keys.
// Categories are deliberately bounded so near-identical variants don't dominate.
const expansions = {
  常用: /^(sparkles|bot|search|globe|lightbulb|puzzle|star|heart|bookmark|zap|rocket|target|compass|house|settings|layout-grid|award|badge|flag|flame|gem|gift|crown|trophy|smile|thumbs)/,
  文档与办公:
    /^(file|folder|book|notebook|clipboard|archive|sticky-note|library|list|text|graduation)/,
  开发与工具:
    /^(code|terminal|bug|database|git|braces|workflow|wrench|cpu|server|plug|blocks|binary|square-code|cog|package|webhook|regex|brackets|variable|hash|component|scan|hammer)/,
  图表与财务:
    /^(chart|activity|trending|calculator|percent|gauge|wallet|credit-card|banknote|landmark|receipt|shopping|circle-dollar|coins|currency|dollar|euro|pound|bitcoin|hand-coins|badge-dollar)/,
  设计与多媒体:
    /^(palette|image|pen|video|music|camera|brush|shapes|layers|layout-template|crop|film|mic|headphones|audio|clapperboard|paint|wand|spline|drafting)/,
  沟通与安全:
    /^(mail|megaphone|message|send|users|user|contact|bell|phone|share|link|shield|lock|key|fingerprint|scan-face)/,
  布局与组件:
    /^(align|layout|panel|columns|rows|grid|table|square|rectangle|circle|separator|between|combine|ungroup)/,
  方向与操作:
    /^(arrow|chevron|chevrons|corner|move|navigation|undo|redo|rotate|refresh|expand|shrink|fullscreen|zoom)/,
  设备与网络:
    /^(monitor|laptop|smartphone|tablet|watch|keyboard|mouse|printer|hard-drive|usb|ethernet|wifi|bluetooth|router|network|satellite|signal|cast|antenna|cable|battery)/,
  时间与天气:
    /^(calendar|clock|alarm|timer|hourglass|history|sun|moon|cloud|rainbow|snowflake|wind|thermometer|tornado|eclipse|haze|umbrella)/,
  地点与出行:
    /^(map|pin|earth|plane|train|tram|bus|car|bike|ship|sailboat|truck|route|footprints|luggage|tent|mountain|hotel|building|store|factory|church)/,
  生活与自然:
    /^(apple|banana|cherry|citrus|grape|carrot|salad|cooking|coffee|cup|utensils|beef|fish|egg|milk|pizza|sandwich|cake|ice-cream|cookie|candy|wine|beer|flower|leaf|tree|sprout|clover|feather|bird|cat|dog|rabbit|paw|bug|squirrel|turtle|snail|shell|wheat|vegan|glass|cup-soda)/,
}
const iconDirectory = new URL(
  '../node_modules/lucide-react/dist/esm/icons/',
  import.meta.url
)
const modules = await Promise.all(
  (await readdir(iconDirectory))
    .filter((file) => file.endsWith('.js'))
    .sort()
    .map(async (file) => {
      const source = await readFile(new URL(file, iconDirectory), 'utf8')
      const match = source.match(/const (\w+) = createLucideIcon\("([^"]+)"/)
      return match ? { name: match[1], slug: match[2] } : null
    })
)
const used = new Set(
  Object.values(groups)
    .flat()
    .map(([name]) => name)
)
for (const [category, pattern] of Object.entries(expansions)) {
  const entries = groups[category] ?? (groups[category] = [])
  const limit = category === '常用' ? 32 : 48
  for (const icon of modules) {
    if (entries.length >= limit) break
    if (
      !icon ||
      used.has(icon.name) ||
      !pattern.test(icon.slug) ||
      icon.slug.endsWith('-off')
    )
      continue
    used.add(icon.name)
    entries.push([icon.name, icon.slug.replaceAll('-', ' ')])
  }
}

const items = Object.entries(groups).flatMap(([category, entries]) =>
  entries.map(([name, label]) => {
    if (!icons[name]) throw new Error(`Unknown Lucide icon: ${name}`)
    const glyph = renderToStaticMarkup(
      createElement(icons[name], { size: 24, color: 'black', strokeWidth: 1.7 })
    )
    // An opaque monochrome artboard keeps exported images readable on any client theme.
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 40 40"><rect width="40" height="40" fill="white"/><g transform="translate(8 8)">${glyph}</g></svg>`
    return {
      key: `lucide:${name.replace(/([a-z0-9])([A-Z])/g, '$1-$2').toLowerCase()}`,
      label,
      category,
      image: 'data:image/svg+xml;base64,' + Buffer.from(svg).toString('base64'),
    }
  })
)
const dest = new URL(
  '../../backend/app/modules/skills/assets/',
  import.meta.url
)
await mkdir(dest, { recursive: true })
const pkg = JSON.parse(
  await readFile(
    new URL('../node_modules/lucide-react/package.json', import.meta.url)
  )
)
await writeFile(
  new URL('icons.json', dest),
  JSON.stringify({ source: `lucide-react ${pkg.version}`, items }, null, 2) +
    '\n'
)
await copyFile(
  new URL('../node_modules/lucide-react/LICENSE', import.meta.url),
  new URL('LUCIDE-LICENSE', dest)
)

// Native glyphs keep the compact picker theme-aware, without bundling the full library.
const names = Object.values(groups)
  .flat()
  .map(([name]) => name)
if (new Set(items.map((item) => item.key)).size !== items.length)
  throw new Error('Duplicate icon key')
await writeFile(
  new URL('../src/lib/resource-icon-glyphs.ts', import.meta.url),
  '// Generated by scripts/build-skill-icons.mjs; do not edit by hand.\n' +
    `import {\n${names.map((name) => `  ${name},`).join('\n')}\n  type LucideIcon,\n} from 'lucide-react'\n\n` +
    'export const resourceIconGlyphs: Record<string, LucideIcon> = {\n' +
    items.map((item, index) => `  '${item.key}': ${names[index]},`).join('\n') +
    '\n}\n'
)
