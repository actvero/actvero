import { useState } from 'react'
import {
  AudioLines,
  Bot,
  Box,
  Braces,
  FileText,
  Fingerprint,
  GitBranch,
  Image,
  Layers3,
  Network,
  Plug,
  ShieldCheck,
  Sparkles,
  Users,
} from 'lucide-react'
import { motion, useReducedMotion } from 'motion/react'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { BrandMark } from '@/features/branding/brand'
import { PreviewFrame } from './effects'

const sections = [
  {
    id: 'models',
    name: '模型网关',
    icon: Network,
    eyebrow: 'MODEL GATEWAY',
    title: ['每一种模型，', '都能各尽所长。'],
    description:
      '连接不同供应商的模型，用统一入口承载对话、检索、图像与语音。团队专注使用，你掌握调用与用量。',
    sources: [
      { icon: Sparkles, label: '对话' },
      { icon: Braces, label: '向量 · 重排' },
      { icon: Image, label: '图像生成' },
      { icon: AudioLines, label: '语音' },
    ],
    hub: '统一模型入口',
    output: '团队应用与客户端',
    points: [
      ['灵活接入', '统一管理供应商渠道，按优先级与权重分配请求。'],
      ['按需开放', '按成员设置模型使用范围，共享统一的调用权限。'],
      ['用量可见', '集中查看调用记录与用量，管理团队的模型额度。'],
    ],
  },
  {
    id: 'experts',
    name: '专家',
    icon: Bot,
    eyebrow: 'TEAM EXPERTS',
    title: ['让专业经验，', '成为团队的能力。'],
    description:
      '把角色指令、业务工具和工作技能组合成专家。将成熟经验沉淀下来，帮助团队以一致的方法完成工作。',
    sources: [
      { icon: FileText, label: '角色指令' },
      { icon: Plug, label: '业务工具' },
      { icon: Box, label: '工作技能' },
      { icon: Layers3, label: '能力依赖' },
    ],
    hub: '专属工作专家',
    output: '交付给需要的团队成员',
    points: [
      ['围绕工作构建', '定义角色与工作要求，为具体任务组合所需能力。'],
      ['持续维护版本', '管理专家版本和依赖，让团队的方法持续演进。'],
      ['有序交付团队', '明确使用范围，让成员获得适合自己的专家。'],
    ],
  },
  {
    id: 'mcp',
    name: 'MCP 工具',
    icon: Plug,
    eyebrow: 'CONNECTED TOOLS',
    title: ['连接业务系统，', '让 AI 付诸行动。'],
    description:
      '通过 MCP 接入已有服务，把工具、提示模板与业务资源带到 AI 身边。从理解需求，到调用真正的业务能力。',
    sources: [
      { icon: Plug, label: 'Tools' },
      { icon: FileText, label: 'Prompts' },
      { icon: Layers3, label: 'Resources' },
      { icon: Fingerprint, label: '连接凭据' },
    ],
    hub: '统一 MCP 接入',
    output: '专家与已适配客户端',
    points: [
      ['发现服务能力', '连接已有 MCP 服务，查看工具参数、提示与资源。'],
      ['管理访问边界', '按服务与成员配置使用范围，管理个人连接凭据。'],
      ['追踪调用过程', '在平台测试连接与工具，并查看调用记录。'],
    ],
  },
  {
    id: 'skills',
    name: 'Skills',
    icon: Box,
    eyebrow: 'REUSABLE KNOW-HOW',
    title: ['把好方法，', '交给每位成员。'],
    description:
      '把流程、规范和经验整理成标准技能包。让有价值的方法可预览、可维护、可分发，成为团队共同的工作积累。',
    sources: [
      { icon: FileText, label: '工作流程' },
      { icon: ShieldCheck, label: '交付规范' },
      { icon: Sparkles, label: '专业经验' },
      { icon: GitBranch, label: '版本积累' },
    ],
    hub: '标准技能包',
    output: '授权分发与客户端安装',
    points: [
      ['轻松整理上传', '上传 ZIP 或文件夹，预览技能内容与文件结构。'],
      ['维护与发布', '管理技能版本，让团队使用已发布的工作方法。'],
      ['按授权分发', '设定可用范围，将标准技能交付到已适配客户端。'],
    ],
  },
] as const

// A conceptual map of each capability, not an interactive console or customer data.
function CapabilityMap({ section }: { section: (typeof sections)[number] }) {
  return (
    <div
      aria-hidden
      className='relative mx-auto hidden w-full max-w-64 flex-col items-center justify-center lg:flex'
    >
      <div className='absolute inset-4 rounded-full bg-portal-glow/60 blur-3xl' />
      <div className='relative grid w-full grid-cols-2 gap-2'>
        {section.sources.map(({ icon: Icon, label }) => (
          <div
            key={label}
            className='flex items-center gap-2 rounded-lg border bg-background/80 px-3 py-3 text-xs text-muted-foreground'
          >
            <Icon className='size-3.5 shrink-0' />
            {label}
          </div>
        ))}
      </div>
      <div className='relative h-7 w-px bg-linear-to-b from-border to-portal-accent/60' />
      <div className='relative flex w-44 flex-col items-center gap-3 rounded-2xl border border-portal-accent/25 bg-background px-5 py-5 shadow-[0_8px_40px_-16px_var(--portal-shadow)]'>
        <BrandMark className='size-9' />
        <span className='text-sm font-medium'>{section.hub}</span>
      </div>
      <div className='relative h-7 w-px bg-linear-to-b from-portal-accent/60 to-border' />
      <div className='relative flex items-center gap-2 text-xs text-muted-foreground'>
        <Users className='size-4' />
        {section.output}
      </div>
    </div>
  )
}

export function ProductOverview() {
  const [active, setActive] = useState('models')
  const reduced = useReducedMotion()
  return (
    <PreviewFrame>
      <div className='flex items-center justify-between gap-3 border-b px-4 py-4 sm:px-6'>
        <div className='flex items-center gap-2'>
          <BrandMark className='size-4' />
          <span className='text-xs font-semibold tracking-wide'>ACTVERO</span>
          <span className='mx-1 h-3 w-px bg-border' />
          <span className='text-xs text-muted-foreground'>能力，一处连接</span>
        </div>
        <span className='hidden font-mono text-[10px] tracking-[0.16em] text-muted-foreground sm:block'>
          EXPLORE THE PLATFORM
        </span>
      </div>
      <Tabs
        value={active}
        onValueChange={setActive}
        orientation='vertical'
        className='gap-0'
      >
        <div className='grid grid-cols-[76px_minmax(0,1fr)] md:grid-cols-[200px_minmax(0,1fr)] lg:grid-cols-[216px_minmax(0,1fr)]'>
          <div className='flex flex-col border-r bg-muted/25 px-1.5 py-5 md:px-4 md:py-7'>
            <p className='mb-5 hidden px-4 text-xs text-muted-foreground md:block'>
              探索产品能力
            </p>
            <TabsList variant='navigation' aria-label='产品能力'>
              {sections.map(({ id, name, icon: Icon }) => (
                <TabsTrigger key={id} value={id}>
                  <Icon className='size-4' />
                  <span>{name}</span>
                </TabsTrigger>
              ))}
            </TabsList>
            <div className='mt-auto hidden items-center gap-2 px-4 pt-10 text-xs leading-6 text-muted-foreground md:flex'>
              <ShieldCheck className='size-4 shrink-0' />
              统一身份与访问授权
            </div>
          </div>
          {sections.map((section, index) => (
            <TabsContent
              key={section.id}
              value={section.id}
              className='min-w-0'
            >
              <motion.div
                initial={reduced ? false : { opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.25 }}
                className='flex h-full flex-col px-4 py-7 sm:px-7 lg:px-10 lg:py-9'
              >
                <div className='grid flex-1 gap-6 lg:grid-cols-[1.3fr_1fr] lg:gap-8'>
                  <div className='flex flex-col justify-center'>
                    <p className='mb-5 font-mono text-[10px] tracking-[0.13em] text-portal-accent md:text-xs'>
                      0{index + 1} / {section.eyebrow}
                    </p>
                    <h2 className='text-2xl leading-[1.4] font-semibold tracking-tight sm:text-3xl xl:text-4xl'>
                      {section.title[0]}
                      <br />
                      {section.title[1]}
                    </h2>
                    <p className='mt-5 max-w-md text-sm leading-7 text-muted-foreground'>
                      {section.description}
                    </p>
                  </div>
                  <CapabilityMap section={section} />
                </div>
                <div className='mt-8 grid gap-5 border-t pt-6 md:grid-cols-3 md:gap-6 lg:mt-9'>
                  {section.points.map(([title, description], point) => (
                    <div key={title}>
                      <p className='flex items-center gap-2 text-sm font-medium'>
                        <span className='font-mono text-[10px] text-muted-foreground'>
                          0{point + 1}
                        </span>
                        {title}
                      </p>
                      <p className='mt-2 text-xs leading-6 text-muted-foreground'>
                        {description}
                      </p>
                    </div>
                  ))}
                </div>
              </motion.div>
            </TabsContent>
          ))}
        </div>
      </Tabs>
    </PreviewFrame>
  )
}
