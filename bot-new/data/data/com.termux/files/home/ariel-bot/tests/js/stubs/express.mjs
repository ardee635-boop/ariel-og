const app = () => new Proxy(function () {}, { get: () => () => app(), apply: () => app() });
const express = () => app(); express.json = () => () => {}; express.static = () => () => {}; express.Router = () => app();
export default express;
