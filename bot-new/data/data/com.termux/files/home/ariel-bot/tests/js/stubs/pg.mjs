class Pool { constructor() { throw new Error('pg stub: tests pre-seed botState._pgPool'); } }
class Client extends Pool {}
export default { Pool, Client };
