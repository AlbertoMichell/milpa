const mongoose = require('mongoose');
const bcrypt = require('bcryptjs');

const UserSchema = new mongoose.Schema({
  username: {
    type: String,
    required: [true, 'El usuario es requerido'],
    unique: true
  },
  password: {
    type: String,
    required: [true, 'La contraseña es requerida'],
    minlength: [6, 'Mínimo 6 caracteres']
  },

  createdAt: {
    type: Date,
    default: Date.now
  }
});

// Antes de guardar, hashea la contraseña si cambió
UserSchema.pre('save', async function (next) {
  if (!this.isModified('password')) return next();
  const salt = await bcrypt.genSalt(10);
  this.password = await bcrypt.hash(this.password, salt);
  next();
});

// Método para comparar contraseña en login
UserSchema.methods.comparePassword = function (candidatePassword) {
  return bcrypt.compare(candidatePassword, this.password);
};

module.exports = mongoose.model('User', UserSchema);

UserSchema.statics.cleanExpiredTempUsers = async function() {
  await this.deleteMany({
    isTemporary: true,
    expiresAt: { $lt: new Date() }
  });
};
