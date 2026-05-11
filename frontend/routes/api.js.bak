// api.js
// Se importan los módulos necesarios de Express y otras librerías.
const express = require('express');
const bcrypt = require('bcryptjs'); // Librería para el hashing de contraseñas.
const jwt = require('jsonwebtoken'); // Librería para crear y verificar JSON Web Tokens.
const User = require('../models/User'); // Se importa el modelo de usuario definido con Mongoose.

// Se crea una instancia del enrutador de Express.
const router = express.Router();

// --- Configuración de Variables de Entorno (Importante para Seguridad) ---
// La clave secreta para firmar los JWT debe ser segura y gestionada fuera del código,
// idealmente a través de variables de entorno.
// En una aplicación real: process.env.JWT_SECRET
const JWT_SECRET = '12345'; 
const JWT_EXPIRES_IN = '24h'; // Tiempo de expiración del token (ej. 1 hora)

// --- RUTAS DE AUTENTICACIÓN ---
// Todas las rutas relacionadas con la autenticación se agrupan bajo el prefijo '/auth'.

/**
 * @route   POST /api/auth/register
 * @desc    Registra un nuevo usuario en el sistema.
 * @access  Público
 * @body    { username, password }
 */
router.post('/auth/register', async (req, res) => {
  // Se extraen username y password del cuerpo de la solicitud.
  const { username, password } = req.body;

  // Validación básica: se verifica que ambos campos estén presentes.
  if (!username || !password) {
    // Si faltan credenciales, se responde con un error 400 (Bad Request).
    return res.status(400).json({ error: 'Por favor, proporcione usuario y contraseña.' });
  }

  // Validación de longitud de contraseña (ejemplo, debería coincidir con el modelo User).
  if (password.length < 6) {
    return res.status(400).json({ error: 'La contraseña debe tener al menos 6 caracteres.' });
  }

  try {
    // Se verifica si ya existe un usuario con el mismo username.
    let user = await User.findOne({ username });
    if (user) {
      // Si el usuario ya existe, se responde con un error 400.
      return res.status(400).json({ error: 'El nombre de usuario ya está en uso.' });
    }

    // Si el usuario no existe, se crea una nueva instancia del modelo User.
    // La contraseña se hasheará automáticamente gracias al middleware 'pre.save' en el modelo User.
    user = new User({
      username,
      password, // El modelo User se encarga del hashing antes de guardar.
    });

    // Se guarda el nuevo usuario en la base de datos.
    await user.save();

    // Se responde con un estado 201 (Created) y un mensaje de éxito.
    // No se devuelve token aquí; el usuario debe hacer login después de registrarse.
    res.status(201).json({ message: 'Usuario registrado exitosamente. Por favor, inicia sesión.' });

  } catch (err) {
    // Si ocurre un error durante el proceso, se registra en la consola y se envía una respuesta de error 500.
    console.error('Error en registro:', err.message);
    res.status(500).json({ error: 'Error en el servidor al intentar registrar el usuario.' });
  }
});


/**
 * @route   POST /api/auth/login
 * @desc    Autentica un usuario y devuelve un JWT si es exitoso.
 * @access  Público
 * @body    { username, password }
 */
router.post('/auth/login', async (req, res) => {
  // Se extraen username y password del cuerpo de la solicitud.
  const { username, password } = req.body;

  // Validación básica: se verifica que ambos campos estén presentes.
  if (!username || !password) {
    // Si faltan credenciales, se responde con un error 400.
    return res.status(400).json({ error: 'Faltan credenciales.' });
  }

  try {
    // Se busca al usuario en la base de datos por su username.
    const user = await User.findOne({ username });
    if (!user) {
      // Si no se encuentra el usuario, se responde con un error 401 (Unauthorized).
      return res.status(401).json({ error: 'Usuario o contraseña inválidos.' });
    }

    // Si se encuentra el usuario, se compara la contraseña proporcionada con la almacenada (hasheada).
    // Se usa el método comparePassword definido en el modelo User.
    const isMatch = await user.comparePassword(password);
    if (!isMatch) {
      // Si las contraseñas no coinciden, se responde con un error 401.
      return res.status(401).json({ error: 'Usuario o contraseña inválidos.' });
    }

    // Si las credenciales son correctas, se procede a crear el payload para el JWT.
    // El payload contiene información que se quiere codificar en el token (no sensible).
    const payload = {
      user: {
        id: user._id.toString(), // Se incluye el ID del usuario.
        username: user.username  // Y su nombre de usuario.
      }
    };

    // Se firma el token JWT con el payload, la clave secreta y opciones (tiempo de expiración).
    jwt.sign(
      payload,
      JWT_SECRET,
      { expiresIn: JWT_EXPIRES_IN },
      (err, token) => {
        if (err) throw err; // Si hay un error al firmar el token, se lanza.
        // Si la firma es exitosa, se devuelve el token y datos básicos del usuario.
        res.json({
          message: 'Login exitoso.',
          token, // El JWT que el cliente debe almacenar y usar para solicitudes autenticadas.
          userId: user._id.toString(),
          username: user.username
        });
      }
    );
  } catch (err) {
    // Si ocurre un error durante el proceso, se registra y se envía una respuesta de error 500.
    console.error('Error en login:', err.message);
    res.status(500).json({ error: 'Error en el servidor.' });
  }
});

// --- MIDDLEWARE DE AUTENTICACIÓN (Ejemplo para futuras rutas protegidas) ---
// Este middleware se utilizaría para verificar el token JWT en las rutas que requieran autenticación.
const verificarToken = (req, res, next) => {
  // Se obtiene el token del encabezado 'Authorization' (comúnmente 'Bearer TOKEN_AQUI').
  const authHeader = req.header('Authorization');
  
  if (!authHeader) {
    return res.status(401).json({ error: 'Acceso denegado. No se proporcionó token.' });
  }

  // El token usualmente viene como "Bearer <token>", así que lo separamos.
  const tokenParts = authHeader.split(' ');
  if (tokenParts.length !== 2 || tokenParts[0] !== 'Bearer') {
      return res.status(401).json({ error: 'Formato de token inválido. Debe ser "Bearer <token>".' });
  }
  const token = tokenParts[1];

  if (!token) {
    // Si no hay token (después de verificar "Bearer "), se deniega el acceso.
    return res.status(401).json({ error: 'Acceso denegado. Token ausente.' });
  }

  try {
    // Se verifica el token usando la clave secreta.
    const decoded = jwt.verify(token, JWT_SECRET);
    // Si el token es válido, se añade el payload decodificado (que incluye user.id y user.username)
    // al objeto 'req' para que las rutas protegidas puedan acceder a la información del usuario.
    req.user = decoded.user;
    next(); // Se pasa al siguiente middleware o al manejador de la ruta.
  } catch (err) {
    // Si el token no es válido (expirado, manipulado), se responde con un error 401.
    res.status(401).json({ error: 'Token inválido o expirado.' });
  }
};


// --- RUTAS PARA OTROS RECURSOS (Ejemplos de cómo se estructuraría) ---
// Aquí es donde se montarían los enrutadores para otros recursos de la aplicación,
// como cultivos, recomendaciones, parcelas, etc.
// Estas rutas estarían protegidas por el middleware 'verificarToken'.

/*
// Ejemplo para rutas de CULTIVOS:
const cultivosRouter = require('./cultivos.routes'); // Suponiendo que existe un archivo 'cultivos.routes.js'
router.use('/cultivos', verificarToken, cultivosRouter); // Todas las rutas en '/api/cultivos' requerirán un token válido.

// Ejemplo para rutas de RECOMENDACIONES:
const recomendacionesRouter = require('./recomendaciones.routes'); // Suponiendo que existe un archivo 'recomendaciones.routes.js'
router.use('/recomendaciones', verificarToken, recomendacionesRouter);
*/

// Se exporta el enrutador para que pueda ser utilizado en `server.js`.
module.exports = router;