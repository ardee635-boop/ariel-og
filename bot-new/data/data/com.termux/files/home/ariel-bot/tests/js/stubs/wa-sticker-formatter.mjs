export class Sticker { constructor() {} setPack() { return this; } setAuthor() { return this; } setType() { return this; } setCategories() { return this; } setID() { return this; } setQuality() { return this; } async toBuffer() { return Buffer.from('STICKER'); } async build() { return Buffer.from('STICKER'); } }
export const StickerTypes = { FULL: 'full', CROPPED: 'crop', CIRCLE: 'circle', ROUNDED: 'rounded' };
export default Sticker;
