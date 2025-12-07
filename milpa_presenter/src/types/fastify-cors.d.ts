// Declaración mínima para evitar ts(2307) si las dependencias no están instaladas localmente.
declare module "@fastify/cors" {
  import type { FastifyPluginCallback } from "fastify";
  const cors: FastifyPluginCallback<any>;
  export default cors;
}
