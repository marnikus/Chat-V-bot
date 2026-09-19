/* Optional QWebChannel diagnostics; never blocks or rewrites calls. */
(function (root, factory) {
  'use strict';
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.WireSchema = api;
}(typeof window === 'undefined' ? globalThis : window, function () {
  'use strict';
  let schema = {methods: {}, signals: {}}, problems = [];
  const own = (obj, key) => Object.prototype.hasOwnProperty.call(obj, key);
  function use(value) {
    if (!value || !value.methods || !value.signals) throw new TypeError('Invalid wire schema');
    schema = value;
    return api;
  }
  async function load(url = 'js/wire-schema.json') {
    const response = await fetch(url);
    if (!response.ok) throw new Error('Wire schema HTTP ' + response.status);
    return use(await response.json());
  }
  function known(name) { return own(schema.methods, name); }
  function arity(name) { return known(name) ? schema.methods[name].arity : null; }
  function params(name) { return known(name) ? schema.methods[name].params.slice() : null; }
  function check(name, args) {
    if (!known(name)) { problems.push('Unknown wire method: ' + name); return false; }
    // QWebChannel optionally takes a trailing result callback outside the Qt signature.
    const count = args.length - (typeof args[args.length - 1] === 'function' ? 1 : 0);
    if (count === arity(name)) return true;
    problems.push('Wire arity mismatch: ' + name + ' expected ' + arity(name) + ', got ' + count);
    return false;
  }
  function guard(bridge) {
    return new Proxy(bridge, {get(target, name) {
      const value = Reflect.get(target, name);
      if (typeof value !== 'function' || typeof name !== 'string') return value;
      return function (...args) { check(name, args); return value.apply(target, args); };
    }});
  }
  function parity(bridge) {
    return Object.keys(schema.methods).filter(name => typeof bridge[name] !== 'function');
  }
  const api = {use, load, known, arity, params, check, guard, parity,
    reset() { problems = []; }, problems() { return problems.slice(); }};
  return api;
}));
