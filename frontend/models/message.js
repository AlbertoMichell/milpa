// models/Message.js
const mongoose = require('mongoose');

const MessageSchema = new mongoose.Schema({
  user: {
    _id: {
      type: mongoose.Schema.Types.ObjectId,
      ref: 'User',
      required: [true, 'El remitente es requerido']
    },
    username: {
      type: String,
      required: [true, 'El nombre de usuario es requerido']
    }
  },
  texto: {
    type: String,
    required: [true, 'El texto es obligatorio'],
    minlength: [2, 'Mínimo 2 caracteres']
  },
  type: {
    type: String,
    enum: ['text', 'image', 'alert'],
    default: 'text'
  },
  createdAt: {
    type: Date,
    default: Date.now
  }
});

module.exports = mongoose.model('Message', MessageSchema);
