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
import type { ModelValues } from './model-form'

export function SpeechFields({ disabled }: { disabled: boolean }) {
  const form = useFormContext<ModelValues>()
  return (
    <Card>
      <CardHeader>
        <CardTitle>语音合成</CardTitle>
      </CardHeader>
      <CardContent className='flex flex-col gap-5'>
        <FormField
          control={form.control}
          name='speech.voice'
          render={({ field }) => (
            <FormItem>
              <FormLabel>音色</FormLabel>
              <FormControl>
                <Input
                  {...field}
                  disabled={disabled}
                  placeholder='填写上游音色 ID'
                />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
        <FormField
          control={form.control}
          name='speech.max_input_characters'
          render={({ field }) => (
            <FormItem>
              <FormLabel>文本上限（字符）</FormLabel>
              <FormControl>
                <Input {...field} disabled={disabled} inputMode='numeric' />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
        <p className='text-sm text-muted-foreground'>WAV · 按输入字符计价</p>
      </CardContent>
    </Card>
  )
}
