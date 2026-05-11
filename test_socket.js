const { io } = require('socket.io-client');
const token = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1c2VyIjp7ImlkIjoiMSIsInVzZXJuYW1lIjoidGVzdHVzZXIifSwiaWF0IjoxNzc2NzE5MTE5LCJleHAiOjE3NzY4MDU1MTl9.vTpHP4aonIcu-XfdjOQcw1ZWw0NsmV6rSgjaXlj3KJE';
const socket = io('http://127.0.0.1:4000', { auth: { token } });

socket.on('connect', () => {
    console.log('Socket conectado');
    socket.emit('mensaje_chat', { texto: '¿Cómo puedo mejorar el rendimiento de mi cultivo de maíz?' });
});

socket.on('nuevo_mensaje', (data) => {
    if (data.usuario === 'AgroBot') {
        console.log('Respuesta de AgroBot: ' + data.texto);
        process.exit(0);
    }
});

setTimeout(() => {
    console.error('Tiempo de espera agotado');
    process.exit(1);
}, 15000);
