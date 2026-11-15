import { useRef, useState } from 'react'
import { Button as GatewayButton } from '@newapi/components/ui/button'
import {
  Tabs as GatewayTabs,
  TabsList as GatewayTabsList,
  TabsTrigger as GatewayTabsTrigger,
  TabsContent as GatewayTabsContent,
} from '@newapi/components/ui/tabs'
import { BookOpen, Plus, RefreshCw } from 'lucide-react'
import { Alert, AlertTitle, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog'
import {
  Empty,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  EmptyContent,
} from '@/components/ui/empty'
import {
  Field,
  FieldGroup,
  FieldLabel,
  FieldError,
} from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import { PageBack, PageHeader } from '@/components/layout/page-header'
import { ListPagination } from '@/components/list-pagination'
import { ListSearch, ListToolbar } from '@/components/list-toolbar'
import { ResourceCard } from '@/components/resource-card'
import { ThemeSwitch } from '@/components/theme-switch'

const examples = Array.from({ length: 12 }, (_, index) => ({
  id: index,
  name:
    index === 0
      ? '产品与服务使用手册'
      : index === 1
        ? '这是用于检查多语言长名称截断的知识库 Knowledge Base Example'
        : `团队知识库 ${index + 1}`,
  description:
    index % 3 === 0
      ? '产品操作、常见问题及服务规范。'
      : index % 3 === 1
        ? '这段较长的描述用于检查资源卡片的两行截断，并确认描述、状态和元信息始终保持一致的阅读顺序。'
        : '',
}))

export function DesignSystemPage() {
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const [selected, setSelected] = useState<string | null>(null)
  const [name, setName] = useState('')
  const [submitted, setSubmitted] = useState(false)
  const [notice, setNotice] = useState('')
  const opener = useRef<HTMLElement | null>(null)
  const nameInput = useRef<HTMLInputElement | null>(null)
  const filtered = examples.filter((item) => item.name.includes(search))

  function openExample(title: string) {
    opener.current = document.activeElement as HTMLElement | null
    setName(title)
    setSubmitted(false)
    setSelected(title)
  }

  return (
    <main className='mx-auto flex min-h-svh max-w-6xl flex-col gap-8 p-4 md:p-8'>
      <PageHeader
        title='组件示例'
        titleAfter={<Badge variant='secondary'>合成数据</Badge>}
        action={<ThemeSwitch />}
      />
      <Tabs defaultValue='list'>
        <TabsList variant='line' aria-label='组件示例'>
          <TabsTrigger value='list'>资源列表</TabsTrigger>
          <TabsTrigger value='controls'>控件与状态</TabsTrigger>
        </TabsList>
        <TabsContent value='list' className='flex flex-col gap-6 pt-4'>
          <PageHeader
            title='知识库'
            action={
              <Button onClick={() => openExample('')}>
                <Plus data-icon='inline-start' />
                创建知识库
              </Button>
            }
          />
          <ListToolbar>
            <ListSearch
              aria-label='搜索知识库'
              placeholder='搜索知识库…'
              value={search}
              onChange={(event) => {
                setSearch(event.target.value)
                setPage(1)
              }}
            />
          </ListToolbar>
          <div className='min-h-80'>
            {filtered.length ? (
              <div className='grid grid-cols-[repeat(auto-fill,minmax(min(100%,15rem),1fr))] gap-3'>
                {filtered.slice((page - 1) * 6, page * 6).map((item) => (
                  <ResourceCard
                    key={item.id}
                    name={item.name}
                    description={item.description}
                    icon={<BookOpen />}
                    status={
                      item.id % 3 !== 2 && (
                        <Badge variant='success' dot>
                          可检索
                        </Badge>
                      )
                    }
                    metadata={`${item.id % 3 === 2 ? 0 : item.id + 1} 份文档`}
                    onOpen={() => openExample(item.name)}
                  />
                ))}
              </div>
            ) : (
              <Empty>
                <EmptyHeader>
                  <EmptyMedia variant='icon'>
                    <BookOpen />
                  </EmptyMedia>
                  <EmptyTitle>没有匹配的知识库</EmptyTitle>
                </EmptyHeader>
                <EmptyContent>
                  <Button
                    variant='outline'
                    onClick={() => {
                      setSearch('')
                      setPage(1)
                    }}
                  >
                    清除搜索
                  </Button>
                </EmptyContent>
              </Empty>
            )}
          </div>
          <ListPagination
            total={filtered.length}
            page={page}
            pageCount={Math.ceil(filtered.length / 6)}
            onPage={setPage}
            unit='个知识库'
          />
        </TabsContent>
        <TabsContent value='controls' className='flex flex-col gap-8 pt-4'>
          <section className='flex flex-col gap-4' aria-label='标题与返回'>
            <h2 className='text-lg font-semibold'>标题与返回</h2>
            <PageHeader
              title='较长的资源名称与多语言标识 LongResourceNameForResponsiveLayoutChecks'
              titleBefore={
                <PageBack
                  label='返回示例列表'
                  onClick={() => setNotice('已触发返回操作')}
                />
              }
              titleAfter={<Badge variant='secondary'>草稿</Badge>}
              action={
                <>
                  <Button
                    variant='outline'
                    onClick={() => setNotice('已保存示例草稿')}
                  >
                    保存草稿
                  </Button>
                  <Button onClick={() => setNotice('已发布示例')}>发布</Button>
                </>
              }
            />
          </section>
          <section className='flex flex-col gap-4' aria-label='按钮对照'>
            <h2 className='text-lg font-semibold'>按钮对照</h2>
            <div className='flex flex-wrap items-center gap-3'>
              <span className='w-24 text-sm text-muted-foreground'>宿主</span>
              <Button onClick={() => openExample('宿主按钮')}>主要操作</Button>
              <Button
                variant='outline'
                onClick={() => setNotice('已触发次要操作')}
              >
                次要操作
              </Button>
              <Button disabled>正在保存</Button>
            </div>
            <div className='flex flex-wrap items-center gap-3'>
              <span className='w-24 text-sm text-muted-foreground'>
                模型网关
              </span>
              <GatewayButton onClick={() => openExample('网关按钮')}>
                主要操作
              </GatewayButton>
              <GatewayButton
                variant='outline'
                onClick={() => setNotice('已触发次要操作')}
              >
                次要操作
              </GatewayButton>
              <GatewayButton disabled>正在保存</GatewayButton>
            </div>
          </section>
          <section className='flex flex-col gap-4' aria-label='网关标签'>
            <h2 className='text-lg font-semibold'>模型网关标签</h2>
            <GatewayTabs defaultValue='metadata'>
              <GatewayTabsList variant='line' aria-label='模型配置'>
                <GatewayTabsTrigger value='metadata'>
                  模型资料
                </GatewayTabsTrigger>
                <GatewayTabsTrigger value='price'>定价</GatewayTabsTrigger>
              </GatewayTabsList>
              <GatewayTabsContent value='metadata'>
                模型资料示例
              </GatewayTabsContent>
              <GatewayTabsContent value='price'>定价示例</GatewayTabsContent>
            </GatewayTabs>
          </section>
          <section className='flex flex-col gap-4' aria-label='表单与状态'>
            <h2 className='text-lg font-semibold'>表单与状态</h2>
            <FieldGroup className='max-w-lg'>
              <Field>
                <FieldLabel htmlFor='input-example'>名称</FieldLabel>
                <Input id='input-example' placeholder='输入名称' />
              </Field>
              <Field>
                <FieldLabel htmlFor='search-example'>搜索</FieldLabel>
                <ListSearch id='search-example' placeholder='输入搜索内容' />
              </Field>
              <Field>
                <FieldLabel htmlFor='description-example'>简介</FieldLabel>
                <Textarea id='description-example' placeholder='输入简介' />
              </Field>
              <Field data-disabled>
                <FieldLabel htmlFor='disabled-example'>不可编辑</FieldLabel>
                <Input id='disabled-example' disabled value='只读示例' />
              </Field>
              <Field data-invalid>
                <FieldLabel htmlFor='invalid-example'>知识库名称</FieldLabel>
                <Input
                  id='invalid-example'
                  aria-invalid
                  aria-describedby='invalid-message'
                  defaultValue=''
                />
                <FieldError id='invalid-message'>请输入知识库名称</FieldError>
              </Field>
            </FieldGroup>
            <div className='grid gap-4 md:grid-cols-2'>
              <Alert variant='destructive'>
                <AlertTitle>加载失败</AlertTitle>
                <AlertDescription>
                  暂时无法取得列表。
                  <Button
                    variant='outline'
                    onClick={() => setNotice('已触发示例重试')}
                  >
                    <RefreshCw data-icon='inline-start' />
                    重试
                  </Button>
                </AlertDescription>
              </Alert>
              <div
                role='status'
                aria-label='正在加载'
                className='flex flex-col gap-3 rounded-xl border p-4'
              >
                <Skeleton className='h-5 w-1/2' />
                <Skeleton className='h-4 w-full' />
                <Skeleton className='h-4 w-3/4' />
              </div>
            </div>
          </section>
          <ListPagination
            page={1}
            pageCount={1}
            onPage={() => {}}
            disabled
            label='加载中的分页'
          />
        </TabsContent>
      </Tabs>
      <p className='text-sm text-muted-foreground' role='status'>
        {notice}
      </p>
      <Dialog
        open={selected !== null}
        onOpenChange={(open) => {
          if (!open) setSelected(null)
        }}
      >
        <DialogContent
          onCloseAutoFocus={(event) => {
            event.preventDefault()
            opener.current?.focus()
          }}
        >
          <form
            onSubmit={(event) => {
              event.preventDefault()
              setSubmitted(true)
              if (!name.trim()) {
                nameInput.current?.focus()
                return
              }
              setNotice(`已保存示例：${name}`)
              setSelected(null)
            }}
            className='flex flex-col gap-6'
          >
            <DialogHeader>
              <DialogTitle>编辑示例</DialogTitle>
              <DialogDescription>
                仅修改当前页面示例，不写入业务数据。
              </DialogDescription>
            </DialogHeader>
            <FieldGroup>
              <Field data-invalid={submitted && !name.trim()}>
                <FieldLabel htmlFor='example-name'>名称</FieldLabel>
                <Input
                  id='example-name'
                  ref={nameInput}
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  aria-invalid={submitted && !name.trim()}
                  aria-describedby={
                    submitted && !name.trim() ? 'name-error' : undefined
                  }
                />
                {submitted && !name.trim() && (
                  <FieldError id='name-error'>请输入名称</FieldError>
                )}
              </Field>
            </FieldGroup>
            <DialogFooter>
              <Button
                type='button'
                variant='outline'
                onClick={() => setSelected(null)}
              >
                取消
              </Button>
              <Button type='submit'>保存示例</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </main>
  )
}
