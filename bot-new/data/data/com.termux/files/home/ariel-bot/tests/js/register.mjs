// Usage: node --no-warnings --import ./tests/js/register.mjs tests/js/golden_handler_test.mjs
import { register } from 'node:module';
register('./loader.mjs', import.meta.url);
