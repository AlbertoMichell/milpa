// Declaración mínima para evitar ts(2307) si las dependencias no están instaladas localmente.
declare module "sanitize-html" {
  type Options = any;
  function sanitizeHtml(input: string, options?: Options): string;
  export default sanitizeHtml;
}
