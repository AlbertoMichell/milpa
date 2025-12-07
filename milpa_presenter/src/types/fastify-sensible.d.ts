// Declaración mínima para evitar ts(2307) si las dependencias no están instaladas localmente.
declare module "@fastify/sensible" {
  import type { FastifyPluginCallback } from "fastify";
  const sensible: FastifyPluginCallback<any>;
  export default sensible;
}
