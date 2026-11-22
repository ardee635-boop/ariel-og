const chain = () => { const o = new Proxy(function () {}, { get: (t, k) => k === 'toBuffer' ? async () => Buffer.from('SHARP') : k === 'then' ? undefined : () => o, apply: () => o }); return o; };
export default chain;
