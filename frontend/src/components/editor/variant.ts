/**
 * Which surface an editor is on, and therefore how much of it is offered.
 *
 * The editor is one component with one node vocabulary — a post and a document
 * store the same shape, and a smart chip works identically in both. What
 * differs is the writing surface: a document is a place to typeset, a notice is
 * a place to say something. So this narrows the *toolbar*, never the schema —
 * a post that already contains a coloured heading (pasted, or written before
 * this was narrowed) still renders it correctly.
 *
 * `post` drops the typesetting controls a notice has no use for — font size,
 * sub/superscript, text and background colour, horizontal rules, column
 * layouts — and reduces the actions bar to the character count, which is what
 * a length limit needs.
 */
export type EditorVariant = "document" | "post";
