// Declaración mínima para evitar ts(2307) en el editor si las deps aún no están instaladas localmente
declare module "@fastify/rate-limit" {
  import type { FastifyPluginCallback } from "fastify";
  const rateLimit: FastifyPluginCallback<any>;
  export default rateLimit;
}
