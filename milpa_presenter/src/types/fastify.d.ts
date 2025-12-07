// Declaración mínima para evitar ts(2307) si las dependencias no están instaladas localmente.
declare module "fastify" {
  export type FastifyPluginAsync<T = any> = any;
  export type FastifyPluginCallback<T = any> = any;
  export interface FastifyInstance {
    register: (...args: any[]) => any;
    get: (...args: any[]) => any;
    post: (...args: any[]) => any;
    addHook?: (...args: any[]) => any;
    listen: (...args: any[]) => Promise<any>;
    log: { info: (...a: any[]) => void; error: (...a: any[]) => void };
  }
  function fastify(...args: any[]): FastifyInstance;
  export default fastify;
}
