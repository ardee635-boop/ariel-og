// bot/lib/alpha.js - the `.alpha <language>` command: shows a language's alphabet(s) in a readable layout.
// Pure data + text builders (no imports), so it can be tested on its own. Wired in at the top of handler/games.js.
//
//   .alpha                 -> list of languages
//   .alpha japanese        -> a language with ONE alphabet answers straight away;
//                             a language with SEVERAL sends a numbered menu, and the person replies to
//                             that menu message with the number. Signs are ignored: "2", ".2", "2." and "#2" all work.
//
// The menu is stateless: its header ("🔤 *Japanese alphabets*") and the numbered lines are read back from the
// quoted message, so a pick still works after a bot restart.

const MENU_RE = /^🔤 \*(.+?) alphabets\*/;

// "あ a, い i" -> ["あ a", "い i"]; tiny helper so the data below stays readable.
const row = (s) => s.split(',').map((x) => x.trim()).filter(Boolean);

// Hiragana rows. Katakana is generated from these (same sounds, code points +0x60).
const HIRA = {
    basic: [
        'あ a, い i, う u, え e, お o',
        'か ka, き ki, く ku, け ke, こ ko',
        'さ sa, し shi, す su, せ se, そ so',
        'た ta, ち chi, つ tsu, て te, と to',
        'な na, に ni, ぬ nu, ね ne, の no',
        'は ha, ひ hi, ふ fu, へ he, ほ ho',
        'ま ma, み mi, む mu, め me, も mo',
        'や ya, ゆ yu, よ yo',
        'ら ra, り ri, る ru, れ re, ろ ro',
        'わ wa, を wo, ん n',
    ],
    voiced: [
        'が ga, ぎ gi, ぐ gu, げ ge, ご go',
        'ざ za, じ ji, ず zu, ぜ ze, ぞ zo',
        'だ da, ぢ ji, づ zu, で de, ど do',
        'ば ba, び bi, ぶ bu, べ be, ぼ bo',
        'ぱ pa, ぴ pi, ぷ pu, ぺ pe, ぽ po',
    ],
    combo: [
        'きゃ kya, きゅ kyu, きょ kyo',
        'しゃ sha, しゅ shu, しょ sho',
        'ちゃ cha, ちゅ chu, ちょ cho',
        'にゃ nya, にゅ nyu, にょ nyo',
        'ひゃ hya, ひゅ hyu, ひょ hyo',
        'みゃ mya, みゅ myu, みょ myo',
        'りゃ rya, りゅ ryu, りょ ryo',
        'ぎゃ gya, ぎゅ gyu, ぎょ gyo',
        'じゃ ja, じゅ ju, じょ jo',
        'びゃ bya, びゅ byu, びょ byo',
        'ぴゃ pya, ぴゅ pyu, ぴょ pyo',
    ],
};

// hiragana -> katakana: shift every hiragana letter (U+3041..U+3096) up by 0x60
const kata = (s) => s.replace(/[ぁ-ゖ]/g, (c) => String.fromCharCode(c.charCodeAt(0) + 0x60));
const kataRows = (rows) => rows.map(kata);

const JA_NOTE = '_Voiced marks (゛) and ゜ change k→g, s→z, t→d, h→b/p. Small ゃゅょ blend with the kana before them._';

export const LANGUAGES = {
    japanese: {
        name: 'Japanese', flag: '🇯🇵', aliases: ['jp', 'ja', 'jpn', 'nihongo'],
        scripts: [
            { name: 'Hiragana', native: 'ひらがな', aliases: ['hira'], sections: [
                { title: 'Basic', rows: HIRA.basic.map(row) },
                { title: 'Voiced', rows: HIRA.voiced.map(row) },
                { title: 'Combinations', rows: HIRA.combo.map(row) },
            ], note: JA_NOTE },
            { name: 'Katakana', native: 'カタカナ', aliases: ['kata'], sections: [
                { title: 'Basic', rows: kataRows(HIRA.basic).map(row) },
                { title: 'Voiced', rows: kataRows(HIRA.voiced).map(row) },
                { title: 'Combinations', rows: kataRows(HIRA.combo).map(row) },
            ], note: '_Used for foreign words, names and emphasis. Same sounds as hiragana; the long vowel mark is ー._' },
        ],
    },
    chinese: {
        name: 'Chinese', flag: '🇨🇳', aliases: ['mandarin', 'zh', 'cn', 'china'],
        scripts: [
            { name: 'Pinyin', native: '拼音', aliases: ['pin'], sections: [
                { title: 'Initials', rows: [
                    row('b b, p p, m m, f f'), row('d d, t t, n n, l l'), row('g g, k k, h h'),
                    row('j j, q q, x x'), row('zh zh, ch ch, sh sh, r r'), row('z z, c c, s s'),
                ] },
                { title: 'Finals', rows: [
                    row('a a, o o, e e, ê ê'), row('ai ai, ei ei, ao ao, ou ou'),
                    row('an an, en en, ang ang, eng eng'), row('er er'),
                    row('i i, u u, ü ü'),
                ] },
                { title: 'Tones', rows: [row('mā 1 high flat, má 2 rising, mǎ 3 dip, mà 4 falling')] },
            ], note: '_Pinyin spells Mandarin with Latin letters. Pronunciation is not the same as English (q ≈ "ch", x ≈ "sh", c ≈ "ts")._' },
            { name: 'Zhuyin (Bopomofo)', native: 'ㄅㄆㄇㄈ', aliases: ['bopomofo', 'zhuyin', 'bpmf'], sections: [
                { title: 'Initials', rows: [
                    row('ㄅ b, ㄆ p, ㄇ m, ㄈ f'), row('ㄉ d, ㄊ t, ㄋ n, ㄌ l'), row('ㄍ g, ㄎ k, ㄏ h'),
                    row('ㄐ j, ㄑ q, ㄒ x'), row('ㄓ zh, ㄔ ch, ㄕ sh, ㄖ r'), row('ㄗ z, ㄘ c, ㄙ s'),
                ] },
                { title: 'Medials', rows: [row('ㄧ i, ㄨ u, ㄩ ü')] },
                { title: 'Finals', rows: [
                    row('ㄚ a, ㄛ o, ㄜ e, ㄝ ê'), row('ㄞ ai, ㄟ ei, ㄠ ao, ㄡ ou'),
                    row('ㄢ an, ㄣ en, ㄤ ang, ㄥ eng'), row('ㄦ er'),
                ] },
            ], note: '_Used mostly in Taiwan. The sounds on the right are the pinyin spelling._' },
        ],
    },
    korean: {
        name: 'Korean', flag: '🇰🇷', aliases: ['kr', 'ko', 'hangul', 'hangeul'],
        scripts: [
            { name: 'Hangul', native: '한글', sections: [
                { title: 'Consonants', rows: [
                    row('ㄱ g/k, ㄴ n, ㄷ d/t, ㄹ r/l'), row('ㅁ m, ㅂ b/p, ㅅ s, ㅇ silent/ng'),
                    row('ㅈ j, ㅊ ch, ㅋ k, ㅌ t'), row('ㅍ p, ㅎ h'),
                ] },
                { title: 'Double consonants', rows: [row('ㄲ kk, ㄸ tt, ㅃ pp, ㅆ ss, ㅉ jj')] },
                { title: 'Vowels', rows: [
                    row('ㅏ a, ㅑ ya, ㅓ eo, ㅕ yeo'), row('ㅗ o, ㅛ yo, ㅜ u, ㅠ yu'), row('ㅡ eu, ㅣ i'),
                ] },
                { title: 'Combined vowels', rows: [
                    row('ㅐ ae, ㅒ yae, ㅔ e, ㅖ ye'), row('ㅘ wa, ㅙ wae, ㅚ oe'), row('ㅝ wo, ㅞ we, ㅟ wi, ㅢ ui'),
                ] },
            ], note: '_Letters stack into syllable blocks, e.g. ㅎ + ㅏ + ㄴ = 한 (han)._' },
        ],
    },
    russian: {
        name: 'Russian', flag: '🇷🇺', aliases: ['ru', 'rus', 'cyrillic'],
        scripts: [
            { name: 'Cyrillic', native: 'Кириллица', sections: [
                { title: 'Letters', rows: [
                    row('А а a, Б б b, В в v, Г г g'), row('Д д d, Е е ye, Ё ё yo, Ж ж zh'),
                    row('З з z, И и ee, Й й y, К к k'), row('Л л l, М м m, Н н n, О о o'),
                    row('П п p, Р р r, С с s, Т т t'), row('У у oo, Ф ф f, Х х kh, Ц ц ts'),
                    row('Ч ч ch, Ш ш sh, Щ щ shch'), row('Э э eh, Ю ю yu, Я я ya'),
                    row('Ы ы ih (deep i)'), row('Ъ ъ hard sign (silent), Ь ь soft sign (silent)'),
                ] },
            ], note: '_33 letters. ь and ъ have no sound of their own: they change the letter before them._' },
        ],
    },
    greek: {
        name: 'Greek', flag: '🇬🇷', aliases: ['gr', 'el', 'ell'],
        scripts: [
            { name: 'Greek', native: 'Ελληνικό', sections: [
                { title: 'Letters (modern sounds)', rows: [
                    row('Α α alpha a, Β β vita v, Γ γ gamma gh/y'), row('Δ δ delta th (this), Ε ε epsilon e'),
                    row('Ζ ζ zita z, Η η ita ee, Θ θ thita th (think)'), row('Ι ι iota ee, Κ κ kappa k, Λ λ lambda l'),
                    row('Μ μ mi m, Ν ν ni n, Ξ ξ ksi ks'), row('Ο ο omikron o, Π π pi p, Ρ ρ ro r'),
                    row('Σ σ/ς sigma s, Τ τ taf t, Υ υ ipsilon ee'), row('Φ φ fi f, Χ χ hi kh, Ψ ψ psi ps, Ω ω omega o'),
                ] },
            ], note: '_24 letters. ς is the form of σ at the end of a word._' },
        ],
    },
    arabic: {
        name: 'Arabic', flag: '🇸🇦', aliases: ['ar', 'ara'],
        scripts: [
            { name: 'Arabic', native: 'العربية', sections: [
                { title: 'Letters (stand-alone form)', rows: [
                    row('ا alif aa, ب baa b, ت taa t, ث thaa th (think)'), row('ج jeem j, ح haa h (breathy), خ khaa kh'),
                    row('د daal d, ذ dhaal dh (this), ر raa r, ز zay z'), row('س seen s, ش sheen sh, ص saad s (heavy)'),
                    row('ض daad d (heavy), ط taa t (heavy), ظ zaa dh (heavy)'), row('ع ayn (throaty), غ ghayn gh, ف faa f'),
                    row('ق qaaf q, ك kaaf k, ل laam l, م meem m'), row('ن noon n, ه haa h, و waaw w/oo, ي yaa y/ee'),
                ] },
            ], note: '_28 letters, written right to left. Letters change shape inside a word; this shows the stand-alone form._' },
        ],
    },
    hebrew: {
        name: 'Hebrew', flag: '🇮🇱', aliases: ['he', 'heb', 'iw'],
        scripts: [
            { name: 'Hebrew', native: 'עברית', sections: [
                { title: 'Letters', rows: [
                    row('א alef (silent), ב bet b/v, ג gimel g, ד dalet d'), row('ה he h, ו vav v/o/u, ז zayin z, ח chet kh'),
                    row('ט tet t, י yod y/ee, כ kaf k/kh, ל lamed l'), row('מ mem m, נ nun n, ס samekh s, ע ayin (silent)'),
                    row('פ pe p/f, צ tsadi ts, ק qof k, ר resh r'), row('ש shin sh/s, ת tav t'),
                ] },
            ], note: '_22 letters, written right to left. ך ם ן ף ץ are the end-of-word forms of כ מ נ פ צ._' },
        ],
    },
    hindi: {
        name: 'Hindi', flag: '🇮🇳', aliases: ['hi', 'hin', 'devanagari'],
        scripts: [
            { name: 'Devanagari', native: 'देवनागरी', sections: [
                { title: 'Vowels', rows: [
                    row('अ a, आ aa, इ i, ई ee'), row('उ u, ऊ oo, ऋ ri'), row('ए e, ऐ ai, ओ o, औ au'), row('अं am, अः ah'),
                ] },
                { title: 'Consonants', rows: [
                    row('क ka, ख kha, ग ga, घ gha, ङ nga'), row('च cha, छ chha, ज ja, झ jha, ञ nya'),
                    row('ट ta, ठ tha, ड da, ढ dha, ण na'), row('त ta, थ tha, द da, ध dha, न na'),
                    row('प pa, फ pha, ब ba, भ bha, म ma'), row('य ya, र ra, ल la, व va'), row('श sha, ष sha, स sa, ह ha'),
                ] },
            ], note: '_Rows 3 and 4 of the consonants differ by tongue position (ट-row curled back, त-row against the teeth)._' },
        ],
    },
    spanish: {
        name: 'Spanish', flag: '🇪🇸', aliases: ['es', 'esp', 'espanol', 'español'],
        scripts: [
            { name: 'Spanish', native: 'Español', sections: [
                { title: 'Letter names', rows: [
                    row('A a, B be, C ce, D de'), row('E e, F efe, G ge, H hache (silent)'), row('I i, J jota, K ka, L ele'),
                    row('M eme, N ene, Ñ eñe, O o'), row('P pe, Q cu, R erre, S ese'), row('T te, U u, V uve, W uve doble'),
                    row('X equis, Y ye, Z zeta'),
                ] },
                { title: 'Marks', rows: [row('á é í ó ú stress, ü gu+e/i, ñ "ny", ¿ ¡ open questions and exclamations')] },
            ], note: '_27 letters, with ñ. ch and ll are no longer separate letters._' },
        ],
    },
    french: {
        name: 'French', flag: '🇫🇷', aliases: ['fr', 'fra', 'francais', 'français'],
        scripts: [
            { name: 'French', native: 'Français', sections: [
                { title: 'Letter names', rows: [
                    row('A a, B bé, C cé, D dé'), row('E e, F effe, G gé, H ache'), row('I i, J ji, K ka, L elle'),
                    row('M emme, N enne, O o, P pé'), row('Q ku, R erre, S esse, T té'), row('U u, V vé, W double vé, X ixe'), row('Y i grec, Z zède'),
                ] },
                { title: 'Accents', rows: [
                    row('é "ay", è/ê "eh", à/â "ah"'), row('ç "s", î/ï "ee", ô "oh"'), row('ù/û "u", ë/ï separate the vowel'), row('œ "uh", æ "ay"'),
                ] },
            ], note: '_26 letters plus accents. Accents change the sound or distinguish words._' },
        ],
    },
    german: {
        name: 'German', flag: '🇩🇪', aliases: ['de', 'ger', 'deutsch'],
        scripts: [
            { name: 'German', native: 'Deutsch', sections: [
                { title: 'Letter names', rows: [
                    row('A ah, B beh, C tseh, D deh'), row('E eh, F eff, G geh, H hah'), row('I ee, J yot, K kah, L ell'),
                    row('M emm, N enn, O oh, P peh'), row('Q koo, R err, S ess, T teh'), row('U oo, V fow, W veh, X iks'), row('Y üpsilon, Z tset'),
                ] },
                { title: 'Extra letters', rows: [row('Ä ä "eh", Ö ö "ur" (lips rounded), Ü ü "ee" (lips rounded), ß "ss"')] },
            ], note: '_26 letters plus ä ö ü ß. All nouns are capitalised._' },
        ],
    },
};

// ── lookup ──────────────────────────────────────────────────────
const norm = (s) => String(s || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/[^a-z0-9]/g, '');

export function findLanguage(word) {
    const k = norm(word);
    if (!k) return null;
    for (const lang of Object.values(LANGUAGES)) {
        if (norm(lang.name) === k || (lang.aliases || []).some((a) => norm(a) === k)) return lang;
    }
    return null;
}

export const languageList = () =>
    Object.values(LANGUAGES).map((l) => `${l.flag} ${l.name}`).join('\n');

export function helpText() {
    return `🔤 *.alpha <language>*\nShows that language's alphabet.\n\n${languageList()}\n\n_Example: .alpha japanese_`;
}

// ── builders ────────────────────────────────────────────────────
const cell = (c) => c;
const joinRow = (cells) => cells.map(cell).join('   ');

export function scriptText(lang, script) {
    const head = script.native && script.native !== script.name ? `${script.name} · ${script.native}` : script.name;
    const out = [`${lang.flag} *${lang.name} · ${head}*`];
    for (const sec of script.sections) {
        out.push('', `*${sec.title}*`, ...sec.rows.map(joinRow));
    }
    if (script.note) out.push('', script.note);
    return out.join('\n');
}

export function menuText(lang) {
    const lines = lang.scripts.map((s, i) => `${i + 1}. ${s.name}${s.native && s.native !== s.name ? ` (${s.native})` : ''}`);
    return `🔤 *${lang.name} alphabets*\n${lines.join('\n')}\n\n_Reply to this message with the number._`;
}

// `.alpha japanese` -> text to send
export function alphaCommand(arg) {
    const q = String(arg || '').trim();
    if (!q) return helpText();
    const lang = findLanguage(q);
    if (!lang) return `_I don't have "${q.slice(0, 30)}" yet._\n\n${languageList()}`;
    return lang.scripts.length === 1 ? scriptText(lang, lang.scripts[0]) : menuText(lang);
}

// A reply to one of our menu messages. `quoted` is the menu text, `reply` what the person typed.
// Returns the text to send, '' if the reply is not a valid pick (so the caller can say so), or null when
// the quoted message is not one of our menus at all.
export function alphaPick(quoted, reply) {
    const m = MENU_RE.exec(String(quoted || ''));
    if (!m) return null;
    const lang = findLanguage(m[1]);
    if (!lang || lang.scripts.length < 2) return null;
    const t = norm(reply);                       // "1", ".1", "1.", "#1" -> "1"
    if (!t) return '';
    let script = null;
    if (/^\d+$/.test(t)) script = lang.scripts[Number(t) - 1] || null;
    else script = lang.scripts.find((s) => norm(s.name) === t || (s.aliases || []).some((a) => norm(a) === t)) || null;
    return script ? scriptText(lang, script) : '';
}

export const isAlphaMenu = (quoted) => MENU_RE.test(String(quoted || ''));
