const mongoose = require('mongoose');

const NotificationSchema = new mongoose.Schema({
  type: {
    type: String,
    enum: ['alert','update','chat'],
    required: true
  },
  title: { type: String, required: true },
  message: { type: String, required: true },
  createdAt: { type: Date, default: Date.now }
});

module.exports = mongoose.model('Notification', NotificationSchema);
