import { useMemo, useImperativeHandle, useRef, type Ref } from 'react'
import { json } from '@codemirror/lang-json'
import { HighlightStyle, syntaxHighlighting } from '@codemirror/language'
import { tags } from '@lezer/highlight'
import CodeMirror, {
  EditorView,
  type ReactCodeMirrorRef,
} from '@uiw/react-codemirror'
import { cn } from '@/lib/utils'

const theme = EditorView.theme({
  '&': {
    backgroundColor: 'var(--background)',
    color: 'var(--foreground)',
    fontSize: '14px',
  },
  '&.cm-focused': { outline: 'none' },
  '.cm-scroller': { fontFamily: 'var(--font-mono)', lineHeight: '1.6' },
  '.cm-content': { padding: '12px 0', caretColor: 'var(--foreground)' },
  '.cm-line': { padding: '0 12px' },
  '.cm-gutters': {
    backgroundColor: 'var(--muted)',
    color: 'var(--muted-foreground)',
    borderColor: 'var(--border)',
  },
  '.cm-cursor': { borderLeftColor: 'var(--foreground)' },
  '&.cm-focused .cm-selectionBackground, .cm-selectionBackground, .cm-content ::selection':
    { backgroundColor: 'color-mix(in oklch, var(--ring) 30%, transparent)' },
  '.cm-matchingBracket': {
    backgroundColor: 'var(--accent)',
    outline: '1px solid var(--ring)',
  },
  '.cm-placeholder': { color: 'var(--muted-foreground)' },
})
const language = [
  json(),
  theme,
  syntaxHighlighting(
    HighlightStyle.define([
      { tag: tags.propertyName, color: 'var(--foreground)', fontWeight: '600' },
      { tag: tags.string, color: 'var(--success)' },
      { tag: [tags.number, tags.bool, tags.null], color: 'var(--chart-2)' },
      { tag: tags.punctuation, color: 'var(--muted-foreground)' },
    ])
  ),
]

type JsonEditorProps = {
  value: string
  onChange?: (value: string) => void
  readOnly?: boolean
  size?: 'default' | 'compact'
  onBlur?: () => void
  disabled?: boolean
  placeholder?: string
  id?: string
  name?: string
  className?: string
  'aria-label'?: string
  'aria-describedby'?: string
  'aria-invalid'?: boolean
  ref?: Ref<{ focus: () => void }>
}

// Local editor only: never persist configuration or load code from a remote CDN.
export function JsonEditor({
  value,
  onChange,
  onBlur,
  disabled,
  readOnly = false,
  size = 'default',
  placeholder,
  id,
  className,
  ref,
  'aria-label': label,
  'aria-describedby': describedBy,
  'aria-invalid': invalid,
}: JsonEditorProps) {
  const editor = useRef<ReactCodeMirrorRef>(null)
  useImperativeHandle(
    ref,
    () => ({ focus: () => editor.current?.view?.focus() }),
    []
  )
  const extensions = useMemo(
    () => [
      ...language,
      EditorView.contentAttributes.of({
        ...(id ? { id } : {}),
        ...(label ? { 'aria-label': label } : {}),
        ...(describedBy ? { 'aria-describedby': describedBy } : {}),
        'aria-invalid': String(!!invalid),
        'aria-disabled': String(!!disabled),
        'aria-multiline': 'true',
        spellcheck: 'false',
        autocorrect: 'off',
        autocapitalize: 'off',
      }),
    ],
    [id, label, describedBy, invalid, disabled]
  )
  return (
    <div
      data-slot='json-editor'
      aria-invalid={invalid}
      className={cn(
        'min-w-0 overflow-hidden rounded-md border border-input shadow-xs focus-within:border-ring focus-within:ring-[3px] focus-within:ring-ring/50 aria-invalid:border-destructive aria-invalid:ring-destructive/20',
        disabled && 'opacity-50',
        className
      )}
    >
      <CodeMirror
        ref={editor}
        value={value}
        onChange={onChange}
        onBlur={onBlur}
        theme='none'
        extensions={extensions}
        editable={!disabled && !readOnly}
        readOnly={disabled || readOnly}
        height={
          size === 'compact'
            ? 'clamp(10rem, 28dvh, 20rem)'
            : 'clamp(16rem, 52dvh, 40rem)'
        }
        width='100%'
        indentWithTab={false}
        placeholder={placeholder}
        basicSetup={{
          foldGutter: false,
          highlightActiveLine: false,
          highlightActiveLineGutter: false,
          highlightSelectionMatches: false,
          autocompletion: false,
          searchKeymap: false,
          defaultKeymap: true,
        }}
      />
    </div>
  )
}
