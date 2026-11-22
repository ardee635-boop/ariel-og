const l = { info() {}, warn() {}, error() {}, debug() {}, trace() {}, fatal() {}, child() { return l; }, level: 'silent' };
export default () => l;
