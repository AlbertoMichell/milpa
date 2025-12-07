// test-socket.js
const { io } = require('socket.io-client');

const socket = io('http://localhost:4000', { reconnection: false });

socket.on('connect', () => {
  console.log('🟢 Conectado como test-client');
  socket.emit('mensaje_chat', {
    texto:   '¡Hola desde test!',
    usuario: 'tester',
    usuarioId: '000000000000000000000000'
  });
});

socket.on('nuevo_mensaje', msg => {
  console.log('📬 Recibido en test-client:', msg);
  process.exit(0);
});

socket.on('disconnect', () => {
  console.log('🔴 Desconectado');
});
