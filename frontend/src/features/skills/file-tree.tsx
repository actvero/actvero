import { ChevronRight, ChevronDown, FileText, Folder } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible'
import { ScrollArea } from '@/components/ui/scroll-area'
import { sizeLabel, type SkillFile } from './shared'

export function FileTree({
  files,
  onSelect,
  prefix = '',
}: {
  files: SkillFile[]
  onSelect: (file: SkillFile) => void
  prefix?: string
}) {
  const children = new Map<string, SkillFile[]>()
  for (const file of files) {
    const segment = file.path.slice(prefix.length).split('/')[0]
    children.set(segment, [...(children.get(segment) ?? []), file])
  }
  return (
    <div className='min-w-0 space-y-1'>
      {[...children].map(([name, group]) => {
        const path = prefix + name
        if (group.length === 1 && group[0].path === path)
          return (
            <Button
              key={path}
              variant='ghost'
              className='w-full justify-start'
              onClick={() => onSelect(group[0])}
              title={path}
            >
              <FileText />
              <span className='min-w-0 flex-1 truncate text-start'>{name}</span>
              <span className='text-xs text-muted-foreground'>
                {sizeLabel(group[0].size)}
              </span>
            </Button>
          )
        return (
          <Collapsible
            key={path}
            defaultOpen={prefix === '' && children.size === 1}
          >
            <CollapsibleTrigger asChild>
              <Button variant='ghost' className='group w-full justify-start'>
                <ChevronRight className='group-data-[state=open]:hidden' />
                <ChevronDown className='hidden group-data-[state=open]:block' />
                <Folder />
                <span className='truncate'>{name}</span>
              </Button>
            </CollapsibleTrigger>
            <CollapsibleContent className='ms-3 border-s ps-2'>
              <FileTree files={group} prefix={path + '/'} onSelect={onSelect} />
            </CollapsibleContent>
          </Collapsible>
        )
      })}
    </div>
  )
}
export function FileBrowser(props: {
  files: SkillFile[]
  onSelect: (file: SkillFile) => void
}) {
  return (
    <ScrollArea viewportClassName='max-h-80' aria-label='技能文件列表'>
      <FileTree {...props} />
    </ScrollArea>
  )
}
