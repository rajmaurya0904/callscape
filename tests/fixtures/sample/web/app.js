import { render, Widget } from './ui.js';
const util = require('./util');
class App extends Widget {
  start() { this.draw(); super.start(); util.log('x'); }
  draw() { render(this); }
}
function boot() { new App().start(); }
boot();
