import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

/** Read-only untrusted Markdown: no raw HTML, remote images or embedded execution. */
export function Markdown({ children }: { children: string }) {
  return (
    <div className='min-w-0 space-y-4 text-sm leading-7 break-words'>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        skipHtml
        components={{
          h1: ({ children }) => (
            <h2 className='mt-2 mb-6 text-2xl font-semibold tracking-tight'>
              {children}
            </h2>
          ),
          h2: ({ children }) => (
            <h3 className='mt-8 mb-4 border-b pb-3 text-xl font-semibold tracking-tight'>
              {children}
            </h3>
          ),
          h3: ({ children }) => (
            <h4 className='mt-6 mb-2 text-lg font-semibold'>{children}</h4>
          ),
          p: ({ children }) => <p className='my-4'>{children}</p>,
          ul: ({ children }) => (
            <ul className='my-4 ms-6 list-disc space-y-2'>{children}</ul>
          ),
          ol: ({ children }) => (
            <ol className='my-4 ms-6 list-decimal space-y-2'>{children}</ol>
          ),
          blockquote: ({ children }) => (
            <blockquote className='my-4 border-s-2 ps-4 text-muted-foreground'>
              {children}
            </blockquote>
          ),
          pre: ({ children }) => (
            <pre className='my-4 overflow-x-auto rounded-md bg-muted p-4 text-sm'>
              {children}
            </pre>
          ),
          code: ({ children }) => (
            <code className='font-mono text-sm'>{children}</code>
          ),
          a: ({ href, children }) =>
            href && /^https?:\/\//i.test(href) ? (
              <a
                href={href}
                target='_blank'
                rel='noopener noreferrer'
                className='text-primary underline underline-offset-4'
              >
                {children}
              </a>
            ) : (
              <span>{children}</span>
            ),
          img: ({ alt }) => (
            <span className='text-muted-foreground'>
              [图片：{alt || '附件'}]
            </span>
          ),
          table: ({ children }) => <Table>{children}</Table>,
          thead: ({ children }) => <TableHeader>{children}</TableHeader>,
          tbody: ({ children }) => <TableBody>{children}</TableBody>,
          tr: ({ children }) => <TableRow>{children}</TableRow>,
          th: ({ children }) => <TableHead>{children}</TableHead>,
          td: ({ children }) => <TableCell>{children}</TableCell>,
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  )
}
