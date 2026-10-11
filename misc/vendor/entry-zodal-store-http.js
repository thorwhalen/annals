// The page has no build step, so @zodal/store-http is bundled once into a classic script
// that sets window.ZodalStoreHttp. Only what the page uses is exported.
export { createHttpProvider, HttpError } from '@zodal/store-http';
