import "katex/dist/katex.min.css";

import ReactMarkdown from "react-markdown";
import rehypeKatex from "rehype-katex";
import remarkBreaks from "remark-breaks";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";

interface MdProps {
  text: string;
  /** Render without block wrappers (for <li>, <summary>, snippet contexts). */
  inline?: boolean;
  /** Keep single newlines as <br> (for pre-formatted conspect bodies). */
  breaks?: boolean;
}

/**
 * Server-rendered Markdown + LaTeX for fused lecture text: inline code,
 * emphasis, $math$ (KaTeX), tables. Adds no client-side JS.
 */
export function Md({ text, inline = false, breaks = false }: MdProps) {
  const remarkPlugins = breaks
    ? [remarkGfm, remarkMath, remarkBreaks]
    : [remarkGfm, remarkMath];

  const markdown = (
    <ReactMarkdown
      remarkPlugins={remarkPlugins}
      rehypePlugins={[rehypeKatex]}
      components={inline ? { p: ({ children }) => <>{children}</> } : undefined}
    >
      {text}
    </ReactMarkdown>
  );

  return inline ? <span className="md">{markdown}</span> : <div className="md">{markdown}</div>;
}
