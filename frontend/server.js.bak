// server.js
require('dotenv').config();
const express = require('express');
const mongoose = require('mongoose');
const socketio = require('socket.io');
const http = require('http');
const path = require('path');
const cors = require('cors');
const jwt = require('jsonwebtoken'); // <--- AÑADIDO: Para verificar tokens JWT

const Message = require('./models/Message');
const Notification = require('./models/Notification');
// Asumimos que api.js está configurado para usar esta misma JWT_SECRET
const JWT_SECRET = process.env.JWT_SECRET || '12345'; 

const app = express();
const server = http.createServer(app);
const io = socketio(server, {
  cors: { origin: '*', methods: ['GET','POST'] }
});

// 1) Conexión a MongoDB y seed de notificaciones
mongoose.connect(process.env.MONGODB_URI, {
  useNewUrlParser: true,
  useUnifiedTopology: true
})
.then(async () => {
  console.log('✅ MongoDB conectado');
  const count = await Notification.countDocuments();
  if (count === 0) {
    await Notification.create([
      { type: 'update', title: 'Versión 1.1.0', message: '¡Ya puedes registrar cultivos!' },
      { type: 'alert',  title: 'Mantenimiento',  message: 'El sistema tendrá downtime a las 22:00' },
      { type: 'chat',   title: 'Chat listo',     message: 'Bienvenido al chat en vivo' }
    ]);
    console.log('🔔 Notificaciones semeadas');
  }
  iniciarServidor();
})
.catch(err => console.error('❌ Error MongoDB:', err));

function iniciarServidor() {
  // Middlewares de Express
  app.use(cors());
  app.use(express.json());
  app.use(express.static(path.join(__dirname, 'MILPA'))); // Servir frontend
  app.use('/api', require('./routes/api')); // Rutas API REST

  // --- Middleware de Autenticación para Socket.IO ---
  // Este middleware se ejecuta para cada socket entrante ANTES de que se establezca la conexión.
  io.use(async (socket, next) => {
    const token = socket.handshake.auth.token; // Token enviado por el cliente

    if (!token) {
      console.log(`🔌 Socket Auth: Conexión rechazada (No token) - ID: ${socket.id}`);
      return next(new Error('Authentication error: No token provided'));
    }

    try {
      // Verificar el token JWT. jwt.verify lanzará un error si el token es inválido.
      const decoded = jwt.verify(token, JWT_SECRET);
     
      socket.user = decoded.user; 
      console.log(`🔒 Socket Auth: Exitoso - Usuario: ${socket.user.username} (ID: ${socket.user.id}), Socket ID: ${socket.id}`);
      next(); // Permitir la conexión
    } catch (err) {
      console.log(`🔌 Socket Auth: Conexión rechazada (Token inválido: ${err.message}) - ID: ${socket.id}`);
      return next(new Error('Authentication error: Invalid token')); // Rechazar la conexión
    }
  });

  // Manejador de conexiones de Socket.IO (solo se ejecuta si el middleware io.use() llama a next())
  io.on('connection', socket => {
    // Ahora podemos asumir que 'socket.user' existe y contiene los datos del usuario autenticado.
    console.log(`🔌 Socket conectado y autenticado: ${socket.id}, Usuario: ${socket.user.username}`);

    // Enviar últimas 3 notificaciones al conectar
    (async () => {
      try {
        const notes = await Notification.find()
          .sort({ createdAt: -1 })
          .limit(3)
          .lean();
        notes.reverse().forEach(n => {
          socket.emit('push_notification', {
            type: n.type,
            title: n.title,
            message: n.message
          });
        });
      } catch (error) {
        console.error("Error al enviar notificaciones iniciales:", error);
      }
    })();

    // Historial inicial de chat
    socket.on('request_initial_data', async () => {
      try {
        console.log(`📜 ${socket.user.username} solicitó historial de chat.`);
        const msgs = await Message.find().sort({ createdAt: 1 }).lean();
        socket.emit('data_update',
          msgs.map(m => ({
            texto:     m.texto,
            fecha:     m.createdAt,
            usuario:   m.user.username,
            usuarioId: m.user._id.toString()
          }))
        );
      } catch (error) {
        console.error("Error al obtener historial de chat:", error);
        socket.emit('error_chat', { message: "No se pudo cargar el historial del chat." });
      }
    });

    // Escuchar el evento mensaje_chat
    socket.on('mensaje_chat', async (data) => {
      // 'data' contiene { texto } enviado por el cliente.
      // 'usuario' y 'usuarioId' ahora se toman de 'socket.user' para mayor seguridad.
      console.log(`💬 mensaje_chat recibido de ${socket.user.username}: "${data.texto}"`);

      try {
        // Guardar mensaje en base de datos usando la información del usuario autenticado del socket.
        const nuevo = new Message({
          user: { 
            _id: socket.user.id,         // <--- MODIFICADO: Usar ID del usuario autenticado
            username: socket.user.username // <--- MODIFICADO: Usar nombre de usuario autenticado
          },
          texto: data.texto,
          type: 'text'
        });

        const saved = await nuevo.save();
        console.log('💾 Mensaje guardado:', saved);

        // Emitir mensaje a todos los clientes conectados
        io.emit('nuevo_mensaje', {
          usuarioId: saved.user._id.toString(),
          usuario: saved.user.username,
          texto: saved.texto,
          fecha: saved.createdAt
        });

        // Responder como bot si aplica
        // Se pasa el ID y nombre del usuario autenticado a la función del bot.
        responderComoBot(saved.texto, socket.user.id, socket.user.username);

      } catch (err) {
        console.error('❌ Error al guardar mensaje:', err);
        socket.emit('error_mensaje', { message: "No se pudo enviar tu mensaje." });
      }
    });

    // Pull manual de datos (podría ser obsoleto si 'request_initial_data' es suficiente)
    socket.on('request_data_update', async () => {
        try {
            console.log(`🔄 ${socket.user.username} solicitó actualización de datos de chat.`);
            const msgs = await Message.find().sort({ createdAt: 1 }).lean();
            socket.emit('data_update',
              msgs.map(m => ({
                texto:     m.texto,
                fecha:     m.createdAt,
                usuario:   m.user.username,
                usuarioId: m.user._id.toString()
              }))
            );
        } catch (error) {
            console.error("Error al actualizar datos de chat:", error);
            socket.emit('error_chat', { message: "No se pudieron actualizar los datos del chat." });
        }
    });

    socket.on('disconnect', () => {
      console.log(`🔌 Socket desconectado: ${socket.id}, Usuario: ${socket.user ? socket.user.username : 'N/A'}`);
    });
  });

  // Arrancar servidor HTTP
  const PORT = process.env.PORT || 4000;
  server.listen(PORT, () => {
    console.log(`🚀 Servidor en http://localhost:${PORT}`);
  });
}

// Función responderComoBot (sin cambios, pero ahora recibe datos de usuario autenticado)
function responderComoBot(mensaje, usuarioId, usuarioNombre) {
  const texto = mensaje.toLowerCase();
  let respuesta = null;

  if (texto.includes('hola')) {
    respuesta = `Hola, ${usuarioNombre}, tienes notificaciones pendientes. El nivel de tus cultivos es óptimo. Tus cultivos a revisar son: maíz, frijol.`;
  } else if (texto.includes('cultivos')) {
    respuesta = `Tus cultivos están en un estado estable, pero requieren seguimiento esta semana.`;
  } else if (texto.includes('maíz')) {
    respuesta = `El estado de tu cultivo de maíz es: bueno. Necesita: riego moderado y revisión de plagas.`;
  } else if (texto.includes('frijol')) {
    respuesta = `El estado de tu cultivo de frijol es: crítico. Necesita: fertilización urgente y monitoreo de humedad.`;
  } else if (texto.includes('notificaciones')) {
    respuesta = `Tienes 3 notificaciones nuevas: mantenimiento programado, nueva versión disponible y alerta de clima.`;
  }

  if (respuesta) {
    setTimeout(async () => {
      const botMensaje = {
        usuarioId: '000000000000000000000999', // ID ficticio del bot
        usuario: 'AgroBot',
        texto: respuesta,
        fecha: new Date().toISOString()
      };
      io.emit('nuevo_mensaje', botMensaje);

      const nuevoBotMsg = new Message({
        user: { _id: botMensaje.usuarioId, username: botMensaje.usuario },
        texto: botMensaje.texto,
        type: 'text'
      });
      try {
        await nuevoBotMsg.save();
        console.log('🤖 Mensaje de AgroBot guardado');
      } catch (error) {
        console.error('❌ Error al guardar mensaje de AgroBot:', error);
      }
    }, 1500);
  }
}