import { useFormContext } from 'react-hook-form'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import type { ModelValues } from './model-form'

export function TranscriptionFields({ disabled }: { disabled: boolean }) {
  const form = useFormContext<ModelValues>()
  return (
    <Card>
      <CardHeader>
        <CardTitle>语音转文字</CardTitle>
      </CardHeader>
      <CardContent className='flex flex-col gap-5'>
        <FormField
          control={form.control}
          name='transcription.max_duration_seconds'
          render={({ field }) => (
            <FormItem>
              <FormLabel>音频上限（秒）</FormLabel>
              <FormControl>
                <Input {...field} disabled={disabled} inputMode='numeric' />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
        <FormField
          control={form.control}
          name='transcription.timestamps'
          render={({ field }) => (
            <FormItem className='flex items-center gap-2'>
              <FormControl>
                <Switch
                  checked={field.value}
                  onCheckedChange={field.onChange}
                  disabled={disabled}
                />
              </FormControl>
              <FormLabel>支持分段时间戳</FormLabel>
            </FormItem>
          )}
        />
        <p className='text-sm text-muted-foreground'>
          PCM WAV · 按文件时长计价（精确到毫秒）
        </p>
      </CardContent>
    </Card>
  )
}
