import {
  ArrowRight,
  AudioLines,
  Bot,
  Box,
  ChevronDown,
  Code2,
  Download,
  Image,
  Network,
  Plug,
  ShieldCheck,
  Sparkles,
  Monitor,
  Users,
} from 'lucide-react'
import { MotionConfig } from 'motion/react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible'
import { useBranding } from '@/features/branding/data'
import { Reveal, SectionHeading, SpotlightCard } from './effects'
import { ProductOverview } from './product-overview'
import { PublicLayout } from './public-layout'

const capabilities = [
  {
    number: '01',
    icon: Network,
    title: '模型网关',
    subtitle: '让每种模型，各尽所长。',
    description:
      '连接不同供应商，统一模型入口、渠道路由与用量。对话、检索、图像和语音，在一处管理。',
    tags: ['多供应商接入', '统一 API', '额度与用量'],
  },
  {
    number: '02',
    icon: Bot,
    title: '专家',
    subtitle: '把经验，变成团队的能力。',
    description:
      '组合指令、工具与技能，围绕真实工作构建专家。维护版本和依赖，把成熟方法交付给团队。',
    tags: ['能力组合', '版本管理', '按需授权'],
  },
  {
    number: '03',
    icon: Plug,
    title: 'MCP 工具',
    subtitle: '连接系统，也连接行动。',
    description:
      '接入已有 MCP 服务，发现工具、提示与业务资源。统一管理连接，让能力在授权范围内被使用。',
    tags: ['Tools', 'Prompts', 'Resources'],
  },
  {
    number: '04',
    icon: Box,
    title: 'Skills',
    subtitle: '好方法，值得反复使用。',
    description:
      '上传、预览和发布标准技能包。将团队的工作方法积累下来，交给需要它的人。',
    tags: ['标准技能包', '版本发布', '授权分发'],
  },
]
const faqs = [
  [
    'Actvero 与模型供应商是什么关系？',
    'Actvero 是管理和交付 AI 能力的平台。你接入自己的供应商渠道与凭据，平台负责模型入口、访问权限、额度和用量管理。上游服务仍由相应供应商提供。',
  ],
  [
    '支持哪些 AI 能力？',
    '当前模型网关覆盖对话、向量、重排、文生图、语音合成与语音转写。具体接口、模型和参数取决于已接入的渠道；图片和语音的首批支持集中在 OpenAI 兼容渠道。视频和实时语音暂未提供。',
  ],
  [
    '团队的能力和用量怎么管理？',
    '管理员统一接入能力，按成员设置访问范围，并为模型调用配置额度。成员在授权范围内使用，平台保留调用记录与用量，方便团队持续管理。',
  ],
  [
    '团队成员怎么使用？',
    '管理员接入能力并设置使用范围。成员使用个人访问密钥或已适配客户端，权限跟随本人当前授权。桌面客户端通过下载页发布，Windows 和 macOS 安装包以页面提供的版本为准。',
  ],
]

export function PortalPage() {
  const brand = useBranding()
  return (
    <MotionConfig reducedMotion='user'>
      <PublicLayout home>
        <section
          className='relative isolate overflow-hidden pt-16 pb-10 lg:pt-14'
          aria-labelledby='hero-title'
        >
          <div
            aria-hidden
            className='pointer-events-none absolute inset-x-0 top-32 -z-10 mx-auto h-96 max-w-4xl rounded-full bg-portal-glow/50 blur-[100px]'
          />
          <div className='relative mx-auto max-w-4xl px-6 text-center'>
            <Reveal>
              <p className='mb-4 inline-flex items-center gap-2 rounded-full border bg-background/80 px-4 py-2 text-xs tracking-widest text-muted-foreground backdrop-blur-sm'>
                <span className='size-1.5 rounded-full bg-portal-accent' />
                企业 AI 能力平台
              </p>
            </Reveal>
            <Reveal delay={0.08}>
              <h1
                id='hero-title'
                className='text-[clamp(2.9rem,7.2vw,5.6rem)] leading-[1.16] font-semibold tracking-[-0.065em]'
              >
                让企业 AI，
                <br />
                <span className='bg-linear-to-b from-foreground to-muted-foreground bg-clip-text text-transparent'>
                  真正用起来。
                </span>
              </h1>
            </Reveal>
            <Reveal delay={0.16}>
              <p className='mx-auto mt-7 max-w-xl text-base leading-8 text-muted-foreground sm:text-lg'>
                统一管理模型、工具与技能，
                <br className='sm:hidden' />把 AI 能力交付给团队。
              </p>
              <div className='mt-9 flex flex-wrap items-center justify-center gap-3'>
                <Button asChild size='hero'>
                  <a href='/console'>登录</a>
                </Button>
                <Button asChild size='hero' variant='outline'>
                  <a href='/download'>客户端下载</a>
                </Button>
              </div>
            </Reveal>
          </div>
          <div
            id='product'
            className='relative mx-auto mt-16 max-w-6xl scroll-mt-28 px-4 sm:px-6 lg:px-8'
          >
            <ProductOverview />
          </div>
          <div
            className='mx-auto mt-10 flex max-w-4xl flex-wrap items-center justify-center gap-x-7 gap-y-4 px-6 text-sm text-muted-foreground'
            aria-label='支持的能力'
          >
            {[
              { icon: Sparkles, label: '对话' },
              { icon: Code2, label: '向量与重排' },
              { icon: Image, label: '图像生成' },
              { icon: AudioLines, label: '语音合成与转写' },
            ].map(({ icon: Icon, label }) => (
              <span key={label} className='flex items-center gap-2'>
                <Icon className='size-4' />
                {label}
              </span>
            ))}
          </div>
        </section>
        <section
          id='capabilities'
          className='mx-auto max-w-6xl scroll-mt-28 px-6 py-20 lg:px-8 lg:py-28'
          aria-labelledby='capabilities-title'
        >
          <Reveal>
            <div className='mb-10 flex flex-col justify-between gap-5 md:flex-row md:items-end'>
              <SectionHeading eyebrow='ONE WORKSPACE. EVERY CAPABILITY.'>
                <span id='capabilities-title'>
                  从能力接入，
                  <br className='sm:hidden' />
                  到团队使用。
                </span>
              </SectionHeading>
              <p className='max-w-sm text-sm leading-7 text-muted-foreground'>
                将分散的 AI 能力连接起来。
                <br />
                少一些配置负担，多一些真正的协作。
              </p>
            </div>
          </Reveal>
          <div className='grid gap-4 md:grid-cols-2'>
            {capabilities.map(
              (
                { number, icon: Icon, title, subtitle, description, tags },
                index
              ) => (
                <Reveal key={number} delay={(index % 2) * 0.08}>
                  <SpotlightCard className='h-full'>
                    <article className='flex h-full flex-col gap-6 p-7 sm:p-9'>
                      <div className='flex items-center justify-between'>
                        <span className='flex items-center gap-3'>
                          <span className='rounded-xl border bg-background p-3'>
                            <Icon className='size-5' />
                          </span>
                          <h3 className='font-semibold'>{title}</h3>
                        </span>
                        <span className='font-mono text-xs text-muted-foreground'>
                          {number} / 04
                        </span>
                      </div>
                      <div>
                        <p className='text-xl font-medium tracking-tight sm:text-2xl'>
                          {subtitle}
                        </p>
                        <p className='mt-4 max-w-md text-sm leading-7 text-muted-foreground'>
                          {description}
                        </p>
                      </div>
                      <div className='mt-auto flex flex-wrap gap-2'>
                        {tags.map((tag) => (
                          <Badge key={tag} variant='secondary'>
                            {tag}
                          </Badge>
                        ))}
                      </div>
                    </article>
                  </SpotlightCard>
                </Reveal>
              )
            )}
          </div>
        </section>
        <section
          className='border-y bg-muted/25'
          aria-labelledby='workflow-title'
        >
          <div className='mx-auto max-w-6xl px-6 py-20 lg:px-8 lg:py-24'>
            <Reveal>
              <SectionHeading eyebrow='FROM CONNECTION TO COLLABORATION.'>
                <span id='workflow-title'>接入一次，让团队用起来。</span>
              </SectionHeading>
            </Reveal>
            <div className='mt-12 grid gap-10 md:grid-cols-3'>
              {[
                {
                  icon: Plug,
                  title: '接入能力',
                  text: '配置模型渠道，连接 MCP 服务，上传团队所需的技能包。',
                },
                {
                  icon: ShieldCheck,
                  title: '设置边界',
                  text: '按成员配置访问范围，管理模型额度，明确谁可以使用什么。',
                },
                {
                  icon: Users,
                  title: '交付团队',
                  text: '通过统一 API 或已适配客户端使用能力，在平台查看用量与记录。',
                },
              ].map(({ icon: Icon, title, text }, i) => (
                <Reveal key={title} delay={i * 0.08}>
                  <div className='flex items-center gap-4'>
                    <div className='flex size-12 items-center justify-center rounded-full border bg-background'>
                      <Icon className='size-5' />
                    </div>
                    <span className='font-mono text-xs text-muted-foreground'>
                      0{i + 1}
                    </span>
                    {i < 2 && (
                      <div className='hidden h-px flex-1 bg-border md:block' />
                    )}
                  </div>
                  <h3 className='mt-6 text-lg font-semibold'>{title}</h3>
                  <p className='mt-3 max-w-xs text-sm leading-7 text-muted-foreground'>
                    {text}
                  </p>
                </Reveal>
              ))}
            </div>
          </div>
        </section>
        <section
          id='download'
          className='mx-auto max-w-6xl scroll-mt-24 px-6 py-20 lg:px-8 lg:py-28'
          aria-labelledby='download-title'
        >
          <Reveal>
            <div className='grid gap-12 lg:grid-cols-[.85fr_1.15fr] lg:gap-20'>
              <div>
                <SectionHeading
                  eyebrow='YOUR TEAM. YOUR WORKSPACE.'
                  description='从一个属于你的工作空间开始，连接团队所需的 AI 能力。'
                >
                  <span id='download-title'>
                    准备好，
                    <br />
                    开启团队新可能。
                  </span>
                </SectionHeading>
                <div className='mt-8 flex flex-wrap gap-3'>
                  <Button asChild size='hero'>
                    <a href='/console'>登录</a>
                  </Button>
                </div>
              </div>
              <div className='flex flex-col gap-4'>
                <SpotlightCard>
                  <div className='flex flex-col gap-5 p-7'>
                    <div className='flex items-start justify-between gap-4'>
                      <span className='rounded-xl bg-muted p-3'>
                        <Monitor className='size-6' />
                      </span>
                      <Badge variant='outline'>浏览器访问</Badge>
                    </div>
                    <div>
                      <h3 className='text-xl font-semibold'>
                        打开工作空间，即刻连接。
                      </h3>
                      <p className='mt-3 text-sm leading-7 text-muted-foreground'>
                        在一个控制台里，管理团队的模型、工具与技能。
                        <br />
                        从能力配置到用量查看，让协作井然有序。
                      </p>
                    </div>
                    <div>
                      <Button asChild variant='outline'>
                        <a href='/console'>
                          打开控制台
                          <ArrowRight />
                        </a>
                      </Button>
                    </div>
                  </div>
                </SpotlightCard>
                <div className='flex flex-wrap items-center justify-between gap-4 rounded-2xl border p-6'>
                  <div className='flex items-start gap-3'>
                    <Download className='mt-1 size-5 text-muted-foreground' />
                    <div>
                      <h3 className='font-medium'>桌面客户端</h3>
                      <p className='mt-1 text-sm text-muted-foreground'>
                        下载 Windows 或 macOS 客户端，在桌面上使用团队能力。
                      </p>
                    </div>
                  </div>
                  <Button asChild variant='outline'>
                    <a href='/download'>
                      查看客户端下载
                      <ArrowRight />
                    </a>
                  </Button>
                </div>
              </div>
            </div>
          </Reveal>
        </section>
        <section
          className='mx-auto max-w-6xl px-6 pb-24 lg:px-8'
          aria-labelledby='faq-title'
        >
          <div className='grid gap-8 border-t pt-16 lg:grid-cols-[.65fr_1fr] lg:gap-20'>
            <SectionHeading eyebrow='A FEW MORE THINGS.'>
              <span id='faq-title'>你可能还想知道。</span>
            </SectionHeading>
            <div>
              {faqs.map(([question, answer]) => (
                <Collapsible
                  key={question.split('Actvero').join(brand.name)}
                  className='border-b'
                >
                  <CollapsibleTrigger asChild>
                    <Button
                      variant='ghost'
                      size='faq'
                      className='w-full justify-between gap-4 text-start'
                    >
                      <span>{question.split('Actvero').join(brand.name)}</span>
                      <ChevronDown className='shrink-0' />
                    </Button>
                  </CollapsibleTrigger>
                  <CollapsibleContent>
                    <p className='px-2 pt-1 pb-6 text-sm leading-7 text-muted-foreground'>
                      {answer.split('Actvero').join(brand.name)}
                    </p>
                  </CollapsibleContent>
                </Collapsible>
              ))}
            </div>
          </div>
        </section>
      </PublicLayout>
    </MotionConfig>
  )
}
