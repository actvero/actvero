import { useState, type ComponentProps } from 'react'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ChannelTest } from './channel-test'
import { ChannelTestHistory } from './channel-test-history'
import { ChannelDiagnosticBatch } from './diagnostic-batch'

export function ChannelDiagnostics(
  props: ComponentProps<typeof ChannelTest> & { onRefreshChannel?: () => void }
) {
  const [mode, setMode] = useState(props.historyOpen ? 'history' : 'single')
  const [revision, setRevision] = useState(0)
  function finished() {
    setRevision((value) => value + 1)
    props.onFinished?.()
  }
  return (
    <Tabs value={mode} onValueChange={setMode} className='min-w-0'>
      <TabsList>
        <TabsTrigger value='single'>单项测试</TabsTrigger>
        <TabsTrigger value='batch'>批量测试</TabsTrigger>
        <TabsTrigger value='history'>历史记录</TabsTrigger>
      </TabsList>
      <TabsContent value='single' className='min-w-0 pt-4'>
        <ChannelTest {...props} showHistory={false} onFinished={finished} />
      </TabsContent>
      <TabsContent value='batch' className='min-w-0 pt-4'>
        <ChannelDiagnosticBatch
          channel={props.channel}
          operations={props.operations ?? ['chat']}
          onFinished={finished}
          onRefreshChannel={props.onRefreshChannel}
        />
      </TabsContent>
      <TabsContent value='history' className='min-w-0 pt-4'>
        <ChannelTestHistory
          id={props.channel.id}
          revision={revision}
          busy={false}
          initialOpen
        />
      </TabsContent>
    </Tabs>
  )
}
